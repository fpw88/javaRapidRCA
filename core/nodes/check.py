"""审核层：审核根因报告是否完整/可信/满足需求。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.llm import LLM
from core.states import RcaState
from prompt import prompt_templates as prompts
from util._common import _as_text
from util.log import get_logger

logger = get_logger(__name__)


def check(state: RcaState) -> dict:
    """审核层：审核报告是否完整/可信/满足需求，输出审核结论。"""
    report = state.get("report", "")
    logger.debug("审核输入报告：\n%s", report)
    resp = LLM.invoke(
        [SystemMessage(content=prompts.CHECK_PROMPT), HumanMessage(content=report)]
    )
    review = _as_text(resp.content)
    logger.info("审核结论：\n%s", review)
    return {"messages": [AIMessage(content="[Check] 审核结论：\n" + review)]}
