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

## 2026-08-26

**Decision:** 最新未复权行情选择采用“日期优先、同日质量优先”：交易日期不同时仍采用较新来源；交易日期相同时，若主源 OHLCV 内部异常而校验源正常，则整根行情采用校验源，并同步替换未复权历史序列的同日末根 K 线；两源均正常或均异常时保持主源。双源日期、收盘价与成交量校验规则不变。

**Reason:** yfinance 的 A 股数据连续出现开盘价超出日内最高／最低区间，但收盘价与成交量仍与 Tencent 一致。仅在最终写表后执行合法性检查会让正常腾讯行情无法接替异常主源，并使最新行情与未复权历史不一致。整根 K 线切换可保持 OHLCV 内部一致性，避免逐字段拼接出不存在的行情，同时不放宽质量闸门。
