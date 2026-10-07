"""网络延时原始输出的确定性解析。

纯标准库、无 LangChain 依赖。把 `redis-cli -i N --latency`（非 tty）输出解析成
NetLatency（毫秒）。不同 redis-cli 版本 --latency 语义不同，兼容「裸数字行」与
「min=/max=/avg=/samples= 标签」两种格式。
"""
import re
from dataclasses import dataclass
from typing import Optional

_NET_BARE = re.compile(r'^[ \t]*([\d.]+)[ \t]+([\d.]+)[ \t]+([\d.]+)[ \t]+(\d+)[ \t]*$')
_NET_LABELED = re.compile(
    r'min[=:]\s*([\d.]+).{0,60}?max[=:]\s*([\d.]+).{0,60}?avg[=:]\s*([\d.]+).{0,60}?samples[=:]\s*(\d+)',
    re.S | re.I,
)


@dataclass
class RedisNetLatency:
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    samples: int = 0


def parse_redis_net_latency(text: str) -> Optional[RedisNetLatency]:
    """解析 `redis-cli -i N --latency`（非 tty）输出的一行裸数字 `min max avg samples`（毫秒）。"""
    if not text:
        return None
    m = _NET_BARE.search(text)
    if not m:
        m = _NET_LABELED.search(text)
    if not m:
        return None
    return RedisNetLatency(
        min_ms=float(m.group(1)),
        max_ms=float(m.group(2)),
        avg_ms=float(m.group(3)),
        samples=int(m.group(4)),
    )
