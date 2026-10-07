"""
redis指标判级阈值

只装判级用的数值口径，不带逻辑；因子名映射等包内共用口径在 redis_types.py。
"""

INTRINSIC_P0_MS = 50.0   # 固有延时 max 达到此值 定 P0
INTRINSIC_P1_MS = 10.0    # 固有延时 ≥10ms 定 P1
NET_P0_MS = 50.0          # 网络延时均值 >50ms 定 P0
NET_P1_MS = 10.0          # 网络延时均值 >10ms 定 P1
CPU_HIGH_PCT = 90       # CPU 持续 >90%（现仅用于 CPU 因子摘要文案，不参与判级）
O_N_P0_MIN_COUNT = 10     # 窗口内 O(N) 命令条数 ≥ 此值 视为「大量」定 P0
INCR_MIN_COUNT = 10       # INCR 类命令 ≥ 此值 视为「大量 INCR」（提示固有延时高）