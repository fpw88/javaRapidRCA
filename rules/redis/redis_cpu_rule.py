"""CPU 使用率的判据（不单独定级，只报数值与「是否持续高」）。

解析层只吐原始采样 `CpuUsage.pcts`，「是否持续高」这类阈值判断在本层，见 redis_threshold.py。
CPU 因子不参与逐因子定级：`grade_redis_cpu` 的 grade 恒为 ""；CPU 因子的**最终** grade 由组合规则
`redis_cpu_escalation_rule.py`（CPU 持续高时归并命中的延时因子）写入。
本模块提供 CPU 因子摘要文案，以及被组合规则消费的 `cpu_sustained` / `_gt90_count`。
纯标准库、不碰网络、不依赖 LangChain。
"""
from typing import Optional

from parse_metrics.redis import CpuUsage
from rules.redis.redis_threshold import CPU_HIGH_PCT
from rules.redis.redis_types import FactorFlag


def _gt90_count(cpu: Optional[CpuUsage]) -> int:
    """采样里使用率 >CPU_HIGH_PCT 的次数（阈值属本层，解析层只给原始采样）。"""
    if cpu is None:
        return 0
    return sum(1 for v in cpu.pcts if v > CPU_HIGH_PCT)


def cpu_sustained(cpu: Optional[CpuUsage]) -> bool:
    """CPU 是否「持续 >90%」：均值超阈值，或多数采样点 >90%。"""
    if cpu is None:
        return False
    return cpu.mean_pct > CPU_HIGH_PCT or _gt90_count(cpu) >= max(1, cpu.samples // 2)


def grade_redis_cpu(cpu: Optional[CpuUsage]) -> FactorFlag:
    """CPU 因子摘要：本函数的 grade 恒为 ""（不单独定级），只报告数值与是否「持续高」。

    CPU 因子的最终 grade 可能由组合规则 redis_cpu_escalation_rule.py 写入。
    """
    if cpu is None:
        return FactorFlag("cpu", "", ["CPU 采集失败/解析失败"], [])

    summary = [
        (f"CPU指标数据：均值={cpu.mean_pct}%，峰值={cpu.max_pct}%，采样次数={cpu.samples}，> {CPU_HIGH_PCT}%次数={_gt90_count(cpu)}"),
    ]

    return FactorFlag("cpu", "", summary, [])
