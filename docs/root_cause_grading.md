# 故障根因定级标准

> 本文是「故障根因定级」的单一事实来源，与代码实现对齐（`rules/grade.py`、`rules/redis/`、`core/nodes/aggregate.py` 及各维度 prompt）。改口径先改这里。

## 1. 两个定级维度

每个根因由两个维度刻画：

- **grade（根因等级，离散）**：`P0 决定性` / `P1 强相关` / `P2 中等相关` / `未定级`（证据不足或未命中任何规则）。
  - P0（决定性）：直接导致本次响应慢/故障，证据充分，必须优先处理。
  - P1（强相关）：与故障强相关，是重要诱因或放大因素，指标明确异常，但未必是唯一根因。
  - P2（中等相关）：关联较弱，或只是伴随/次要现象，需进一步观察，不急于定性。
- **score（得分 0-100，连续）**：综合证据强度、异常幅度、因果链完整度、与故障现象吻合度打分，用于同 grade 内细排。

## 2. grade 与 score 的关系

score 是连续主信号，grade 由 score 阈值映射，保证二者永远单调一致、排序简单：

- `80 ≤ score ≤ 100` → P0（决定性）
- `50 ≤ score < 80` → P1（强相关）
- `0 ≤ score < 50` → P2（中等相关）
- 无法打分 → 未定级（无 grade，兜底排最后）

## 3. score 打分口径（可解释）

score = 证据充分度(40) + 异常幅度(30) + 因果链完整度(20) + 现象吻合度(10)，四项加权得 0-100。

## 4. 根因最终排序规则

1. 先按 grade：P0 > P1 > P2 > 未定级。
2. grade 相同：按 score 降序。
3. 未定级（无 grade）的根因：排在所有已定级根因之后；连 score 也没有的并列垫底。
4. 完全并列（grade、score 都相同）：按证据条数降序，仍并列则保持原顺序。

## 5. 规则命中 → 用户自定义优先

> 当前 `dimension_provenance.rules` 恒为空、`RULE_CONTENT` 为空字典。本节机制与代码保留，供后续新规则使用。
> 现有的 CPU 归并规则（§5.1）**不走**这条覆盖链：它的文案由规则层直接生成并写进因子的 `custom_root_cause`/`custom_suggestion`，再由 redis 子智能体透传成 `dimension_provenance` 的 `root_cause`/`suggestion`，汇聚层同样逐字采用——即「用户指定优先」的落地方式有两条，目的相同。

1. 规则引擎命中某规则（rule_id，如「规则N」）→ 确定性产出 grade/score + 因果链 `rule_text`。
2. 查 `constant/rule_content.py` 的 `RULE_CONTENT[rule_id]`：
   - 用户定义了 `root_cause` → 最终报告「根因」逐字采用用户原文，不改写。
   - 用户定义了 `suggestion` → 最终「处理建议」把用户列表按序放最前，其余由模型补充。
3. 用户没自定义 → 模型结合 `rule_text`（确定性因果链）自行发挥。
4. 定级覆盖：默认用户自定义只覆盖「措辞」（root_cause/suggestion），不覆盖定级；如需用户也能指定定级，给 `RULE_CONTENT` 增可选 `grade`/`score` 字段（有则覆盖）。

## 5.1 规则：CPU 持续高时的延时归并

条件（**两者同时成立**才触发）：

1. `cpu_sustained(cpu)` 为真：CPU 均值超 `CPU_HIGH_PCT`，或多数采样点超该阈值（`rules/redis/redis_cpu_rule.py`）。
2. 固有延时/网络延时**至少一个**命中 P0/P1（「和、或」= 任一命中即可，不要求两者都命中）。

命中后（`rules/redis/redis_cpu_escalation_rule.py`）：

1. CPU 因子的 grade 取命中延时因子中的**高者**（`rules/grade.py` 的 `higher_grade`）。
2. 命中因子的 summary 与 evidence 一并并入 CPU 因子的 summary / evidence。
3. CPU 因子的 `custom_root_cause` 按**实际命中的**延时因子生成，模板 = 「redis服务器cpu使用率较高，导致redis服务器的%s较高，进而阻塞java程序运行。」：双边命中填「固有延时、网络延时」，单边命中只填命中的那一个（如只命中网延即为「…导致redis服务器的网络延时较高…」），不写没命中的指标。`custom_suggestion` 为固定列表（文案模板与建议常量都在 `redis_cpu_escalation_rule.py` 顶部）。
4. **命中的**延时因子从因子表移除（未命中的保留作反证），因此摘要里不再单列它们；`FACTOR_KEYS` 是静态合法标签白名单，**不要**因归并而从白名单里删除 intrinsic/net（命中集由 `redis_validate.py` 按 `score.factors` 动态算）。
5. 条件不成立时规则不触发：`grade_redis_cpu` 自身仍恒返回 grade `""`，CPU 因子不参与定级。

