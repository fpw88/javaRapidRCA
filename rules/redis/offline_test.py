"""本包离线自测：`python -m rules.redis.offline_test`。

喂入 4 段真实原始输出样本，断言解析、判级、校验、渲染全链（不连服务器）。
原入口是 `python rules/redis/redis_analyzer.py`——那个文件已按关注点拆成本包各模块。
"""
import re

from parse_metrics.redis import (
    parse_redis_cpu_usage, parse_redis_intrinsic_latency, parse_redis_net_latency, parse_redis_slowlog,
)

from rules.grade import grade_from_score

from rules.redis import (
    format_digest, render_conclusion, score_redis, set_last_score, validate_conclusion,
)
from rules.redis.redis_cpu_rule import _gt90_count


def main() -> None:
    net_raw = "0.912 8.123 2.345 60\n"
    intrinsic_raw = (
        "Max latency so far: 1 microseconds.\n"
        "Max latency so far: 2 microseconds.\n"
        "Max latency so far: 62 microseconds.\n"
        "\n"
        "1720022176 total runs (avg latency: 0.0580 microseconds / 580.00 nanoseconds per run).\n"
        "Worst run took 404x longer than the average latency.\n"
    )
    slowlog_raw = (
        "[slowlog len]\n14\n[slowlog get 128]\n"
        "1) 1) (integer) 14\n"
        "   2) (integer) 1720022176\n"
        "   3) (integer) 12345678\n"
        "   4) 1) \"HGETALL\"\n"
        "      2) \"user:1001\"\n"
        "   5) \"127.0.0.1:12345\"\n"
        "   6) \"\"\n"
        "2) 1) (integer) 13\n"
        "   2) (integer) 1720022000\n"
        "   3) (integer) 250000\n"
        "   4) 1) \"KEYS\"\n"
        "      2) \"*\"\n"
        "   5) \"127.0.0.1:54321\"\n"
        "   6) \"\"\n"
    )
    cpu_raw = (
        "%Cpu(s):  5.6 us,  2.3 sy,  0.0 ni, 91.8 id,  0.1 wa,  0.0 hi,  0.2 si,  0.0 st\n"
        "%Cpu(s):  3.0 us,  1.0 sy,  0.0 ni, 95.5 id,  0.0 wa,  0.0 hi,  0.5 si,  0.0 st\n"
    )

    net = parse_redis_net_latency(net_raw)
    intrinsic = parse_redis_intrinsic_latency(intrinsic_raw)
    slowlog = parse_redis_slowlog(slowlog_raw)
    cpu = parse_redis_cpu_usage(cpu_raw)

    assert net is not None and abs(net.avg_ms - 2.345) < 1e-9 and net.samples == 60, net
    assert intrinsic is not None and abs(intrinsic.max_ms - 0.062) < 1e-9, intrinsic
    assert slowlog is not None and slowlog.count == 2 and slowlog.o_n_count == 2 \
        and slowlog.entries[0].cmd == "HGETALL" and slowlog.entries[0].key == "user:1001", slowlog
    assert cpu is not None and cpu.samples == 2 and _gt90_count(cpu) == 0 \
        and abs(cpu.mean_pct - 6.35) < 0.1, cpu

    score = score_redis(net, intrinsic, cpu, slowlog)
    score.digest = format_digest(score)
    set_last_score(score)
    print(score.digest)

    # 负向：本样本 CPU 6.35%、延时均未命中 → 归并规则不触发，四因子齐全、CPU 不定级
    cpu_f = next(f for f in score.factors if f.factor == "cpu")
    assert len(score.factors) == 4 and cpu_f.grade == "", score.factors

    # 校验：慢日志只 2 条 O(N)，未到「大量」阈值 → 给 P0 应被拦
    bad = {"redis_root_causes": [{"cause": "O(N)操作", "grade": "P0", "factor": "slowlog",
                                  "evidence": ["HGETALL user:1001 1条"]}]}
    hard, soft = validate_conclusion(bad, score)
    assert hard, "应当拦下未命中阈值的 P0"
    print("\n[校验-应拦下] hard=%s" % hard)

    # 校验：合法结论（证据不足）
    ok = {"redis_root_causes": [], "excluded": [], "insufficient_evidence": True, "next_steps": []}
    hard, soft = validate_conclusion(ok, score)
    assert not hard, hard
    print("[校验-通过] 证据不足结论合法，soft=%s" % soft)
    print("\n[渲染结论]")
    print(render_conclusion(ok))

    escalation_test(slowlog)
    score_order_test(slowlog)
    print("\n自测通过")


