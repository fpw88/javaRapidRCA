"""jvm线程堆栈分析 维度子图状态定义。"""
import operator
from typing import Annotated, TypedDict

from langchain.agents import AgentState
from langgraph.graph.message import add_messages


class JvmStackAnalyzeState(AgentState):
    """jvm_stack_analyze 智能体的状态：在 AgentState 上扩展本次分析的堆栈文件路径字段。

    1、字段由 analyze_thread_dump 工具用 Command 回写。
    2、create_agent 必须用 state_schema声明它。
    3、LangGraph 的 state channel 按 key 名同名共享。故JvmStackState需要有同字段名。
    """
    jvm_stack_dump_file_path: str


class JvmStackState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    route: list[str]  # 路由决策：命中的深挖子智能体列表（空 = 无外部依赖，直接汇聚）
    jvm_stack_dump_file_path: str  # 原始堆栈文件路径
    dimension_provenance: Annotated[list[dict], operator.add]
    jvm_stack_analyze_result: Annotated[list, add_messages]  # jvm_stack_analyze 节点的分析结果消息