三者本是一因一果（CPU 高 → 延时高 → 阻塞 Java），归并避免同一根因被拆成多条重复计数。代价是多命中时整体得分会被去重（固有延时 P1 + 网延 P1：55 → 50；P0 + P1：82 → 80），score 只会降、且不跨 grade 档。

## 5.2 redis 因子级 score 与展示顺序

`FactorFlag.score`（0-100，可为 `None`＝未取分）是**因子级**得分，与 §2 的**维度级** score（`_compute_overall_score` 按 P0/P1 个数算出）是两回事，互不影响。

**取分口径**（`rules/redis/redis_types.py: score_from_overshoot`）——与 grade 口径自洽，保证 `grade_from_score(score) == 该因子的 grade`，故两者永不矛盾、不会越级：

| 因子 | 度量 | 取分 |
|---|---|---|
| 固有延时 | `max_ms` | `<10ms` → 无分；`[10, 50)` → 50~79；`≥50` → 80~98（超出越多分越高） |
| 网络延时 | `avg_ms` | 同上公式（用网的 `NET_P1_MS`/`NET_P0_MS`） |
| 慢日志 | O(N) 条数 / 大key | 未命中 → 无分；O(N) 命中 → `80 + 18·min((n−10)/10, 1)`；**仅靠大key 命中 → 定额 80** |
| CPU | — | 恒无分（不单独判级）；归并（§5.1）时取被并入因子的**最高分** |

**展示顺序**（`rules/redis/redis_types.py: factor_sort_key`）：先 `grade_rank`（P0 > P1 > P2 > 未命中），grade 相同再按 score **降序**；score 缺失者**在同定级内垫底**；同分或同缺分之间不做确定性约束（稳定排序保持原顺序），**由大模型判断**。落地三处：摘要渲染顺序（`redis_digest.py`）、`redis_subagent` 收集 `root_cause`/`suggestion` 的顺序、`REDIS_PROMPT` 要求模型照摘要顺序排 `redis_root_causes`/`next_steps`。

> 注：由于取分口径与 grade 用同一套区间，**当前「先 grade 再 score」等价于「纯按 score 降序」**。两者仍分开写，是为了将来某个因子的取分口径与 grade 区间不一致时依旧 grade 优先。

## 6. 谁来算

- **redis 子智能体**：由逐因子判级 + 组合规则（`rules/redis/redis_scorer.py` 调 `redis_cpu_escalation_rule.py`）确定性算 grade + score。
- **其余维度（cpu/memory/diskio/gc、mysql 子智能体、jvm 堆栈分析本体）**：各维度 agent 按 prompt 口径给 grade/score，结论末尾以标记 `[GRADE=<P0|P1|P2> SCORE=<0-100>]` 输出。
- **jvm 线程堆栈分析维度**：redis 侧有确定性 grade/score 时，用它覆盖 LLM 给的值（`core/nodes/jvm_stack_nodes/jvm_stack_deep_dive_nodes.py`）。
- **aggregate**（`core/nodes/aggregate.py`）：解析各维度 grade/score 做确定性排序，LLM 只负责组织文案与建议。

## 7. 落点

| 关注点 | 文件 |
|---|---|
| grade/score 阈值、标记解析、排序键、取更高 grade（`higher_grade`） | `rules/grade.py` |
| 各 metric 判级阈值（固有延时 max ≥ `INTRINSIC_P0_MS` 定 P0 / ≥ `INTRINSIC_P1_MS` 定 P1、网络延时均值 ≥ `NET_P0_MS` 定 P0 / ≥ `NET_P1_MS` 定 P1、O(N) 条数 ≥ `O_N_P0_MIN_COUNT` 定 P0、INCR 条数 ≥ `INCR_MIN_COUNT` 提示；`CPU_HIGH_PCT` 不参与逐因子判级，经 `cpu_sustained` 参与 §5.1 的归并判据） | `rules/redis/redis_threshold.py`（数值只此一处） |
| 各 metric 逐因子判级 | `rules/redis/redis_<metric>_rule.py` |
| 组合规则：CPU 持续高时归并延时因子（§5.1，含根因文案模板与建议常量） | `rules/redis/redis_cpu_escalation_rule.py` |
| 因子级 score 取分口径与展示顺序（§5.2） | `rules/redis/redis_types.py`（`score_from_overshoot` / `factor_sort_key`） |
| 规则引擎确定性得分 | `rules/redis/redis_scorer.py` |
| 维度 prompt 定级要求 | `prompt/prompt_templates.py`（`FACTOR_GRADING`、`GRADE_SCORE_INSTRUCTION`） |
| 确定性排序 | `core/nodes/aggregate.py` |
| 规则命中→用户自定义（机制保留，当前无规则产出） | `constant/rule_content.py`、`core/agents/redis_subagent.py` |
| redis 确定性定级注入 jvm 结论 | `core/nodes/jvm_stack_nodes/jvm_stack_deep_dive_nodes.py` |
