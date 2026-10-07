"""内存维度诊断工具。"""
from langchain.tools import tool

from util._common import cap
from util.ssh_client import run_cmd


@tool
def get_memory_overview() -> str:
    """查看整机内存与 swap 概况（free -m + vmstat -s）。"""
    cmd = (
        "echo '== free =='; free -m; "
        "echo '== vmstat =='; vmstat -s 2>/dev/null | head -15"
    )
    return cap(run_cmd(cmd))


@tool
def get_memory_top_processes() -> str:
    """按 RSS 排序列出内存占用最高的进程。"""
    return cap(run_cmd("ps -eo pid,user,rss,vsz,comm --sort=-rss | head -20"))


@tool
def get_oom_events() -> str:
    """查看最近 OOM / 被杀进程事件（dmesg）。"""
    cmd = "dmesg -T 2>/dev/null | grep -iE 'out of memory|oom|killed process' | tail -20 || echo '(无权限或无 dmesg)'"
    return cap(run_cmd(cmd))
