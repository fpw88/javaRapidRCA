"""mysql 子智能体：构建智能体并包成 jvm 子图节点。"""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from core.agents._runtime import invoke_drain, subagent_config
from core.llm import LLM
from core.states import JVM_STACK_AGENT, MYSQL_SUBAGENT, JvmStackState
from prompt import prompt_templates as prompts
from tools import mysql_tools
from util.log import get_logger

logger = get_logger(__name__)

THREAD_SUFFIX = "mysql"
TASK = "请排查 mysql 侧问题。"


def build_mysql_sub_node():
    """构建 mysql 子智能体并包成 jvm 子图节点。"""
    agent = create_agent(
        model=LLM,
        tools=[
            mysql_tools.get_mysql_processlist,
            mysql_tools.get_mysql_innodb_status,
            mysql_tools.get_mysql_slow_queries,
        ],
        system_prompt=prompts.MYSQL_PROMPT,
        checkpointer=InMemorySaver(),
    )

    def mysql_sub_node(state: JvmStackState) -> dict:
        config = subagent_config(THREAD_SUFFIX)
        text = invoke_drain(agent, [{"role": "user", "content": TASK}], config)
        rendered = "mysql子智能体结论：\n" + text
        logger.info("mysql子智能体结论：%s", text.splitlines()[0] if text else "")
        return {
            "messages": [AIMessage(content=rendered)],
            "dimension_provenance": [{"dimension": JVM_STACK_AGENT, "sub_agent": MYSQL_SUBAGENT, "rules": []}],
        }

    return mysql_sub_node
