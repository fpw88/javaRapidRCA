
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from core.graph import build_graph
from util._common import _ask, _as_text
from util.log import get_logger, setup_logging

logger = get_logger(__name__)


def run(task: str) -> None:
    graph = build_graph()

    #print(draw_mermaid())

    # 5 维并发 + 深入层委派会有大量工具调用，默认 25 步会被顶穿，故放宽。
    config = {"configurable": {"thread_id": "rca-txid"}, "recursion_limit": 300}

    result = graph.invoke({"messages": [HumanMessage(content=task)]}, config=config)

    while True:
        #跑到 END 后 __interrupt__ 会为空，循环break退出。
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break
        logger.info("收到 %d 个人工中断，等待输入", len(interrupts))

        #最后一轮时：resume 后图一路跑到 END，result = 最终完整状态
        if len(interrupts) == 1:
            ans = _ask(interrupts[0].value)
            result = graph.invoke(Command(resume=ans), config=config)
        else:
            # 多并发中断（如 GC 与 jvm线程堆栈分析 各自要 PID）：按中断 id 分别回填
            resume_map = {it.id: _ask(it.value) for it in interrupts}
            result = graph.invoke(Command(resume=resume_map), config=config)

    _print_report(result)





def _print_report(result: dict) -> None:
    """打印最终结论"""
    report = result.get("report")
    if report:
        print("\n[排查报告]\n" + report)
        return
    for m in result.get("messages", []):
        if getattr(m, "type", None) == "ai" and getattr(m, "content", ""):
            print("\n[Agent]\n" + _as_text(m.content))







