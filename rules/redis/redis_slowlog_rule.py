"""慢日志的确定性判级。

解析层 `parse_redis_slowlog` 只吐结构化聚合（O(N) 计数、大key分组、INCR 计数、TOP）；
「多少条算大量」这类阈值住在规则层，见 redis_threshold.py。
纯标准库、不碰网络、不依赖 LangChain。
"""
from typing import Optional

from parse_metrics.redis import SlowlogSummary
from rules.redis.redis_threshold import INCR_MIN_COUNT, O_N_P0_MIN_COUNT
from rules.redis.redis_types import FactorFlag


def grade_redis_slowlog(slowlog: Optional[SlowlogSummary]) -> FactorFlag:
    """慢日志判级：大量 O(N) 或大key/热key 定 P0；大量 INCR 是固有延时高的提示。"""
    if slowlog is None:
        return FactorFlag("slowlog", "", ["慢日志采集失败/解析失败"], [])
    parts = ["慢日志共 %d 条：O(N)命令 %d 条，大key/热key组 %d 个，INCR类 %d 条"
             % (slowlog.count, slowlog.o_n_count, len(slowlog.big_key_groups), slowlog.incr_count)]
    if slowlog.top_commands:
        parts.append("TOP: " + " ".join("%s×%d" % (c, n) for c, n in slowlog.top_commands))
    grade, ev, score = "", "", None
    if slowlog.o_n_count >= O_N_P0_MIN_COUNT:
        grade = "P0"
        # 条数越多分越高：刚够阈值 80 分，两倍阈值及以上封顶 98
        score = min(98, int(round(80 + 18 * min(
            (slowlog.o_n_count - O_N_P0_MIN_COUNT) / O_N_P0_MIN_COUNT, 1.0))))
        ev = "O(N)/集合操作命令 %d 条（≥%d）" % (slowlog.o_n_count, O_N_P0_MIN_COUNT)
    elif slowlog.big_key_groups:
        g = slowlog.big_key_groups[0]
        grade = "P0"
        score = 80  # 仅靠大key/热key命中：定额（无「超出多少」可量化，取 P0 下限）
        ev = "大key/热key：%s %s 出现 %d 次，平均 %.1fms" % (g.cmd, g.key, g.count, g.avg_ms)
    if slowlog.incr_count >= INCR_MIN_COUNT:
        parts.append("（大量 INCR：%d 条，提示可能是固有延时高导致，而非慢日志本身）" % slowlog.incr_count)
    if slowlog.big_key_groups:
        detail = "；".join("%s %s ×%d avg%.1fms" % (g.cmd, g.key, g.count, g.avg_ms)
                           for g in slowlog.big_key_groups[:3])
        parts.append("大key明细: " + detail)
    return FactorFlag("slowlog", grade, parts, [ev] if ev else [], score=score)
