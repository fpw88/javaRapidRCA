"""LangChain 工具：列出 Java 进程、抓取线程堆栈。逻辑在 util/jvm_stack_util.py，这里只是工具壳。"""
import os
from typing import Annotated

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.types import Command, interrupt

from config.config import STACK_DUMP_DIR
from util._common import write_text
from util.ssh_client import ssh_exec
from util.jvm_stack_util import (
    parse_dump_from_file,
    build_report,
    report_path,
    is_detail_file,
    read_detail_file,
    _list_java_processes,
    _resolve_tool,
    _save_dump,
)


@tool
def get_thread_dump() -> str:
    """获取某个 Java 进程的线程堆栈，保存到本地文件（不把堆栈内容交给大模型）。

    会先展示进程列表，然后中断询问用户选择 PID（人工在环）。
    """
    procs = _list_java_processes()
    pid = interrupt({
        "question": "请输入要抓取线程堆栈的 PID",
        "processes": procs,
    })
    pid = str(pid).strip()
    if not pid:
        return "未选择 PID，操作已取消。"

    # 定位 jstack/jcmd 真实路径（非交互 SSH 的 PATH 可能不含 JDK bin）
    jstack = _resolve_tool(pid, "jstack")
    jcmd = _resolve_tool(pid, "jcmd")

    out, err = "", ""
    if jstack:
        out, err = ssh_exec(f"{jstack} {pid}")
    if not out.strip() and jcmd:
        out, err = ssh_exec(f"{jcmd} {pid} Thread.print")
    if out.strip():
        path = _save_dump(pid, out.strip())
        return f"线程堆栈已保存到本地文件: {path}（{len(out.encode('utf-8'))} 字节），未交给大模型分析。"
    return f"无法获取 PID {pid} 的线程堆栈: {err.strip() or '未找到可用的 jstack/jcmd'}"





@tool
def analyze_thread_dump(file_path: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """分析已保存的线程堆栈文件，统计高频调用序列。

    只读本地文件，不连服务器。总报告只含栈顶摘要与各明细文件路径；每个栈顶的
    线程全栈明细由 build_report 各自落盘，堆栈原文不返回给大模型。
    拿到 get_thread_dump 的文件路径后必须调用本工具。
    同时把本次分析的堆栈文件路径回写到 state 字段 jvm_stack_dump_file_path，供溯源产物命名。
    """
    if not os.path.isfile(file_path):
        return f"找不到文件: {file_path}"
    try:
        threads = parse_dump_from_file(file_path)
    except OSError as e:
        return f"读取堆栈文件失败: {e}"

    summary = build_report(threads, file_path, STACK_DUMP_DIR)
    report = write_text(report_path(file_path, STACK_DUMP_DIR), summary)

    return Command(update={
        # 原样存调用方给的路径，落盘时再取 basename 命名
        "jvm_stack_dump_file_path": file_path,
        "messages": [ToolMessage(
            content=f"分析报告已保存: {report}\n{summary}",
            tool_call_id=tool_call_id,
        )],
    })



@tool
def read_stack_detail(file_path: str) -> str:
    """读取一个栈顶明细文件里的全部线程栈，用于聚合定位根因。

    总报告里每个可疑栈顶都带一行「该栈顶对应的 N 个堆栈明细见: <路径>」，把这个路径传进来即可：
    - 一个可疑栈顶仅读一次对应的栈明细文件。
    - 明细内容全部读到，在末尾会明确说明：全读到了。
    - 明细文件超过一定长度会被截断，在末尾也会明确说明被截断了。如果没有明确说明被截断的也表示被截断了。截断后也结束不再读取。
    只能读 analysis_*_stacktop_*.txt 明细文件，原始 dump 不提供给大模型。
    """
    if not os.path.isfile(file_path):
        return f"找不到文件: {file_path}"
    # 白名单：路径必须落在 dumps/ 且是明细文件，挡住原始 dump 被整份读进上下文
    if os.path.normpath(os.path.dirname(os.path.abspath(file_path))) != os.path.normpath(STACK_DUMP_DIR) or not is_detail_file(file_path):
        return (f"只能读取栈顶明细文件（{STACK_DUMP_DIR} 下的 analysis_*_stacktop_*.txt），"
                f"原始堆栈文件不提供给大模型: {file_path}")
    return read_detail_file(file_path)


if __name__ == "__main__":
    # 用 DUMP_DIR 拼绝对路径，回到仓库根 `python -m tools.jvm_stack_tools` 也能跑
    file_path = os.path.join(STACK_DUMP_DIR, "thread_dump_5309_20261002_175519.txt")
    result = analyze_thread_dump.func(file_path, tool_call_id="selftest")
    if isinstance(result, Command):  # 正常分支回写 state，异常分支（文件不存在等）仍返回字符串
        print(result.update["messages"][0].content)
        print("回写的堆栈文件路径:", result.update["jvm_stack_dump_file_path"])
    else:
        print(result)

    # 明细回读自测（离线，不连服务器）
    detail = os.path.join(STACK_DUMP_DIR, "analysis_thread_dump_5309_20261002_175519_stacktop_1.txt")
    print("\n[读明细文件]")
    print(read_stack_detail.func(detail))
    print("\n[读原始 dump 应被拒]")
    print(read_stack_detail.func(file_path))

