"""redis 判级摘要渲染（给大模型看的紧凑中文摘要）。

`format_digest` 把 RedisScore 渲染成「数值+定级已由代码算好」的事实清单，模型只做归因。
`_safe_text` 是摘要出口收口：保证结果能被 GBK 控制台 print 而不抛 UnicodeEncodeError。
纯标准库、不碰网络、不依赖 LangChain。
"""
from rules.redis.redis_types import FACTOR_NAME, RedisScore, factor_sort_key


def format_digest(score: RedisScore) -> str:
    """把 RedisScore 渲染成给大模型的紧凑中文摘要。"""
    lines = ["redis 各因子已采集并确定性判级（下列数值与定级由代码算好，请勿重算或改判）；"
             "已按「定级 → 分数」排序，越靠前越应作为首要根因，同定级同分数或未取分的由你判断先后：", ""]
    for f in sorted(score.factors, key=factor_sort_key):
        tag = f.grade if f.grade else "未命中"
        if f.score is not None:
            tag += "（分数 %d）" % f.score
        summary = f.summary or [""]
        lines.append("[%s] %s → 定级：%s" % (FACTOR_NAME.get(f.factor, f.factor), summary[0], tag))
        for s in summary[1:]:
            lines.append("    %s" % s)
        for ev in f.evidence:
            lines.append("    证据：%s" % ev)
        if f.custom_root_cause:
            lines.append("    指定根因（必须原样采用）：%s" % f.custom_root_cause)
        for s in f.custom_suggestion:
            lines.append("    指定建议（必须原样采用）：%s" % s)
    lines.append("")
    lines.append("请基于以上事实做归因；若定 P0/P1，必须对应上面某个「已命中」的因子；无命中则写证据不足。")
    return _safe_text("\n".join(lines))


def _safe_text(s: str) -> str:
    """摘要出口收口：保证结果能被 GBK 控制台 print 而不抛 UnicodeEncodeError。"""
    try:
        s.encode("gbk")
        return s
    except UnicodeEncodeError:
        return s.encode("gbk", "replace").decode("gbk")
