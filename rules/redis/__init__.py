"""Redis 的规则计算层：确定性判级 / 得分 / 摘要渲染 / 结论校验。

同一条链上的另外两层：
    1、原始输出的解析在 parse_metrics/redis/，
    2、命令构造与采集在util/redis_command.py。对外统一从本包导入，调用方不直接摸包内文件。

包内文件：
- redis_threshold.py       判级阈值（只装数值，不带逻辑）
- redis_types.py          FactorFlag / RedisScore / 因子口径
- redis_<metric>_rule.py  逐因子判级：intrinsic / net / cpu / slowlog
- redis_cpu_escalation_rule.py  组合规则：CPU 持续高时把命中的延时因子并入 CPU
- redis_scorer.py         组装：逐因子判级 → 组合规则归并 → 整体得分（score_redis）
- redis_digest.py         给大模型的摘要渲染（format_digest）
- redis_validate.py       抗幻觉校验 + 线程局部最近判级结果

`set_last_score` / `get_last_score` 用线程局部变量把最近一次判级结果交给消费方
（redis 子智能体读它做确定性定级）。纯标准库、不碰网络、不依赖 LangChain。
"""
from .redis_digest import format_digest
from .redis_scorer import score_redis
from .redis_types import FactorFlag, RedisScore, factor_sort_key
from .redis_validate import (
    get_last_score,
    render_conclusion,
    set_last_score,
    validate_conclusion,
)
