"""线程堆栈本地解析与重复调用序列统计。

1、解析与统计部分纯标准库、无 LangChain 依赖（LangChain 工具壳在 tools/jvm_stack_tools.py，
   本模块只提供逻辑）：本地部分只读 dump 文件、只写分析产物（总报告由调用方落盘，
   每个栈顶的线程全栈明细由 build_report 自己落盘；大模型的分析结果与维度结论由调用方
   分别用 analyze_result_path / conclusion_path 落盘，便于溯源）。
   另含抓取线程堆栈用的 SSH 辅助（列 Java 进程 / 定位 jstack-jcmd / 保存 dump），只有这三个会连服务器。
2、build_report 产出总报告（体积由 _TOP_N / _GROUP_PREFIX_LINE / _FRAME_LINE_MAX 限制）：
   每个高频栈顶只记录栈顶帧 + 该栈顶明细文件的位置，不记录线程全栈。
3、总报告进大模型上下文；明细默认不进，由大模型通过 read_detail_file 按需、一次一个文件、
   单次最多 _DETAIL_READ_LINES_MAX 行读进来（超出截断）。dump 原文两者都不含。
"""
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from config.config import STACK_DUMP_DIR
from util.ssh_client import ssh_exec


_FRAME_LINE_MAX = 120           # 栈行显示长度上限
_GROUP_PREFIX_LINE = 10         # 取栈顶前 N 帧参与聚类
_GROUP_FILTER_DEEP = 20         # 栈深低于此值的线程不参与聚类（浅栈多为噪声）
_TOP_N = 5                      # 分析结果中：默认展示 top N 个高频簇
_ANALYZER_FILTER_THREAD=10      # 分析结果中，线程数量低于此值的不展示（线程数少的多为噪声）
_ALL_STACK_PER_GROUP = 3        # 每个栈顶的明细文件里保留的前 N 个「不重复」线程全栈
_ANALYSIS_PREFIX = "analysis_"  # 分析产物文件名前缀（总报告与明细共用）
_DETAIL_SUFFIX = "_stacktop_"   # 每个栈顶明细文件的后缀（其后跟栈顶序号）
_RESULT_SUFFIX = "_result"      # analyze 阶段大模型分析结果的落盘后缀
_CONCLUSION_SUFFIX = "_conclusion"  # 维度最终结论的落盘后缀
_DETAIL_READ_LINES_MAX = 1000   # 单次回读明细文件的行数硬上限，超出截断（模型无法要更大的窗口）


# --- 正则 ---

# 合成类名里的动态地址：$$Lambda/0x00007f...、LambdaForm$DMH/0x00007f...
# '.' '/' 在 Java 标识符里非法，"[./]0x" 只可能出现在这种合成类名里，无误伤。
_ADDR = re.compile(r"[./]0x[0-9a-fA-F]+")
# 代码行号：Foo.java:123 -> Foo.java
_LINE_NO = re.compile(r":\d+\)")
# JDK 模块前缀：java.base@21.0.12.1/Reference.java -> Reference.java
_MODULE = re.compile(r"\((?:[a-zA-Z0-9_.]+@[0-9][0-9A-Za-z.\-+]*)/([^)]*)\)")

# Java 线程头："name" #9 [3243] daemon prio=... os_prio=...
# 三个要点：名字用 .*?（允许含双引号）；[tid] 是 JDK9+ 才有的，加 ? 兼容 JDK8；
# 锚定 "prio=\d+ os_prio=" 以排除 "GC Thread#12" 这类引号内含 # 的 VM 线程头。
_JAVA_HEADER = re.compile(r'^"(?P<name>.*?)" #\d+ (?:\[\d+\] )?(?:daemon )?prio=\d+ os_prio=')
# VM/GC 线程头："GC Thread#12" os_prio=0 cpu=... runnable（无 #N、无 prio=）
_VM_HEADER = re.compile(r'^"(?P<name>.*?)" os_prio=\d+')

# 帧行 = 一个 Tab + "at "；状态行 = 3 空格 + State:
_FRAME = re.compile(r"^\tat ")
_STATE = re.compile(r"^ {3}java\.lang\.Thread\.State: (?P<state>.+)$")

# 明细文件的线程块头：[第 1 个线程堆栈明细] 线程名称：...（由 _detail_text 产出，回读靠它切块）
_DETAIL_HEADER = re.compile(r"^\[第 (?P<idx>\d+) 个线程堆栈明细\]")



