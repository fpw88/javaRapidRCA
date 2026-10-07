"""汇聚层：把本轮各维度结论汇总成根因排序报告。"""
import json
import re

from langchain_core.messages import AIMessage, SystemMessage

from core.llm import LLM
from core.states import RcaState
from prompt import prompt_templates as prompts
from util._common import _as_text
from rules.grade import parse_grade_score, sort_key
from util.log import get_logger

logger = get_logger(__name__)

_DIM_NAME_RE = re.compile(r"维度结论\[([^\]]*)\]:")


def _dim_name(text: str) -> str:
    """从「维度结论[<维度名>]: …」落款里提取维度名。"""
    m = _DIM_NAME_RE.search(text or "")
    return m.group(1) if m else "未知维度"


def aggregate(state: RcaState) -> dict:
    """汇聚层：汇总本轮各维度结论 → 根因排序 → 报告。"""
    current = list(state["messages"])[state.get("round_start", 0):]  # 本轮各维度结论
    conclusions = [
        _as_text(m.content) for m in current
        if getattr(m, "type", None) == "ai"
        and _as_text(m.content).startswith(prompts.DIMENSION_MARKER)
    ]
    logger.info("开始汇聚各维度结论（共 %d 条）", len(conclusions))
    for c in conclusions:
        logger.info("维度结论：%s", c.splitlines()[0] if c else "")
        logger.debug("维度结论全文：\n%s", c)

    # 确定性排序：解析各维度定级标记（grade/score），先 grade 后 score、未定级垫底
    candidates = []
    for c in conclusions:
        grade, score = parse_grade_score(c)
        candidates.append({"dimension": _dim_name(c), "grade": grade, "score": score})
    candidates.sort(key=sort_key)
    logger.info("根因定级排序：%s",
                [(c["dimension"], c["grade"], c["score"]) for c in candidates])
    ranking_block = ""
    if candidates:
        lines = []
        for i, cand in enumerate(candidates, 1):
            tag = "%s / %s" % (cand["grade"], cand["score"]) if cand["grade"] else "未定级"
            lines.append("%d. %s —— %s" % (i, cand["dimension"], tag))
        ranking_block = (
            "\n\n[根因定级排序（已按 grade→score 排好，报告须按此顺序，不得调换）]\n"
            + "\n".join(lines)
        )

    prov = state.get("dimension_provenance", [])
    logger.info("汇聚来源信息：%s", prov)
    source_block = ""
    if prov:
        source_block = "\n\n[结构化来源信息（维度→子智能体→规则号）]\n" + json.dumps(prov, ensure_ascii=False)
    directive_block = ""
    directives = []
    for entry in prov:
        sub = entry.get("sub_agent", "")
        if entry.get("root_cause"):
            directives.append("- 根因（%s）：%s" % (sub, entry["root_cause"]))
        for s in (entry.get("suggestion") or []):
            directives.append("- 首条建议（%s）：%s" % (sub, s))
    if directives:
        directive_block = "\n\n【用户指定内容，必须逐字使用、不得改写】\n" + "\n".join(directives)
    msgs = [SystemMessage(content=prompts.AGGREGATE_PROMPT + ranking_block + source_block + directive_block)] + current
    report = _as_text(LLM.invoke(msgs).content)
    logger.info("汇聚报告：\n%s", report)
    return {"report": report, "messages": [AIMessage(content=report)]}
