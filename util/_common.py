"""各维度诊断工具共用的输出截断与文本落盘封装。

执行远程命令本身在 util/ssh_client.py（`ssh_exec` / `run_cmd`）。
"""
import os
import time
from config.config import METRICS_STORE_DIR


def cap(text: str, max_lines: int = 60, max_chars: int = 6000) -> str:
    """截断过长的诊断输出，末行注明被截断量。"""
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines]) + f"\n…(其余 {len(lines) - max_lines} 行已截断)"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…(其余 {len(text) - max_chars} 字符已截断)"
    return text


def write_text(path: str, text: str) -> str:
    """以 UTF-8 把文本写入 path（自动建父目录），返回 path。

    溯源产物的唯一写入口：不经 _safe_text（那是给 GBK 控制台用的，写盘会破坏非 GBK 字符）。
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path

def get_metric_store_path(key:str)-> str:
    """获取监控指标存储路径"""
    os.makedirs(METRICS_STORE_DIR, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")

    return os.path.join(METRICS_STORE_DIR, f"{key}_{ts}.txt")


def _ask(value) -> str:
    """渲染一次中断并读入人工回复。"""
    if isinstance(value, dict):
        detail = value.get("processes") or value.get("detail")
        if detail:
            print("\n" + "=" * 60)
            print(detail)
            print("-" * 60)
        return input(value.get("question", "请输入") + ": ").strip()
    return input(f"\n{value}: ").strip()


def _as_text(content) -> str:
    """把模型返回的 content（str / list / None）统一成字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(_as_text(c.get("text", "")))
            else:
                parts.append(str(c))
        return "".join(parts)

    return str(content or "")


def _last_ai_message(messages):
    """取消息列表中最后一条 AI 消息；无则 None。"""
    ai = [m for m in messages if getattr(m, "type", None) == "ai"]
    return ai[-1] if ai else None