@dataclass
class ThreadStack:
    name: str
    frames: list = field(default_factory=list)   # 归一化后的帧，已去 "at " 前缀
    state: object = None                         # 'TIMED_WAITING (parking)' 等



def artifact_stem(dump_path: str) -> str:
    """总报告与明细文件共用的主干：analysis_<dump主干>。"""
    return _ANALYSIS_PREFIX + os.path.splitext(os.path.basename(dump_path))[0]


def report_path(dump_path: str, out_dir: str) -> str:
    """总报告文件路径（内容由调用方写入）。"""
    return os.path.join(out_dir, artifact_stem(dump_path) + ".txt")


def detail_path(dump_path: str, out_dir: str, rank: int) -> str:
    """第 rank 个栈顶的明细文件路径。"""
    return os.path.join(out_dir, "%s%s%d.txt" % (artifact_stem(dump_path), _DETAIL_SUFFIX, rank))


def analyze_result_path(dump_path: str, out_dir: str) -> str:
    """analyze 阶段分析结果的落盘路径（analysis_<dump主干>_result.txt，内容由调用方写入）。"""
    return os.path.join(out_dir, artifact_stem(dump_path) + _RESULT_SUFFIX + ".txt")


def conclusion_path(dump_path: str, out_dir: str) -> str:
    """维度最终结论的落盘路径（analysis_<dump主干>_conclusion.txt，内容由调用方写入）。"""
    return os.path.join(out_dir, artifact_stem(dump_path) + _CONCLUSION_SUFFIX + ".txt")


# --- SSH 采集辅助（连服务器抓 dump；只有这里会碰网络）---

def _list_java_processes() -> str:
    """列出服务器上所有 Java 进程，返回 PID、用户和完整命令行。"""
    cmd = "ps -eo pid,user,args | grep -i java | grep -v grep"
    out, err = ssh_exec(cmd)
    if out.strip():
        return out.strip()
    if err.strip():
        return "获取进程列表失败: " + err.strip()
    return "未发现 Java 进程"


def _resolve_tool(pid: str, tool: str) -> str:
    """返回 jstack/jcmd 的可执行路径（优先进程所用 JDK），找不到返回空串。

    paramiko 的非交互 SSH 会话不加载 .bashrc/.bash_profile，PATH 里通常没有
    $JAVA_HOME/bin，导致裸 `jstack`/`jcmd` 报 command not found。
    """
    script = (
        f'B=$(dirname "$(readlink -f /proc/{pid}/exe 2>/dev/null)"); '
        f'[ -x "$B/{tool}" ] || B=$(dirname "$(dirname "$B")")/bin; '
        f'[ -x "$B/{tool}" ] || B=$(dirname "$(readlink -f "$(command -v java)" 2>/dev/null)"); '
        f'[ -x "$B/{tool}" ] && echo "$B/{tool}" || command -v {tool}'
    )
    out, _ = ssh_exec(script)
    return out.strip().splitlines()[0].strip() if out.strip() else ""


