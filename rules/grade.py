"""根因定级与排序的共享工具（纯标准库，无 LangChain 依赖）。

统一「grade（P0/P1/P2/未定级）+ score（0-100）」的阈值、标记格式与排序键，
供规则引擎（rules/redis/redis_scorer.py）、jvm 子图汇聚（core/nodes/jvm_stack_nodes/）
与汇聚层（core/nodes/aggregate.py）共用，保证定级口径一致。

本模块是 rules/ 下的**跨维度通用口径**，不属于任何 rules/<middleware>/ 子包——各维度的
判级阈值（如固有延时的 INTRINSIC_P0_MS，见 rules/redis/redis_threshold.py）在各自子包里，
这里只统一「score 怎么映射成 grade」。

约定：score 是连续主信号（0-100），grade 由 score 阈值映射，保证二者单调一致、排序简单。
"""
import re

GRADE_P0="P0"
GRADE_P1="P1"

# score → grade 阈值
GRADE_P0_MIN = 80
GRADE_P1_MIN = 50

# grade 优先级（越小越靠前）；未定级用 "" 表示、排最后
GRADE_RANK = {"P0": 0, "P1": 1, "P2": 2}

# 维度结论末尾的定级标记格式
GRADE_SCORE_MARKER = "[GRADE=<P0|P1|P2> SCORE=<0-100>]"
_GRADE_SCORE_RE = re.compile(r"\[GRADE\s*=\s*(P0|P1|P2)?\s*SCORE\s*=\s*(\d{1,3})\s*\]", re.IGNORECASE)


def grade_from_score(score) -> str:
    """score(0-100) → grade；None/空 → 未定级('')。"""
    if score is None:
        return ""
    if score >= GRADE_P0_MIN:
        return "P0"
    if score >= GRADE_P1_MIN:
        return "P1"
    return "P2"


def grade_rank(grade) -> int:
    """grade 的排序优先级：P0=0 < P1=1 < P2=2 < 未定级=3。"""
    return GRADE_RANK.get(str(grade).upper(), 3)


def higher_grade(*grades) -> str:
    """取多个 grade 中的最高者（P0 > P1 > P2 > 未定级）。

    非法值 / 空 / None 一律忽略；全为未定级时返回 ""。跨维度通用口径：
    grade 比较一律走 GRADE_RANK，各维度勿再自写 if/elif。
    """
    best = ""
    for g in grades:
        g = str(g or "").strip().upper()
        if g not in GRADE_RANK:
            continue
        if not best or GRADE_RANK[g] < GRADE_RANK[best]:
            best = g
    return best


def parse_grade_score(text) -> tuple:
    """从结论文本解析定级标记，返回 (grade, score)。

    grade 以 score 为准归一（保证二者一致）；未匹配到标记返回 ("", None)。
    """
    m = _GRADE_SCORE_RE.search(text or "")
    if not m:
        return "", None
    score = int(m.group(2))
    return grade_from_score(score), score


def strip_grade_score(text) -> str:
    """去掉结论文本里的定级标记（用于注入确定性定级前清理）。"""
    return _GRADE_SCORE_RE.sub("", text or "").strip()


def grade_score_line(grade, score) -> str:
    """渲染一行定级标记。"""
    return "[GRADE=%s SCORE=%s]" % (grade, score)


def sort_key(entry: dict):
    """root cause 候选的确定性排序键：先 grade、再 score 降序、再证据条数降序。

    entry 形如 {"dimension":..., "grade":"P0", "score":90, "evidence":[...], ...}。
    未定级（无 grade/score）排最后；三者都并列时保持传入顺序（稳定排序）。
    """
    score = entry.get("score")
    grade = entry.get("grade") or grade_from_score(score)
    if score is None:
        score = -1.0
    else:
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = -1.0
    evidence_n = len(entry.get("evidence") or [])
    return (grade_rank(grade), -score, -evidence_n)
