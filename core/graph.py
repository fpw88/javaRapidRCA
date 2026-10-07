"""主图装配。模型来自 core.llm 的全局常量 LLM，不再逐层传参。"""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from core.agents import build_dimension_agents
from core.states import ALL_DIMENSIONS, RcaState
from core.nodes import (
    _route_after_orchestrator,
    aggregate,
    check,
    orchestrator,
    reinput,
)


def build_graph():
    agents = build_dimension_agents()

    builder = StateGraph(RcaState)
    builder.add_node("orchestrator", orchestrator)
    for name, agent in agents.items():
        builder.add_node(name, agent)
    builder.add_node("aggregate", aggregate)
    builder.add_node("check", check)
    builder.add_node("reinput", reinput)

    builder.add_edge(START, "orchestrator")
    # orchestrator 出边：Send 并发 fan-out 到各维度，或意图不明确转 reinput
    builder.add_conditional_edges("orchestrator", _route_after_orchestrator)
    builder.add_edge("reinput", "orchestrator")
    for name in ALL_DIMENSIONS:
        builder.add_edge(name, "aggregate")
    # 汇聚 → 审核 → 输出
    builder.add_edge("aggregate", "check")
    builder.add_edge("check", END)

    graph=builder.compile(checkpointer=InMemorySaver())


    # raw_mermaid = (graph
    #                .get_graph(xray=True)  # xray--x光穿透
    #                .draw_mermaid())
    # print(raw_mermaid)

    return graph
