"""固有延时原始输出的确定性解析。

纯标准库、无 LangChain 依赖。解析 `redis-cli --intrinsic-latency N` 输出，并把
单位从 μs 归一成 ms（阈值是 ms、原文是 μs，归一避免判级单位错位）。
"""
import re
from dataclasses import dataclass
from typing import Optional

_INTRINSIC_MAX = re.compile(r'Max latency so far:\s*([\d.]+)\s*microseconds')
_INTRINSIC_AVG_US = re.compile(r'avg latency:\s*([\d.]+)\s*microseconds')
_INTRINSIC_AVG_NS = re.compile(r'avg latency:\s*[\d.]+\s*microseconds\s*/\s*([\d.]+)\s*nanoseconds')
_INTRINSIC_WORST = re.compile(r'Worst run took\s*([\d.]+)x')


@dataclass
class IntrinsicLatency:
    max_ms: float = 0.0
    avg_ms: float = 0.0
    worst_mult: float = 0.0


def parse_redis_intrinsic_latency(text: str) -> Optional[IntrinsicLatency]:
    """解析 `redis-cli --intrinsic-latency N` 输出，单位归一 μs→ms。

    取最后一次 `Max latency so far: X microseconds` 为 max；`avg latency: X microseconds`
    为 avg；`Worst run took Xx` 为最差倍数。
    """
    if not text:
        return None
    maxes = _INTRINSIC_MAX.findall(text)
    if not maxes:
        return None
    max_us = float(maxes[-1])
    avg_m = _INTRINSIC_AVG_US.search(text)
    avg_us = float(avg_m.group(1)) if avg_m else 0.0
    if avg_m is None:
        avg_ns = _INTRINSIC_AVG_NS.search(text)
        if avg_ns:
            avg_us = float(avg_ns.group(1)) / 1000.0
    worst = _INTRINSIC_WORST.search(text)
    return IntrinsicLatency(
        max_ms=max_us / 1000.0,
        avg_ms=avg_us / 1000.0,
        worst_mult=float(worst.group(1)) if worst else 0.0,
    )
