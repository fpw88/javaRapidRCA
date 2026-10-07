"""redis 结论校验闸门（抗幻觉）与结论渲染。

`set_last_score` / `get_last_score` 用线程局部变量把最近一次判级结果交给消费方
（redis 子智能体读它做确定性定级）。`validate_conclusion` 把大模型结论与已判级事实比对，
产出 hard/soft 问题清单；`render_conclusion` 把模型 JSON 结论渲染成上层（jvm线程堆栈分析）
能吸收的可读文本。纯标准库、不碰网络、不依赖 LangChain。
"""
import re
import threading
from typing import Optional

from rules.redis.redis_types import FACTOR_KEYS, RedisScore


_last_score = threading.local()


def set_last_score(score: RedisScore) -> None:
    _last_score.score = score


def get_last_score() -> Optional[RedisScore]:
    return getattr(_last_score, "score", None)


def validate_conclusion(conclusion: dict, score: RedisScore):
    """校验大模型结论与已判级事实是否一致。

    返回 (hard_issues, soft_issues)：
    - hard：P0/P1 断言没有对应因子命中支撑（或 factor 非法）——应触发修正。
    - soft：证据里出现摘要未有的数值（疑似编造）、命中却声明证据不足——仅提示。
    """
    hard, soft = [], []
    eligible = {f.factor for f in score.factors if f.grade in ("P0", "P1")}

    known = _numbers(score.digest)
    causes = conclusion.get("redis_root_causes") or []
    if not isinstance(causes, list):
        causes = []
    for c in causes:
        if not isinstance(c, dict):
            continue
        grade = str(c.get("grade", "")).upper()
        factor = str(c.get("factor", "")).lower()
        if grade in ("P0", "P1"):
            if factor not in FACTOR_KEYS:
                hard.append("根因『%s』的 factor 非法：%s" % (c.get("cause", ""), factor or "空"))
            elif factor not in eligible:
                hard.append("根因『%s』定 %s，但 %s 因子未命中阈值（代码未判 P0/P1）"
                            % (c.get("cause", ""), grade, factor))
        for ev in (c.get("evidence") or []):
            if not isinstance(ev, str):
                continue
            for n in _numbers(ev):
                if not any(abs(n - k) < 1e-6 for k in known):
                    soft.append("证据『%s』里的数值 %s 未出现在采集摘要中，疑似编造" % (ev, _fmt_num(n)))

    if _truthy(conclusion.get("insufficient_evidence")) and eligible:
        soft.append("已有因子命中阈值，却声明 insufficient_evidence=true，请复核")
    return hard, soft


def render_conclusion(conclusion: dict) -> str:
    """把大模型的 JSON 结论渲染成给上层（jvm线程堆栈分析）吸收的可读文本。"""
    causes = conclusion.get("redis_root_causes") or []
    lines = ["redis子智能体结论："]
    if not isinstance(causes, list) or not causes:
        lines.append("  - 证据不足，未定位到 redis 侧根因。")
    for c in causes:
        if not isinstance(c, dict):
            continue
        lines.append("  - [%s] %s（因子：%s，置信：%s）"
                     % (c.get("grade", "?"), c.get("cause", ""),
                        c.get("factor", "?"), c.get("confidence", "?")))
        for ev in (c.get("evidence") or []):
            lines.append("      证据：%s" % ev)
    if _truthy(conclusion.get("insufficient_evidence")):
        lines.append("  - 备注：证据不足，暂不定 P0/P1。")
    excl = conclusion.get("excluded") or []
    if excl:
        lines.append("  - 已排除：" + "；".join(str(e) for e in excl))
    steps = conclusion.get("next_steps") or []
    if steps:
        lines.append("  - 建议：" + "；".join(str(s) for s in steps))
    return "\n".join(lines)


# ----------------------------------------------------------------- 辅助

def _numbers(text: str) -> set:
    return {float(x) for x in re.findall(r'\d+\.\d+|\d+', text or "")}


def _fmt_num(n: float) -> str:
    return ("%.3f" % n).rstrip("0").rstrip(".")


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")
