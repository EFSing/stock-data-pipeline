# DECISION_LOG.md — 重要决策记录

只记录重要架构／交易规则决策，不记录普通 Bug 修复。

## 2026-08-21

**Decision:** 确立 GitHub 仓库为项目唯一可信事实来源，`AGENTS.md` + `docs/` 作为跨 AI 工具共享上下文。

**Reason:** 项目将在多设备、多 AI 工具间接力开发，聊天记录不可作为长期记忆。

---

**Decision:** 项目版本基线定为 `V0.2`。

**Reason:** 行情抓取、双源校验、Google Sheets 写入已完成；交易决策引擎（Swing/Market Structure/Setup/Risk）尚未开始。仓库此前无版本号文件。

---

**Decision:** 保持现有扁平模块结构，不强行迁移到 `src/` 包布局。

**Reason:** 现有 4 个模块职责清晰且稳定；交易决策模块增多前的大规模重构风险大于收益。渐进重构优先。

---

**Decision:** 波浪分析采用「主情景 + 备选情景」，不武断输出唯一浪型；证据不足输出 `UPTREND_UNKNOWN_WAVE`。

**Reason:** 降低 Elliott Wave 主观性，防止行情波动时频繁改浪。

---

**Decision:** R/R 是交易准入条件，不是固定止盈；先算合理 Target 再算 R/R，禁止倒推目标价。

**Reason:** 防止为满足 R/R 阈值人为制造目标价格。

---

**Decision:** Swing 区分 `CONFIRMED` 与 `PROVISIONAL`。

**Reason:** 防止 Look-ahead Bias，回测时禁止拿未来确认的 Swing 回填过去信号。

---

**Decision:** 在 `requirements.txt` 增加 `tzdata` 依赖。

**Reason:** Windows 本地开发缺少系统时区数据库，`ZoneInfo("Asia/Shanghai")` 会报错；GitHub Actions 的 Ubuntu 环境自带但本地需要显式安装。

---

## 2026-08-22

**Decision:** Phase 1 Trading Core 采用克制目录结构 `trading/`（models/indicators/swing/structure/fibonacci/risk），单一权威实现，输入复用 `core.Quote`，不新建 Bar 类型。

**Reason:** 全仓库搜索确认无任何交易概念既有实现；避免重复实现与过度拆文件。

---

**Decision:** `SwingPoint` 记录 `pivot_index/pivot_date`（Swing 发生时间）与 `confirmed_index/confirmed_date`（信息实际可用时间）；任何历史决策只能用 `confirmed_index <= t` 的 Swing。

**Reason:** 明确「as-of t」语义，防止未来数据回填修改历史决策。

---

**Decision:** `MarketStructure.trend` 增加 `TRANSITION` 与 `UNKNOWN`；Swing 数量不足或结构不明确时禁止强制分类为趋势/区间。

**Reason:** 避免在证据不足时武断判定市场状态。

---

**Decision:** `fibonacci.py` 不依赖 `structure.py`，Fibonacci 只消费 `SwingPoint`。

**Reason:** 降低模块耦合，Fibonacci 是纯几何计算，不应绑定趋势判定。

---

**Decision:** `risk_reward()` 使用 `execution_stop` 计算真实 R/R；Structural Invalidation 与 Execution Stop 是两个独立概念，不在 R/R 计算中混用。

**Reason:** 结构失效与执行止损语义不同，混用会导致风险被高估或低估。

---

**Decision:** 指标定义固定：Wilder ATR、Wilder RSI、EMA 标准 `2/(N+1)`；warm-up 区间返回 `None`；指标序列长度与输入 Quotes 对齐。

**Reason:** 保证指标可复现、与输入逐位对齐，warm-up 不含未来信息。

---

**Decision:** Swing V1 以 causal pivot 为基础，可选 ATR / percentage minimum excursion filter 降噪；禁止使用事后重绘 ZigZag。

**Reason:** ZigZag 事后重标历史节点天然引入 look-ahead bias；causal pivot + excursion filter 保证因果性。

---

**Decision:** Trading Core 输入强制校验：日期严格升序、无重复、同一 symbol/market；异常 fail fast（抛异常），不静默排序或修正。

**Reason:** 输入脏数据静默修正会掩盖上游问题；显式失败更安全。

---

**Decision:** Phase 1 `PositionSize` 只输出 theoretical quantity / risk capital / max loss；A股手数、港股 lot size 等 executable rounding 待市场元数据接入后再做，不在本 PR 硬编码。

**Reason:** 避免过早绑定市场规则，保持 Phase 1 计算层纯净。

---

**Decision:** SETUP_03 多头 Execution Stop = `breakout_price - atr_buffer * ATR`，Structural Invalidation 保持 `platform_low`；R/R 始终用 Execution Stop 计算。

**Reason:** 结构失效价（platform_low）是「认错」的最终边界，而非执行止损；若用 platform_low 做止损，risk 偏宽导致多数突破 R/R 天然偏低（系统 mathematically dead）。用突破价下方 ATR buffer 作为执行止损，让 R/R 能真实反映盈亏比，同时保留 structural_invalidation 作为独立失效概念。

---

**Decision:** Decision 的 Target 语义：历史前高 + Fib 1.272/1.618 均为候选；过滤 None/≤planned_entry 后按价格升序依次为 T1/T2/T3；R/R quality 以最近有效目标 T1 为 gate，不指定历史前高优先。

**Reason:** 最近目标最保守，以其 R/R 作为准入闸门，防止用遥远目标的高 R/R 掩盖近期风险。

---

**Decision:** Phase 4 `交易决策` Sheet 仅展示 Trading Core 已生成的 `Setup` / `Decision`；仅在正式收盘且 qfq 最后一根日期与 chosen 行情日期一致时运行当日决策。qfq 使用 `自选清单.历史数据源`，仅允许 yfinance / BaoStock，不复用 Tencent/Sina 快照链。Setup/Decision 全部参数从 `参数设置` 显式读取并原样传入。

**Reason:** 防止展示层复制交易公式、非正式数据触发决策、快照源误入历史计算，以及生产环境因隐式默认值产生不可追踪的参数漂移。

---

**Decision:** Phase 5A SETUP_03 Historical Replay & Diagnostics 作为只读诊断层实现，逐个历史交易日仅向现有 `detect_platform_breakout()` / `decide_platform_breakout()` 传入 `quotes[:i+1]` 前缀；不复制 Swing / Setup / Decision 交易逻辑，不写入正式 `交易决策` 表，不修改生产参数。

**Reason:** 回放输出用于诊断每个标的历史 Setup 状态分布与 CONFIRMED 日 Decision 结果；前缀输入是最直接的 as-of 防线，可防止未来 bar、未来 Swing 或未来突破污染历史状态。

---

**Decision:** Phase 5A replay 汇总明确区分「状态日」与「事件」：CONFIRMED 事件仅在 `setup.confirmed_index == 当前 replay index` 当日记录，FAILED 事件仅在 `setup.state_entered_index == 当前 replay index` 当日记录；Decision 只在真正 CONFIRMED 事件日运行一次。

**Reason:** `detect_platform_breakout()` 的 CONFIRMED/FAILED 是终态，在没有新 Setup 前后续 bar 可能继续返回同一终态。若按终态状态重复计数，会把持续天数误判为多次确认/失败并重复运行 Decision。

---

## 2026-08-24

**Decision:** 生产 Google Sheets 发布与 Historical Replay 共用 `trading.events.evaluate_setup03_event()` 的终态事件语义。`CONFIRMED/FAILED` 是状态；只有 `confirmed_index == 当前最后索引` / `state_entered_index == 当前最后索引` 才是首次终态事件。`交易决策` 仅发布新的 CONFIRMED Decision 事件，并以已有 Sheet 事件键阻止同日重跑再次计算 Decision。

**Reason:** PR #10 的生产路径按每日状态运行 Decision，而 PR #11 的回放路径按首次终态事件运行，两者语义分叉；仅依赖 Sheet upsert 虽不增加重复键，仍会重复计算入场方案并把持续 CONFIRMED 状态误作新交易信号。

---

**Decision:** SETUP_03 真实回放在 Trading Core 前增加只读数据质量门控：保留数据源原始顺序以检查重复/乱序，校验空序列、最小样本、最新日期、最新数据滞后与异常日历缺口；enabled=0 或 calculable=0 时 workflow 失败，但失败诊断 artifact 始终上传。

**Reason:** 排序后再校验会掩盖源数据日期乱序；全部标的跳过仍成功会产生“回放已完成”的假阳性。质量阈值与 Trading 参数一起写入事件 artifact 参数快照，确保结果可追踪。

---

**Decision:** Phase 5B SETUP_03 Research Backtest 只消费 `trading.events.evaluate_setup03_event()` 通过 Historical Replay 产生的 CONFIRMED event contract。T 日仅确认信号，T+1 Open 才可模拟执行；生产 `platform_tolerance_pct=0` 保持不变。敏感性 54 组参数仅输出客观统计，不排名、不选“最佳参数”、不回写生产配置。

**Reason:** 保证 Phase 5B 与生产发布使用同一事件语义，避免回测重建终态事件或根据结果篡改历史信号。

---

**Decision:** 在生产 Position Management / Exit 尚未定义前，Phase 5B 的 `final_R` 使用显式 research-only 20 交易日首障碍口径：stop 与 T1 同 bar 按保守 stop-first；20D 未触发则按期末 close 盯市；不足 20D 且未触发为 censored，不进入 R 统计。`sample_size` 是有可观测 `final_R` 的成交样本数，另行输出 `confirmed_count` / `executed_count` / `censored_count`。

**Reason:** 当前不应虚构多段止盈或持仓管理为生产规则；明确的保守诊断口径使 expectancy / profit factor 可复现，同时对未成熟样本避免端点偏差。

---

**Decision:** Phase 5B 的时间顺序固定为：T 日 SETUP_03 首次 CONFIRMED 后，使用仅截至 T 日的 as-of 数据生成生产 Decision；只有 `DecisionAction.ENTRY_ALLOWED` 才成为 T+1 执行候选。T+1 才读取 Open 并依次归类：`Open < breakout_price` → `SKIP_GAP_BELOW_BREAKOUT`；`breakout_price <= Open <= entry_zone_high` → `EXECUTED` 且 `actual_entry=Open`；`Open > entry_zone_high` → `SKIP_GAP_ABOVE_ENTRY_ZONE`。无 T+1 bar 仅适用于已通过 Decision gate 的候选。

**Reason:** CONFIRMED 是 Setup 终态事件，不等于自动成交；生产 Decision 是 T 日前置 gate。先检查 T+1 再检查 Decision 会把末日 `NO_TRADE` 错分为无 T+1，从而污染漏斗并模糊真实零成交原因。研究结果即使为零成交也不得据此放宽生产规则。

---

**Decision:** Phase 5B 日线 excursion 采用不虚构分钟顺序的保守退出 bar 口径：首次退出之前的 bar 使用完整 high/low；STOP bar 的 adverse excursion 截止 stop，退出 bar 内先后不明的 favorable high 不计；T1 bar 的 favorable excursion 截止 T1，而仍高于 stop 的 low 可能发生在 T1 前，按保守 worst-case 纳入 adverse excursion。退出后的 bar 与越过首个退出障碍后的价格不再计入 MFE/MAE。`observation_days` 表示从 T+1 起到首次退出且包含退出 bar 的实际观察交易日数；无退出时才记录可用 forward bars（最多 20）。

**Reason:** 日线 OHLC 无法证明同一 bar 内 high/low 的先后。直接使用退出 bar 完整极值会出现 stop-first `final_R=-1` 却同时把同 bar 后续高点计入 MFE 的内部矛盾；明确 barrier-capped 口径可复现且不伪造分钟级路径。

---

## 2026-08-25

**Decision:** Phase 5C 将 SETUP_03 Decision gate reason 实现在生产 Decision 计算函数内部：同一次计算返回原有不可变 `Decision` 与只读 `DecisionDiagnostics`。兼容入口 `decide_platform_breakout()` 仍只返回原 `Decision`；事件层把 diagnostics 随统一 CONFIRMED contract 传给 Replay/Research。Research 只投影 reason 与中间值，不复制 ATR、Entry Zone、Target 或 R/R 判断。

**Reason:** Decision action 与拒绝原因必须共享 Single Source of Truth，才能解释 CONFIRMED → NO_TRADE 而不产生规则漂移；将 diagnostics 与 `Decision` 分离也能保证生产对象、Sheet 投影和交易行为完全不变。

---

**Decision:** Phase 5C 固定 54 组网格逐事件只允许一个 reason，逐参数组合强制 `CONFIRMED = ENTRY_ALLOWED + 所有 rejection reason`。缺失或未知诊断显式落入 `OTHER_NO_TRADE`，不得丢样本；结果仅按原网格稳定顺序输出，不排名、不打分、不选最佳参数。

**Reason:** 研究目标是定位新增 CONFIRMED 被哪个生产 gate 拒绝，而不是根据样本内结果调参或放宽规则；显式守恒和 OTHER 兜底可防止无法解释的样本静默消失。

---

