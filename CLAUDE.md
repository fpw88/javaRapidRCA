# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目是什么

LangChain/LangGraph 1.x 多智能体，用于排查「Java 服务响应慢」的根因：解析排查请求 → 派发到 CPU / 内存 / 磁盘IO / GC / 线程堆栈 5 个维度做诊断 → 汇聚成根因排序报告 → 审核后输出。通过 SSH 连目标服务器执行诊断命令；也支持直接分析本地已抓取的线程堆栈文件（不连服务器）。

## 环境与运行

- 用 **conda**（env 名 `rca_env`），**不用 uv**。依赖：`pip install -r requirements.txt`（langchain 1.2.x / langchain-openai / paramiko / python-dotenv）。
- 配置走 `.env`（`config/config.py` 用 dotenv 加载）。**仓库里没有 `.env.example`**，直接建 `.env`。必备项（缺任一项 `main.py` 直接 `SystemExit`）：`MODEL` / `MODEL_API_KEY` / `SSH_HOST` / `SSH_USER` / `SSH_PASSWORD`。其余：`MODEL_PROVIDER`(默认 openai) / `MODEL_BASE_URL` / `SSH_PORT` / `LOG_LEVEL`。模型走 OpenAI 兼容接口（`MODEL_BASE_URL`）。
  - **redis 在另一台机器**时单独给 `REDIS_HOST` + `REDIS_SSH_PORT|USER|PASSWORD`（不填则回退主 SSH）；网络延时在主 SSH 上测、固有延时/慢日志在 `REDIS_SSH` 上测，所以这两台**都要有 redis-cli**。
  - `MEASURE_SECONDS`(默认 60) / `MEASURE_INTERVAL_SECONDS`(默认 5) 控制采集时长与采样间隔——**单次采集会阻塞 60 秒以上**，调试采集时先调小。
  - 例外：mysql 的 `MYSQL_HOST|PORT|USER|PASSWORD` **不走 `config/config.py`**，是在 `tools/mysql_tools.py` 里直接 `os.getenv`（host 默认回退 `SSH_HOST`）。
- 运行：`python main.py [任务描述]`；不带参数用 `main.py` `__main__` 里的默认任务——当前**写死为「分析 `dumps/` 下某个具体 dump 文件」**（其余候选任务在注释里），不是全量服务器排查。
- **无 pytest / lint 套件**。改完用 `python -m py_compile <files>` 做语法检查。现有的三个自测入口：
  - `python -m rules.redis.offline_test` —— redis 规则层的**主回归自测**：喂真实原始输出样本，断言解析 → 判级 → 组合规则归并 → 摘要 → 校验全链，纯离线、不连服务器。**改 `rules/redis/` 后必跑。**
  - `python tools/jvm_stack_tools.py` —— 线程堆栈分析的离线自测。
  - `python test/tool_test.py` —— **要连真实服务器**（直接调 `diagnose_redis` 采集）。

## 架构（大图）

图在 `core/graph.py` 装配：`orchestrator`（意图识别 → 选维度）→ 条件边 `Send` **并发** fan-out 到 5 个维度 agent → `aggregate`（汇总 → 根因排序报告）→ `check`（审核）→ END；另有 `reinput` 回路（意图不明确时中断让用户重输）。

- 核心文件：`core/states/`（图状态 `RcaState`/`JvmStackState` 分文件 + 常量 + 解析辅助）、`core/nodes/`（按层的节点 + 路由函数：`orchestrator.py` / `aggregate.py` / `check.py`，子包 `jvm_stack_nodes/` 放 jvm 子图的节点定义，`__init__.py` 聚合导出）、`core/agents/`（按维度的智能体构建，每维度一个文件，`__init__.py` 的 `build_dimension_agents` 是唯一入口）、`core/llm.py`（全局 `LLM` 常量）、`core/graph.py`（`build_graph()`）。`main.py` 是 CLI 入口 + 人工在环 resume 循环（在 `core/agent.py` 的 `run()`）+ 报告打印。
- 每个维度是 `create_agent`（LangChain 1.x）子智能体；`jvm线程堆栈分析` 是更深的子图（`core/agents/jvm_stack_agent.py` 的 `build()` 只做装配：建 agent + 连边 + 编译；其节点定义在 `core/nodes/jvm_stack_nodes/`，redis/mysql 子智能体节点分别在 `core/agents/redis_subagent.py` / `mysql_subagent.py`），把 `redis子智能体` / `mysql子智能体` 作为子图节点，通过 `dimension_provenance` 结构化字段把「子智能体 + 规则号」经 state 传给汇聚层。
- 人工在环：工具里 `interrupt()`（选 PID、抓堆栈等）；`core/agent.py` 的 `run()` 用 `Command(resume=...)` 按中断 id 回填，支持多并发中断。

