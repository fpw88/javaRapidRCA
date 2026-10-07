"""cpu 维度智能体。"""
from prompt import prompt_templates as prompts
from tools import cpu_tools

NAME = "cpu"
SYSTEM_PROMPT = prompts.CPU_PROMPT
TOOLS = [cpu_tools.get_cpu_overview, cpu_tools.get_cpu_hot_threads]
