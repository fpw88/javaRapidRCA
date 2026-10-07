"""慢日志原始输出的确定性解析与聚合。

纯标准库、无 LangChain 依赖。把 `slowlog get N`（非 raw）的 RESP 原文解析成结构化条目，
再聚合成 SlowlogSummary（O(N) 计数、大key/热key 分组、INCR 计数、TOP 命令）。原文不进大模型。
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# 大key/热key 候选口径：同 (cmd,key) 出现 ≥ BIG_KEY_MIN_COUNT 次且平均耗时 ≥ BIG_KEY_MIN_AVG_MS
BIG_KEY_MIN_COUNT = 10    # 同 (cmd,key) 出现 ≥ 此值 视为「大key/热key」候选
BIG_KEY_MIN_AVG_MS = 10.0  # 同 (cmd,key) 平均耗时 ≥ 此值 才视为「耗时久」

# O(N)/集合操作命令白名单（命中即计入 o_n_count）
O_N_COMMANDS = {
    "KEYS", "HGETALL", "SMEMBERS", "LRANGE", "ZRANGE", "ZRANGEBYSCORE",
    "ZRANGEBYLEX", "ZREVRANGE", "ZREVRANGEBYSCORE", "SORT", "SSCAN", "HSCAN",
    "ZSCAN", "SUNION", "SUNIONSTORE", "SINTER", "SINTERSTORE", "SDIFF", "SDIFFSTORE",
    "SMOVE", "ZUNIONSTORE", "ZINTERSTORE",
}
# INCR 类命令（大量出现 → 提示固有延时高，而非慢日志本身是根因）
INCR_COMMANDS = {"INCR", "INCRBY", "INCRBYFLOAT", "DECR", "DECRBY"}

# 条目头：外层下标 + 内层字段1(id)  `1) 1) (integer) 14`
_SLOWLOG_ENTRY = re.compile(r'^[ \t]*\d+\)\s+\d+\)\s+\(integer\)\s+\d+\s*$')
_SLOWLOG_DURATION = re.compile(r'^[ \t]*3\)\s+\(integer\)\s+(\d+)\s*$', re.M)
_SLOWLOG_CMD = re.compile(r'^[ \t]*4\)\s+1\)\s+"([^"]*)"\s*$', re.M)
# 参数续行（更深缩进，≥4 空格）里的 quoted 值；字段5/6（客户端地址/名字）缩进较浅，不会命中
_SLOWLOG_ARG = re.compile(r'^[ \t]{4,}\d+\)\s+"([^"]*)"\s*$', re.M)


@dataclass
class SlowlogEntry:
    duration_us: int = 0
    cmd: str = ""
    key: str = ""

    @property
    def duration_ms(self) -> float:
        return self.duration_us / 1000.0


@dataclass
class BigKeyGroup:
    cmd: str
    key: str
    count: int
    avg_ms: float


@dataclass
class SlowlogSummary:
    count: int = 0
    entries: list = field(default_factory=list)
    o_n_count: int = 0
    big_key_groups: list = field(default_factory=list)  # list[BigKeyGroup]
    incr_count: int = 0
    top_commands: list = field(default_factory=list)    # list[(cmd, count)]


def parse_redis_slowlog(text: str) -> Optional[SlowlogSummary]:
    """解析 `slowlog get N`（非 raw）输出，聚合成结构化摘要。

    每个条目按 SLOWLOG GET 的固定字段序 [id, timestamp, duration(μs), args, client, name]
    提取：duration(字段3)、cmd(args[0])、key(args[1])。
    """
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r'(?=' + _SLOWLOG_ENTRY.pattern + r')', text, flags=re.M)

    entries = []
    for block in blocks:
        if not block.strip():
            continue
        dm = _SLOWLOG_DURATION.search(block)
        if not dm:
            continue
        duration_us = int(dm.group(1))
        cmd_m = _SLOWLOG_CMD.search(block)
        cmd = cmd_m.group(1) if cmd_m else ""
        key = ""
        if cmd_m:
            tail = block[cmd_m.end():]
            km = _SLOWLOG_ARG.search(tail)
            if km:
                key = km.group(1)
        entries.append(SlowlogEntry(duration_us=duration_us, cmd=cmd.upper(), key=key))

    if not entries:
        # 无慢日志（slowlog len=0）也算有效：返回空 summary，不当作解析失败
        return SlowlogSummary(count=0)

    o_n_count = sum(1 for e in entries if e.cmd in O_N_COMMANDS)
    incr_count = sum(1 for e in entries if e.cmd in INCR_COMMANDS)
    top_commands = Counter(e.cmd for e in entries).most_common(5)

    # 大key/热key：同 (cmd,key) 高频且平均耗时久（INCR 类无 key 语义，跳过）
    groups = {}
    for e in entries:
        if not e.key or e.cmd in INCR_COMMANDS:
            continue
        groups.setdefault((e.cmd, e.key), []).append(e.duration_ms)
    big = []
    for (cmd, key), durs in groups.items():
        cnt = len(durs)
        avg = sum(durs) / cnt
        if cnt >= BIG_KEY_MIN_COUNT and avg >= BIG_KEY_MIN_AVG_MS:
            big.append(BigKeyGroup(cmd=cmd, key=key, count=cnt, avg_ms=avg))
    big.sort(key=lambda g: (-g.avg_ms, -g.count))

    return SlowlogSummary(
        count=len(entries),
        entries=entries,
        o_n_count=o_n_count,
        big_key_groups=big,
        incr_count=incr_count,
        top_commands=top_commands,
    )
