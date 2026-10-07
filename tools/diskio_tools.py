"""磁盘 IO 维度诊断工具。"""
from langchain.tools import tool

from util._common import cap
from util.ssh_client import run_cmd


@tool
def get_disk_overview() -> str:
    """查看磁盘使用率与 IO 状况（df + iostat）。"""
    cmd = (
        "echo '== df =='; df -h; "
        "echo '== iostat =='; iostat -x 1 2 2>/dev/null | tail -30 || echo '(无 iostat)'"
    )
    return cap(run_cmd(cmd))


@tool
def get_diskio_top_processes() -> str:
    """查看 IO 占用最高的进程（pidstat -d / iotop）。"""
    cmd = "pidstat -d 1 2 2>/dev/null | tail -25 || iotop -bon1 2>/dev/null | head -25 || echo '(无 pidstat/iotop)'"
    return cap(run_cmd(cmd))