**Decision:** Phase 5D 对真正进入 Historical Replay 的完整 `Quote` 使用版本化 canonical schema `setup03-replay-input-v1`。字符串原样保存、日期使用 ISO-8601、所有数值以 Python `float.hex()` 精确编码；逐 symbol 哈希 canonical bar stream，再对按 symbol 排序的 manifest 计算 dataset aggregate SHA-256。

**Reason:** 十进制 CSV 格式化、字典顺序或不同输出表头都不应影响输入身份；精确浮点编码能检测单根 OHLC/辅助字段的位级修订，排序后的二级哈希同时保证 watchlist 遍历顺序不影响结果。

---

**Decision:** Phase 5D frozen input 使用 artifact-only deterministic gzip JSONL，首行嵌入 input manifest。读取时必须重算并完全匹配 manifest，随后把 Quote 原样送入既有 Replay/Decision/Research 链；workflow 可通过 prior run ID 下载 frozen artifact，禁止在 frozen 模式重新抓取历史行情。

**Reason:** `same input + same config/code = same replay result` 必须能在真实 workflow 中独立验证，而不受上游行情修订或三年滚动窗口影响；artifact 不进入 Git，避免把大型历史数据写入仓库。

---

**Decision:** manifest comparison 对每个 symbol 采用稳定的主分类优先级：added/removed → bar count → date range → same-count content hash → identical，并始终保留前后 count/range/hash 供审阅。

**Reason:** 一次变化可能同时影响数量与日期；单一优先分类便于自动汇总，而保留全部前后字段不会丢失次级差异信息。

---

**Decision:** Phase 5E Frozen Dataset Validation 固定使用 Phase 5D 首轮 live run `32826696259` 经 frozen run `32829662164` 验证的 canonical dataset，aggregate hash 为 `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`；生产参数版本同时锁定为 `sha256:abe4d3026892`。Phase 5E 入口必须是 frozen input，hash 或参数版本漂移立即失败。

**Reason:** Phase 5E 的正式历史描述必须消除 live historical OHLC 修订与配置漂移；同时固定 input identity 和生产参数 identity，才能让结果可审阅、可复现且不会悄然换样本或换规则。

---

**Decision:** Phase 5E 只统计生产参数下既有 ReplayEvent / Decision / T+1 execution contract，不运行 Phase 5B 的 54 组敏感性网格。信号后 forward return、MFE、MAE 以 CONFIRMED 日 `signal_close` 为锚，观察后续 5/10/20 个交易日的 close/high/low，仅作为描述性路径诊断；它与实际成交后的 `Setup03TradeOutcome` 分开，不定义生产持仓规则。

**Reason:** 正式冻结样本验证与参数诊断必须分离。生产漏斗为零时，应客观报告收益与 Edge 不可评估并定位阻断阶段，而不是借用非生产参数样本、调参或把事后路径伪装成可交易绩效。

---

**Decision:** Phase 5D/5E 固定数据集已参与开发诊断，明确不属于最终样本外保留集。Phase 5E 不选择参数、不放宽 tolerance / R/R / ATR stop / Target / Entry Zone / execution rules，也不启动正式 out-of-sample validation。

**Reason:** 已被反复观察和用于诊断的数据不能再提供独立样本外证据；把描述性结论与未来 OOS validation 分开可防止选择偏差和过度宣称 Edge。

---

**Decision:** Phase 5F 的 Confirmation Gate reason 必须由 `trading.setup` 同一次 production SETUP_03 状态机计算产生。兼容 API 继续只返回原 `Setup`，只读 diagnostics 随 event/replay contract 传递，research 层不复制任何 Setup 公式。

**Reason:** CONFIRMED 前失败原因必须与真实生产短路顺序和中间值一致；若在 research 层重建 Swing/结构/平台判断，会引入第二套交易逻辑与漂移风险。

---

**Decision:** 每个 frozen bar 按 production gate 的稳定优先级只归入一个 terminal reason，并强制总数守恒。同时失败的其他条件可作为 auxiliary diagnostics 与 near-miss 分布输出，但不参与 terminal 求和。

**Reason:** 唯一归因可证明 6032 bars 无丢失、无重复；辅助多失败保留条件相关性信息，避免因互斥分类而掩盖下游同时过严的约束。

---

**Decision:** Phase 5G 只在 Phase 5E/5F 的固定 dataset 与 production 参数版本上改变 `platform_tolerance_pct`，tolerance 顺序固定为 `0%、0.5%、1%、1.5%、2%、3%、5%、7.5%、10%`。每档重新走既有 strict as-of Replay → Setup/Decision → T+1 execution contract，研究层只聚合已有 diagnostics 与事件，不复制任何 Trading Core 公式。

**Reason:** 单参数隔离和同源计算是判断数量、集中度与结构质量随 tolerance 变化的必要条件；固定顺序且不排名可避免把描述性敏感性研究变成样本内优化。

---

**Decision:** `platform_tolerance_pct=0` 在代码中的确定语义是多个 Swing High 与 Swing Low 的归一化 span 必须严格为零（精确相等）。Phase 5G 将“该默认配置是否表达预期的平台语义”与“非零 tolerance 应选何值”视为两个问题：前者可审计，后者本阶段不回答；不自动修改 production 默认值或 Sheets 配置。

**Reason:** 有效的数值输入不等于合理的业务默认值，而确认默认语义异常也不授权根据同一开发数据选择生产策略参数。两者分离可以避免从诊断直接跳到调参或 OOS。

---

**Decision:** Phase 5H 固定研究 `2.5%、3%、3.5%、4%、4.5%、5%、5.5%`，并仅以 `7.5%、10%` 作为结构压力测试边界。每档继续通过 production strict as-of Replay/Setup 路径；市场比较必须同时报告绝对计数与每千 bar 发生率，不读取 forward return、MFE、MAE、胜率或 P&L。

**Reason:** Phase 5H 的问题是固定 percentage tolerance 是否在不同市场表达一致结构，而不是样本内参数优化；发生率标准化可把 watchlist bars composition 与结构偏置分开。

---

**Decision:** Phase 5H 的波动标准化只使用截至诊断 bar 的 Wilder ATR 与 20 日 close-to-close 实现波动率。相邻 tolerance 的精确稳定性以 `symbol + CONFIRMED date` 计算 Jaccard/retention；另在同一 symbol 内最近日期一对一匹配报告 date drift。即使发现市场异质性，本阶段也不实施 market-specific tolerance。

**Reason:** as-of 标准化避免未来波动泄漏；同时保留精确事件集合与日期漂移可以区分事件新增/消失和同一标的信号时间移动。市场专属定义需要独立阶段与预先冻结设计，不能由当前开发样本直接决定。

---

## 2026-08-26

**Decision:** Phase 5I 以版本化、机器可读的 `research/setup03_frozen_spec.json` 作为 SETUP_03 冻结 inventory 与治理边界的单一事实来源。规范固定 Phase 5G／5H 证据身份、Phase 5E dataset hash、已有 strict-as-of 研究协议和 OOS 前禁止继续调参声明；关键值由 canonical SHA-256 完整性合同保护，同一 freeze version 下漂移必须失败。

**Reason:** 冻结阶段首先要关闭可审计的研究自由度并防止证据、样本或协议悄然变化，而不是把分散在代码和 Markdown 中的研究常量当作隐式规范。

---

**Decision:** Phase 5I 的正式参数冻结结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`。Phase 5G 只隔离了 `platform_tolerance_pct`，Phase 5H 虽显示主研究区部分相邻稳定，但仍存在事件日期漂移、stress boundary 脆弱、市场覆盖小且不均、无 JP 且无 regime 证据。因此不选择 tolerance，不把保持恒定的 lookback/window/proximity 误称为已有证据支持的冻结，并将相关信号自由度显式标记为 `UNRESOLVED`。

**Reason:** “零容差语义退化”不能推出任一替代值；用同一开发诊断集继续搜索或提前查看 OOS 都会扩大选择偏差。证据不足时冻结治理边界、记录缺口，才符合非优化阶段的因果与审计要求。

---

## 2026-08-27

**Decision:** Phase 5J 预注册并冻结 SETUP_03 structural validation protocol，机器可读单一事实来源为 `research/setup03_structural_validation_protocol.json`，版本为 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v1`，最终状态固定为 `VALIDATION_PROTOCOL_REGISTERED_NOT_EXECUTED`。protocol 记录父级 Phase 5I `SETUP_03-FREEZE-2026-08-26-v1` 及 critical-values integrity identity `sha256:447b20182f54b8c994042227bbfbaf94c50b2a9b4ade7332058a014915390a15`。

**Reason:** Phase 5I 只关闭研究自由度并确认尚不足以正式冻结参数；Phase 5J 的职责是先把未来 validation 的样本、门槛、选择顺序和禁区写成不可悄然漂移的 contract，而不是用新的历史数据或 replay 先行试验。

---

**Decision:** Phase 5K future development-validation 的正式 production tolerance 候选严格限定为 `3.0%、4.0%、5.0%`；`2.5%、5.5%、7.5%、10.0%` 只能作为 diagnostic/stress boundaries，`3.5%、4.5%` 及其他未列值不得成为 production candidate。`setup_swing_lookback=5` 与 `platform_window=40` 仅保留 v1 incumbent design constant，不声明最优；market-specific、regime-specific、volatility-normalized production rule v1 禁用。

**Reason:** 这是将 Phase 5I 的 unresolved 状态收敛为预注册的验证问题边界，不把历史研究网格或诊断边界误写成生产候选，也不在 validation 前扩大参数自由度。

---

**Decision:** 未来 development-validation dataset 固定覆盖 CN/HK/US/JP/SE，每市场至少 8 个标的、总计至少 40 个标的、每市场目标至少约 6000 个有效日 K bars。标的必须在看到 SETUP_03 输出前按市场、流动性、历史长度、数据完整性等非信号元数据确定；symbol manifest 必须先冻结并 SHA-256 hash，再允许 Phase 5K 获取和分析行情；任何根据 SETUP_03 结果替换、增加或删除标的均禁止；覆盖不足返回 `INSUFFICIENT_COVERAGE`。该数据集属于 development validation，不是最终 OOS。

**Reason:** 预先冻结 universe 和 manifest identity 才能把结构稳定性证据与信号驱动的样本选择分离；小于预注册覆盖要求时应报告证据不足，不能静默改变样本。

---

**Decision:** Phase 5K 结构门槛固定为：每市场每候选至少 8 个 CONFIRMED；相邻正式候选 CONFIRMED Jaccard ≥60%、retention ≥80%；匹配事件日期漂移 median ≤5、P90 ≤15 个交易日；市场 CONFIRMED 事件集中度 ≤35%；标的 CONFIRMED 事件集中度 ≤25%；相邻正式候选每千 bar CONFIRMED 发生率相对增幅 ≤50%。market/symbol concentration 必须对 3%/4%/5% 每个 candidate 分别计算，denominator 分别是该 candidate 在全部五个市场/全部 validation symbols 的 CONFIRMED，不得合并候选事件。样本不足使用 `INSUFFICIENT_VALIDATION_EVIDENCE`，其余门槛失败使用 `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`，均不得根据结果调节。

**Reason:** 这些门槛覆盖 evidence sufficiency、相邻稳定性、时间漂移、市场/标的集中度和 bar-normalized 增长；将缺少样本与结构失败分开，避免把不可判断误报成通过或失败。

---

**Decision:** 正式参数选择预注册为 lexicographic conservative rule，并固定 candidate qualification semantics：3% 必须满足 3% 自身全部 candidate-level thresholds 及 3%→4% 全部 adjacent-pair thresholds；4% 必须满足 4% 自身全部 candidate-level thresholds 及 3%→4%、4%→5% 两侧全部 adjacent-pair thresholds；5% 必须满足 5% 自身全部 candidate-level thresholds 及 4%→5% 全部 adjacent-pair thresholds。按 3%→4%→5% 顺序选择首个 qualified candidate；三者均不满足为 `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`，主要因样本不足无法判断为 `INSUFFICIENT_VALIDATION_EVIDENCE`。禁止使用 forward return、MFE、MAE、win rate、P&L 或任何收益指标，也不从 market/regime 结果生成 production 参数。

**Reason:** 先满足约束再取最小可行候选，保持参数选择的保守、可复现和与收益表现解耦；Phase 5J 只注册规则，不执行选择。

---

