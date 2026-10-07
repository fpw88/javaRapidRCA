"""redis 子智能体：构建智能体并包成 jvm 子图节点；结论校验（_finalize）当前停用，结论原样上传。"""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from core.agents._runtime import invoke_drain, subagent_config
from core.llm import LLM
from core.states import JVM_STACK_AGENT, REDIS_SUBAGENT, JvmStackState
from prompt import prompt_templates as prompts
from rules.redis import factor_sort_key, get_last_score
from tools import redis_tools
from util.log import get_logger

logger = get_logger(__name__)

THREAD_SUFFIX = "redis"
TASK = "请排查 redis 侧问题。"


def build_redis_sub_node():
    """构建 redis 子智能体并包成 jvm 子图节点；逐因子判级的确定性定级写进 dimension_provenance。"""
    agent = create_agent(
        model=LLM,
        tools=[redis_tools.diagnose_redis],
        system_prompt=prompts.REDIS_PROMPT,
        checkpointer=InMemorySaver(),
    )

    def redis_sub_node(state: JvmStackState) -> dict:
        logger.info(REDIS_SUBAGENT+f" 开始进行深入分析")
        config = subagent_config(THREAD_SUFFIX)
        text = invoke_drain(agent, [{"role": "user", "content": TASK}], config)
        score = get_last_score()
        # rules 恒为空；保留该键以维持 dimension_provenance 的字段结构契约
        entry = {"dimension": JVM_STACK_AGENT, "sub_agent": REDIS_SUBAGENT, "rules": []}
        # 确定性定级：逐因子判级算好的整体 grade/score（命中任一因子才带），供汇聚层确定性排序
        if score is not None and score.grade:
            entry["grade"] = score.grade
            entry["score"] = score.score
        # 规则层指定的文案（如 CPU 持续高归并延时因子时写在 cpu 因子上），
        # 汇聚层据此逐字采用，不再由大模型发挥。
        # 按因子展示顺序（先定级、同定级再按分数）收集：优先根因取自最靠前的因子，
        # 建议也按同一顺序累积，使「首条建议」来自最优先的因子。
        factors = sorted(score.factors, key=factor_sort_key) if score is not None else []
        rule_root_cause = next((f.custom_root_cause for f in factors if f.custom_root_cause), "")
        rule_suggestions = [s for f in factors for s in f.custom_suggestion]
        if rule_root_cause:
            entry["root_cause"] = rule_root_cause
        if rule_suggestions:
            entry["suggestion"] = rule_suggestions
        logger.info("redis 确定性定级：grade=%s，score=%s，entry=%s",
                    entry.get("grade"), entry.get("score"), entry)
        logger.info("redis子智能体结论：%s", text.splitlines()[0] if text else "")
        return {
            "messages": [AIMessage(content=text)],
            "dimension_provenance": [entry],
        }

    return redis_sub_node
