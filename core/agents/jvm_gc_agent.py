"""gc 维度智能体。"""
from core.states import JVM_GC_AGENT
from prompt import prompt_templates as prompts
from tools import jvm_gc_tools

NAME = JVM_GC_AGENT
SYSTEM_PROMPT = prompts.JVM_GC_PROMPT
TOOLS = [
    jvm_gc_tools.pick_java_pid,
    jvm_gc_tools.get_gc_stats,
    jvm_gc_tools.get_gc_cause,
    jvm_gc_tools.get_heap_info,
]
