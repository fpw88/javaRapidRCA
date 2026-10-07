"""LangChain/LangGraph 1.x 多层 Orchestrator 多智能体：Java 服务响应慢排查。

整体图结构：

    __start__ --> orchestrator
    orchestrator -.->|conditional / Send| cpu / memory / diskio / gc / jvm线程堆栈分析
    orchestrator -.->|意图不明确| reinput --> orchestrator
    cpu/memory/diskio/gc/jvm线程堆栈分析 --> aggregate
    aggregate --> check
    check -->|审核通过| __end__

分层：
    接入层  orchestrator —— 意图识别、任务规划、路由
    编排层  _route_after_orchestrator —— 条件边 Send 并行 fan-out 到各维度（或转 reinput）
    诊断层  5 个 create_agent 子图（cpu/memory/diskio/gc/jvm线程堆栈分析）
    深入层  jvm线程堆栈分析 子图内部委派 redis子智能体/mysql子智能体 子图节点
    汇聚层  aggregate —— 汇总本轮各维度结论 → 根因排序 → 报告
    审核层  check —— 审核报告是否完整/可信/满足需求后输出
    人工在环 interrupt() 在工具/reinput 内触发，run() 里用 ID 键 Command(resume=...) 回填。

用法：
    python main.py [任务描述]
    不带参数时使用默认任务。
"""
import sys
from core.agent import run
from config.config import LOG_LEVEL, SSH, MODEL_API_KEY, MODEL
from util._common import _ask
from util.log import setup_logging, get_logger

logger = get_logger(__name__)

def _check_config() -> None:
    missing = []
    if not MODEL:
        missing.append("MODEL")
    if not MODEL_API_KEY:
        missing.append("MODEL_API_KEY")
    if not SSH["host"] or not SSH["username"] or not SSH["password"]:
        missing.append("SSH_HOST / SSH_USER / SSH_PASSWORD")
    if missing:
        raise SystemExit("缺少配置，请先在 .env 中填写: " + ", ".join(missing))


if __name__ == "__main__":
    setup_logging(LOG_LEVEL)
    _check_config()

    #task = " ".join(sys.argv[1:]) or "全面排查服务器上 Java 服务响应慢的问题"
    #task = " ".join(sys.argv[1:]) or "对dumps目录下的thread_dump_3234_20260928_192549.txt线程堆栈进行分析"
    task = " ".join(sys.argv[1:]) or "对dumps目录下的thread_dump_5309_20261002_175519.txt线程堆栈进行分析"
    #task = " ".join(sys.argv[1:]) or "分析堆栈"

    # rst=_ask({
    #     "detail":f"目标服务器：{SSH["host"]}。开始排查任务：{task}",
    #     "question":"请确认(y/n)"
    # })
    #
    # if rst=="y" or rst=="Y":
    #     run(task)

    run(task)