# ----------------------------------------------------------------- 组合规则：CPU 持续高归并延时因子

# CPU 每次采样使用率 ≈98% → cpu_sustained 为真
CPU_HIGH_RAW = (
    "%Cpu(s):  2.0 us,  3.0 sy,  0.0 ni,  2.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st\n"
    "%Cpu(s):  3.0 us,  2.0 sy,  0.0 ni,  3.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st\n"
)
# 固有延时 max=60000μs → 60ms ≥ INTRINSIC_P0_MS(50) 定 P0
INTRINSIC_HIGH_RAW = (
    "Max latency so far: 12000 microseconds.\n"
    "Max latency so far: 60000 microseconds.\n"
    "\n"
    "1720022176 total runs (avg latency: 500.0000 microseconds / 500.00 nanoseconds per run).\n"
    "Worst run took 120x longer than the average latency.\n"
)
# 网络延时 avg=11.5ms ≥ NET_P1_MS(10) 定 P1（低于 NET_P0_MS(50)）
NET_P1_RAW = "0.900 25.000 11.500 60\n"
# 固有延时 max=62μs → 0.062ms，未命中任何阈值
INTRINSIC_LOW_RAW = (
    "Max latency so far: 62 microseconds.\n"
    "1720022176 total runs (avg latency: 0.0580 microseconds / 58.00 nanoseconds per run).\n"
)
# 网络延时 avg=2.345ms，未命中任何阈值
NET_LOW_RAW = "0.912 8.123 2.345 60\n"

EXPECTED_SUGGESTION = ["先排查redis服务器的cpu是不是由其他进程占用。降低redis服务器的cpu使用率后再次排查。"]
# 根因文案按「实际命中的」延时因子生成：双边命中写两个，单边命中只写那一个
BOTH_CAUSE = "redis服务器cpu使用率较高，导致redis服务器的固有延时、网络延时较高，进而阻塞java程序运行。"
NET_ONLY_CAUSE = "redis服务器cpu使用率较高，导致redis服务器的网络延时较高，进而阻塞java程序运行。"
INTRINSIC_ONLY_CAUSE = "redis服务器cpu使用率较高，导致redis服务器的固有延时较高，进而阻塞java程序运行。"


def _score(cpu_raw: str, intrinsic_raw: str, net_raw: str, slowlog):
    s = score_redis(parse_redis_net_latency(net_raw), parse_redis_intrinsic_latency(intrinsic_raw),
                    parse_redis_cpu_usage(cpu_raw), slowlog)
    s.digest = format_digest(s)
    return s


def _cpu_of(s):
    return next(f for f in s.factors if f.factor == "cpu")


