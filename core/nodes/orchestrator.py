"""接入/编排层：意图识别、维度派发路由、意图不明确时的人工重输。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Send, interrupt

from core.llm import LLM
from core.states import ALL_DIMENSIONS, JVM_STACK_AGENT, RcaState, _normalize_dimensions, _parse_intent_decision_as_json
from prompt import prompt_templates as prompts
from util._common import _as_text
from util.log import get_logger

logger = get_logger(__name__)


def orchestrator(state: RcaState) -> dict:
    """接入层：仅意图识别。解析排查请求 → 定维度；意图不明确则转 reinput 人工重输。"""
    task = _as_text(state["messages"][-1].content)
    logger.info("开始意图识别")
    resp = LLM.invoke(
        [SystemMessage(content=prompts.ORCHESTRATOR_PROMPT), HumanMessage(content=task)]
    )

    decision = _parse_intent_decision_as_json(_as_text(resp.content))
    if str(decision.get("clear", "")).strip().lower() == "false":  # 意图不明确 → 转 reinput
        logger.info("意图不明确，转 reinput 请用户重新输入")
        return {
            "orchestrator_action": "reinput",
            "round_start": len(state["messages"]),
            "messages": [AIMessage(content="[Orchestrator] 意图不明确，转 reinput 请用户重新输入")],
        }
    dimensions = _normalize_dimensions(decision.get("dimensions"))
    extra_arg = decision.get("extra_arg") or {}
    logger.info("意图识别结果：维度=%s", dimensions)
    note = f"[Orchestrator] 意图识别：维度={dimensions}"
    return {
        "dimensions": dimensions,
        "extra_arg": extra_arg,
        "orchestrator_action": "continue",
        "round_start": len(state["messages"]),
        "messages": [AIMessage(content=note)],
    }


def _dim_task(state: RcaState, dimension: str) -> str:
    parts = ["请开始本维度排查，并按要求输出结论。"]
    stack_file = state.get("extra_arg", {}).get("stack_file")
    if dimension == JVM_STACK_AGENT and stack_file:
        parts.append(f"用户指定了线程堆栈文件：{stack_file}，请直接调用 analyze_thread_dump 分析该文件，不要连接服务器抓取。")
    return " ".join(parts)


def _route_after_orchestrator(state: RcaState):
    """条件边：意图不明确转 reinput，否则 Send 并发 fan-out 到各维度。"""
    if state.get("orchestrator_action") == "reinput":
        return "reinput"
    dims = state.get("dimensions") or ALL_DIMENSIONS
    logger.info("并发派发维度：%s", "、".join(dims))
    return [Send(d, {"messages": [HumanMessage(content=_dim_task(state, d))]}) for d in dims]


def reinput(state: RcaState) -> dict:
    """接入层：意图不明确时中断询问用户，把重新输入的内容回灌 orchestrator。"""
    ans = interrupt({"question": "意图不明确，请重新描述排查问题（目标服务器/服务、现象、想查的维度）"})
    return {"messages": [HumanMessage(content=str(ans).strip())]}
