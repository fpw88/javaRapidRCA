"""diskio 维度智能体。"""
from prompt import prompt_templates as prompts
from tools import diskio_tools

NAME = "diskio"
SYSTEM_PROMPT = prompts.DISKIO_PROMPT
TOOLS = [diskio_tools.get_disk_overview, diskio_tools.get_diskio_top_processes]