def escalation_test(slowlog) -> None:
    """组合规则五个场景：双边命中 / 只命中网延 / 只命中固有延时 / CPU 高但延时未命中 / 延时命中但 CPU 平稳。"""
    # A：CPU 持续高 + 固有延时 P0 + 网延 P1（「和」）→ 延时因子并入 cpu，grade 取高者 P0
    a = _score(CPU_HIGH_RAW, INTRINSIC_HIGH_RAW, NET_P1_RAW, slowlog)
    cpu_a = _cpu_of(a)
    assert [f.factor for f in a.factors] == ["cpu", "slowlog"], [f.factor for f in a.factors]
    assert cpu_a.grade == "P0", cpu_a.grade                       # 取固有延时 P0（高于网延 P1）
    assert cpu_a.score == 84, cpu_a.score                          # 取被并入因子的最高分（固有延时 60ms）
    assert any("固有延时指标数据" in s for s in cpu_a.summary), cpu_a.summary
    assert any("网络延时指标数据" in s for s in cpu_a.summary), cpu_a.summary
    assert any("固有延时 max=60.0 ms" in e for e in cpu_a.evidence), cpu_a.evidence
    assert cpu_a.custom_root_cause == BOTH_CAUSE, cpu_a.custom_root_cause   # 双边命中写两个
    assert cpu_a.custom_suggestion == EXPECTED_SUGGESTION, cpu_a.custom_suggestion
    assert a.grade == "P0" and a.score == 80, (a.grade, a.score)  # 归并前会是 82（P0+1×P1）
    assert "[固有延时]" not in a.digest and "[网络延时]" not in a.digest
    assert "四因子" not in a.digest and "必须原样采用" in a.digest
    assert BOTH_CAUSE in a.digest
    print("\n[归并-A 摘要]\n%s" % a.digest)

    # A 的校验语义：并入后不再认 intrinsic，认 cpu
    hard, _ = validate_conclusion({"redis_root_causes": [
        {"cause": "延时高", "grade": "P0", "factor": "intrinsic", "evidence": []}]}, a)
    assert hard, "归并后仍以 intrinsic 定 P0，应被拦下"
    hard, _ = validate_conclusion({"redis_root_causes": [
        {"cause": "redis CPU 高导致延时", "grade": "P0", "factor": "cpu",
         "evidence": ["固有延时 max=60.0 ms ≥ 50.0 ms"]}]}, a)
    assert not hard, hard

    # B：CPU 持续高但固有延时/网延均未命中 → 不触发，四因子齐全、CPU 不定级
    b = _score(CPU_HIGH_RAW, INTRINSIC_LOW_RAW, NET_LOW_RAW, slowlog)
    assert [f.factor for f in b.factors] == ["intrinsic", "net", "cpu", "slowlog"], b.factors
    assert _cpu_of(b).grade == "" and b.score is None, (_cpu_of(b).grade, b.score)

    # C：延时命中但 CPU 平稳 → 不触发，固有延时定级原样保留在自身因子上
    c = _score(cpu_low_raw(), INTRINSIC_HIGH_RAW, NET_P1_RAW, slowlog)
    assert [f.factor for f in c.factors] == ["intrinsic", "net", "cpu", "slowlog"], c.factors
    assert next(f for f in c.factors if f.factor == "intrinsic").grade == "P0"
    assert _cpu_of(c).grade == "" and c.score == 82, (_cpu_of(c).grade, c.score)

    # D：CPU 持续高 + 只有网络延时命中 → 文案只写网络延时，未命中的固有延时因保留原样
    d = _score(CPU_HIGH_RAW, INTRINSIC_LOW_RAW, NET_P1_RAW, slowlog)
    cpu_d = _cpu_of(d)
    assert [f.factor for f in d.factors] == ["intrinsic", "cpu", "slowlog"], d.factors
    assert cpu_d.grade == "P1", cpu_d.grade
    assert cpu_d.custom_root_cause == NET_ONLY_CAUSE, cpu_d.custom_root_cause
    assert "固有延时" not in cpu_d.custom_root_cause, cpu_d.custom_root_cause
    assert "[网络延时]" not in d.digest and "[固有延时]" in d.digest
    print("[归并-D] 只命中网络延时：%s" % cpu_d.custom_root_cause)

    # E：CPU 持续高 + 只有固有延时命中 → 文案只写固有延时
    e = _score(CPU_HIGH_RAW, INTRINSIC_HIGH_RAW, NET_LOW_RAW, slowlog)
    cpu_e = _cpu_of(e)
    assert [f.factor for f in e.factors] == ["net", "cpu", "slowlog"], e.factors
    assert cpu_e.grade == "P0", cpu_e.grade
    assert cpu_e.custom_root_cause == INTRINSIC_ONLY_CAUSE, cpu_e.custom_root_cause
    assert "网络延时" not in cpu_e.custom_root_cause, cpu_e.custom_root_cause
    print("[归并-E] 只命中固有延时：%s" % cpu_e.custom_root_cause)

    print("[归并-B/C] 未命中条件的两个场景均未触发归并")


