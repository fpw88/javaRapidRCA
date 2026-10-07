"""网络延时的确定性判级。

1、Redis Cloud 默认告警：“延迟高于”的默认触发阈值为 10 毫秒
https://support.redislabs.com/hc/en-us/articles/28281180049298-Setting-Up-Alerts-in-Redis-Cloud

"""
from typing import Optional

from parse_metrics.redis import RedisNetLatency
from rules.grade import GRADE_P0, GRADE_P1
from rules.redis.redis_threshold import NET_P1_MS, NET_P0_MS
from rules.redis.redis_types import FactorFlag, score_from_overshoot


def grade_redis_net(net: Optional[RedisNetLatency]) -> FactorFlag:
    """网络延时判级：均值 ≥ NET_P0_MS 定 P0、≥ NET_P1_MS 定 P1（用 avg 作度量）。"""
    if net is None:
        return FactorFlag("net", "", ["网络延时采集失败/解析失败"], [])
    if net.avg_ms >= NET_P0_MS:
        grade = GRADE_P0
        ev = f"网络延时均值 {net.avg_ms:.3f} ms ≥ {NET_P0_MS:.0f}ms"
    elif net.avg_ms >= NET_P1_MS:
        grade = GRADE_P1
        ev = f"网络延时均值 {net.avg_ms:.3f} ms ≥ {NET_P1_MS:.0f}ms"
    else:
        grade, ev = "", ""

    summary = [
        (f"网络延时指标数据： min={net.min_ms:.3f} ms max={net.max_ms:.3f} ms avg={net.avg_ms:.3f} ms 采样={net.samples}，\n"
         f"网络延时阈值： avg ≥ {NET_P0_MS:.0f}ms 定 P0 / ≥ {NET_P1_MS:.0f}ms 定 P1"),
    ]

    return FactorFlag(
        factor="net",
        grade=grade,
        summary=summary,
        evidence=[ev] if ev else [],
        score=score_from_overshoot(net.avg_ms, NET_P1_MS, NET_P0_MS),
    )
