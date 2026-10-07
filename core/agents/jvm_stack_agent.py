"""jvm线程堆栈分析 维度子图：analyze（jstack 分析）→ route（LLM 路由）→
深挖子智能体（redis/mysql/…，注册表驱动）→ jvm_stack_aggregate（落款维度结论）。

redis/mysql 等作为子图节点（而非工具）：
- 拓扑显式、易扩展（新增子智能体 = 在 _DEEP_DIVE_REGISTRY 加一行 + core/states/__init__.py 的 JVM_STACK_DEEP_DIVE_SUBAGENTS 追加名字）；
- 确定性事实（规则号）写进 dimension_provenance，经 state 通道直通汇聚层，不靠 LLM 文本传。

本文件只负责装配：建 agent + 连边 + 编译；各节点定义在 `core/nodes/jvm_stack_nodes/`。
"""
from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph

from core.agents.mysql_subagent import build_mysql_sub_node
from core.agents.redis_subagent import build_redis_sub_node
from core.llm import LLM
from core.nodes.jvm_stack_nodes import capture_jvm_stack_analyze_result, jvm_stack_aggregate, jvm_stack_deep_div_route
from core.states import (
    JVM_STACK_DEEP_DIVE_SUBAGENTS,
    JvmStackAnalyzeState,
    JvmStackState,
    MYSQL_SUBAGENT,
    REDIS_SUBAGENT,
)
from prompt import prompt_templates as prompts
from tools.jvm_stack_tools import analyze_thread_dump, get_thread_dump, read_stack_detail

# 深挖子智能体注册表：名字 → 构建该子图节点的零参工厂。新增子智能体在此加一行，并在 core/states/__init__.py 的 JVM_STACK_DEEP_DIVE_SUBAGENTS 追加名字。
_DEEP_DIVE_REGISTRY = {
    REDIS_SUBAGENT: build_redis_sub_node,
    MYSQL_SUBAGENT: build_mysql_sub_node,
}


def build():
    """构建并编译 jvm线程堆栈分析 子图。"""
    jvm_stack_analyze_agent = create_agent(
        model=LLM,
        tools=[get_thread_dump, analyze_thread_dump, read_stack_detail],
        system_prompt=prompts.JVM_STACK_ANALYZE_PROMPT,
        # 扩展状态：analyze_thread_dump 工具回写堆栈文件路径用（未声明会因未知 key 报错）
        state_schema=JvmStackAnalyzeState,
    )

    g = StateGraph(JvmStackState)

    g.add_node("jvm_stack_analyze", jvm_stack_analyze_agent)
    g.add_node("jvm_stack_capture_result", capture_jvm_stack_analyze_result)
    for name in JVM_STACK_DEEP_DIVE_SUBAGENTS:
        g.add_node(name, _DEEP_DIVE_REGISTRY[name]())
        g.add_edge(name, "jvm_stack_aggregate")
    g.add_node("jvm_stack_aggregate", jvm_stack_aggregate)

    g.add_edge(START, "jvm_stack_analyze")
    g.add_edge("jvm_stack_analyze", "jvm_stack_capture_result")
    g.add_conditional_edges("jvm_stack_capture_result", jvm_stack_deep_div_route)
    g.add_edge("jvm_stack_aggregate", END)

    jvm_stack_graph=g.compile()

    return jvm_stack_graph