# ----------------------------------------------------------------- 因子级 score 与展示顺序

# 网络延时 avg=300ms → P0，分数封顶 98（高于固有延时 60ms 的 84 分）
NET_HIGH_RAW = "0.900 400.000 300.000 60\n"


def _factor_lines(digest: str) -> list:
    """摘要里因子行的出现顺序（行首形如「[固有延时] …」）。"""
    return re.findall(r"^\[([^\]]+)\]", digest, re.M)


def score_order_test(slowlog) -> None:
    """排序键：先定级、同定级再按分数降序；同分/无分保持原顺序（交大模型）。"""
    # 口径不变量：有分的因子，score 映射回的 grade 必须等于自己的 grade（故不会出现越级）
    for s in (_score(cpu_low_raw(), INTRINSIC_HIGH_RAW, NET_P1_RAW, slowlog),
              _score(cpu_low_raw(), INTRINSIC_HIGH_RAW, NET_HIGH_RAW, slowlog),
              _score(CPU_HIGH_RAW, INTRINSIC_HIGH_RAW, NET_P1_RAW, slowlog)):
        for f in s.factors:
            if f.score is not None:
                assert grade_from_score(f.score) == f.grade, (f.factor, f.grade, f.score)

    # 全未命中（都无分）→ 稳定排序，保持 factors 原构造顺序
    low = _score(cpu_low_raw(), INTRINSIC_LOW_RAW, NET_LOW_RAW, slowlog)
    assert all(f.score is None for f in low.factors), low.factors
    assert _factor_lines(low.digest) == ["固有延时", "网络延时", "CPU使用率", "慢日志"], low.digest

    # 同定级（都是 P0）、分数不同 → 分数高的在前（网络延时 98 > 固有延时 84）
    hi = _score(cpu_low_raw(), INTRINSIC_HIGH_RAW, NET_HIGH_RAW, slowlog)
    by_factor = {f.factor: f for f in hi.factors}
    assert by_factor["net"].score > by_factor["intrinsic"].score, by_factor
    assert _factor_lines(hi.digest) == ["网络延时", "固有延时", "CPU使用率", "慢日志"], hi.digest

    # 定级不同 → 定级高的在前：CPU 归并出的 P0 要排在未命中的慢日志之前（场景 A）
    a = _score(CPU_HIGH_RAW, INTRINSIC_HIGH_RAW, NET_P1_RAW, slowlog)
    assert _factor_lines(a.digest) == ["CPU使用率", "慢日志"], a.digest
    print("\n[排序] 同定级按分数：%s" % _factor_lines(hi.digest))
    print("[排序] 全无分保持原顺序：%s" % _factor_lines(low.digest))


def cpu_low_raw() -> str:
    """CPU 平稳（使用率 ≈6%）的采样，与主用例的低样本同口径。"""
    return (
        "%Cpu(s):  5.6 us,  2.3 sy,  0.0 ni, 91.8 id,  0.1 wa,  0.0 hi,  0.2 si,  0.0 st\n"
        "%Cpu(s):  3.0 us,  1.0 sy,  0.0 ni, 95.5 id,  0.0 wa,  0.0 hi,  0.5 si,  0.0 st\n"
    )


if __name__ == "__main__":
    main()