def _save_dump(pid: str, content: str) -> str:
    """把线程堆栈写入本机 DUMP_DIR，返回文件路径（thread_dump_<pid>_<时间戳>.txt）。"""
    os.makedirs(STACK_DUMP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(STACK_DUMP_DIR, f"thread_dump_{pid}_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def is_detail_file(path: str) -> bool:
    """判断是否本模块产出的栈顶明细文件（analysis_*_stacktop_*.txt）。

    白名单总闸：原始 dump（thread_dump_*.txt，上兆）绝不能按明细读给大模型。
    前缀/后缀只在这里判一次，调用方（jvm_stack_tools.py）不要再自己拼字符串判断。
    """
    name = os.path.basename(path or "")
    return name.startswith(_ANALYSIS_PREFIX) and _DETAIL_SUFFIX in name and name.endswith(".txt")


def read_detail_file(path: str) -> str:
    """读一个栈顶明细文件的全部线程栈，单次最多 _DETAIL_READ_LINES_MAX 行。

    一次读一个文件（= 一个栈顶下的全部代表线程），不再按线程拆读；超过上限**截断**，
    末行注明总行数与已显示范围，超出部分大模型就看不到了——上限是防深栈灌爆上下文的硬闸。
    帧行在写盘时已按 _FRAME_LINE_MAX 截断，这里不做「反截断」去回扫原始 dump：
    类名+方法已经够定位，回扫 1.6MB 原文得不偿失。
    内容不像明细文件时返回可读的错误字符串，不抛异常。
    """
    lines = _detail_lines(path)
    if not lines:
        return "该文件不是栈顶明细文件（未找到线程明细块）: %s" % path

    total = len(lines)
    out = lines[:_DETAIL_READ_LINES_MAX]
    if total > len(out):
        out.append("\n\n\n（本文件共 %d 行，已显示前 %d 行，其余 %d 行已截断）"
                   % (total, len(out), total - len(out)))
    else:
        out.append("\n\n\n（本文件共 %d 行，已全部显示）" % total)
    return _safe_text("\n".join(out))


def _detail_lines(path: str) -> list:
    """读出明细文件的有效行，丢掉空行与 _detail_text 留下的 \\r 残行。

    一条线程块头都没有，说明这不是明细文件，返回空列表让调用方报错。
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not any(_DETAIL_HEADER.match(ln) for ln in lines):
        return []
    return lines


def build_report(threads, dump_path: str, out_dir: str, group_prefix_line: int = _GROUP_PREFIX_LINE) -> str:
    """把线程列表压成总报告，并把每个栈顶的线程全栈明细各自落盘。

    结构：全局统计（状态分布）-> top_n 簇的栈顶摘要 + 该簇明细文件位置。
    去噪仅按栈深：len(t.frames) < _GROUP_FILTER_DEEP 的浅栈线程不参与聚类，状态分布仍基于全部线程。

    每个栈顶的明细写进 out_dir/<analysis_<dump主干>_stacktop_<n>.txt>，总报告里只记该路径，
    线程全栈不进总报告，也就不进大模型上下文。返回总报告文本。
    """

    os.makedirs(out_dir, exist_ok=True)

    #打印摘要
    lines = [
        "线程堆栈分析摘要：",
        "   1、展示前 %d 个高频栈顶。分析方式：取栈顶前 %d 行聚合；栈深小于 %d 的不参与聚合；线程数少于 %d 的栈顶不参与根因分析。"
        % (_TOP_N, group_prefix_line, _GROUP_FILTER_DEEP,_ANALYZER_FILTER_THREAD),
        "   2、线程总数: %d" % len(threads),
    ]
    state_counts = Counter(_base_state(t.state) for t in threads)
    lines.append("   3、线程状态分布: " + ", ".join("%s x %d个" % (s, c) for s, c in state_counts.most_common()))
    lines.append("\n")

    # 参与聚类的栈
    analyzed = [t for t in threads if len(t.frames) >= _GROUP_FILTER_DEEP]
    groups = {}
    for t in analyzed:
        #groups.setdefault() 是字典 dict 的方法，常用来做分组或计数
        #如果 key 存在不修改字典；如果 key 不存在插入 key。
        groups.setdefault(_key_of(t, group_prefix_line), []).append(t)
    #把 groups 按值（列表长度）从大到小排序（-len(kv[1])）；长度相同时，再按键从小到大排（kv[0]）。
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    #过滤线程数少的聚类
    ranked=[(key,members) for key,members in ranked if len(members) >= _ANALYZER_FILTER_THREAD]



    for rank, (key, members) in enumerate(ranked[:_TOP_N], 1):
        #打印栈顶
        states = Counter(_base_state(t.state) for t in members)
        names = Counter(_pattern(t.name) for t in members)
        lines.append("")
        lines.append("可疑堆栈的共同栈顶-%d: %d 个线程对应该栈顶。 线程状态分布：%s。最大栈深 %d 。最小栈深 %d"
            % (rank,
               len(members),
               "/".join("%s x %d个" % (s, c) for s, c in states.most_common(3)),
               max(len(t.frames) for t in members),
               min(len(t.frames) for t in members)))
        lines.append("  线程名: " + " ； ".join("%s x %d个" % (n, c) for n, c in names.most_common(3)))
        for i, f in enumerate(key,1):
            lines.append("  %2d. %s" % (i, f[:_FRAME_LINE_MAX]))
        if len(members[0].frames) > len(key):
            lines.append("  ...(已省略后续帧)")

        #线程全栈明细不再进总报告，只记录明细文件位置；明细各自落盘。
        path = detail_path(dump_path, out_dir, rank)
        lines.append("")
        lines.append("  该栈顶对应的 %d 个堆栈明细见: %s" % (_ALL_STACK_PER_GROUP,path))

        with open(path, "w", encoding="utf-8") as f:
            f.write(_detail_text(rank,members))

    return _safe_text("\n".join(lines))


def _detail_text(rank: int, members) -> str:
    """单个栈顶的线程全栈明细（纯本地文件内容，不交给大模型）。

    自带栈顶帧与线程头，便于脱离总报告单独阅读。
    """
    reps = _dedupe_by_stack(members, _ALL_STACK_PER_GROUP)
    lines = []

    for j, t in enumerate(reps, 1):
        lines.append("[第 %d 个线程堆栈明细] 线程名称：%s ；线程状态：(%s)；栈深 %d" % (j, t.name, _base_state(t.state), len(t.frames)))
        for i, f in enumerate(t.frames, 1):
            lines.append("    %2d. %s" % (i, f[:_FRAME_LINE_MAX]))

        lines.append("\r\n")

    return "\n".join(lines)



def normalize_frame(frame: str) -> str:
    """归一化一帧，抹掉每次 dump 都会变的噪声，便于模糊聚类。

    - /0x... 动态地址：必须抹，否则同一逻辑帧因地址不同被分成多簇，跨 dump 无法比较。
    - 代码行号 Foo.java:123 -> Foo.java。
    - JDK 模块前缀 java.base@21.0.12.1/：抹掉（单 dump 内恒定；跨 JDK 版本可比）。
    - (Native Method) / (Unknown Source)：保留原样，信息量大且短。
    """
    frame = _ADDR.sub("", frame)
    frame = _LINE_NO.sub(")", frame)
    return _MODULE.sub(r"(\1)", frame)



def parse_dump(text: str) -> list:
    """把整份 dump 解析成线程列表。

    线程边界只用线程头判定，绝不用「非帧行」判定：附属行（\\t- parking to wait for /
    locked / waiting on / waiting to lock）夹在帧中间，按非帧行切会把同一条线程切成
    2~3 段；也因此文件末尾最后一条线程不会丢。
    """
    threads = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw in text.split("\n"):
        if _FRAME.match(raw):
            if threads:
                threads[-1].frames.append(normalize_frame(raw[4:].strip()))
            continue
        m = _JAVA_HEADER.match(raw)
        if m:
            threads.append(ThreadStack(name=m.group("name")))
            continue
        m = _VM_HEADER.match(raw)
        if m:
            threads.append(ThreadStack(name=m.group("name")))
            continue
        m = _STATE.match(raw)
        if m and threads and threads[-1].state is None:
            threads[-1].state = m.group("state").strip()
        # 其余行一律忽略：Threads class SMR info 指针行 / 空行 / No compile task /
        # 末行 "JNI global refs: ..."
    return threads



def parse_dump_from_file(file_path: str) -> list:
    """读取堆栈文件并解析。"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return parse_dump(f.read())



def _key_of(t: ThreadStack, group_prefix_line: int):
    """聚类 key：只取栈顶前 group_prefix_line 帧，第 N 帧以后不参与聚类。"""
    return tuple(t.frames[:group_prefix_line] if group_prefix_line else t.frames)


def _dedupe_by_stack(members, limit):
    """按完整帧序列去重，按 dump 顺序返回前 limit 个不重复线程。"""
    seen, out = set(), []
    for t in members:
        k = tuple(t.frames)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= limit:
            break
    return out



def _pattern(name: str) -> str:
    """http-nio-8080-exec-330 -> http-nio-*-exec-*"""
    return re.sub(r"\d+", "*", name)



def _safe_text(s: str) -> str:
    """摘要出口收口：保证结果能被 GBK 控制台 print 而不抛 UnicodeEncodeError。

    只作用于摘要字符串，绝不作用于 dump 文件本身（原文件保持 UTF-8 原样）。
    代价是极罕见的非 GBK 线程名会变成 '?'，对模型理解无影响。
    """
    try:
        s.encode("gbk")
        return s
    except UnicodeEncodeError:
        return s.encode("gbk", "replace").decode("gbk")



def _base_state(state) -> str:
    """'TIMED_WAITING (parking)' -> 'TIMED_WAITING'；None(VM/GC 线程) -> '无状态'。"""
    if not state:
        return "无状态"
    return state.split()[0]