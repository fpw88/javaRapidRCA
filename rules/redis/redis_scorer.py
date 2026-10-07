"""redis 各因子的判级组装：逐因子判级 → 组合规则归并 → 整体得分/定级。

逐因子判级各在自己模块（redis_<metric>_rule.py），跨因子的组合规则在
redis_cpu_escalation_rule.py，本模块只做组装与整体归纳。
纯标准库、不碰网络、不依赖 LangChain。
"""
from typing import Optional
from rules.grade import grade_from_score
from parse_metrics.redis import CpuUsage, IntrinsicLatency, RedisNetLatency, SlowlogSummary
from rules.redis.redis_cpu_escalation_rule import apply_cpu_escalation
from rules.redis.redis_cpu_rule import grade_redis_cpu
from rules.redis.redis_intrinsic_rule import grade_redis_intrinsic
from rules.redis.redis_net_rule import grade_redis_net
from rules.redis.redis_slowlog_rule import grade_redis_slowlog
from rules.redis.redis_types import RedisScore


def score_redis(net: Optional[RedisNetLatency], intrinsic: Optional[IntrinsicLatency],
                cpu: Optional[CpuUsage], slowlog: Optional[SlowlogSummary]) -> RedisScore:
    # 顺序执行规则
    factors = [
        grade_redis_intrinsic(intrinsic),
        grade_redis_net(net),
        grade_redis_cpu(cpu),
        grade_redis_slowlog(slowlog),
    ]

    #CPU 持续高时：归并固有延时、网络延时
    factors = apply_cpu_escalation(factors, cpu)

    overall = _compute_overall_score(factors)
    return RedisScore(factors=factors, score=overall, grade=grade_from_score(overall))


def _compute_overall_score(factors) -> Optional[int]:
    """由逐因子判级归纳出 redis 侧的确定性整体得分（None=未命中任何阈值）。"""
    p0 = sum(1 for f in factors if f.grade == "P0")
    p1 = sum(1 for f in factors if f.grade == "P1")
    if p0:
        return min(80 + 5 * (p0 - 1) + 2 * p1, 98)
    if p1:
        return min(50 + 5 * (p1 - 1), 74)
    return None
