"""CPU 持续高时：归并固有延时、网络延时的摘要、证据

CPU 持续高会引起固有延时/网络延时升高，三者本是同一条因果链。归并规则如下：
1、cpu的grade使用固有延时、（和、或）网络延时中的高者
2、合并固有延时、网络延时的摘要、证据
3、指定根因描述话术、处理建议话术
"""
from dataclasses import replace
from typing import Optional

from parse_metrics.redis import CpuUsage
from rules.grade import GRADE_P0, GRADE_P1, higher_grade
from rules.redis.redis_cpu_rule import cpu_sustained
from rules.redis.redis_types import FACTOR_NAME, FactorFlag


ROOT_CAUSE_TEMPLATE = (
    "redis服务器cpu使用率较高，导致redis服务器的{factor_names}较高，进而阻塞java程序运行。"
)

CUSTOM_SUGGESTION = ["先排查redis服务器的cpu是不是由其他进程占用。降低redis服务器的cpu使用率后再次排查。"]

# 会被并入 CPU 的延时因子
_LATENCY_FACTORS = ("intrinsic", "net")


def apply_cpu_escalation(factors: list[FactorFlag], cpu: Optional[CpuUsage]) -> list[FactorFlag]:
    """命中条件时把延时因子并入 cpu 并移除命中的延时因子
    """
    if not cpu_sustained(cpu):
        return factors

    hits = [f for f in factors if f.factor in _LATENCY_FACTORS and f.grade in (GRADE_P0, GRADE_P1)]
    if not hits:
        return factors

    hit_names = {f.factor for f in hits}
    merged = []
    for f in factors:
        if f.factor in hit_names:
            continue  # 命中的延时因子并入 cpu，不再单列
        if f.factor == "cpu":
            f = replace(  # 不改动 grade_redis_cpu 返回的对象本身
                f,
                grade=higher_grade(f.grade, *(h.grade for h in hits)),
                score=_highest_score(hits),
                summary=list(f.summary) + [s for h in hits for s in h.summary],
                evidence=list(f.evidence) + [e for h in hits for e in h.evidence],
                custom_root_cause=_root_cause_text(hits),
                custom_suggestion=list(CUSTOM_SUGGESTION),
            )
        merged.append(f)
    return merged


def _highest_score(hits) -> Optional[int]:
    """被并入因子的最高分（都没取分则 None）。

    与 grade 取高者用同一个 merged 集合，保证 grade_from_score(score) 仍等于合并后的 grade。
    """
    scores = [h.score for h in hits if h.score is not None]
    return max(scores) if scores else None


def _root_cause_text(hits) -> str:
    """按「命中的」延时因子生成根因文案：匹配到哪个就只写哪个。。
    """
    names = "、".join(FACTOR_NAME.get(h.factor, h.factor) for h in hits)
    return ROOT_CAUSE_TEMPLATE.format(factor_names=names)