**Amendment:** 为消除 protocol-governance 歧义，Phase 5J v1 的 canonical protocol hash 由 `sha256:b0fe288b66ff5a86b127d57c1cb2493b583d252dcb169edbc86fab52830948bd` 绑定到 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v1` 的不可变 version/hash contract。loader 同时验证 stored hash 与当前内容重算值一致，以及 version 对应的 pinned hash 一致；因此只改保护字段并重算 JSON 内 hash、但不升级 version 的内容必须失败。parent identity 还必须与实际 `research/setup03_frozen_spec.json` 的 `freeze_version`、`freeze_decision`、`critical_values_sha256` 三项一致。

**Reason:** integrity envelope 只能发现未同步 hash；显式 version/hash contract 才能阻止同一 protocol version 下的同步重算漂移，并把 Phase 5I parent identity 绑定到实际文件。

---

**Decision:** `arm_proximity_pct=0` 在 Phase 5J 只接受 AST 静态依赖审计。审计确认它只影响 WATCH/ARMED proximity threshold transitions、ARMED/WATCH diagnostics、参数校验和传递；正式 `close_t > breakout_price`、`close_t < structural_invalidation` 以及 `trading.events` 的 CONFIRMED terminal event predicate 不依赖该值。因此 v1 保持关闭；若未来代码审计发现其影响正式 CONFIRMED terminal semantics，必须停止并另行报告，不得自行设计替代值。

**Reason:** ARMED 是正式确认之前的中间状态；在没有证据证明 terminal semantics 改变前，静态审计足以支持保持现状，但不授权做数据研究或改 Trading Core。

---

**Decision:** 最新未复权行情选择采用“日期优先、同日质量优先”：交易日期不同时仍采用较新来源；交易日期相同时，若主源 OHLCV 内部异常而校验源正常，则整根行情采用校验源，并同步替换未复权历史序列的同日末根 K 线；两源均正常或均异常时保持主源。双源日期、收盘价与成交量校验规则不变。

**Reason:** yfinance 的 A 股数据连续出现开盘价超出日内最高／最低区间，但收盘价与成交量仍与 Tencent 一致。仅在最终写表后执行合法性检查会让正常腾讯行情无法接替异常主源，并使最新行情与未复权历史不一致。整根 K 线切换可保持 OHLCV 内部一致性，避免逐字段拼接出不存在的行情，同时不放宽质量闸门。

---

## 2026-08-27

**Decision:** PR #24 的 metadata-only foundation 保留为历史治理证据但不合并；PR #24 已关闭且未合并，branch `research/phase5k-a0-metadata-provenance-foundation` 与 head `497bf541e5b92454d4866a066e09364ecdbede4c` 不删除。后续不再追求五市场完整 security-master provenance framework 作为生产路径。

**Reason:** PR #24 正确记录了 `METADATA_PROVENANCE_UNAVAILABLE` 与 fail-closed 边界，但当前业务 deployment scope 已收缩为 CN/US；关闭并保留 branch/PR 证据可以审计历史判断，同时避免把五市场未证明框架扩张进 main。

---

**Decision:** 建立独立 Phase 5J-v2 scope revision，protocol version 为 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US`。validation markets 固定为 CN/US；HK/JP/SE 排除。CN 只启用 SSE/SZSE Main Board common A shares，STAR/ChiNext 分别注册为 `CN_STAR_REGISTERED_INACTIVE` / `CN_CHINEXT_REGISTERED_INACTIVE`，不得进入 Phase 5K、OHLCV 或 qualification，未来启用必须升级 protocol version。

**Reason:** 这是在任何 Phase 5K validation data 或 SETUP_03 output 被查看前记录的 deployment scope revision，不是结果驱动删样本。v1 五市场 protocol 保持为历史注册证据，不被直接继续使用或原地修改。

---

**Decision:** Phase 5J-v2 保持 production tolerance candidates `3%/4%/5%`、`setup_swing_lookback=5`、`platform_window=40`、`arm_proximity_pct=0`、Jaccard/retention/drift/rate、symbol concentration、`LEXICOGRAPHIC_CONSERVATIVE` 与 qualification matrix；移除原五市场 market concentration gate，改为 CN 与 US 各自独立满足剩余结构门槛，禁止市场间补偿。CN primary quota 为 CSI300/500/1000 `12/14/14`，US primary quota 为 S&P500/Nasdaq-100/SOX/IGV `12/10/8/10`；两市场目标均为 `40 PRIMARY/20 RESERVE`。QQQ、SOX index、IGV ETF 只允许 aggregate diagnostics。

**Reason:** v2 只修订 deployment scope 与在两市场下可满足的 concentration semantics，不重新搜索 structural thresholds/tolerance，不读取收益指标，不运行 validation 或正式参数选择。

---

**Decision:** HiThink Financial API 先作为 CN Research Data Provider 做只读 capability/provenance smoke test，不修改生产腾讯/新浪逻辑。2026-08-27 17:52:18 +08:00 的 7 个 bounded GET probe 均 HTTP 200 但 `code=2003`；未配置 `HITHINK_FINANCE_API_KEY`，因此当前仅证明 endpoint/auth error envelope，不能证明代码表、指数成分、market dump、复权因子或交易日历的数据权限与 as-of semantics。原始响应已保存并计算 SHA-256，market dump 未下载。

**Reason:** API Key/额外 entitlement 缺失时必须 fail closed；不得用未授权响应伪造 source metadata、历史成分 snapshot 或 Phase 5K data。后续只有在真实 key/授权可用、响应 `code=0` 且保留 source timestamp/as-of/raw hash 后，才可另行审阅是否进入 Phase 5K-A1。

---

**Amendment:** 2026-08-27 18:16:12 +08:00 在标准与提升权限执行上下文重跑 HiThink bounded GET smoke test；runner 在 Process/User/Machine scope 均未看到 `HITHINK_FINANCE_API_KEY`，未读取或输出任何 Key 内容。7/7 endpoint 均 HTTP 200 / `code=2003`，因此权限、数据字段与 source timestamp/as-of semantics 仍未证明。该环境传播 blocker 必须先解决，不能把未授权响应作为 `code=0` 能力结论，也不能开始 Phase 5K-A1。

**Reason:** 用户环境变量可能在桌面进程启动后才配置，或存在于不同执行上下文；在没有 Key 到达 runner 的情况下，必须保持 fail closed 并保留 raw response hash，而不是请求用户在聊天中粘贴凭证。

---

**Amendment:** 2026-08-27 18:34:47 +08:00 在网络可用执行上下文重跑同一 7 个 bounded GET probes；7/7 均 HTTP 200 / `code=0`。A 股代码表 bounded probe 返回 1 条，CSI300/500/1000 分别返回 300/500/1000 条当前成分；market-dump endpoint 返回短期签名地址元数据（300 秒）但未下载；复权接口返回 `ex_date_ms` 与公司行动字段但未提供明确预计算 adjustment factor/公式；交易日历返回 243 个交易日，覆盖 2025-08-27 至 2026-08-27，未证明约 6000 根有效日 K 的 CN validation coverage。原始响应仅保留在 ignored local artifact 并计算 SHA-256，API Key 未打印、记录或提交。结论维持 `HITHINK_CN_RESEARCH_DATA_PROVIDER_NOT_READY`，不生成 Phase 5K-A1 manifest、不下载/构建 Phase 5K dataset、不运行 SETUP_03、不访问最终 OOS。

**Reason:** `HTTP 200 + code=0` 证明五项接口组当前可访问，但 adjustment-factor semantics 与 validation-range calendar coverage 仍不足以证明 Phase 5K 数据提供能力；必须继续 fail closed。

---

**Decision:** Phase 5K-A1 只冻结 CN/US 当前 official/authoritative universe snapshot 与 deterministic manifest，不开始 Phase 5K-B。已实际保存七份 raw source payload 和 provenance：HiThink CSI300/500/CSI1000 为 `300/500/1000` 条，Nasdaq NDX/SOX 官方 weighting 为 `102/30` 条，Wikipedia S&P 500 当前权威公开表为 `503` 条，iShares IGV 官方 holdings 为 `106` 条 equity holdings（原始 holding rows `111`）。HiThink 三源实际 retrieval 均为 HTTP 200 / `code=0`，source snapshot SHA-256 分别为 CSI300 `sha256:58332afe7797da75cc1d1026f3fb27d06e97426529d062ee930085b1bea8648b`、CSI500 `sha256:25d939dc58550505a235db954c03b93e1be6ebf683476ee313e37431df2cb20b`、CSI1000 `sha256:6575a038a601fc3ab1333824428c1aed159241f99ce27536fbdb4a9ab5cc4bc0`；US source SHA-256 为 S&P500 `sha256:32eca758ea1a94135662133e4447b3c9c403d4d46a399938a3a0e951b65b4af5`、Nasdaq-100 `sha256:20a20fedff466078ebe43339f29b2d6c70e7af04c5edca2f00cfe998e74656f7`、SOX `sha256:2a4f26676a09f336e24da84645fc87a109a5a41cdeb825e3eb8611613302ebff`、IGV `sha256:5a3df9a6b1231d966d25ecbf904b4d708b1d22223e7d4f0ae7a95219bdc0de03`。

**Reason:** A1 必须使用实际抓取日的 current constituent/holding snapshot，并把 endpoint、retrieval timestamp、source/API timestamp、HTTP/API state、raw path、raw SHA-256 和 count 固定在 provenance 中。CN board classifier 只保留 SSE/SZSE Main Board common A shares；实际排除且保持 registered inactive 的 STAR/ChiNext 数量分别为 CSI300 `20/34`、CSI500 `72/69`、CSI1000 `122/233`（STAR/ChiNext）。

---

**Amendment:** 2026-08-27 22:18:08 +08:00 对 S&P Dow Jones Indices 公共 S&P 500 页面执行 bounded retrieval probe。页面可访问并提供指数说明/Full Constituents List 入口，但返回内容未满足完整机器可读 `Constituent`/`Symbol` 表且至少 400 行的冻结合同；因此不能将该页面当作可重复的完整 constituent snapshot，也不能继续把 Wikimedia/Wikipedia 作为 authoritative production provenance。

**Decision:** 保留原 `SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v1` 及其 canonical SHA-256 `sha256:4a33391d57488937bcdd7e501ca65a2ae3dc1c5475e41203f22bbe2e03c057eb` 和 v1 Wikimedia raw snapshot 作为历史审计 artifact，但 v1 不得参与新的 manifest generation。新 v2 bundle 采用 iShares IVV 官方 issuer holdings 作为明确 proxy，source identity 固定为 `S&P500_UNIVERSE_PROXY_IVV_OFFICIAL_HOLDINGS`，source class 为 `OFFICIAL_ETF_ISSUER_HOLDINGS_PROXY`，不得称为 official S&P 500 constituents。

**Evidence:** IVV raw endpoint 为 `https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv`，retrieval timestamp `2026-08-27T22:17:46+08:00`，Fund Holdings as of `Aug 25, 2026`，HTTP 200，parser `ishares_holdings_csv_equity_rows_v1`，504 equity holdings / 508 parsed holding rows，raw SHA-256 `sha256:633cc4df8492582d847030b3aaf10134792cbb2de1722088bb6dfb2c967bb7b5`。provenance 明确记录 IVV 可能含 cash/derivatives/temporary positions 或 issuer/share-class differences，且 holdings 可能不同于 index roster。

**Decision:** 生成新的 `SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2`，canonical SHA-256 为 `sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433`；v1 与 v2 分别由 version → hash contract 锁定，v2 rebuild 只接受 v2 source bundle，Wikimedia source 无法进入新的 frozen manifest。CN CSI300/500/1000 scope、CN quota `12/14/14`、US quota `12/10/8/10`、canonical identity first-attribution、SHA-256 deterministic ranking、每市场 `40 PRIMARY + 20 RESERVE` 及 Phase 5J-v2、SETUP_03 frozen parameters/structure thresholds 全部保持不变。

**Reason:** Source provenance 改变属于 immutable governance 的新版本，不得静默覆盖 v1；明确 proxy 身份、raw evidence、retrieval contract 与 limitation，才能保留可审计性并避免把 ETF holdings 误报为指数官方成分。该 amendment 仍只做 metadata/universe freeze，不读取 OHLCV、不运行 Phase 5K、SETUP_03、CONFIRMED、return/MFE/MAE/P&L、final OOS、Sheets 或 Phase 5K-B。

**Decision:** A1 selection spec `SETUP_03-CN-US-UNIVERSE-SELECTION-2026-08-27-v1` 固定 seed `SETUP_03-CN-US-FIXED-SHA256-SEED-2026-08-27-v1`，canonical ranking 为 `SHA256(fixed_seed|market|cohort|canonical_symbol)` digest ascending、同 digest 以 canonical symbol ascending；CN cohort 顺序为 `CSI300 → CSI500 → CSI1000`，US 为 `SP500 → NASDAQ100 → SOX → IGV`。cross-cohort duplicate 使用 v2 注册的 canonical identity，由 first declared cohort attribution；每个 identity 在同一 market 最多出现一次。A1 selection spec canonical SHA-256 为 `sha256:327e8f20b7ff3464d5bd8b44133ed1fc4633f143ca38e3a2cdeeeb216559b30f`。

**Reason:** 选择只使用 source-provided membership 与 canonical identity，不使用 SETUP_03 output、WATCH/ARMED/CONFIRMED、历史 OHLCV、forward return、MFE/MAE、win rate、P&L、profit factor、expectancy 或 signal frequency。Primary quota 固定 CN `12/14/14`、US `12/10/8/10`；完成各市场 40 PRIMARY 后，按相同 first-attributed cohort/hash 顺序冻结 20 RESERVE。

