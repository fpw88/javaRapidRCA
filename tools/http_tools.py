"""外部 HTTP 调用侧排查工具。"""
from langchain.tools import tool

from util._common import cap
from util.ssh_client import run_cmd


@tool
def get_http_latency(url: str) -> str:
    """测量外部 HTTP 接口的响应码与各阶段耗时（curl）。"""
    cmd = "curl -o /dev/null -s -w 'HTTP %{http_code} connect=%{time_connect}s total=%{time_total}s\\n' " + url
    return cap(run_cmd(cmd, timeout=30))
