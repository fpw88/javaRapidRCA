"""按维度构建智能体：每个维度一个文件，对外只暴露 build_dimension_agents。

普通维度（cpu/memory/diskio/gc）各自声明 NAME / SYSTEM_PROMPT / TOOLS，由本模块统一
create_agent；jvm线程堆栈分析 是深入层子图，由 jvm_stack.build 单独装配。

新增普通维度：加一个 <dim>.py + 在 _SIMPLE_MODULES 注册 + 把维度名加进 core/states/__init__.py 的 ALL_DIMENSIONS。
"""
from langchain.agents import create_agent

from core.agents import cpu_agent, diskio_agent, jvm_gc_agent, jvm_stack_agent, memory_agent
from core.llm import LLM
from core.states import JVM_STACK_AGENT

# 走统一 create_agent 的声明式维度；顺序即 graph 加节点顺序
_SIMPLE_MODULES = (cpu_agent, memory_agent, diskio_agent, jvm_gc_agent)


def build_dimension_agents() -> dict:
    """维度名 → 可作图节点（普通维度为 agent，jvm线程堆栈分析 为编译后的子图）。"""
    agents = {
        module.NAME: create_agent(
            model=LLM, tools=module.TOOLS, system_prompt=module.SYSTEM_PROMPT
        )
        for module in _SIMPLE_MODULES
    }
    agents[JVM_STACK_AGENT] = jvm_stack_agent.build()
    return agents
