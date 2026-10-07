"""jvm线程堆栈分析 子图节点：capture_analyze_result（落分析结果字段）+
route（LLM 路由决策）+ jvm_stack_aggregate（落款维度结论）。

模型统一走 core.llm 的全局常量 LLM。
"""
import os

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Send

from config.config import STACK_DUMP_DIR
from core.llm import LLM
from core.states import (
    JVM_STACK_AGENT,
    JVM_STACK_DEEP_DIVE_SUBAGENTS,
    JvmStackState,
    REDIS_SUBAGENT,
    _normalize_agent_name,
    _parse_intent_decision_as_json,
)
from prompt import prompt_templates as prompts
from util._common import _as_text, _last_ai_message, write_text
from rules.grade import grade_score_line, strip_grade_score
from util.jvm_stack_util import analyze_result_path, conclusion_path
from util.log import get_logger

logger = get_logger(__name__)


def _persist_artifact(state: JvmStackState, path_func, text: str, label: str) -> None:
    """把大模型产出落到 dumps/，文件名沿用「analysis_<dump主干>」主干，便于按 dump 回溯源。

    堆栈文件路径由 analyze_thread_dump 回写在 state["jvm_stack_dump_file_path"]；取不到就告警跳过，
    不猜名字也不落空文件。basename 是为了挡住路径穿越。
    """
    dump = os.path.basename(str(state.get("jvm_stack_dump_file_path") or "").strip())
    if not text.strip() or not dump.endswith(".txt"):
        logger.warning("%s 未落盘（堆栈文件路径=%r）", label, dump)
        return
    logger.info("%s 已保存: %s", label, write_text(path_func(dump, STACK_DUMP_DIR), text))



def capture_jvm_stack_analyze_result(state: JvmStackState) -> JvmStackState:
    """把 analyze 智能体的最终分析消息落到独立字段，供路由/汇聚直接读取（不再扫 messages）。

    写的是 messages 里那条原消息对象（id 已由 messages 通道的 add_messages 落定）：
    字段用 add_messages 合并，同 id 就地替换，故节点重跑不会堆积重复消息。
    """
    msg = _last_ai_message(state.get("messages", []))
    if msg is None:
        logger.warning(f"{JVM_STACK_AGENT} 分析结果为空")
        return {}
    analysis = _as_text(msg.content)
    logger.info("%s 分析结果：\n %s", JVM_STACK_AGENT, analysis)
    _persist_artifact(state, analyze_result_path, analysis, JVM_STACK_AGENT + " 分析结果")

    return {"jvm_stack_analyze_result": [msg]}


def jvm_stack_deep_div_route(state: JvmStackState):
    """LLM 读 analyze 的分析，输出 JSON 路由决策。"""
    res = state.get("jvm_stack_analyze_result") or []
    analysis = _as_text(res[-1].content) if res else ""
    resp = LLM.invoke([SystemMessage(content=prompts.STACK_ROUTE_PROMPT), HumanMessage(content=analysis)])
    decision = _parse_intent_decision_as_json(_as_text(resp.content))
    raw = decision.get("route")
    raw = [raw] if isinstance(raw, str) else (raw or [])  # 容错 LLM 返回 str 还是 list
    hits = [c for c in JVM_STACK_DEEP_DIVE_SUBAGENTS
           if _normalize_agent_name(c) in {_normalize_agent_name(r) for r in raw}]
    hits = hits or ["jvm_stack_aggregate"]  # 无外部依赖时直接汇聚（必须是列表，字符串会被按字符拆成 Send）
    logger.info("%s 路由决策：%s", JVM_STACK_AGENT, hits)

    return  [Send(t, {}) for t in hits]


def jvm_stack_aggregate(state: JvmStackState) -> dict:
    """把 analyze 分析与子智能体结论汇总成落款维度结论。"""
    msgs = [SystemMessage(content=prompts.STACK_CONCLUDE_PROMPT)] + list(state.get("messages", []))
    conclusion = _as_text(LLM.invoke(msgs).content)
    # 确定性定级优先：redis 子智能体命中规则时，用规则引擎的 grade/score 覆盖 LLM 给的标记
    prov = state.get("dimension_provenance", [])
    det = next((e for e in prov if e.get("sub_agent") == REDIS_SUBAGENT and e.get("grade")), None)
    if det:
        conclusion = strip_grade_score(conclusion) + "\n" + grade_score_line(det["grade"], det["score"])
    logger.info("%s 维度结论：%s", JVM_STACK_AGENT, conclusion.splitlines()[0] if conclusion else "")
    # 落盘放在定级覆盖之后，保证文件与进入 state 的结论逐字一致
    _persist_artifact(state, conclusion_path, conclusion, JVM_STACK_AGENT + " 维度结论")
    return {"messages": [AIMessage(content=conclusion)]}
