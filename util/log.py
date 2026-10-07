"""日志配置：统一 format、按级别输出，并压低第三方库日志避免刷屏。"""
import logging

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# 这些第三方库在 DEBUG 下非常吵（尤其 paramiko），统一压到 WARNING。
_NOISY = (
    "paramiko",
    "paramiko.transport",
    "httpx",
    "httpcore",
    "urllib3",
    "openai",
    "langchain",
    "langgraph",
)


def setup_logging(level: str = "INFO") -> None:
    """配置根日志级别；第三方库压到 WARNING。"""
    root = logging.getLogger()
    if not root.handlers:  # 幂等：避免重复添加 handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    root.setLevel(level.upper())
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