**Decision:** 冻结 manifest `SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v1`，canonical SHA-256 为 `sha256:4a33391d57488937bcdd7e501ca65a2ae3dc1c5475e41203f22bbe2e03c057eb`，parent identity 为 Phase 5J-v2 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US` / `sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0`。manifest 使用不可变 version → pinned hash contract；测试证明修改内容后同步重算内部 hash、version 不变仍 fail；从 frozen raw snapshots + provenance deterministic rebuild 可 exact reproduce manifest。manifest status 固定为 `MANIFEST_FROZEN_NOT_FETCHED`。QQQ、SOX index、IGV ETF 只记录为 `AGGREGATE_DIAGNOSTIC_ONLY`，不计入 40 US equities、不参与 qualification 或 ranking。

**Reason:** 双层 version/hash pinning 能同时发现未同步 hash 与同版本内容漂移；raw snapshot hash 校验能阻止输入文件在 freeze 后被静默替换。Phase 5K-A1 完成后停止，不下载 validation OHLCV、不构建 Phase 5K dataset、不运行 SETUP_03、不访问 CONFIRMED/收益指标/最终 OOS、不修改 production SETUP_03、Trading Core、Decision、execution 或 Google Sheets。

---

**Decision:** Phase 5K-B0 将 development-validation dataset acquisition 冻结为机器可读 contract `SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v1`，canonical SHA-256 为 `sha256:daed425278bf7b2cca00ede87b56dddc3bc9d47be51508a6800369105f2da039`，状态固定为 `DATASET_ACQUISITION_CONTRACT_FROZEN_NOT_ACQUIRED`。contract loader 必须实际读取并验证 Phase 5J-v2 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US` / `sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0` 与 A1 v2 `SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2` / `sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433`；同 version 即使同步重算内部 hash 也必须 fail。

**Reason:** B0 的职责是先冻结数据获取与数据质量边界，隔离后续历史样本获取与任何信号/收益观察。父级 protocol 与 A1 roster identity 若不绑定到实际 pinned files，B1 可能在错误 scope、错误 universe 或隐式规则下取得数据。

**Decision:** validation 日期固定为证券本地交易日 `2017-01-01` 至 `2026-08-26` inclusive；CN 只使用 `HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED` 的 `/api/a-share/prices/historical`、`interval=1d`、`adjust=forward`；US 只使用 `IBKR_TWS_API_ADJUSTED_LAST` 的 `STK`、`1 day`、`ADJUSTED_LAST`、`useRTH=1`、`end cutoff=2026-08-26`、`keepUpToDate=false`，并预注册 2017 至 2026 的固定 calendar-year chunks。CN API key 只允许通过 `HITHINK_FINANCE_API_KEY` 环境变量提供；任何 key 都不得打印、记录或提交。US 的 canonical symbol→conId/primaryExchange/currency/request contract 及 API/TWS version 必须在 B1 首次历史请求前 resolve、冻结和写入 manifest；在 identity、权限、历史数据或 ADJUSTED_LAST 不可证明时，状态为 `US_PROVIDER_NOT_READY`，不得 fallback。

**Reason:** 两个市场的 corporate-action semantics 必须分别固定为 HiThink forward-adjusted OHLC 与 IBKR ADJUSTED_LAST，不能将未复权价格或其他 provider 的历史结果混入正式 validation。预注册请求窗口避免根据返回结果动态挑选更有利的时间段；B0 不伪造尚未发生的 IBKR contract identity/version。

**Decision:** canonical bar schema 固定为 `market/canonical_symbol/date/open/high/low/close/volume/source_provider/adjustment_mode`，raw response 与 request/provenance metadata 单独保存。每条 bar 必须通过 local-date、finite positive OHLC、OHLC ordering、non-negative volume、end-date、唯一日期校验；完全一致的 normalized duplicate 可 deterministic dedupe，价格或 OHLCV 冲突一律 `DATA_CONFLICT_FAIL_CLOSED`。没有记录即没有 bar，禁止 forward-fill、interpolation、previous-close suspension substitution、synthetic bar 和跨市场 calendar 补行。

**Reason:** 统一 schema 和 fail-closed QC 能保留 provider 的事实边界，不把缺失或冲突数据静默转换成可交易的观测；raw bytes/hash 与 normalized hash 分开，才能同时审计来源证据和标准化结果。

**Decision:** RESERVE 只能在任何 SETUP_03 evaluation 前因机器可读客观数据失败激活，原因限于 `SYMBOL_NOT_RESOLVABLE`、`PROVIDER_NO_DATA`、`FATAL_OHLC_INTEGRITY_FAILURE`、`DUPLICATE_IDENTITY_CONFLICT`、`INSUFFICIENT_FOR_REQUIRED_WARMUP`，并严格按 A1 frozen `manifest_rank` 顺序激活；CONFIRMED 数量、信号质量、收益、MFE/MAE、胜率、P&L 或参数结果不得触发替换。CN/US 各自目标 `40 PRIMARY`、`20 RESERVE`；每市场至少 8 valid symbols、至少 6000 valid daily K bars、总计至少 40 valid symbols，市场之间不得补偿。reserve 用尽或目标 roster 不足时为 `TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW`，coverage 不足时为 `INSUFFICIENT_COVERAGE`，均不得自动降低门槛或进入 evaluation。

**Reason:** 将 replacement 绑定到预注册的客观数据失败和冻结 rank，才能阻止 validation universe 被信号结果选择；CN/US 独立 gates 保留 coverage failure 的真实归因，不让一个市场的数量掩盖另一个市场的不足。

**Decision:** B0 记录 `platform_window=40` 与 `setup_swing_lookback=5` 的 warmup dependency，排除 dependency prefix 后才允许形成 evaluable state day；历史不足以形成至少一个 evaluable bar 时为 `INSUFFICIENT_FOR_REQUIRED_WARMUP`，不得因上市较晚人工延长历史。B1 成功后的预注册状态为 `DEVELOPMENT_VALIDATION_DATASET_FROZEN_NOT_EVALUATED`，但 B0 不生成该状态；B0 期间不获取正式 validation OHLCV、不运行 SETUP_03、不查看 CONFIRMED/return/MFE/MAE/win rate/P&L、不修改 production/Trading Core/Decision/execution/Sheets，也不启动 final OOS。

**Reason:** warmup 是数据可用性前置条件，不是信号筛选条件；把它与 B1 的数据集 freeze 状态分开，可以在不接触 SETUP_03 output 的情况下先冻结可复现的获取和 QC contract。

---

**Decision:** 在不修改 v1 historical audit evidence 的前提下，PR #27 将 active B0 acquisition contract 升级为 `SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v2`，canonical SHA-256 固定为 `sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588`；v1 `sha256:daed425278bf7b2cca00ede87b56dddc3bc9d47be51508a6800369105f2da039` 仅作 immutable historical audit evidence。B1 后续必须绑定 active v2，不能回退 v1。

**Decision:** CN wire contract 固定为 HiThink `/api/a-share/prices/historical` 的 `thscode=<canonical symbol>`、`interval=1d`、`start=1483200000000`、`end=1787759999999`、`adjust=forward`。`2017-01-01 00:00:00.000 Asia/Shanghai` 与 `2026-08-26 23:59:59.999 Asia/Shanghai` 先按固定 Asia/Shanghai wall-clock 解释并转换为 integer Unix ms；B1 返回后仍按 security-local date `2017-01-01 <= date <= 2026-08-26` 做 deterministic inclusive filter。该 conversion timezone/rule 属于 B0 v2，不由 B1 临时决定。

**Decision:** US wire contract 固定 Contract 的 `conId`（B1 前唯一 resolved/frozen）、`secType=STK`、`exchange=SMART`、`primaryExchange`（resolved/frozen）与 `currency`（resolved/frozen），并固定 `reqHistoricalData(endDateTime, durationStr, barSizeSetting, whatToShow, useRTH, formatDate, keepUpToDate, chartOptions)` 为预注册 chunk end date `23:59:59 US/Eastern`、`1 Y`、`1 day`、`ADJUSTED_LAST`、`1`、`1`、`false`、`[]`。API version field、TWS version field、`B1_IBKR_RESOLVED_CONTRACT_DETAILS` identity source 与 US/Eastern timezone semantics 均必须在首次 history request 前冻结。2017–2026 chunks 不能只记录日期；返回数据严格按 chunk local-date inclusive range filter，overlap 只允许 exact deterministic dedupe，冲突 fail closed。

**Decision:** final roster 只允许已经通过同一 provider/QC/warmup validation 的 `VALID_ACCEPTED` symbols。PRIMARY 失败只按 A1 frozen reserve rank 激活，reserve 也必须通过相同 validation，直到形成每市场 40 个 accepted symbols 或 reserve 耗尽；目标未达时为 `TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW`。新增 invariant `final_roster_count == valid_symbols`，不一致为 `FINAL_ROSTER_VALIDITY_MISMATCH` 并 fail closed；因此 `final_roster_count=40` 且 `valid_symbols=8` 不得 `COVERAGE_OK`。

**Decision:** Phase 5J-v2 hard evidence minimum（每市场至少 8 valid symbols、总计至少 40、每市场至少 6000 bars）与 Phase 5K-B dataset readiness target（CN/US 各 40 valid accepted symbols）独立保留。hard minimum 通过不再自动覆盖 40-valid-symbol readiness gate；只有两市场 final roster 与 valid accepted symbols 均为 40、且各自满足 6000 bars，才具备 dataset readiness。整个 hardening 仍不获取正式 OHLCV、不运行 SETUP_03、不开始 B1、不访问 CONFIRMED/收益指标/OOS、不修改 production/Sheets。

**Reason:** 这些变更只冻结 acquisition wire semantics、local-date filtering、accepted-roster identity 与 fail-closed readiness governance，避免 B1 依赖抽象日期、动态 IBKR duration、未验证 reserve 或仅满足 development minimum 的伪 40-roster；不把任何数据结果或信号结果引入 acquisition contract。

---

**Decision:** 2026-08-28 调整当前开发路线：IBKR/Phase 5K-B1-A provider readiness 暂缓至策略正式冻结后的 formal validation；本轮只做 development-only strategy stability research，不部署 TWS/IB Gateway、不读取 formal validation dataset、不启动 final OOS。PR #28 保留其分支与 commits，标记 `DEFERRED_PENDING_STRATEGY_FREEZE` 后关闭且不合并；A1、B0、Phase 5J formal contracts 与 readiness pin 不修改。

**Decision:** 基于 `main@40a3e5f980bf82a85717748ae106847793d1469f` 冻结独立 development universe `SETUP_03-DEVELOPMENT-UNIVERSE-CN-US-2026-08-28-v1`，唯一候选来源为 A1 v2 saved snapshots；先排除全部 120 个 A1 formal identities，再按新的固定 SHA-256 非信号 selection spec 选取 CN/US 各 20 个 symbols。universe manifest SHA-256 为 `sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046`，symbol-list SHA-256 为 `sha256:03f9d0973340d27c04e9d53c86722100c0b0e6c42d7249147409781a73e904d5`，机器校验的 A1 intersection 为空；不按任何 setup、signal、return、MFE/MAE、P&L 或参数结果替换样本。

**Decision:** development historical data 只使用 `YFINANCE_DEVELOPMENT_HISTORICAL` / `YFINANCE_AUTO_ADJUST_TRUE`，local-date window 为 2017-01-01 至 2026-08-26 inclusive；Tencent/Sina 仅保留为当前快照能力，不与历史 bars 拼接。40 个 selected symbols 中，CN 7/20 通过 strict QC（12,140 bars），US 19/20 通过 strict QC（40,986 bars）；CN 13、US 1 因 `invalid OHLC ordering` 排除，不补 bar、不合成 suspension bar、不启用新 provider、不自动换股。dataset manifest SHA-256 为 `sha256:253c02fba6eb7273588af571f367c19695056261b9985a181f46a42072f2cf67`，aggregate normalized dataset SHA-256 为 `sha256:a3bbac39d46120b9cac46e72d43209600a004e6a28df31b53a711b692279b695`，状态为 `DEVELOPMENT_DATASET_COVERAGE_SHORTFALL_REQUIRES_REVIEW`。

**Decision:** 从上述冻结 valid subset 生成 structure-only evidence pack，固定 lookback `5`、window `40`、arm `0`；tolerances 为 production `3%/4%/5%`，stress-only `2.5%/5.5%/7.5%/10%`。报告只包含 coverage、state/terminal conservation、funnel、sensitivity、concentration、event frequency、adjacent stability、QC exclusions 与 sparse/zero evidence；不计算 forward return、MFE/MAE、P&L、OOS 或 formal validation。由于 development dataset coverage shortfall，最终状态为 `BLOCKER_DEVELOPMENT_YFINANCE_COVERAGE_SHORTFALL`，不把结构统计升级为策略或参数决策。

**Decision:** 修复 HiThink capability smoke test 的环境隔离：测试显式覆盖 key absent/present 两种环境，验证 configured key 仅传入 probe 且不出现在 serialized report；runtime semantics 与实际 API capability 未修改。

---

