"""子智能体调用基础设施：中断排空与会话线程隔离。"""
from langgraph.config import get_config
from langgraph.types import Command

from util._common import _ask, _as_text


def subagent_config(suffix: str) -> dict:
    """子智能体沿用父图 thread_id 并加后缀，避免同一子图内多子智能体会话串扰。"""
    parent_thread = get_config()["configurable"].get("thread_id", "rca-txid")
    return {"configurable": {"thread_id": f"{parent_thread}:{suffix}"}}


def invoke_drain(agent, payload: list, config: dict) -> str:
    """调用子智能体并排空其中断，返回最后一条消息文本。"""
    result = agent.invoke({"messages": payload}, config=config)
    while True:
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break
        if len(interrupts) == 1:
            result = agent.invoke(Command(resume=_ask(interrupts[0].value)), config=config)
        else:
            resume_map = {it.id: _ask(it.value) for it in interrupts}
            result = agent.invoke(Command(resume=resume_map), config=config)
    msgs = result.get("messages", [])
    return _as_text(msgs[-1].content) if msgs else ""
