"""CPU 使用率原始输出的确定性解析。

纯标准库、无 LangChain 依赖。解析 `top -b` 的 %Cpu 行（已由 grep 过滤），
cpu 使用率 = 100 - id。本层不套任何阈值：逐次采样的使用率原样放进 CpuUsage.pcts，
「是否持续 >90%」这类判断属于规则层（rules/redis/redis_cpu_rule.py）。
"""
import re
from dataclasses import dataclass
from typing import Optional

_CPU_IDLE = re.compile(r'([\d.]+)\s+id\b')


@dataclass
class CpuUsage:
    mean_pct: float = 0.0
    max_pct: float = 0.0
    samples: int = 0
    pcts: tuple = ()   # 逐次采样的整机使用率，供规则层按自己的阈值判「持续高」


def parse_redis_cpu_usage(text: str) -> Optional[CpuUsage]:
    """解析 `top -b` 的 %Cpu 行（grep '%Cpu' 过滤后），cpu 使用率 = 100 - id。"""
    if not text:
        return None
    vals = []
    for line in text.splitlines():
        m = _CPU_IDLE.search(line)
        if m:
            vals.append(100.0 - float(m.group(1)))
    if not vals:
        return None
    return CpuUsage(
        mean_pct=sum(vals) / len(vals),
        max_pct=max(vals),
        samples=len(vals),
        pcts=tuple(vals),
    )
