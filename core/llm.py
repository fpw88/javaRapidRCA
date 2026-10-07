"""全局 LLM 常量：模块级构建一次，各 agent/node 直接 import 使用。

"""
from langchain.chat_models import init_chat_model

from config.config import MODEL, MODEL_API_KEY, MODEL_BASE_URL, MODEL_PROVIDER


def _build_model():
    return init_chat_model(
        model=MODEL,
        model_provider=MODEL_PROVIDER,
        base_url=MODEL_BASE_URL,
        api_key=MODEL_API_KEY,
        temperature=0.7,
        max_tokens=131072,  # 128K
        extra_body={"thinking": {"type": "disabled"}},
    )


def _require_model_config() -> None:
    """常量是 import 时构建的，缺凭据会让 langchain-openai 抛 SDK 原始异常；
    这里先兜成和 main._check_config() 一致的友好提示（SystemExit 不带 traceback）。"""
    missing = [name for name, value in (("MODEL", MODEL), ("MODEL_API_KEY", MODEL_API_KEY)) if not value]
    if missing:
        raise SystemExit("缺少配置，请先在 .env 中填写: " + ", ".join(missing))


_require_model_config()
LLM = _build_model()
