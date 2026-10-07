"""redis 规则层的数据模型与因子口径。

`FactorFlag` / `RedisScore` 是判级结果的数据类（对外 API）；`FACTOR_NAME` / `FACTOR_KEYS`
是包内跨模块共用的因子口径——判级、渲染、校验三处都按同一套因子名与顺序走，改口径只动这里。
`factor_sort_key` / `score_from_overshoot` 是因子级展示顺序与取分口径，同样只此一处。
纯标准库、不碰网络、不依赖 LangChain。
"""
from dataclasses import dataclass, field
from typing import Optional

from rules.grade import grade_rank


@dataclass
class FactorFlag:
    """判级因子口径"""
    factor: str       # "net" | "intrinsic" | "cpu" | "slowlog"
    grade: str        # "P0" | "P1" | "P2" | ""（空=未命中阈值）
    summary: list[str]   # 数值摘要（含阈值是否命中），每个元素一行/一个要点
    evidence: list[str]  # 命中时的证据描述列表（未命中为空列表）
    custom_root_cause: str = ""          # 用户自定义的根因描述话术。用户未自定义时再由大模型发挥
    custom_suggestion: list[str] = field(default_factory=list)    # 用户自定义的处理建议话术。用户未自定义时再由大模型发挥
    score: Optional[int] = None          # 因子级得分（0-100）；None=未取分 → 排序时同定级内垫底


@dataclass
class RedisScore:
    factors: list[FactorFlag] = field(default_factory=list)  # list[FactorFlag]
    digest: str = ""                             # format_digest 产物（校验器据此取已知数值）
    score: Optional[int] = None                  # 整体确定性得分（0-100；None=未命中任何阈值）
    grade: str = ""                              # 整体确定性定级（由 score 映射；空=未定级）


# ----------------------------------------------------------------- 因子口径（包内共用，不对包外导出）

FACTOR_NAME = {
    "net": "网络延时",
    "intrinsic": "固有延时",
    "cpu": "CPU使用率",
    "slowlog": "慢日志",
}

# 校验层认的合法 factor（顺序沿用原实现）
FACTOR_KEYS = ("slowlog", "intrinsic", "net", "cpu")


# ----------------------------------------------------------------- 因子级 score 与展示顺序

def score_from_overshoot(value: float, p1: float, p0: float) -> Optional[int]:
    """按「实测值超出阈值的幅度」给因子级得分（0-100），与 grade 口径自洽。

    低于 P1 阈值 → None（未命中，不给分）；[p1, p0) → 50~79（对应 P1）；
    ≥ p0 → 80~98（对应 P0，超出越多分越高）。
    上界钳制保证 grade_from_score(结果) 恒等于该因子的 grade，二者不会互相矛盾。
    """
    if value is None or value < p1:
        return None
    if value < p0:
        return min(79, int(round(50 + 30 * (value - p1) / (p0 - p1))))
    return int(round(80 + 18 * min((value - p0) / p0, 1.0)))


def factor_sort_key(f: FactorFlag) -> tuple:
    """因子的展示顺序：先 grade 优先级，grade 相同再按 score 降序。

    score 缺失时在**同定级内**垫底；同分/同缺分之间不做确定性约束（stable sort
    保持原顺序），最终先后由大模型判断。
    """
    return (grade_rank(f.grade), -(f.score if f.score is not None else -1))