**Decision:** PR #29 continuation 对 immutable development dataset v1 的 14 个 `invalid OHLC ordering` symbols 做只读逐 bar yfinance raw 对照审计。审计固定读取 v1 adjusted artifact，不改写 v1；同日 raw 请求使用 `auto_adjust=False`、`actions=True`、`repair=False`，并记录 adjusted/raw OHLC、violation type、absolute/relative violation、IEEE-754 binary64 ULP distance、raw validity、raw/adjusted Close、implied adjustment factor、corporate actions 与 adjustment reconstruction ULP。30 个 violating bars 中 4 个为 `NUMERIC_ADJUSTMENT_ROUNDING_ONLY`，26 个为 `MATERIAL_PROVIDER_OR_RAW_OHLC`；仅对前者允许新增版本化 QC comparison rule `OHLC_ORDERING_NUMERICAL_COMPARISON-IEEE754-ULP-2026-08-28-v1`，上限 8 ULP、不得修改价格，material violation 继续 fail closed。

**Decision:** 因 CN yfinance material/raw OHLC ordering 问题仍造成 coverage shortfall，development-only dataset v2 采用统一 CN BaoStock qfq（`query_history_k_data_plus`、`frequency=d`、`adjustflag=2`、canonical `.SH/.SZ` 映射为 `sh./sz.`）与 US yfinance historical 的 provider split。请求窗口和 local-date semantics 固定为 2017-01-01 至 2026-08-26 inclusive；raw request、wire fields、raw/normalized hash、QC 和禁止事项均写入 v2 manifest。BaoStock 已返回的 valid-OHLC、blank activity suspension rows 只规范为 volume=0，不创建日期或 synthetic bar；不使用 Tencent/Sina 历史、不插值、不 forward-fill、不拼接 history、不按 signal 选择或替换 symbol。

**Evidence:** v2 dataset manifest SHA-256 为 `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`，ordering diagnostic SHA-256 为 `sha256:49be531b4e7337d847ee872b3875debe21d659f1978e2674975c018eec40ef23`；aggregate normalized dataset SHA-256 为 `sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356`，40/40 symbols、84,284 bars 通过 QC（CN 20/40,873；US 20/43,411），状态为 `DEVELOPMENT_DATASET_READY_FOR_STABILITY_DIAGNOSTICS`。结构证据固定 lookback=5、window=40、arm proximity=0，覆盖 production 3%/4%/5% 与 stress-only 2.5%/5.5%/7.5%/10%，不包含 returns、MFE、MAE、P&L、winrate 或 final OOS。`precompute_swings=False` 与 `True` 完成 40 symbols × 7 tolerances、逐 bar Setup/diagnostics/event/Decision parity，280 cells 全部 0 mismatch；最终状态为 `READY_FOR_STRATEGY_RESEARCH_DECISION`。

**Boundary:** 本轮不运行 Phase 5K formal validation、Phase 5K-B1、final OOS 或 strategy auto-selection；A1/B0/Phase 5J formal artifacts 与 v1 dataset artifact 保持不变。PR #29 不创建新 PR、不 merge；PR #28 仍为 deferred/closed 历史治理状态。下一步停止在策略研究决策点，等待研究设计者决定是否修改策略逻辑或另行注册研究设计。

---

**Decision:** 2026-08-28 在不改写冻结 v2 dataset/universe、A1/B0/Phase 5J formal artifacts 或 v1 audit artifact 的前提下，新增 audit-only `research/legacy_main_replay.py`，固定基准 identity 为 `main@40a3e5f980bf82a85717748ae106847793d1469f`。参考语义对每个 bar 使用 `quotes[:i+1]`，以原始 `evaluate_setup03_event(prefix, risk_capital, setup_parameters, decision_parameters)` positional seam 重新进入既有 Setup/Event/Decision 路径；该 reference 不进入 production implementation。为使全量审计可完成，运行时使用已证明 output-identical 的 causal Setup snapshot cache；raw prefix reference 仍保留用于直接 audit/regression，cache 不进入 production。

**Evidence:** 在冻结 v2 replay input 上完成 CN/US 40 symbols × 7 tolerances = 280 cells，逐 bar 589,988 comparisons、逐 event 3,120 comparisons；Setup state/operands、Setup diagnostics、CONFIRMED/FAILED dates、signal/confirmed dates、Decision action/diagnostics/deterministic fields 全部比较。`LEGACY_MAIN_PARITY_MISMATCHES=0`；legacy vs current shared path `0`，legacy vs precomputed path `0`。v2 provider split 仍为 CN BaoStock qfq / US yfinance historical，coverage 仍为 CN 20/40,873、US 20/43,411、ALL 40/84,284；immutable OHLC audit 仍为 4 numeric-rounding-only / 26 material bars。

**Decision:** 生成 tracked immutable structure-only capsule `research/development/development_strategy_decision_capsule_v2.json` 及报告 `research/development/development_strategy_decision_capsule_v2.md`。capsule 绑定 universe `sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046`、dataset manifest `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`、normalized aggregate `sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356`、replay input `sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18` 与 capsule file SHA-256 `sha256:5a0726dccc0bbe273e32b05a71434bec8dde85859483cc9e3f1745d630b17458`。capsule 输出 2.5/3/4/5/5.5/7.5/10% 的 CN/US/ALL coverage、state、event、boundary、concentration、sparse、adjacent stability、cross-market ratios 与 machine-readable descriptive flags；未放入任何 outcome metric，也不自动选择 tolerance。

**Decision:** 研究 gate 状态更新为 `READY_FOR_SOL_STRATEGY_DECISION`。3%→4% 的 ALL adjacent exact-date Jaccard 为 `66.34%`、retained `136/149`；4%→5% 为 `72.40%`、retained `181/192`。3%/4%/5% ALL CONFIRMED events 为 `149/192/239`，event density 为 `1.77/2.28/2.84 per 1000 bars`；CN/US event-density ratios 为 `0.677/0.759/0.764`，platform-density ratios 为 `0.883/0.910/0.941`。机械 flags 只作为事实描述：`SPARSE_AT_3=true`、`STRUCTURAL_EXPANSION_4_TO_5=true`、`CROSS_MARKET_DIVERGENCE=true`、`CONCENTRATION_HIGH=true`、`ADJACENT_STABILITY_HIGH=true`、`ADJACENT_STABILITY_LOW=true`、`NO_CLEAR_STRUCTURAL_PLATEAU=true`；不把这些 flags 解读为盈利或参数选择。

**Boundary:** 已运行 focused tests、full unittest（261 tests）、HITHINK key present/absent、py_compile、compileall、git diff --check；未重新抓取数据、未切换 provider/symbol、未修改策略、未运行 formal validation、未访问或写入 returns/MFE/MAE/P&L/winrate/final OOS。PR #29 不创建新 PR、不 merge，等待研究设计者决策。

---

**Decision:** 2026-08-28 PR #29 qualification closeout 保留 v2 tracked capsule/evidence identity 不变，新增 v3 capsule `research/development/development_strategy_decision_capsule_v3.json` 及报告。v3 仍绑定 universe `sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046`、dataset manifest `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`、normalized aggregate `sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356` 与 replay input `sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18`。对当前冻结 v2 replay input 按 CN/US 分别构造 `sorted(union(all valid local trading dates))` session set；现有 same-symbol nearest-date 一对一 matching 顺序保持不变，calendar-day distance 作为 descriptive historical field 保留，新增 `trading_day_drift` 作为 qualification distance，并以 session ordinal absolute difference 计算。周末/市场非交易日回归测试验证不会计入 trading-day distance。

**Evidence:** 严格读取并执行 Phase 5J-v2 frozen qualification matrix：3% candidate 绑定自身 thresholds + 3%→4%，4% 绑定自身 thresholds + 3%→4% 和 4%→5%，5% 绑定自身 thresholds + 4%→5%；CN/US 独立评估，无 market compensation。52 个 candidate × market × threshold rows 均包含 observed value、operator、frozen threshold、margin 与 PASS/FAIL。minimum events、symbol concentration、Jaccard、retention、rate relative increase 全部通过；交易日 drift 为 CN 3%→4% median/P90 `7.0/8.6`、US `10.0/19.8`，CN 4%→5% `9.5/456.5`、US `5.0/279.6`。所有 candidate 均因一个或多个 frozen drift threshold 失败，`qualified_candidates=[]`，机械 lexicographic result 为 `lexicographic_candidate=null`，最终状态为 `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`。failure breakdown、margin、0–2/3–5/6–10/11–15/>15 buckets 与 3%→4%、4%→5% extreme drift Top 20 均写入 v3 capsule；没有删除 pair、扩大窗口、修改 matching 或 threshold。

**Integrity / Boundary:** v3 capsule file SHA-256 为 `sha256:3fa511fa43b146fae9d1a17799b1ae17ce44ba4915ec4813d7120e53eef5b24c`，canonical payload SHA-256 为 `sha256:e9ec07fa5c1d5fede6b87c5ee0f453fc8a47a786c6725458e98e741faf6dbcee`。冻结 main parity 仍为 280 cells、589,988 bars、3,120 events、`LEGACY_MAIN_PARITY_MISMATCHES=0`；未重新抓取/替换数据、未改 production parameter 或 SETUP_03、未读取收益指标、未启动 formal Phase 5K validation 或 final OOS、未 merge。

---

**Decision:** 2026-08-28 先冻结独立 Phase 5J-v3 event identity/matching protocol，再允许建立第二套 development holdout。机器可读单一事实来源为 `research/setup03_phase5j_v3_event_matching_protocol.json`，版本为 `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`，canonical SHA-256 为 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。exact `(market, symbol, confirmed_date)` 先 retained；其余只在同 market、同 symbol 内，以冻结 `platform_window=40` 作为 inclusive 最大 40 trading sessions，`>40` 永远 unmatched。

**Decision:** v3 matcher 的正式目标为先最大化合法一对一匹配基数，再最小化总 trading-session distance；同成本使用按 `(old_session_ordinal,new_session_ordinal)` 序列的 lexicographically smallest deterministic tie-break。动态规划只允许 order-preserving/non-crossing pair，且同一输入跨机器生成相同 canonical result。drift median/P90 只对合法 matched pairs 计算；unmatched 继续完整进入 Jaccard、retention、added、disappeared，不能由 matching 隐藏。

**Governance:** PR #29 的 nearest-date v3 qualification 仅保留为历史 evidence；当前状态恢复为 `NOT_READY_FOR_FORMAL_FREEZE_DUE_TO_EVENT_MATCHING_PROTOCOL_UNDERSPECIFICATION`，不得解释为 `SETUP_03_STRUCTURALLY_REJECTED`。既有 3%/4%/5% candidates、stress-only 边界、lookback/window/proximity、drift/Jaccard/retention/concentration/rate thresholds、qualification matrix 与 `LEXICOGRAPHIC_CONSERVATIVE` 全部按 parent v2 绑定；不得修改 SETUP_03、引入新 tolerance、访问 Final OOS、启动 formal Phase 5K-B1、使用 IBKR 或读取收益指标。

**Boundary:** 本 commit 只冻结 protocol、matcher 与 regression tests；未读取第二套 holdout 的 OHLCV、SETUP_03 output、event、signal 或 outcome，未生成第二套 universe/dataset，未修改 production/Sheets。后续 holdout 只能在本 protocol freeze commit 之后创建。

---

