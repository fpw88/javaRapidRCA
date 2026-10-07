"""状态定义与共享辅助：常量、公共方法，并 re-export 主图/子图状态。

- 主图状态 RcaState 定义在 rca_state.py，子图状态 JvmStackState 定义在 jvm_stack_state.py。
- 规范名称常量、维度列表、深挖子智能体列表，以及各层共用的辅助函数统一放这里。
"""
import json
import re

from core.states.jvm_stack_state import JvmStackAnalyzeState, JvmStackState
from core.states.rca_state import RcaState

# 各智能体的规范名称（唯一来源，改这里即全局生效）
JVM_STACK_AGENT = "jvm线程堆栈分析"
JVM_GC_AGENT = "jvmGC分析"
REDIS_SUBAGENT = "redis子智能体"
MYSQL_SUBAGENT = "mysql子智能体"

ALL_DIMENSIONS = ["cpu", "memory", "diskio", JVM_GC_AGENT, JVM_STACK_AGENT]

# jvm线程堆栈分析 可深挖的外部依赖子智能体（顺序即路由匹配优先级）。
# 新增子智能体（如 elasticsearch）只需在此追加名字，并在 core/agents/jvm_stack_agent.py 的 _DEEP_DIVE_REGISTRY 注册「名字 → 构建该子图节点的零参工厂」。
JVM_STACK_DEEP_DIVE_SUBAGENTS = [REDIS_SUBAGENT, MYSQL_SUBAGENT]


def _parse_intent_decision_as_json(text: str) -> dict:
    """解析 orchestrator 输出的 JSON，失败则返回空 dict（由调用方兜底全维度）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        #去掉Markdown 代码围栏。re.DOTALL：让正则表达式中的 . 能够匹配换行符 \n
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        #在字符串 cleaned 中搜索一个以 { 开头、以 } 结尾的片段，并允许中间跨越多行。匹配结果保存在 m 中
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        try:
            return json.loads(m.group(0)) if m else {}
        except Exception:
            return {}


def _normalize_dimensions(dims) -> list[str]:
    """把 orchestrator 给的维度名规整到合法集合（去空格/大小写容错）；空/非法时兜底全维度。"""
    canonical = {_normalize_agent_name(d): d for d in ALL_DIMENSIONS}
    out = []
    for d in (dims or []):
        c = canonical.get(_normalize_agent_name(d))
        if c and c not in out:
            out.append(c)
    return out or ALL_DIMENSIONS


def _normalize_agent_name(s) -> str:
    """名称归一化 key：去空格 + 小写，用于容错匹配 LLM 输出的名称变体（如 JVM线程堆栈分析 → jvm线程堆栈分析）。"""
    return str(s).replace(" ", "").lower()
