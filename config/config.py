"""集中读取配置：模型（OpenAI 兼容接口）+ SSH 连接信息。"""
import os

from dotenv import load_dotenv

from util.log import get_logger

logger = get_logger(__name__)

load_dotenv()

# 模型（OpenAI 兼容接口）
MODEL = os.getenv("MODEL", "")
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# SSH 连接信息
SSH = {
    "host": os.getenv("SSH_HOST", ""),
    "port": int(os.getenv("SSH_PORT", "22")),
    "username": os.getenv("SSH_USER", ""),
    "password": os.getenv("SSH_PASSWORD", ""),
}

# Redis 所在机器的 SSH 连接信息（测固有延时需在 Redis 机器上执行）。
# host 直接用 REDIS_HOST（Redis 机器 ip）；端口/口令/用户名默认回退到主 SSH，可在 .env 用 REDIS_SSH_* 覆盖。
REDIS_SSH = {
    "host": os.getenv("REDIS_HOST") or SSH["host"],
    "port": int(os.getenv("REDIS_SSH_PORT") or SSH["port"]),
    "username": os.getenv("REDIS_SSH_USER") or SSH["username"],
    "password": os.getenv("REDIS_SSH_PASSWORD") or SSH["password"],
}

# 线程堆栈与分析产物保存目录（本机，即运行 agent 的机器）
STACK_DUMP_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../dumps"))
#指标采集目录
METRICS_STORE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../dumps/metrics"))

# 采样时长与采样间隔（秒）
_DEFAULT_MEASURE_INTERVAL_SECONDS = 5

_MEASURE_SECONDS=int(os.getenv("MEASURE_SECONDS") or 60)
_MEASURE_INTERVAL_SECONDS=int(os.getenv("MEASURE_INTERVAL_SECONDS") or _DEFAULT_MEASURE_INTERVAL_SECONDS)

## 间隔大于总时长的话只会采到一次，回退到默认间隔
if _MEASURE_INTERVAL_SECONDS >= _MEASURE_SECONDS:
    logger.warning(
        "MEASURE_INTERVAL_SECONDS=%s 大于 MEASURE_SECONDS=%s，回退为默认值 %s 秒",
        _MEASURE_INTERVAL_SECONDS, _MEASURE_SECONDS, _DEFAULT_MEASURE_INTERVAL_SECONDS,
    )
    _MEASURE_INTERVAL_SECONDS = _DEFAULT_MEASURE_INTERVAL_SECONDS