**Decision:** protocol freeze commit `46169d7` 之后，冻结第二套 independent development holdout universe。机器可读 manifest 为 `research/development_holdout/universe_manifest.json`，版本 `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2`，manifest SHA-256 为 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`，symbol-list SHA-256 为 `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`。selection 使用新的固定 seed `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-FIXED-SHA256-SEED-2026-08-29-v1` 和 digest-ascending ranking；候选只来自 A1 v2 保存的七份 official/proxy source snapshots，选择发生在任何 OHLCV、SETUP_03、event 或 outcome 读取之前。

**Evidence:** 冻结 40 个 equity symbols（CN 20 / US 20），A1 formal 120 intersection 为 `[]`，development universe v1 40 intersection 为 `[]`；两套排除证明和 source snapshot identities 均写入 manifest。A1 v2、development v1、source snapshots、CN Main Board scope、cohort quotas 与 symbol metadata 保持原样，未使用 signal/result-driven selection 或 replacement。

**Boundary:** 当前 universe 仍为 development-only、not formal validation、not final OOS；此阶段未获取 historical OHLCV、未运行 SETUP_03、未读取 event/signal/returns/MFE/MAE/P&L、未启动 formal Phase 5K-B1、未使用 IBKR、未修改 production/Sheets。下一步才允许按冻结 provider/QC contract 获取 dataset。

---

**Decision:** protocol freeze 与第二套 result-independent universe freeze 完成后，按固定 provider contract 获取第二套 development holdout。CN 20/20 使用 `BAOSTOCK_DEVELOPMENT_QFQ` / `baostock.query_history_k_data_plus` / `frequency=d` / `adjustflag=2`；US 20/20 使用 `YFINANCE_DEVELOPMENT_HISTORICAL` / adjusted historical / `repair=False`。2017-01-01 至 2026-08-26 local-date window、无补日期/插值/synthetic bar/history splice/provider switch/OHLC mutation；BaoStock blank activity 只在既有 equal-OHLC row 上规范 volume=0。结果为 40/40 valid symbols、86,305 valid bars（CN 41,274、US 45,031）、provider/QC exceptions=0。dataset manifest SHA-256 为 `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`，normalized aggregate 为 `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`，replay input 为 `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`。

**Evidence:** 在冻结 replay input 上复用既有 main-baseline parity audit 与当前 shared/precomputed replay path；固定 7 tolerances、40 symbols，完成 280 cells、604,135 bar comparisons、3,008 event comparisons，`LEGACY_MAIN_PARITY_MISMATCHES=0`、shared/precomputed mismatch 均为 0。按冻结 v3 event protocol 输出 exact `(market,symbol,confirmed_date)` retained、residual same market/symbol one-to-one non-crossing minimum-distance matching、`>40` unmatched、完整 added/disappeared/unmatched 与 matched-only trading-day drift。

**Decision:** 严格执行冻结 qualification matrix：3% candidate 绑定自身 thresholds+3%→4%，4% 绑定自身 thresholds+两侧 adjacent pair，5% 绑定自身 thresholds+4%→5%；CN/US 独立评估、无 market compensation。52 rows 中 candidate 3% 与 4% 均有 CN/US failures；5% 的 US cell 全通过但 CN 的 Jaccard / drift threshold 失败，因此 `qualified_candidates=[]`、`lexicographic_candidate=null`，当前真实 Sol 状态为 `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`。该状态是第二套 development structure-only evidence 的机械结论，不等同于 `SETUP_03_STRUCTURALLY_REJECTED`，也不选择或写入 production tolerance。

**Boundary / Integrity:** 冻结 dataset/replay manifests 与 capsule/report 已提升到 tracked `research/development_holdout/`、`research/development/`；raw/normalized bars、frozen JSONL 与 CSV 仍位于 ignored `artifacts/phase5j_v3_development_holdout/`。capsule 记录 protocol SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`、holdout universe SHA-256 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65` 及上述 dataset/replay hashes。未读取 returns/MFE/MAE/P&L/winrate/profit factor/expectancy，未访问 Final OOS，未启动 formal Phase 5K-B1，未使用 IBKR，未修改 SETUP_03、production、Sheets 或 historical PR #29 v3 evidence。下一步停在 Sol 决策，等待新授权。

**Audit correction:** 2026-08-29 发现原 `acquire_and_freeze_holdout()` 先用 provisional dataset manifest 写入 replay wrapper、再生成包含 replay-input aggregate 的 final dataset manifest，导致 tracked wrapper 错误绑定 provisional dataset SHA。修复冻结链为 normalized data → replay input/aggregate → final dataset manifest → replay wrapper，并让 `load_frozen_holdout()` 实际验证 wrapper 自身 integrity、dataset↔wrapper binding、embedded replay aggregate↔dataset binding、frozen replay input equality 及 40 symbols/86,305 bars 计数。使用现有 frozen replay input 重生成 tracked wrapper；dataset SHA `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`、normalized aggregate `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`、replay aggregate `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`、protocol/universe identity、capsule/report 与 qualification 均不变；wrapper integrity 更新为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。新增 cross-binding mutation fail-closed regression；未 refetch provider、未替换 symbol、未修改 frozen OHLCV、SETUP_03、production 或研究设计。

## 2026-08-29

### Decision: establish repository handoff governance and frozen-artifact recovery registry

**Context:** 本项目同时存在 production pipeline、多个研究/协议阶段、squash-merged PR、未合并 PR、ignored replay/raw/normalized artifacts 与多设备开发场景。仅依赖旧的 `CURRENT_STATUS.md` 或聊天上下文，无法可靠区分当前 checkout、远端 main、PR head、CI exact-head、已冻结输入和未完成 backup。

**Decision:** 新增根目录 `HANDOFF.md` 作为当前可执行交接快照；`docs/CURRENT_STATUS.md` 作为正式状态；`docs/DECISION_LOG.md` 作为长期决策历史；`docs/FROZEN_ARTIFACT_POLICY.md` 与 `docs/FROZEN_ARTIFACT_REGISTRY.json` 作为重要 artifact 的恢复治理与机器可读登记。新会话必须先读取 HANDOFF，再读取 CURRENT_STATUS、DECISION_LOG、相关治理/协议/架构文件，并核对真实 Git/PR/CI/artifact/hash。文档与客观证据冲突时统一标记 `PROJECT_GOVERNANCE_STATE_CONFLICT` 并停止猜测。

**Rationale:** 将“当前要做什么”和“为什么这样决定”分离，能够让新设备直接执行下一步，同时保留长期历史；对不进入 Git 的 correctness-critical bytes 强制记录本地存在、hash 验证、persistent backup 和 recovery verification，避免用重新生成的近似文件冒充 frozen artifact。

**Alternatives considered:** 继续依赖聊天记录或把完整 Git history 复制进 README；拒绝，因为二者都不能提供当前 exact-head/PR/CI 对账，也会把快照、正式状态、决策理由和 artifact 恢复责任混在一起。把大型 artifacts 全部提交 Git；拒绝，因为当前项目已有 ignored payload，且体积/生命周期不适合用 Git 替代持久 artifact storage。

**Consequences:** 本次治理初始化不改变 Trading Core、provider、SETUP_03、production Sheet 或研究结果；当前 Phase 5J-v3 holdout backup 仍明确为 `FROZEN_ARTIFACT_BACKUP_STAGED_CLOUD_UPLOAD_REQUIRED`，在 persistent backup 与独立恢复验证完成前不能标记 `FULLY_RECOVERABLE`，也不能启动尚未核实的 Phase 5J-v4。

**Revisit condition:** 只有远端 main/PR/CI/artifact 状态、存储策略或项目阶段发生客观变化，或研究设计者明确授权扩大 scope 时，才更新本治理约定；任何 artifact identity 变化必须新建版本并保留旧 identity。

**Relevant commit / PR:** this governance initialization commit on `research/phase5j-v4-lifecycle-attribution`; PR at initialization: `NONE`. The governance snapshot records the latest substantive source head; it does not record a SHA for a commit that contains the snapshot itself. Exact PR tip, CI and merge state are verified live from GitHub.

---

## 2026-08-29

### Decision: record externally verified persistent recovery of the second Phase 5J-v3 holdout

**Context:** The local governance snapshot still described the second development holdout as local/hash verified only. The user supplied an external ChatGPT audit record showing that the exact ZIP bytes were uploaded to Google Drive and independently re-read from that cloud object with an identical SHA-256.

**Decision:** Record the second holdout as `LOCAL_PRESENT=PASS`, `HASH_VERIFIED=PASS`, `PERSISTENT_BACKUP_PRESENT=PASS`, `RECOVERY_VERIFIED=PASS`, and `FULLY_RECOVERABLE`. Register Google Drive as the persistent provider, logical path `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`, file ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`, ZIP size `3,086,881` bytes, and SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`.

**Rationale:** The cloud object identity and independent reread close the persistence and transport-integrity gap without changing any frozen dataset bytes, manifest, replay aggregate, universe, protocol, or capsule. The evidence is recorded as an external audit fact; this session intentionally does not repeat Google Drive network verification.

**Boundary:** The earlier development universe v1 and its associated payload remain `UNRECOVERABLE`; the verified second-holdout backup does not cover or replace them. Phase 5J-v3 remains development-only and structure-only, with `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`; the user has now authorized continuation of the already-frozen Phase 5J-v4 task `SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE` under all existing causal, frozen-input, descriptive-only, and no-Final-OOS constraints.

**Revisit condition:** Reopen only if the external object becomes unavailable, the recovered bytes/hash no longer match, a governance/Git/PR/CI/artifact conflict appears, or the frozen research contract is explicitly changed with a new version and preserved prior identity.

**Relevant commit / PR:** this correction is intended for commit `docs: record verified frozen artifact cloud recovery` on `research/phase5j-v4-lifecycle-attribution`; PR remains `NONE` until the Phase 5J-v4 work is complete and reviewed.

---

## 2026-08-29

### Audit note: Phase 5J-v4 execution is blocked by missing repository-verifiable contract

**Evidence checked:** After the cloud-recovery governance correction, the current checkout, all local and remote refs, reflog/unreachable commits, existing local artifacts, and the supplied original task attachment were searched for `SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE` and its protocol/source/tests. Only the phase name supplied by the user was found; no v4 contract or implementation was located.

**Decision:** Mark the current execution blocker as `PHASE5J_V4_PROTOCOL_NOT_PRESENT`. Do not invent causal attribution rules, historical symptom concordance definitions, windows, thresholds, inputs, outputs, or evidence semantics from the phase name alone. No Phase 5J-v4 run, new research artifact, or v4 PR is claimed.

**Boundary:** The second Phase 5J-v3 holdout remains exact and `FULLY_RECOVERABLE` according to the externally supplied cloud audit. Its dataset/replay/universe/protocol identities remain unchanged. Phase 5J-v3 remains development-only and structure-only with `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`; Final OOS, provider access, production changes, and Phase 5K-B1 remain out of scope.

**Resolution condition:** Resume only when the exact frozen v4 protocol, source, and tests are restored or supplied in a repository-verifiable commit/path. Then re-read them, validate the holdout bindings, and continue under the existing as-of, causal, frozen-input, descriptive-only, and outcome-access boundaries.

---

## 2026-08-29

### Decision: freeze the Phase 5J-v4 lifecycle attribution protocol before results

**Correction:** The earlier `PHASE5J_V4_PROTOCOL_NOT_PRESENT` observation was factually correct about repository contents but incorrectly framed as a recovery blocker. Phase 5J-v4 had only completed Sol research design and had never been persisted, hashed, committed, implemented, or tested. The correct prior state is `PHASE5J_V4_PROTOCOL_NOT_YET_PERSISTED`; this is `NOT_AN_ARTIFACT_LOSS_EVENT`.

**Decision:** Persist the supplied exact Sol specification as `research/protocols/setup03_phase5j_v4_lifecycle_attribution_protocol.json`, version `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`, canonical SHA-256 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`, with a concise Chinese companion and version/hash-pinned loader/tests. Freeze the exact second holdout identity, adjacent 3%→4% and 4%→5% pairs, FIRST_DIVERGENCE_BAR semantics, deterministic mutually exclusive root taxonomy, separate propagation taxonomy, research-only lineage, single-mechanism counterfactuals, historical symptom concordance scope, parity requirements, outputs, recommendations and stop state before any real holdout attribution is run.

**Boundary:** This freeze task does not read real holdout attribution results, refetch early development v1, create a third dataset, access A1 formal OHLCV or Final OOS, read outcomes, change production SETUP_03, or modify Phase 5J-v3 matching/qualification. Real attribution may begin only after the independent commit `research: freeze Phase 5J-v4 lifecycle attribution protocol` exists.

---

## 2026-08-29

### Decision: Phase 5J-v4 causal attribution is ready for Sol structural decision

**Evidence:** After protocol freeze commit `4be4545bc2ddf54c3e970a162160c9fe3e464d4d`, the exact second holdout produced 258,915 every-bar trace rows, 1,031 deterministic lifecycles and 177 real first-divergence episodes. Pooled root ranking is low-span 88, high-span 69, both-span 20. The 3%→4% pair is low/high/both 53/28/9 and both CN/US are low-span dominant; 4%→5% is 35/41/11, with CN high-span dominant and US low-span dominant. This is `MIXED_CAUSAL_STRUCTURE`, not a single-mechanism result and not a tolerance selection.

**Propagation / counterfactual:** 3%→4% has 90 roots and 76 downstream divergent lifecycles; 4%→5% has 87/69. Downstream propagation is terminal-index cascade or no cascade, with max depth 4. Holding the lower-tolerance terminal-index seam fixed / suppressing terminal-index propagation removes or restores 76 and 69 downstream lifecycles respectively; fixing detection/anchors produces no additional same-root recovery in this evidence. All interventions are `RESEARCH_CAUSAL_DIAGNOSTIC_ONLY` and `NOT_A_CANDIDATE_RULE`.

**Parity / boundaries:** Against `origin/main@142b7345a5640b1e87932e41f3dc9311172bf54c`, 120 cells, 258,915 Setup bar outputs and 1,028 CONFIRMED/FAILED events have zero mismatches. The second holdout, Phase 5J-v3 qualification and prior frozen tracked content are unchanged; no provider/refetch/third dataset/A1 formal OHLCV/outcome/Final OOS/Phase 5K-B1 path was used. Historical PR #29 evidence is symptom-only: CN 3→4 partial, US 3→4 concordant, CN/US 4→5 partial, all `NOT_CAUSAL_REPLICATION`.

**Decision:** Set `PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`. Recommend `REDESIGN_PLATFORM_BOUNDARY_SEMANTICS` then `REDESIGN_TERMINAL_REARM_ORCHESTRATION`; do not implement either in this phase. Capsule file SHA-256 is `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`; deterministic trace SHA-256 is `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`.

### Decision: tracked provenance file hashes use Git-normalized LF bytes

**Context:** PR #32's first CI run exposed that Windows CRLF working-tree bytes and Linux/Git LF bytes produced different raw SHA-256 values for unchanged tracked provenance files. The existing content comparison already normalized EOLs, but the recorded per-file hashes did not.

