"""主图（RcaState）状态定义。"""
import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class RcaState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    dimensions: list[str]       # orchestrator意图识别结果
    report: str                 # 最终结论报告
    round_start: int            # 本轮消息在 messages 中的起点下标（aggregate 只看本轮结论）
    orchestrator_action: str    # orchestrator 路由：continue（fan-out）/ reinput
    extra_arg: dict[str, str]   # orchestrator 解析出的额外参数（如 stack_file 指定要分析的堆栈文件）
    dimension_provenance: Annotated[list[dict], operator.add]  # 各维度委派的子智能体+命中规则号（结构化证据来源）
