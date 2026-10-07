"""Redis 各指标原始输出的纯解析层。

把采集到的原始命令输出（`redis-cli --latency` / `--intrinsic-latency` / `slowlog get N` / `top`）
解析成结构化数据类。本层不判级、不碰网络、不依赖 LangChain——判级与结论校验在
rules/redis/，命令构造与采集在 util/redis_command.py。

各维度一个文件：redis_net_latency.py 网络延时 / redis_intrinsic_latency.py 固有延时 /
redis_slowlog.py 慢日志 / redis_cpu_usage.py CPU 使用率。对外统一从本包导入。

本包只导出解析函数、数据类，以及**解析期**的口径（慢日志命令白名单 O_N_COMMANDS/INCR_COMMANDS、
大key候选口径 BIG_KEY_*）——它们决定 dataclass 里有什么。判级阈值（P0/P1 多少毫秒、CPU 多少百分比
算持续高）不在这里，归规则层 rules/redis/redis_threshold.py。
"""
from .redis_cpu_usage import CpuUsage, parse_redis_cpu_usage
from .redis_intrinsic_latency import IntrinsicLatency, parse_redis_intrinsic_latency
from .redis_net_latency import RedisNetLatency, parse_redis_net_latency
from .redis_slowlog import (
    BIG_KEY_MIN_AVG_MS, BIG_KEY_MIN_COUNT, INCR_COMMANDS, O_N_COMMANDS,
    BigKeyGroup, SlowlogEntry, SlowlogSummary, parse_redis_slowlog,
)