**Decision:** Define tracked text provenance file identity as SHA-256 over LF-normalized bytes, enforce the same rule in governance tests and Phase 5J-v4 prior-frozen parity, and regenerate the v4 capsule/report/hash manifest. Canonical dataset, replay, protocol, and payload identities are unchanged; this decision only removes checkout-platform ambiguity.

**Why:** A tracked provenance identity must be stable across supported Windows development and Linux CI checkouts. Raw worktree EOL bytes are not a portable Git content identity.

---

## 2026-08-29

### Decision: preserve project-wide strategy identity and freeze the final SETUP_03 ATR boundary development family

**Context:** PR #32 Phase 5J-v4 was independently verified and squash-merged into remote `main@21c73977195682df576750648765b1b74d8824e2`; main push CI run `33259644890` succeeded. Sol accepted the bounded next step `REDESIGN_PLATFORM_BOUNDARY_SEMANTICS`. Existing governance wording could nevertheless be read as if Platform Breakout were the whole project.

**Decision:** Make the project identity explicit in `AGENTS.md` and `HANDOFF.md`: the long-term strategy is the `docs/TRADING_SYSTEM_SPEC.md` flow `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`, with four first-version Setup families (`SETUP_01` Wave 2 → Wave 3, `SETUP_02` Wave 3 Continuation, `SETUP_03` Platform Breakout, `SETUP_04` Extreme Fear Reversal). `SETUP_03` is one sub-strategy; its current Phase or commit depth does not change the overall route, and route changes require explicit user approval plus a decision-log entry.

Freeze the only permitted v5 structural family before OHLCV acquisition: ATR-normalized platform boundary with Wilder ATR period 14, current as-of reference bar, symmetric high/low ATR denominator and pre-registered thresholds `1.0/1.5/2.0/2.5`. The protocol is `research/protocols/setup03_atr_boundary_structural_qualification_protocol.json`, version `SETUP_03-ATR-BOUNDARY-STRUCTURAL-QUALIFICATION-2026-08-29-v1`, canonical SHA-256 `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b`. The metadata-only clean development universe is frozen at 20 CN + 20 US symbols, manifest SHA-256 `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b`.

**Boundary:** Only platform boundary semantics may vary; causal swing, strict as-of, lifecycle, breakout, confirmed/failed, Decision, Entry Zone, stop/target/RR, execution, terminal and rearm semantics remain fixed. Incumbent fixed-percentages are descriptive reference only, not a search. No second boundary family, market-specific tuning, high/low independent tuning, outcomes, Final OOS, formal Phase 5K-B1, or production change is permitted. The clean roster was selected from A1 metadata snapshots before OHLCV and excludes A1 formal, development v1, second holdout and candidate design identities.

**Next gate:** After the freeze commit, acquire only the new clean holdout under the existing CN BaoStock / US yfinance development contract, then run structure-only qualification and one deterministic repeat. Stop with `READY_FOR_FORMAL_VALIDATION` if a candidate survives every registered gate in both markets; stop with `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` if none survives; or use `READY_FOR_DECISION_INSUFFICIENT_CLEAN_DEVELOPMENT_HOLDOUT_UNIVERSE` if the frozen independent universe is insufficient. Do not merge the resulting PR or start formal validation without the next explicit decision.

---

## 2026-08-30

### Decision: stop SETUP_03 structural development after the registered ATR family failed stability qualification

**Evidence:** The frozen clean holdout acquired 40/40 accepted symbols and 88,075 bars (CN 42,355; US 45,720) under the existing CN BaoStock qfq / US yfinance adjusted development contract. Dataset manifest SHA-256 is `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29`; normalized aggregate is `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`; replay aggregate is `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76`; provider/QC exceptions are zero.

The four pre-registered ATR thresholds `1.0/1.5/2.0/2.5` all passed candidate-level minimum events, event-symbol coverage, concentration, HHI and zero-event pathology checks. None survived every independent adjacent pair gate in both CN and US. The 1.0→1.5 pair had exact Jaccard `45.10%` CN / `52.21%` US and lifecycle divergence `94.31%` / `88.02%`; the 2.0→2.5 pair improved Jaccard to `78.95%` / `73.91%`, but lifecycle divergence remained `62.91%` / `79.25%`. The complete matrix has 124 rows.

Shared causal-swing versus precomputed-swing parity passed for 280 cells, 616,525 bar comparisons and 3,253 terminal-event comparisons with zero mismatches. The full structure-only run was repeated once with identical canonical digest (`sha256:baa52ae56873b44599b4188c8e17aa251788c4708af59236b2247d822dc631b7`). Decision capsule canonical payload is `sha256:5c799f5f9b2d2655c0dd1ff4fd773af32e3e05d805175d696791c80fe767a42b`.

**Decision:** Set `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`. Do not select an ATR threshold, tune another ATR period/family, compensate markets, independently tune high/low boundaries, change terminal/rearm orchestration, modify production, or use the result for Final OOS/formal validation. Return the next core research recommendation to Wave Scenario Engine → `SETUP_01` → `SETUP_02`. Any future SETUP_03 continuation requires a new explicit research decision and a new protocol/version.

**Boundary:** The evidence remains development-only and structure-only. No returns, forward returns, MFE, MAE, P&L, winrate or expectancy was accessed; formal Phase 5K-B1, IBKR formal OHLCV and Final OOS remain unread.

### Closeout audit: retain ATR-normalized implementation as failed research-only candidate family

**Evidence:** `trading/setup.py` contains the optional `ATR_NORMALIZED_BOUNDARY_MODE` branch required to reproduce the Phase 5J-v5 structure-only evidence. The current `main.py` parameter parser emits only the existing percentage boundary inputs; `SheetsClient.config()` exposes the `参数设置` rows without adding a mode selector; production workflows invoke the existing entrypoints without ATR mode arguments; and `trading.events.evaluate_setup03_event()` forwards the production setup parameter dictionary without selecting ATR mode. The default on the shared Setup entrypoint remains `PERCENTAGE`.

**Decision:** Preserve the research implementation and explicitly mark it `RESEARCH_ONLY`, `NOT_PRODUCTION_AUTHORIZED`, and `FAILED_STRUCTURAL_CANDIDATE_FAMILY`. Add regression coverage for the marker and for the production parameter/Decision path so the ATR mode cannot become an implicit production selection.

**Boundary:** This is a closeout governance and regression clarification only. It does not change the percentage production default, Sheets schema, workflow behavior, Decision semantics, Trading Core outputs, terminal/rearm behavior, or any existing trade behavior. The Phase 5J-v5 result remains `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`; no ATR threshold is selected and no new research is started.

## 2026-08-30

### Decision: production holdings date is a market-session field, not a run-time field

**Context:** The live `最新行情` sheet contains both `交易日期` and `抓取时间`. The prior production orchestration used wall-clock `expected_latest_trade_date()` as a freshness target and combined latest quote publication with historical/qfq/SETUP_03/Decision work. This was unsafe for delayed Friday-to-Saturday runs, market-local US sessions, and future-dated provider observations. The actual latest-row mapping is now explicitly audited: `main.run()` writes `交易日期` from the chosen `Quote.trade_date`, while `抓取时间` is the Beijing `fetched_at` timestamp.

**Decision:** Establish the long-term invariant `交易日期 = 市场真实 session trade_date` and `运行时间 = 北京时间 fetched_at`; neither field may substitute for the other. A-share dates remain A-share market dates. US dates remain the US local regular-session date and must not be incremented because the Beijing run has crossed midnight. Provider timestamps are normalized in the security's market timezone before becoming `Quote.trade_date`.

**Decision:** Production latest source selection is evidence-first and fail-closed: reject future-dated quotes; derive the latest completed session from sane observed source dates and the market-local close buffer; prefer the newer sane source when source dates differ; treat the older source as stale; and keep the row `待复核` with an explicit single-source/stale note when two sources do not validate the same session. An ordinary-weekday freshness guard is a lower bound only and does not infer exchange holidays.

**Decision:** Scheduled Asia/US jobs use explicit `latest` mode and write only `最新行情`, `校验记录`, and `运行日志`. They do not fetch/write historical data or qfq, do not run SETUP_03 or Decision, and report `history_rows_written=0`. `full` mode is available only through explicit manual `workflow_dispatch` selection (and deliberate local CLI use); existing percentage production defaults and trading behavior remain unchanged.

**Reason:** Separating market-session evidence from Beijing run time removes the date-shift ambiguity while preserving the existing display-time convention. Separating latest-only orchestration from full strategy processing prevents a routine holdings refresh from rewriting history or triggering a strategy path.

**Evidence / Boundary:** Regression coverage includes A-share and US Friday-to-Beijing-Saturday delays, source-date mismatch in both directions, same-date dual validation, future dates, before/after close, weekend/weekday guards, and UTC/BJT timestamp boundaries. The production Sheet smoke must verify every enabled holding's trade date, chosen/verifier source, validation status and Beijing run time before this hotfix is declared `PRODUCTION_HOLDINGS_DATE_BUG_FIXED_AND_LIVE_VERIFIED`. No Wave Engine, new research, Final OOS, or automatic hotfix merge is authorized.

### Production smoke finding: bounded latest provider windows are required

**Evidence:** The first real latest-only smoke wrote correct market dates for CN/HK/US, but `SIVE.ST` remained at `2026-08-27` and was explicitly marked `待复核` because yfinance's `period=5d` response exposed a `2026-08-28` row with missing `close`. A direct Yahoo Chart request using explicit `period1/period2` returned a sane `2026-08-28` OHLCV row. The missing-close row must not be converted into a fabricated quote.

**Decision:** The latest yfinance provider uses an explicit bounded `start/end` window tied to the run's bounded date, and retries through bounded Yahoo Chart when the provider tail is incomplete. If all available rows remain incomplete or stale, preserve the valid older quote and keep the row explicitly pending; never fill a missing price or mark it verified.

**Boundary:** This is a production latest-data freshness correction only. It does not change market-session date semantics, source-verification rules, percentage production defaults, Trading Core, SETUP_03, historical/qfq/Decision behavior, or the no-Wave-Engine/no-new-research boundary.

### Final live verification: production holdings session-date bug fixed

**Evidence:** PR #34 implementation head `a9a7a06d546412d4de390029baaa5ff4d44ee263` passed exact-head CI `33265845873`; PR #34 is `OPEN / CLEAN / MERGEABLE`. Final manual latest-only workflow runs `33265877563` (Asia) and `33265875055` (US) both completed successfully from that head. Their summaries reported Asia `3/3 verified` and US `6 verified + 1 single-source current/pending`, with `history_rows_written=0` and `decision_rows_written=0` in both runs.

The live `持仓股股票行情数据中台` readback covered all 10 enabled holdings. Every `最新行情.交易日期` is the market session date `2026-08-28`, including US Friday session dates and SIVE's Friday row obtained through bounded Yahoo Chart; no future date, Beijing cross-midnight +1, or stale 2026-08-27 row remained. `抓取时间` remains Beijing time (`2026-08-30 01:28:31` / `01:32:25`) and is formatted as DATE_TIME, while `交易日期` is formatted as DATE. US source-date mismatches remain explicitly `待复核`; SIVE remains explicitly single-source `待复核`, not falsely dual-source verified.

**Decision:** Set `PRODUCTION_HOLDINGS_DATE_BUG_FIXED_AND_LIVE_VERIFIED`. Keep scheduled Asia/US jobs on latest-only; retain full mode as explicit manual-only workflow dispatch. The invariant remains `交易日期 = 市场真实 session trade_date` and `运行时间 = 北京时间 fetched_at`.

**Boundary:** Do not merge PR #34 automatically. Do not start Wave Engine, new research, Final OOS, formal validation, or any SETUP_03 continuation.

### Decision: implement a finite causal Wave Scenario Engine v1 and read-only shadow

**Context:** After PR #34 closeout and the registered `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` result, the next authorized core route is Wave Scenario Engine → `SETUP_01` → `SETUP_02`. The first engine must provide structural context without reopening SETUP_03 or pretending to be a complete Elliott Wave counter.

**Decision:** Register `WAVE-SCENARIO-ENGINE-2026-08-30-v1`. The engine exposes only `WAVE_2_TO_3_CANDIDATE`, `WAVE_3_CONTINUATION_CANDIDATE`, `ABC_CORRECTION_CANDIDATE`, `UPTREND_UNKNOWN_WAVE`, `DOWNTREND_OR_INVALID_FOR_LONG`, and `NO_VALID_SCENARIO`. It always returns primary and alternate scenarios with explicit evidence, counter-evidence, rule-count evidence score, confirmed Swing identities, candidate legs, Fibonacci regions, structural invalidation, invalidation reason, and SETUP_01/02 context eligibility.

**Causal boundary:** Inputs are first bounded to `data <= as_of_date`; daily structure reuses existing confirmed Swing and Market Structure semantics; weekly bars aggregate actual session dates and exclude a Monday-to-Thursday incomplete ISO week (a Friday-close or later as-of may include the completed observed week). A fixed as-of evaluation must be invariant to appended future bars. Weekly downtrend blocks long-side context even when daily prices rebound. Wave 2 remains WATCH-like until its structural evidence is sufficient; a Fib/EMA/RSI hit alone cannot start Wave 3. Continuation additionally requires the current daily state to remain `UPTREND`, not merely a historical HH/HL sequence.

