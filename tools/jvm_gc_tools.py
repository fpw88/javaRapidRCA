"""JVM GC 维度诊断工具。"""
from langchain.tools import tool
from langgraph.types import interrupt

from util._common import cap
from util.ssh_client import run_cmd
from tools.jvm_stack_tools import _list_java_processes, _resolve_tool


@tool
def pick_java_pid() -> str:
    """列出 Java 进程并中断询问用户选择 PID（供 GC 维度使用）。"""
    procs = _list_java_processes()
    pid = interrupt({"question": "请输入要分析 GC 的 Java 进程 PID", "processes": procs})
    pid = str(pid).strip()
    return pid or "未选择 PID，操作取消"


@tool
def get_gc_stats(pid: str) -> str:
    """采样 JVM GC 各代使用率与耗时（jstat -gcutil）。"""
    jstat = _resolve_tool(pid, "jstat")
    if not jstat:
        return f"未找到 PID {pid} 的 jstat（需与目标进程同用户或 root）"
    return cap(run_cmd(f"{jstat} -gcutil {pid} 1000 5"))


@tool
def get_gc_cause(pid: str) -> str:
    """查看最近一次 GC 的原因（jstat -gccause）。"""
    jstat = _resolve_tool(pid, "jstat")
    if not jstat:
        return f"未找到 PID {pid} 的 jstat"
    return cap(run_cmd(f"{jstat} -gccause {pid}"))


@tool
def get_heap_info(pid: str) -> str:
    """查看堆配置与各分区占用（jcmd GC.heap_info）。"""
    jcmd = _resolve_tool(pid, "jcmd")
    if not jcmd:
        return f"未找到 PID {pid} 的 jcmd"
    return cap(run_cmd(f"{jcmd} {pid} GC.heap_info"), max_lines=80)
