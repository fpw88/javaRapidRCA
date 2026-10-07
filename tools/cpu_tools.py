"""CPU 维度诊断工具。"""
from langchain.tools import tool

from util._common import cap
from util.ssh_client import run_cmd


@tool
def get_cpu_overview() -> str:
    """查看整机 CPU 负载与占用最高的进程（uptime + top + mpstat）。"""
    cmd = (
        "echo '== uptime =='; uptime; "
        "echo '== top =='; top -bn1 | head -25; "
        "echo '== mpstat =='; mpstat 1 2 2>/dev/null || echo '(无 mpstat)'"
    )
    return cap(run_cmd(cmd))


@tool
def get_cpu_hot_threads(pid: str) -> str:
    """查看某 Java 进程内 CPU 占用最高的线程（top -H），用于定位忙等/自旋线程。"""
    return cap(run_cmd(f"top -H -b -n1 -p {pid} | head -40"))