**Fibonacci boundary:** The engine calls the existing `trading.fibonacci` implementation and only converts its levels into adjacent candidate regions. Fib is context, not a standalone signal. Evidence score is a count of named satisfied predicates, not a probability and not calibrated by returns.

**Shadow boundary:** `scripts/run_wave_shadow.py` and manual `wave-shadow.yml` read enabled holdings and explicit qfq history, then write only JSON/CSV report artifacts and a summary. They do not write Google Sheets, history, Decision, production configuration, ENTRY, returns, MFE/MAE, P&L, or OOS results.

**Reason:** This creates the minimum auditable structural context required before independent SETUP_01/02 work while preserving strict as-of causality, uncertainty labeling, the existing single-source Fibonacci implementation, and the project-wide no-SETUP_03-reopen boundary.

### Closeout evidence: v1 shadow is ready for Sol review, with one fail-closed data-quality exception

**Evidence:** PR #35 head `713c553002c44d789b0b2fb447ecbc8994557cf3` passed exact-head CI run `33268068010`; the read-only shadow workflow run `33268067998` completed successfully and produced JSON/CSV artifacts for all 10 enabled holdings. The report evaluated 9 holdings, recorded 1 error, and had `unknown_primary_ratio=0.5`; primary family counts were `DOWNTREND_OR_INVALID_FOR_LONG=3`, `WAVE_2_TO_3_CANDIDATE=1`, `UPTREND_UNKNOWN_WAVE=4`, `ABC_CORRECTION_CANDIDATE=1`, and `NO_VALID_SCENARIO=1`.

**Data quality boundary:** MU/美光科技 has an empty `历史数据源`. The runner did not guess a provider and returned `NO_VALID_SCENARIO` with an explicit error, making the report status `PARTIAL_DATA_QUALITY`. The remaining nine rows were evaluated without Sheets writes, history/Decision writes, `ENTRY_ALLOWED`, returns, OOS or other outcome access. The missing source must be resolved explicitly before claiming a complete 10/10 shadow.

**Decision:** Set `WAVE_SCENARIO_ENGINE_V1_SHADOW_READY_FOR_SOL_REVIEW`. Keep PR #35 open and do not auto-merge it. Sol review must decide whether the finite v1 scenario semantics are acceptable and how to repair/re-run the MU configuration; no independent SETUP_01/02 trading implementation is authorized yet.

### Decision: Wave Engine v1 correctness closeout before Sol review

**Context / finding:** The previously reviewed PR #35 head was
`b3da9e87a25b3a56c341a6096c021666150a19d5`, with exact-head CI
`33268711570` and shadow `33268711569`. Review found that historical yfinance
could return the previous valid row when its newest observed row had
`Close=null`, without trying the existing Yahoo Chart fallback. Review also
found that `LOW -> HIGH -> LOW` was not enforced as a true upward impulse at
the candidate boundary, and that an as-of close at or below the impulse origin
could leave `SETUP_01` context eligible before a newer low was confirmed.

**Decision:** Keep qfq/raw historical providers fail-closed on incomplete OHLC
tails: use the existing Yahoo Chart fallback, preserve qfq adjustment, and do
not fill, fabricate, or forward-fill OHLC. Make `peak.price > origin.price` an
explicit Wave 2→3 predicate. When the as-of close is at or below the impulse
origin, emit UNKNOWN/invalid-for-long context with `SETUP_01` eligibility
false. Apply the same structural-origin invalidation to ABC candidates without
expanding the taxonomy. Wave shadow now records `history_last_date`,
`latest_completed_session`, `freshness_status`, and flat primary/alternate
fields; stale qfq history is `DATA_STALE` and is not evaluated.

**Evidence:** The final implementation source head is
`bbb851fb0c995aebaa2e19de1a67607e39ed3173`. Exact-head CI
`33296199323` and read-only shadow `33296199336` both succeeded. The shadow
requested 10 holdings, evaluated 8, and recorded 2 fail-closed errors: MU has
an empty `历史数据源`, and SIVE.SE qfq history ended at `2026-08-27` versus
the ordinary-calendar freshness lower bound `2026-08-28`. All successfully
evaluated US holdings reached `2026-08-28`; no US holding silently remained
at `2026-08-27`. The report has `returns_accessed=false`,
`oos_accessed=false`, and `sheets_written=false`. Frozen research artifacts
were not changed.

**Decision:** Set
`WAVE_SCENARIO_ENGINE_V1_CORRECTNESS_CLOSEOUT_READY_FOR_SOL`. Keep PR #35
`OPEN / CLEAN / MERGEABLE`; do not merge it and do not start independent
`SETUP_01`/`SETUP_02` implementation before Sol review.

### Decision: implement SETUP_01 Wave 2 → Wave 3 v1 as a separate structural lifecycle

**Context:** PR #35 has been squash-merged into the latest `main` and the
registered Wave Scenario Engine v1 is now the only Wave context source for
this work. The next authorized implementation is SETUP_01; SETUP_02 remains
out of scope and SETUP_03 remains closed.

**Decision:** Register
`SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`. Implement a separate immutable
SETUP_01 evaluation and strict as-of replay layer with the lifecycle
`NONE`, `WATCH`, `ARMED`, `CONFIRMED`, `FAILED`. The evaluator accepts only
the Wave Engine primary `WAVE_2_TO_3_CANDIDATE` with
`setup01_context_eligible=true`, a non-`DOWNTREND` weekly parent, and three
confirmed causal Swings in `LOW → HIGH → LOW` order. It requires
`Wave1 peak > Wave1 origin`, `Wave2 low > Wave1 origin`, and
`Wave2 low < Wave1 peak`; otherwise no valid SETUP_01 lifecycle is created.
Explicit ABC correction context and weekly downtrend block confirmation.

**Lifecycle boundary:** `ARMED` uses the protocol-fixed causal recovery
threshold `close >= Wave2 low + 0.5 × (Wave1 peak − Wave2 low)` while
`close <= Wave1 peak`. `CONFIRMED` requires a daily close strictly greater
than Wave 1 peak. Before confirmation, `close <= Wave 1 origin` is the Wave
Scenario invalidation and `close <= confirmed Wave 2 low` is the separate
SETUP_01 trade-structure invalidation. Fib ratios `0.382`, `0.5`, `0.618`,
and `0.786` are reused from `trading/fibonacci.py` for descriptive region
diagnostics only; no Fib, RSI, EMA, return, or outcome metric is a gate.

**Replay and shadow boundary:** Every replay snapshot evaluates only the
visible historical prefix and emits deterministic first-entry `CONFIRMED`
or `FAILED` event identities. The real holdings shadow is read-only and
produces JSON/CSV diagnostics only; it does not call SETUP_03 Decision, emit
`ENTRY_ALLOWED`, write Sheets, or access returns, forward returns, MFE, MAE,
P&L, Final OOS, or formal validation. This is a structural review node, not
authorization for SETUP_01 Decision/Risk or a production signal.

**Reason:** A dedicated setup type preserves the meaning and compatibility
of SETUP_03 while making the Wave 2 → Wave 3 assumptions, counter-scenario,
causality, invalidations, and review evidence explicit. The fixed recovery
rule is intentionally simple and non-optimized; no parameter grid or
market-specific Fib rule is introduced.

## 2026-08-30

### Decision: close the SETUP_01 terminal-event projection self-reference and event-semantics gap

**Governance:** Tracked governance files record the latest substantive implementation/source head and the corresponding business/protocol/decision/next-action snapshot. They do not record the final commit SHA that contains their own docs-only update. PR final tip, exact-head CI, mergeability and merge commit are live GitHub evidence. `HANDOFF_CURRENT_AND_CONSISTENT` means the repository state and governance snapshot agree; it does not require a self-referential SHA. This supersedes any historical `THIS_COMMIT` wording and prevents an infinite docs-only update loop.

**Implementation:** The latest substantive source head for PR #36 is `eed768bec92365615b05b0a8314cf555e44b22ac`, following the previous review head `ca9ec6e93518e7e47c13f8f41a7f5751c9fd24d0`. `Setup01Evaluation` and its JSON projection now expose `terminal_event_type`, `terminal_event_date`, `is_new_confirmed_event_as_of`, `is_new_failed_event_as_of`, and `is_live_preconfirmation_candidate`. The first two preserve the current lifecycle's historical terminal fact; the new-event flags are true only when the matching terminal date equals the as-of date; live candidate is true only for `WATCH`/`ARMED`.

**Replay/shadow boundary:** Replay consumes the explicit new-event flags, so a persisted historical `CONFIRMED` state is not re-emitted or re-decided on later dates. The read-only real-holdings shadow exposes both nested projection fields and top-level `new_confirmed_today`, `new_failed_today`, `live_candidate`, and `historical_terminal` fields. Lifecycle transitions, structural event identity and event counts are unchanged. Regression coverage proves a later as-of snapshot can remain `CONFIRMED` while `is_new_confirmed_event_as_of=false` and the replay event count remains one.

**Boundary:** This closeout does not start `SETUP_02`, reopen `SETUP_03`, or access returns, MFE, MAE, P&L or Final OOS. The previous CI/shadow runs `33300273163`/`33300273180` do not cover the new source head; exact-head CI, re-run real holdings shadow and PR state must be re-verified before PR #36 merge.

### Decision: close PR #36 and implement an independent SETUP_01 Decision/Risk v1

**Governance closeout evidence:** The terminal-vs-new-event projection fix was
verified on PR #36 final tip `84fa676955e9a8226dd332881b8058cd5d4528fb`, with
exact-head CI `33316698003` and structural shadow `33316697983` both success.
PR #36 was then squash-merged under the user authorization; the real merge
commit is `3a6d417ede3594c05003ea18ce65bd4562eff294`, and main exact-head CI
`33316793033` succeeded. Governance now explicitly avoids requiring tracked
HANDOFF/CURRENT_STATUS files to contain their own final commit SHA; live PR
tip/CI/mergeability remains the source for that fact.

**Decision:** From that new main, register and implement
`SETUP-01-DECISION-RISK-2026-08-30-v1` as a separate evaluator. It consumes
only `Setup01ReplayEvent` values with `event_type=CONFIRMED` and a first
CONFIRMED event on T. An event identity can produce at most one Decision;
persistent historical terminal CONFIRMED state is ignored. T close forms a
plan only, and the earliest feasibility observation is T+1 OPEN.

**Protocol:** For the long side, `confirmation_level=Wave1 peak`,
`planned_entry=T close`, entry zone is `[Wave1 peak, Wave1 peak + 0.5*ATR14(T)]`,
and execution stop is `confirmed Wave2 low - 0.5*ATR14(T)`. Wave Scenario
Invalidation remains Wave1 origin and SETUP_01 structural invalidation remains
Wave2 low; neither is overwritten by the execution stop. Targets are built
before R/R from T-known confirmed highs and the existing
`trading.fibonacci.EXTENSION_RATIOS`; Wave3 projection uses the generic helper
`base + (reference_end-reference_start)*ratio`. Existing shared risk rules
remain unchanged: RR<2 is `NO_TRADE`, 2–3R is `NORMAL`, 3–5R is
`HIGH_QUALITY`, and >5R requires target reasonableness checking. Risk capital
is explicit; holdings shadow does not infer NAV or position size.

**Development funnel evidence:** The frozen DEVELOPMENT_EXPOSED structural
CONFIRMED stream contains 745 first-entry events (CN 299, US 446). The
Decision/Risk funnel produced 745 Decision rows: `ABOVE_ENTRY_ZONE=464`,
`RR_BELOW_MINIMUM=276`, `ENTRY_ALLOWED=5`. The five T+1 OPEN attempts produced
`EXECUTED=4` and `SKIP_GAP_BELOW_CONFIRMATION=1`. Total/CN/US/symbol scope
rows and conservation checks are emitted. This is descriptive execution
feasibility only; no return, MFE, MAE, P&L or OOS field is read.

**Current holdings evidence:** Registered Wave structural read-only shadow on
PR #37 source head, run `33318129223`, requested 10 holdings, evaluated 8 and
fail-closed 2. It showed 7 historical terminal rows, including INTC and DRAM
whose terminal CONFIRMED dates precede the current as-of date, and one live
`WATCH` candidate (`000725.SZ`). `new_confirmed_today=0` and
`new_failed_today=0`; therefore the Decision layer must generate zero new
holding Decisions. SIVE.SE remains stale and MU has no configured history
source; neither is guessed. The dedicated Decision shadow workflow is
registered as a manual post-merge workflow because a new unmerged PR workflow
must not be granted Google Secrets access; the local regression covers the
same historical-terminal/live-candidate no-redecision contract.

**Review boundary:** PR #37 is OPEN and must not be auto-merged. This node is
`SETUP_01_DECISION_RISK_V1_READY_FOR_SOL_REVIEW`. Do not start SETUP_02,
reopen SETUP_03, write Sheets, or enter outcome/backtest/OOS work without a
separate Sol decision.
