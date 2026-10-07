"""memory 维度智能体。"""
from prompt import prompt_templates as prompts
from tools import memory_tools

NAME = "memory"
SYSTEM_PROMPT = prompts.MEMORY_PROMPT
TOOLS = [
    memory_tools.get_memory_overview,
    memory_tools.get_memory_top_processes,
    memory_tools.get_oom_events,
]
