"""固有延时的确定性判级。

1、redis 官方给出的延迟质量参考标准如下
    最大延迟范围	      系统质量评估
    < 100 微秒	        优秀
    100 - 500 微秒	    对大多数工作负载可接受
    500 - 1000 微秒	    需要调优
    > 1 毫秒	            存在严重的操作系统干扰

    “最差运行”比平均值高出 10 倍或更多，表明操作系统正在引入抖动。

https://raw.githubusercontent.com/OneUptime/blog/refs/heads/master/posts/2026-03-31-redis-cli-intrinsic-latency-system/README.md#1

2、如下阈值，根据实际故障案例设置。可按需调整
"""
from typing import Optional

from parse_metrics.redis import IntrinsicLatency
from rules.grade import GRADE_P0, GRADE_P1
from rules.redis.redis_threshold import INTRINSIC_P0_MS, INTRINSIC_P1_MS
from rules.redis.redis_types import FactorFlag, score_from_overshoot


def grade_redis_intrinsic(intrinsic: Optional[IntrinsicLatency]) -> FactorFlag:
    """固有延时判级：max ≥ INTRINSIC_P0_MS 定 P0、≥ INTRINSIC_P1_MS 定 P1（用 max 作度量）。"""
    if intrinsic is None:
        return FactorFlag("intrinsic", "", ["固有延时采集失败/解析失败"], [])
    if intrinsic.max_ms >= INTRINSIC_P0_MS:
        grade, ev = GRADE_P0, f"固有延时 max={intrinsic.max_ms} ms ≥ {INTRINSIC_P0_MS} ms"
    elif intrinsic.max_ms >= INTRINSIC_P1_MS:
        grade, ev = GRADE_P1, f"固有延时 max={intrinsic.max_ms} ms ≥ {INTRINSIC_P1_MS} ms"
    else:
        grade, ev = "", ""

    summary = [
        (f"固有延时指标数据：max={intrinsic.max_ms} ms，avg={intrinsic.avg_ms} ms，"
         f"最差运行比平均值高出 {intrinsic.worst_mult} 倍。\n"
        f"固有延时阈值：≥ {INTRINSIC_P0_MS} ms 定 P0 / ≥ {INTRINSIC_P1_MS} ms 定 P1"),
    ]

    return FactorFlag(
        factor="intrinsic",
        grade=grade,
        summary=summary,
        evidence=[ev] if ev else [],
        score=score_from_overshoot(intrinsic.max_ms, INTRINSIC_P1_MS, INTRINSIC_P0_MS),
    )
