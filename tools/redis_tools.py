"""Redis 深入排查工具。

本文件只是 `@tool` 调度壳
"""
from concurrent.futures import ThreadPoolExecutor

from langchain.tools import tool

from config.config import SSH, REDIS_SSH
from parse_metrics.redis import (
    parse_redis_cpu_usage, parse_redis_intrinsic_latency, parse_redis_net_latency, parse_redis_slowlog,
)
from rules.redis import format_digest, score_redis, set_last_score
from util import redis_command
from util.log import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------- 单入口

@tool
def diagnose_redis() -> str:
    """采集 Redis 四因子（慢日志/网络延时/固有延时/CPU）并确定性判级，返回结构化摘要。

    一次性完成「采集→解析→判级」，原始命令输出不进大模型；返回摘要里已含各因子的
    数值与定级（P0/P1/未命中），模型只做归因，不要重算数值或改判阈值。
    """
    # 预检 redis-cli（把 interrupt() 中断点前置，避免并发采集里 interrupt）
    cli_java = redis_command.ensure_redis_cli(SSH)         # 网络延时在 Java 服务器上测
    cli_redis = redis_command.ensure_redis_cli(REDIS_SSH)  # 固有延时/慢日志在 Redis 机器上测

    def run_redis_net_latency():
        return redis_command.collect_net_latency() if not cli_java.startswith("(") else None

    def run_redis_intrinsic_latency():
        return redis_command.collect_intrinsic_latency() if not cli_redis.startswith("(") else None

    def run_redis_slowlog():
        return redis_command.collect_slowlog() if not cli_redis.startswith("(") else None

    def run_redis_cpu_usage():
        return redis_command.collect_cpu_usage()

    with ThreadPoolExecutor(max_workers=4) as ex:
        #把函数提交给线程池执行，并立即返回一个Future对象
        f_redis_net_latency = ex.submit(run_redis_net_latency)
        f_redis_intrinsic_latency = ex.submit(run_redis_intrinsic_latency)
        f_redis_slowlog = ex.submit(run_redis_slowlog)
        f_redis_cpu_usage = ex.submit(run_redis_cpu_usage)

        #获取结果：Future.result() 会阻塞当前线程，直到对应任务执行完成，并返回函数结果。
        redis_net_latency_raw = f_redis_net_latency.result()
        redis_intrinsic_latency_raw = f_redis_intrinsic_latency.result()
        redis_slowlog_raw = f_redis_slowlog.result()
        redis_cpu_usage_raw = f_redis_cpu_usage.result()

    net = parse_redis_net_latency(redis_net_latency_raw) if redis_net_latency_raw else None
    intrinsic = parse_redis_intrinsic_latency(redis_intrinsic_latency_raw) if redis_intrinsic_latency_raw else None
    slowlog = parse_redis_slowlog(redis_slowlog_raw) if redis_slowlog_raw else None
    cpu = parse_redis_cpu_usage(redis_cpu_usage_raw) if redis_cpu_usage_raw else None

    score = score_redis(net, intrinsic, cpu, slowlog)
    digest = format_digest(score)
    score.digest = digest
    set_last_score(score)
    logger.info("Redis 判级摘要：\n%s", digest)
    return digest