读代码的入口（比本文更细/更权威，先看这几个）：

- **`main.py` 顶部的模块 docstring** 画了完整的图结构与分层（接入 / 编排 / 诊断 / 深入 / 汇聚 / 审核）。
- **`docs/root_cause_grading.md`** 是**定级口径的单一事实来源**：grade/score 阈值、根因最终排序规则、redis 的 CPU 归并规则、因子级 score 与展示顺序。**改定级口径先改它**，再改 `rules/grade.py` 与各维度实现。
- **`asset/metric_data_format/redis/`** 存各指标的**原始输出样本**（cpu/latency/net/slowlog 各一份），写解析器前先对着它看真实格式。
- **`core/agent.py` 的 `run()`**：`recursion_limit=300`（5 维并发 + 深入层委派工具调用很多，**默认 25 会被顶穿**，加维度 / 加子智能体时留意）；`thread_id` 写死 `"rca-txid"`；checkpointer 用 `InMemorySaver`。

## 跨文件契约（改代码前必读）

- **维度结论落款**：各维度 prompt 要求结论以 `维度结论[<dim>]:` 开头（常量 `DIMENSION_MARKER`，在 `prompt/prompt_templates.py`）。`aggregate` 靠这个前缀识别各维度结论——改 prompt 或 aggregate 任一侧都要保持同步。
- **工具按维度分文件**：`tools/` 下每维度一个文件，`stack` 维度在 `tools/jvm_stack_tools.py`；共享的 SSH 执行在 `util/ssh_client.py`（`ssh_exec` 返回 (stdout, stderr)；`run_cmd` 只返回 stdout，空输出时把 stderr 当说明返回），输出截断 / 文本落盘在 `util/_common.py`（`cap` / `write_text`）。新增普通维度要同步改 3 处：工具文件、`prompt/prompt_templates.py` 的 prompt、`core/agents/<dim>.py`（声明 `NAME` / `SYSTEM_PROMPT` / `TOOLS`，并在 `core/agents/__init__.py` 的 `_SIMPLE_MODULES` 注册），另需把维度名加进 `core/states/__init__.py` 的 `ALL_DIMENSIONS`。
- **redis 三层与顶层目录一一对应**：`parse_metrics/<middleware>/`（**解析**：原始命令输出 → 结构化数据类，纯函数 `parse_*`，纯标准库、不碰网络、不依赖 LangChain）→ `rules/<middleware>/`（**规则计算**：确定性判级 / 得分 / 摘要渲染 / 结论校验；redis 的按关注点拆——`redis_threshold.py` 判级阈值 / `redis_types.py` 数据类与因子口径 / `redis_<metric>_rule.py` 逐因子判级（与解析层 `redis_<metric>*` 一一对应）/ `redis_cpu_escalation_rule.py` 组合规则（跨因子：CPU 持续高时把命中的延时因子并入 CPU，**不是**逐因子判级）/ `redis_scorer.py` 组装（逐因子判级 → 组合规则归并 → 整体得分）/ `redis_digest.py` 摘要 / `redis_validate.py` 校验）→ 采集层（**命令构造与采集**，带副作用，redis 的在 `util/redis_command.py`）。两层都从各自子包的 `__init__.py` 统一导出**函数与数据类**（模块内部的配置常量不导出），调用方 import 子包、不直接摸文件；加新解析器 / 新规则就加进对应子包的 `__init__.py`。**目前只有 redis 走这套三层**：`parse_metrics/mysql/` 是空目录，mysql 只有 `core/agents/mysql_subagent.py` + `tools/mysql_tools.py`（没有解析层与规则层）——给 mysql 补规则时按 redis 的形状建。
- **常量归哪层，看它决定什么**：**判级阈值**（P0/P1 多少毫秒、O(N)/INCR 算「大量」的条数）住在**规则层** `rules/redis/redis_threshold.py`，解析层一个阈值都不持有；**解析期口径**（命令白名单 `O_N_COMMANDS`/`INCR_COMMANDS`、大key候选口径 `BIG_KEY_*`）留在 `parse_metrics/redis/`，因为它们决定解析出的 dataclass 里有什么；**三方共用口径**（score↔grade 阈值、定级标记解析、`sort_key`）放 `rules/grade.py`——它是 rules/ 下的跨维度通用口径，不属于任何 `rules/<middleware>/` 子包，被规则引擎 / jvm 子图汇聚 / `core/nodes/aggregate.py` 共用。判例：`CPU_HIGH_PCT` 曾由 `score_redis` 判级用、且曾因解析层拿它数 `gt90_count` 而被焊在解析层——现已改为解析层只吐原始采样 `CpuUsage.pcts`、规则层自己套阈值；`grade_redis_cpu` **自身**仍恒返回 grade `""`（不单独定级），但 `CPU_HIGH_PCT` / `cpu_sustained` 已被组合规则 `redis_cpu_escalation_rule.py` 复用（`cpu_sustained` 为真且固有延时/网络延时命中 P0/P1 时归并，见下一条），因此该常量**重新间接参与判级**。
- **CPU 持续高归并延时因子（rules/redis/redis_cpu_escalation_rule.py）**：`cpu_sustained(cpu)` 为真、且固有延时/网络延时**至少一个**命中 P0/P1（「和、或」= 任一命中即可）时，把命中因子的 grade（**取高者**，用 `rules/grade.py` 的 `higher_grade`）、summary、evidence 并入 CPU 因子，把文案写进 `cpu.custom_root_cause` / `cpu.custom_suggestion`（根因文案按**实际命中的**延时因子套模板生成——单边命中只写那一个、双边才写「固有延时、网络延时」，因子名取 `redis_types.py` 的 `FACTOR_NAME`），并把**命中的**延时因子从因子表移除（未命中的延时因子照常保留作反证）。要点：单因子判级函数（`redis_<metric>_rule.py`）一律不改，`grade_redis_cpu` 自身仍恒返回 `""`；`_compute_overall_score` 公式不改（多命中会被去重，score 只降、不跨 grade 档）；文案模板与建议常量在 `redis_cpu_escalation_rule.py` 顶部，改措辞只动这一处。`redis_types.py` 的 `FACTOR_KEYS` 是**静态合法标签白名单**（命中集由 `redis_validate.py` 按 `score.factors` 动态算），归并后**不要**从白名单里删 intrinsic/net。
- **因子级 score 与展示顺序（rules/redis/redis_types.py）**：`FactorFlag.score`（0-100，可为 `None`＝未取分）是**因子级**得分，与维度级 `_compute_overall_score` 的 score（数 P0/P1 个数）是两回事，互不影响。取分口径 `score_from_overshoot` 保证 `grade_from_score(score) == 该因子 grade`（故 grade 与 score 不会互相矛盾）；展示顺序 `factor_sort_key` = **先 `grade_rank`、同 grade 再按 score 降序**，score 缺失在同定级内垫底，同分/同缺分不排序、交大模型判断。落地三处：`redis_digest.py` 的摘要渲染顺序、`redis_subagent.py` 收集 `root_cause`/`suggestion` 的顺序（`root_cause` 取排序最前的那条，不再取「列表里第一个非空者」）、`REDIS_PROMPT` 要求模型照摘要顺序排 `redis_root_causes`/`next_steps`。
- **redis 采集层（util/redis_command.py）**：`collect_*` 采集并落盘原始输出（dumps/metrics/），`ensure_redis_cli` 做预检并含 langgraph `interrupt()`，**必须由调用方在并发采集之前调用**（并发线程里中断无法回填）。注：它的 `_LOCAL_INSTALL_SCRIPT` 用 `__file__` + `..` 定位 `asset/shell/`——**改这个模块的目录深度（挪包/挪层）必须同步改 `..` 的层数**，否则路径会静默指到仓库外、只表现为「本地安装脚本不存在」的告警。
- **本地堆栈分析**：`util/jvm_stack_util.py` 是纯标准库、离线解析 jstack dump（不依赖 LangChain）；原始 dump 不交给大模型，只产出摘要报告 + 每栈顶的明细文件，模型用 `read_stack_detail` 按需读明细。抓取线程堆栈的 SSH 辅助（列 Java 进程 / 定位 jstack-jcmd / 存 dump）也在该模块，`tools/jvm_stack_tools.py` 只是 `@tool` 壳。
- **dumps/ 产物命名（溯源）**：一次排查的产物同主干，按名字即可从 dump 追到结论——`thread_dump_<pid>_<ts>.txt`（原始 dump，`_save_dump`）→ `analysis_<dump主干>.txt`（解析总报告）/`_stacktop_<n>.txt`（栈顶明细，`build_report` 写）→ `_result.txt`（analyze 阶段大模型分析，`capture_jvm_stack_analyze_result` 写）/`_conclusion.txt`（维度结论，`jvm_stack_aggregate` 在定级覆盖后写）。命名与 path 函数都在 `util/jvm_stack_util.py`，落盘统一走 `write_text`；产物目录常量是 `config/config.py` 的 `STACK_DUMP_DIR`（采集原始指标落 `METRICS_STORE_DIR`/`dumps/metrics/`）。堆栈文件路径由 `analyze_thread_dump` 工具用 `Command` 回写 `JvmStackState.jvm_stack_dump_file_path`（故 `create_agent` 必须传 `state_schema=JvmStackAnalyzeState`），落盘命名只取 basename。
- **结构化来源（dimension_provenance）**：`jvm线程堆栈分析` 子图的 `redis子智能体`/`mysql子智能体` 节点（`core/agents/redis_subagent.py` / `mysql_subagent.py`）把「子智能体 + 命中规则号」写进 `core/states/` 的 `dimension_provenance`（`operator.add` 合并），`core/nodes/aggregate.py` 的 `aggregate` 据此渲染「证据维度」的 `jvm线程堆栈分析 > redis子智能体 > 规则号` 层级——改节点写入或 aggregate 读取任一侧都要保持字段结构 `{"dimension","sub_agent","rules"}` 一致。redis 的 entry 还会带两个**可选**键 `root_cause`（str）/ `suggestion`（list[str]）——由 redis 子智能体从因子的 `custom_root_cause`/`custom_suggestion` 透传，`core/nodes/aggregate.py` 据此生成「【用户指定内容，必须逐字使用、不得改写】」；`rules` 目前恒为 `[]`。
- **规范名称（core/states/__init__.py）**：`jvm线程堆栈分析` / `redis子智能体` / `mysql子智能体` 三个名称集中定义在 `core/states/__init__.py`（`JVM_STACK_AGENT` / `REDIS_SUBAGENT` / `MYSQL_SUBAGENT`），内部 key、图节点名、路由 token、prompt、`dimension_provenance` 全部引用这些常量，改名只动这一处；`_normalize_agent_name()` 做去空格+小写归一化容错 LLM 输出。
- **模型常量（core/llm.py）**：LLM 模型对象是 `core/llm.py` 的模块级常量 `LLM`，各 agent / node 直接 `from core.llm import LLM` 使用，**不要**再作为函数参数逐层传递。该模块在 import 时即构建模型，缺 `MODEL` / `MODEL_API_KEY` 会以 `SystemExit` 抛出与 `main.py` 一致的友好提示（`api_key=""` 会让 langchain-openai 抛 SDK 原始异常，故必须有这个前置守卫）。
- **用户自定义规则内容（constant/rule_content.py）**：`RULE_CONTENT` 按规则名（如「规则N」）映射 `root_cause`（str，根因描述）与 `suggestion`（list[str]，首部处理建议），稀疏可选；规则命中时由节点（redis 子智能体，`core/agents/redis_subagent.py`）把用户内容 + `rule_text`（规则引擎确定性因果链）随 `dimension_provenance` 传，汇聚层据此「用户指定优先、大模型兜底」。改措辞只动这一处。注意：`RULE_CONTENT` 现为空字典、暂无消费方，此机制与文件保留供后续新规则使用——现有的 CPU 归并规则（规则见下条）**不走**这个覆盖层，它的文案由规则层 `redis_cpu_escalation_rule.py` 按命中因子生成后直接写进因子的 `custom_root_cause`/`custom_suggestion`，再由 redis 子智能体透传（链路：因子字段 → `dimension_provenance` 的 `root_cause`/`suggestion` → aggregate 逐字采用）。

## 坑与约定

- **GBK 控制台**：Windows 中文控制台里 `print` ✓/✗（U+2713/U+2717）会让 Python 直接崩溃，且**只在运行到那一行才暴露**；`util/jvm_stack_util.py` 与 `rules/redis/redis_digest.py` 各有一个 `_safe_text()`（把文本转成 GBK 可编码）就是为此，新增面向控制台的输出时沿用这个守卫。
- **`tools/http_tools.py` 目前是死代码**：`get_http_latency` 没有被任何 agent 或图节点引用，别以为它在生效。
- **日志**：`LOG_LEVEL`（INFO = 关键动作 + 关键产出，DEBUG = 详情）。`util/log.py` 的 `setup_logging` 会把 paramiko / httpx / langchain 等第三方日志压到 WARNING，避免 `DEBUG` 被刷屏。
