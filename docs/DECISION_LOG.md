# DECISION_LOG.md — 重要决策记录

> 只记录长期有效、未来开发不能随意推翻的重要架构／交易规则决策及理由。
> 普通 bugfix、PR review correction、测试数量变化、request accounting、小型
> provider 实现细节、临时 runtime 调试结论、merge/CI 过程不作为长期 Decision。
> 动态工程事实（SHA、PR、CI、merge）以 Git / GitHub 实时状态为准；历史过程由
> Git 保存，本文件不做 archive。最后实质更新：2026-09-06。

---

## 2026-08-21 — 仓库作为唯一事实源与项目基线

**Decision:** GitHub 仓库是本项目唯一可信事实来源；`AGENTS.md` + `docs/` 作为跨
AI 工具共享上下文。项目版本基线为 `V0.2`。

**Reason:** 项目在多设备、多 AI 工具间接力开发，聊天记录不可作为长期记忆；版本
基线用于明确“行情与校验已完成、决策引擎各阶段尚在推进”的阶段事实。

## 2026-08-21 — 扁平模块结构

**Decision:** 保持现有扁平模块结构，不强行迁移到 `src/` 包布局。

**Reason:** 现有模块职责清晰且稳定；决策模块增多前的大规模重构风险大于收益，
渐进重构优先。

## 2026-08-21 — Wave 主／备情景与 R/R 准入语义

**Decision:** 波浪分析采用“主情景 + 备选情景”，不武断输出唯一浪型；证据不足输出
`UPTREND_UNKNOWN_WAVE`。R/R 是交易准入条件，不是固定止盈；先算合理 Target 再算
R/R，禁止倒推目标价。

**Reason:** 降低 Elliott Wave 主观性、防止行情波动时频繁改浪；防止为满足 R/R
阈值人为制造目标价格。

## 2026-08-21 — Swing 确认与回测因果性

**Decision:** Swing 区分 `CONFIRMED` 与 `PROVISIONAL`；回测禁止拿未来确认的
Swing 回填过去信号。

**Reason:** 防止 Look-ahead Bias。

## 2026-08-22 — Trading Core 目录与数据模型

**Decision:** Phase 1 Trading Core 采用克制目录结构 `trading/`
（models/indicators/swing/structure/fibonacci/risk），单一权威实现，输入复用
`core.Quote`，不新建 Bar 类型。

**Reason:** 全仓库确认无既有交易概念实现；避免重复实现与过度拆文件。

## 2026-08-22 — SwingPoint as-of 语义

**Decision:** `SwingPoint` 记录 `pivot_index/pivot_date`（Swing 发生时间）与
`confirmed_index/confirmed_date`（信息实际可用时间）；任何历史决策只能用
`confirmed_index <= t` 的 Swing。

**Reason:** 明确 as-of t 语义，防止未来数据回填修改历史决策。

## 2026-08-22 — Market Structure 与 Fibonacci 边界

**Decision:** `MarketStructure.trend` 增加 `TRANSITION` 与 `UNKNOWN`；Swing 数量
不足或结构不明确时禁止强制分类。`fibonacci.py` 不依赖 `structure.py`，只消费
`SwingPoint`。

**Reason:** 避免证据不足时武断判定市场状态；Fibonacci 是纯几何计算，不应绑定
趋势判定。

## 2026-08-22 — Execution Stop 与 R/R

**Decision:** `risk_reward()` 使用 `execution_stop` 计算真实 R/R；Structural
Invalidation 与 Execution Stop 是两个独立概念，不在 R/R 计算中混用。

**Reason:** 结构失效与执行止损语义不同，混用会导致风险被高估或低估。

## 2026-08-22 — 指标与输入契约

**Decision:** 指标定义固定：Wilder ATR、Wilder RSI、EMA 标准 `2/(N+1)`；warm-up
返回 `None`；序列长度与输入 Quotes 对齐。Swing V1 基于 causal pivot（可选 ATR /
percentage minimum excursion filter 降噪），禁止事后重绘 ZigZag。输入强制校验
日期严格升序、无重复、同一 symbol/market，异常 fail fast。

**Reason:** 保证可复现、逐位对齐且无未来信息；显式失败比静默修正更安全。

## 2026-08-22 — PositionSize 边界

**Decision:** Phase 1 `PositionSize` 只输出 theoretical quantity / risk capital /
max loss；A股手数、港股 lot size 等 executable rounding 等市场元数据接入后再做。

**Reason:** 避免过早绑定市场规则，保持计算层纯净。

## 2026-08-22 — SETUP_03 止损与 Target 语义

**Decision:** SETUP_03 多头 Execution Stop =
`breakout_price − atr_buffer × ATR`，Structural Invalidation 保持 `platform_low`；
R/R 始终用 Execution Stop。Decision Target：历史前高 + Fib 1.272/1.618 均为候选，
过滤 None/≤ planned_entry 后按价格升序 T1/T2/T3；R/R gate 以最近有效目标 T1 为准。

**Reason:** platform_low 是认错的最终边界而非执行止损，用它算 R/R 会系统性地
杀死所有突破策略；最近目标最保守，可防止遥远目标的高 R/R 掩盖近期风险。

## 2026-08-22 — 展示层与参数显式化

**Decision:** `交易决策` Sheet 只展示 Trading Core 已生成的 Setup / Decision；
正式收盘且 qfq 末根与 chosen 行情日期一致时才运行当日决策。qfq 历史只允许
yfinance / BaoStock，不复用 Tencent/Sina 快照链。Setup/Decision 参数全部从
`参数设置` 显式读取并原样传入。

**Reason:** 防止展示层复制公式、非正式数据触发决策、快照源误入历史计算以及
隐式默认值造成参数漂移。

## 2026-08-24 — 终态事件语义（生产与回放共用）

**Decision:** 生产发布与 Historical Replay 共用 `trading.events` 的终态事件语义：
`CONFIRMED/FAILED` 是状态；只有当前最后索引首次进入终态才是事件。`交易决策`
仅发布新的 CONFIRMED Decision 事件，并以 Sheet 事件键阻止同日重跑重复计算。

**Reason:** 生产按每日状态、回放按首次终态事件，两者分叉会把持续状态误作新
信号并重复计算 Decision。

## 2026-08-24 — 回放只读数据质量门控

**Decision:** SETUP_03 真实回放在 Trading Core 前保留源数据原始顺序并校验空序列、
最小样本、最新日期、最新数据滞后与异常日历缺口；enabled=0 或 calculable=0 时
workflow 失败但诊断 artifact 仍上传。

**Reason:** 排序后再校验会掩盖源乱序；全跳过仍成功会产生“回放已完成”的假阳性。

## 2026-08-24 — Phase 5B 研究口径

**Decision:** Phase 5B 只消费 replay 产生的 CONFIRMED event contract；T 日仅确认
信号，T+1 Open 才模拟执行；生产 `platform_tolerance_pct=0` 不变。研究 R 使用
显式 research-only 20 交易日首障碍保守口径；T 日 Decision 必须先于 T+1 检查；
日线 excursion 采用 barrier-capped 保守口径，不虚构同一 bar 内 high/low 先后。
敏感性结果不排名、不选参数、不回写生产。

**Reason:** 回测必须与生产共用同一事件语义且不因结果篡改规则；无法证明 bar 内
路径顺序时，宁可保守也不伪造分钟级路径。

## 2026-08-25 — Decision diagnostics Single Source of Truth

**Decision:** Decision gate reason 在生产 Decision 计算内部产生：同一次计算返回
不可变 `Decision` 与只读 `DecisionDiagnostics`；Research 只投影 reason 与中间值，
不复制 ATR / Entry Zone / Target / R/R 判断。

**Reason:** 拒绝原因与 Decision 必须共享同源实现，才能解释 CONFIRMED → NO_TRADE
而不产生第二套交易逻辑与规则漂移。

## 2026-08-25 — 冻结研究输入与诊断边界（Phase 5D/5E）

**Decision:** Phase 5D 使用版本化 canonical replay-input schema（字符串原样、
ISO-8601 日期、`float.hex()` 精确数值、逐 symbol 哈希 + 排序聚合哈希），frozen
input 以 artifact-only gzip JSONL 保存并在读取时重算 hash。Phase 5E 固定 Phase 5D
canonical dataset 与生产参数版本，只做描述性 forward-path 诊断。已用于开发的
数据集明确不是最终样本外保留集。

**Reason:** `same input + same config/code = same result` 必须可独立验证；描述性
结论与正式 OOS 分离，防止选择偏差与过度宣称 Edge。

## 2026-08-25 — Phase 5F/5G/5H 研究协议

**Decision:** Phase 5F 的 confirmation gate reason 由 production SETUP_03 状态机
同一次计算产生，逐 frozen bar 只归一个 terminal reason 并强制守恒。Phase 5G 只在
固定 dataset 上改变 `platform_tolerance_pct`（固定顺序），不排名。Phase 5H 只做
市场间结构一致性诊断（as-of ATR / 20 日波动率标准化 + 精确事件 Jaccard/retention
/date drift），任何发现不自动产生 market-specific tolerance。

**Reason:** 单参数隔离与同源计算是结构诊断的前提；用开发样本做市场专属定义或
参数选择会造成选择偏差。

## 2026-08-26 — Phase 5I 参数冻结审计

**Decision:** 以版本化机器可读 `research/setup03_frozen_spec.json` 作为 SETUP_03
冻结 inventory 与治理边界的单一事实源，关键值由 canonical SHA-256 完整性合同
保护。正式冻结结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`：tolerance、
lookback/window/proximity、market/regime/波动率 production 定义保持 `UNRESOLVED`。

**Reason:** 冻结阶段先关闭可审计的研究自由度，防止证据、样本或协议悄然变化；
证据不足时不选择参数，也不提前查看 OOS。

## 2026-08-27 — Phase 5J 结构验证协议（v1/v2）

**Decision:** 预注册并冻结 SETUP_03 structural validation protocol（v1 五市场、
v2 CN/US scope），状态为 `VALIDATION_PROTOCOL_REGISTERED_NOT_EXECUTED`。正式
production tolerance 候选仅 `3.0% / 4.0% / 5.0%`；`2.5% / 5.5% / 7.5% / 10.0%`
只能作诊断/stress 边界。`setup_swing_lookback=5`、`platform_window=40` 仅保留为
incumbent constants；market/regime/volatility-normalized production rule 禁用。

**Decision:** 结构门槛、qualification matrix 与选择规则预注册并冻结：每市场每候选
至少 8 个 CONFIRMED；Jaccard ≥60%、retention ≥80%、drift median ≤5 / P90 ≤15；
集中度上限；3% 绑定自身 + 3%→4%、4% 绑定自身 + 两侧、5% 绑定自身 + 4%→5%；
按 3%→4%→5% lexicographic 选择首个 qualified candidate。禁止使用 forward
return / MFE / MAE / win rate / P&L 等收益指标。protocol version/hash contract
不可变：同一 version 下内容同步重算 hash 也必须失败。

**Reason:** 未来 validation 的样本、门槛、选择顺序和禁区必须成为不可悄然漂移的
contract，而不是用开发数据先行试验或按结果调参。

## 2026-08-27 — 未来 validation 数据边界

**Decision:** 未来 development-validation dataset 覆盖 CN/US（CN 仅 Main Board
active），标的须在读取 SETUP_03 输出前按非信号元数据冻结并哈希；禁止按结果替换
/增删标的；不足覆盖返回 `INSUFFICIENT_COVERAGE`。CN 使用 BaoStock qfq 契约，
US 使用 yfinance adjusted 契约；无补日期、插值、synthetic bar、history splice 或
provider fallback。

**Reason:** 预先冻结 universe 与 provider/QC contract 才能把结构证据与信号驱动
样本选择分离，保证 frozen input 可复现、可审计。

## 2026-08-27 — 数据源研究结论

**Decision:** HiThink CN API capability smoke 结论为
`HITHINK_CN_RESEARCH_DATA_PROVIDER_NOT_READY`（未证明预计算复权公式、日历样本
不足），不据此启动正式获取。S&P500 官方构成不可机器读取时，正式 provenance
使用明确标记的 `S&P500_UNIVERSE_PROXY_IVV_OFFICIAL_HOLDINGS`，不得称为 official
S&P500 constituents。Phase 5K-A1 v2 universe manifest 与 Phase 5K-B0 acquisition
contract（CN wire 参数与 IBKR 参数）已冻结，状态为未获取。

**Reason:** 数据能力必须由真实响应证明；provenance 必须诚实标记 proxy；
formal dataset 获取契约须在抓取前冻结。

## 2026-08-28/29 — SETUP_03 development evidence 与 v3 matching

**Decision:** development dataset v2（40/84,284 bars）与第二套 independent
holdout（40/86,305 bars）均只产生 structure-only evidence；v3 qualification
matrix 结果为 `qualified_candidates=[]`（`VALIDATION_FAIL_NOT_READY_FOR_FORMAL_
FREEZE` / `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`），未选择
tolerance。事件 matching 使用冻结 v3 protocol：exact `(market, symbol,
confirmed_date)` retained，其余同市场/同 symbol 内 one-to-one、non-crossing、
最大基数后最小总 trading-session distance，最多 `platform_window=40` sessions。

**Reason:** 冻结 event matching 消除“按结果微调匹配”的歧义；结构证据必须机械、
可复现，且不能读取收益指标或 Final OOS。

## 2026-08-29 — Frozen artifact 生成顺序

**Decision:** frozen dataset 生成顺序固定为 normalized data → replay input /
aggregate → final dataset manifest → replay wrapper；loader 必须验证 wrapper
integrity 与所有 cross-binding。修复类问题只重生成 wrapper integrity，不改变
frozen bytes / manifest / 研究结果。

**Reason:** provisional-hash cross-binding 会破坏恢复身份的可信度；固定顺序与
fail-closed binding 验证保证 frozen input 身份一致。

## 2026-08-29 — 治理初始化与 frozen-artifact registry

**Decision:** 引入根目录 `HANDOFF.md`（现场交接）、`docs/CURRENT_STATUS.md`（正式
状态）、`docs/DECISION_LOG.md`（长期决策）、`docs/FROZEN_ARTIFACT_POLICY.md` 与
`docs/FROZEN_ARTIFACT_REGISTRY.json`（非 Git correctness-critical artifact 的
恢复治理与机器可读登记）。不进入 Git 的 frozen bytes 只有在
`LOCAL_PRESENT / HASH_VERIFIED / PERSISTENT_BACKUP_PRESENT / RECOVERY_VERIFIED`
全部成立时才能标为 `FULLY_RECOVERABLE`。

**Reason:** 多设备开发需要“当前要做什么”和“为什么这样决定”分离；对大体积 frozen
payload 强制记录恢复证据，避免用近似重生成冒充 frozen artifact。

## 2026-08-29 — tracked provenance 文件哈希采用 LF-normalized bytes

**Decision:** tracked text provenance 文件身份 = LF-normalized bytes 的 SHA-256；
governance tests 与 frozen parity 使用同一规则。

**Reason:** Windows 工作树 CRLF 与 Linux/Git LF 的 raw hash 不同；文件身份必须
跨 checkout 平台稳定。

## 2026-08-29 — Phase 5J-v4 先冻结 protocol 再执行

**Decision:** Phase 5J-v4 lifecycle attribution 在真实归因前先持久化、哈希并冻结
machine-readable protocol；只对 frozen holdout 输出 research trace / root /
propagation / lineage / counterfactual，全部标 `RESEARCH_CAUSAL_DIAGNOSTIC_ONLY`。
归因结果为 `MIXED_CAUSAL_STRUCTURE`（low/high/both-span 混合），推荐的是 redesign
boundary/rearm semantics，不是新规则实现。

**Reason:** 因果归因必须按预注册口径执行，不能从阶段名或事后症状推断机制，
也不能把诊断 seam 变成候选交易规则。

## 2026-08-30 — SETUP_03 structural development 停止

**Decision:** 预注册 ATR-normalized boundary family（v5）qualification 失败：
candidate-level 门通过但 adjacent/lifecycle 门未通过，`qualified_candidates=[]`。
正式状态设为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。ATR-normalized 实现保留并
显式标 `RESEARCH_ONLY / NOT_PRODUCTION_AUTHORIZED /
FAILED_STRUCTURAL_CANDIDATE_FAMILY`；production 默认仍为 percentage path。
后续 SETUP_03 继续必须由新的明确研究决策 + 新 protocol/version 授权。

**Reason:** 不选择失败 family 的阈值，不另调 ATR 周期/家族、不补偿市场、不改
terminal/rearm；结构证据不足时应把核心路线归还 Wave → SETUP_01 → SETUP_02。

## 2026-08-30 — 生产行情日期与 scheduled latest 边界

**Decision:** 长期不变量为 `交易日期` = 市场真实 session trade_date，
`抓取时间` = 北京时间 fetched_at，两者不可互换。最新 source 选择 evidence-first
且 fail-closed：拒绝 future date，sane source 中最新的已完成 session 优先，另一源
stale 时保持 `待复核`。scheduled Asia/US 只运行 `latest` 模式，不读写历史/qfq、
不运行 SETUP_03/Decision；`full` 只能显式手动选择。

**Reason:** 分离 market-session evidence 与运行时间消除跨午夜日期错位；latest-only
与 full 分离防止行情刷新误触发历史/策略路径。latest yfinance 需要显式 bounded
窗口并在 provider 尾部不完整时经 bounded Yahoo Chart 重试，绝不补造价格。

## 2026-08-30 — Wave Scenario Engine v1 与 SETUP_01 结构层

**Decision:** 注册 `WAVE-SCENARIO-ENGINE-2026-08-30-v1`：输入先截断到
`data <= as_of_date`，输出有限 primary/alternate 情景 + 证据/反证/rule-count
evidence score + Fib 描述性区域 + structural invalidation + SETUP_01/02 context
eligibility；Wave 2→3 要求 `peak.price > origin.price`；weekly downtrend 阻断
long-side context；fixed as-of 对 appended future bars 不变。

**Decision:** SETUP_01 v1 是独立 immutable evaluator + strict as-of replay：
`NONE/WATCH/ARMED/CONFIRMED/FAILED`，只接受 primary `WAVE_2_TO_3_CANDIDATE`，
要求 `LOW→HIGH→LOW` 三个 confirmed Swing、Wave1 peak > origin、Wave2 low >
origin 且 < peak；close 严格 > Wave1 peak 才 CONFIRMED；事件 identity 只在首次
终态日发出（`is_new_confirmed_event_as_of` 等显式 flag），后续 as-of 不得重发或
重算。

**Reason:** 先建立可审计结构上下文再谈 Decision/Risk；Wave 引擎与每个 Setup 必须
保持严格 as-of、主情景、single-source Fibonacci 和“状态不等于事件”的语义。

## 2026-08-31 — holdings-data-manager 与 coverage contract

**Decision:** 新增 repository-local Skill（薄 contract）+ `holdings_data_manager.py`
实现单标的 `ADD/REENTER/CLOSE/SYNC`；身份规范化复用 provider registry；
`自选清单.启用` 是持仓身份事实源；不新增 Sheet 列、registry 或第二套 holdings
事实源。CLOSE 只停用当前视图，不删除历史/校验/映射。history coverage 只使用
observed session dates：raw/qfq 日期集一致、无重复、至少 180 bar、末日到目标、
起点 ≤7 天、异常中段 gap ≤14 天；不按 weekday 造 bar。

**Reason:** 单标的新增入口不应复用批量 full pipeline；覆盖与 QC 必须以 provider
观测到的真实 session 为准，避免把节假日当缺口或伪造休市日 bar。

## 2026-08-31 — holdings command bus 安全边界

**Decision:** ChatGPT/Codex 到仓库的 holdings 操作走 GitHub Issue command bus：
标题固定 `[HOLDINGS_COMMAND]`，body 为严格 JSON v1（单 symbol、固定 operation 集、
`dry_run`），workflow 只由 `issues.opened` 触发；job-level 校验 governed
repository、non-PR、actor/sender/Issue-user 均为 `EFSing`，Python 层做二次
authoritative allowlist。dry-run/invalid route 无 Google Secrets；live route 才从
既有 GitHub Secrets 注入凭证并以非取消 concurrency 串行执行。bridge 只委托
`HoldingsDataManager.execute()`，回执不含账户/成本/NAV/P&L。

**Reason:** 外部模型不能自由触达 shell/Sheets；必须先用可审阅、fail-closed、
单符号、串行的受控命令桥接真实写入，避免并发乱序与凭证泄漏。

## 2026-08-31/09-01 — SETUP_01/02 Decision/Risk 执行语义

**Decision:** SETUP_01/02 Decision/Risk 共用同一 frozen 执行契约：只消费首次
`CONFIRMED` 事件（exactly-once identity）；T close 只形成 plan，禁止同 bar 执行；
最早 T+1 exact session `OPEN`；Target-before-RR；`actual_entry != None ⇔ outcome
== EXECUTED`，skip 保留 `t1_open/actual_rr` 但不保留 `actual_entry`。
Development session identity = `FROZEN_DATASET_MARKET_SESSION_SET`；production
执行前的前置条件为 `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_
PRODUCTION_EXECUTION`（已登记，本阶段不接第三方 calendar）。

**Reason:** 首次终态事件语义必须贯穿 Decision/T+1，防止持续状态重触发；执行与
风险记账需要明确 entry basis，未成交不得臆造成交。

## 2026-09-01 — holdings lifecycle closure 与 enable-last

**Decision:** ADD/REENTER 闭合成一个操作：normalize → 最近已完成 session latest
snapshot → 同一 completed trade_date 的 raw/qfq history QC → upsert latest →
append validation → **最后** enable watchlist。已启用重复 ADD 先逐组件修复再返回
`IDEMPOTENT`；不重复抓完整历史。抽取 `latest_snapshot.py` 作为 scheduled latest
与 holdings 共享的 evaluator/projection。

**Reason:** enable-last + 组件级重试幂等保证任一中间写失败后重试只补缺失部分，
不产生重复 validation；单一 latest pipeline 防止第二套行情语义。

## 2026-09-01/02 — SETUP_02 Decision/Risk 几何修正

**Decision:** 废弃 `structural_invalidation → HIGH3` 的 continuation target 投影
（与最小 R/R 数学不兼容），正式 protocol v2 target =
`LOW2 + (HIGH1−LOW0) × existing EXTENSION_RATIO`，source=
`WAVE3_FIB_EXTENSION`，provenance 记录 LOW0/HIGH1/LOW2/ratio；剩余 target 过滤
`> planned_entry` 后升序 T1/T2/T3 再做 R/R。旧 `INVALID_STRUCTURE` rows 全部
重新归类为 `STALE_CONFIRMATION_GEOMETRY`（`structural_invalidation >= HIGH3`）。

**Reason:** 即使 canonical 最大 r 也无法满足固定 2R 的几何必须弃用；不用降 R 阈值
/放宽 Entry Zone / 收紧 stop 或查看 outcome 来“修复”数学缺陷。

## 2026-09-02 — Position Management + Exit v1

**Decision:** Position Management 只消费 SETUP_01/02 `EXECUTED` rows；origin
geometry、actual entry、initial stop、structural invalidation、targets、Wave
anchors、one-R 不可变。Immutable `PositionTarget` 原样冻结前三个 target
candidates 的 price/order/source/provenance，不重算 target。MFE/MAE、Wave5
context、stop/exit 与 advisory 全部 causal；Wave5 不能强制退出或新建 entry。
报告禁止 win rate / aggregate P&L / expectancy / profit factor / Sharpe /
optimized thresholds / Final OOS。

**Reason:** 持仓管理与退出必须共享冻结的 entry/target/stop 事实；研究层只描述
机械行为，不把 outcome 统计用于调参或生产。

## 2026-09-02 — Portfolio Risk V1 与 remaining capital-loss 语义

**Decision:** `PORTFOLIO-RISK-2026-09-02-v1` 是 downstream fail-closed capacity
gate，常量 `0.005 / 0.02 / 0.01`。风险公式固定为：

```text
remaining_loss_risk_per_share = max(actual_entry − active_protective_stop, 0)
remaining_loss_risk_fraction = quantity × remaining_loss_risk_per_share / reference_nav
```

`current_price` 不参与 capacity；lock profit floor 为 0 且不能抵补其他仓位；
`actual_entry` 缺失时 fail closed（绝不 fallback 到现价）；gap/slippage tail risk
不在框架内。一个 canonical symbol 一个 open long；risk group 只来自可靠 metadata；
production UNKNOWN group fail closed。same-session 顺序 deterministic；failed
T+1 release；stop raise/exit release capacity。

**Reason:** Portfolio Risk 管理的是剩余本金损失风险，不是 mark-to-stop giveback；
引入现价会把锁定利润误当 capacity 并让风险随行情波动而变。

## 2026-09-02 — allocation_budget 语义

**Decision:** `allocation_budget` 是用户明确授权给该账户整个策略风险账本的总
策略预算，不是 broker NAV / 账户净值 / 总资产 / 入出金 / P&L / purchasing power。
已有 positions 与 approved proposals 共用同一预算 denominator。预算本身绝不代表
approval；生产分配只在 event identity 被显式批准（`approved_event_identities`）、
预算有效、未 pending/settled 且 Portfolio Risk prerequisites 成立时进入分配。
未批准 `ENTRY_ALLOWED` 保持 `STRATEGY_PROPOSAL`。

**Reason:** 预算输入不能等于用户批准；同日多 proposal 只处理被批准 identity，
否则会绕过 proposal → approval → allocation 边界。

## 2026-09-02 — Daily Decision Chain v1

**Decision:** 构建 read-only prospective Daily Decision Chain，在 frozen Wave /
SETUP_01/02 / Portfolio Risk / Position Management / Wave5 之上做单账户编排；
可输出 T 日 prospective Decision，不提交 broker order，不把机械 T+1 ledger 观察
当成真实成交。生产需要正式 universe、可靠 NAV、risk-group metadata、position
origin、exact exchange-calendar session 与持久 `DecisionStateStore`；缺失
fail closed。禁止把 `自选清单`、weekday guard 或 legacy `交易决策` Sheet 静默提升
为这些 production 事实源。

**Reason:** 下一个产品边界是每日决策支持而非自动交易；编排层只接线，不复制或
重定义冻结策略 Single Source of Truth。

## 2026-09-03 — Daily Chain 编排硬化

**Decision:** 数据质量先于 Wave/Setup/Decision/Position Management；bad/stale/
unavailable/incomplete T 一律 fail closed，不产生 synthetic PM 指标。Portfolio
Risk 合并 global `existing_positions` 与 authoritative `OpenPositionState`，
canonical key 去重，关键字段冲突以
`PORTFOLIO_EXISTING_POSITION_CONFLICT` fail closed。dual same-symbol/T first-entry
CONFIRMED 是 upstream invariant violation（`DUAL_CONFIRMED_UPSTREAM_INVARIANT_
VIOLATION`），不保留 SETUP_01-over-SETUP_02 tie-break。T+1 观察必须
`DATA_OK` 且 exact expected bar 唯一才进入 executor/settle；缺失/歧义保持
pending。非空 `OpenPositionState` 即使无 `portfolio_position` 也阻断同 symbol
新 entry。

**Reason:** 编排边界缺陷会在真实生产数据上制造错误成交或错误释放；frozen
contract 不允许被编排层静默放宽或仲裁。

## 2026-09-03 — Production Prerequisites V1

**Decision:** 生产边界固定为五个 Sheets contract：`策略账户`、`策略股票池`、
`策略风险分组`、`策略持仓`、系统-owned `策略决策状态`。账户按 market/currency
隔离（CN=CNY/XSHG、US=USD/XNYS），无 FX；`SheetsDecisionStateStore` 为 V1
persistent backend（typed canonical JSON、account-scoped identity、append-only
compound protocol、默认 read-only）。production T+1 用 `exchange_calendars`
exact next real session；unsupported/future/holiday/未完成 session fail closed。
Latest 与 QFQ 行必须带显式 currency；缺失 QFQ = `DATA_UNAVAILABLE`；空 enabled
account fail closed。preflight 永不写。

**Reason:** 账户风险账本、正式 universe、权威持仓 origin 与 exact session 都是
不可从名称/watchlist/历史猜出的生产事实；V1 选择最小显式契约并 fail-closed。

## 2026-09-05 — Candidate Universe 架构边界

**Decision:** Candidate layer 位于数据质量与完整策略链之前，只决定标的是否值得
进入完整分析，不产生 `ENTRY_ALLOWED` / `STRATEGY_PROPOSAL` / 买入信号。CN
affordability：真实 minimum-unit notional `<=10,000 CNY` preferred、
`10,000 < notional <= 20,000 CNY` retained、`>20,000 CNY` excluded；US candidate
一股 `>1,000 USD` excluded，allocation 阶段 1,000 USD hard cap 单独复核。
Liquidity 只使用 20D/60D traded-notional proxy（成交额缺失用 close×volume）；
不做全市场绝对流动性阈值；`TOP_N_PER_SECTOR=20` 是集中可调常量，不进入
Strategy protocol。

**Reason:** Candidate 是交易前可交易性/分析资源边界，不是新信号层；把 affordability
与分散性放在重历史/策略计算之前可降低资源消耗而不污染冻结策略语义。

## 2026-09-07 — Dynamic Candidate 仅作发现，正式池晋级后才进入生命周期

**Decision:** Dynamic Candidate 是 discovery-only 输入。它可以进入同一套只读
Strategy/Daily 分析并出现在 JSON/Markdown 报告，但不得写入策略决策状态、发布
event identity、创建或结算 T→T+1 pending、进入 Portfolio allocation，或产生生产
执行资格。Candidate 与正式 `策略股票池` 重叠时，按正式池身份处理；Candidate-only
标的若要进入正式交易生命周期，必须由人工加入正式 `策略股票池`，补齐现有账户、
risk group、origin、calendar、budget 等生产前置条件后重新运行。正式池之外的已有
持仓仍可进入只读 Position Management，不借此把持仓提升为正式策略池。

**Reason:** 这保持一个正式、可审计的 stateful lifecycle，避免动态发现集合与持久
状态 identity、approval 和 T+1 ledger 发生隐式耦合；人工 promotion 是进入正式交易
语义的明确控制点，不新增第二套状态机或新的 Sheet contract。

## 2026-09-06 — Strategy history runtime 与 CN/US 独立

**Decision:** CN 与 US 收盘时段不同，Candidate/Strategy history runtime 必须按
市场独立 fetch/evaluate/summarize/fail；`--market all` 只是开发便利，不是
acceptance 标准。CN deep history 固定 `daily + adj_factor`（chunk=5、最多 1000
completed bars、exact T）；US 保持 IWB + yfinance batch，且 US auto-adjusted
Strategy history 只允许请求 latest completed XNYS session（historical as-of
replay 在 deep fetch 前 fail closed）。temporary Tushare-compatible gateway 只是
本地只读 shadow 机制，不是长期 production provider 决策。

**Reason:** 一个市场的失败不应抹掉另一个市场的合法结果；未来/假日/未完成 T 的
历史复权路径会污染 as-of 语义，因此 fail closed；临时 gateway 不得被解释为
provider 架构变化。

## 2026-09-06 — 治理体系职责重新收敛（Governance slim）

**Decision:** 长期治理模型收敛为：

1. Git / GitHub 是 branch、HEAD、PR、commit、diff、CI 的唯一实时事实源；治理文档
   不再长期镜像易变 SHA / CI run ID，只允许 HANDOFF 作 branch/PR 语义描述。
2. `HANDOFF.md` 只做“当前开发现场恢复文件”；删除旧 Engineering Event / Historical
   Event 流水账，不另建 archive / registry / 新治理文件保存历史。
3. `docs/CURRENT_STATUS.md` 只做“系统能力地图”；不保存历史 PR 过程、blocker
   演变、测试数量、CI run ID、commit SHA。
4. `docs/DECISION_LOG.md` 只保留长期有效决策与理由；普通 bugfix / review
   correction / 测试数量变化 / 小型 provider 细节不作为长期 Decision。
5. docs-only governance 更新原则上不触发完整 unittest / runtime shadow 等高成本
   验证；docs-only 默认验证上限为 `git diff --check`、现有 Markdown/JSON 语法
   检查与必要 grep/consistency check，不新增 validator / registry / protocol /
   CI workflow / 测试框架。
6. `HANDOFF_CURRENT_AND_CONSISTENT` 只表示 HANDOFF 能恢复现场、CURRENT_STATUS
   与能力无实质矛盾、长期 Decision 无已知冲突、无重大状态错误；不要求实时 main
   SHA、exact-head CI 或 docs-only 后重新完整验证。
7. `PROJECT_GOVERNANCE_STATE_CONFLICT` 只用于真正影响正确开发的问题；docs-only
   HEAD 变化、CI run ID 过期、测试计数、历史 event 未同步等自然过期信息不升级
   为冲突。

**Reason:** 原治理文件把大量可复现历史与验证过程写入 docs，形成“docs commit →
HEAD 变 → 重验 → 再 sync”的无限 reconcile 成本；Git 本身已是历史记录，治理文档
应只承载恢复现场、能力地图与长期决策三类最低必要信息。

## 2026-09-13 — Prospective Paper Trade Lifecycle V1

**Decision:** 前瞻模拟跟踪使用独立 system-owned `策略模拟账本` append-only
worksheet，以 `event_identity + lifecycle_event_type` exactly-once 记录
`PAPER_PLAN_CREATED`、exact T+1 `PAPER_T1_EXECUTED` / `PAPER_T1_SKIPPED`、
`PAPER_CLOSED` 与 `PAPER_COVERAGE`。只有新的 `CONFIRMED` event 且既有
SETUP_01/02 individual Decision 为 `ENTRY_ALLOWED` 时，才允许在显式
`--paper-track` 下自动纳入 Paper；`AUTO_APPROVE_FOR_PAPER_TRACKING` 与
`AUTO_APPROVE_TECHNICAL_ENTRY_ALLOWED` 不等于 production approval，也不写正式
strategy state、组合风险、账户 P&L 或 broker order。Candidate-only 可以进入
Paper，但 `promotion_required=true` 且不获得 state persistence / production
execution eligibility。

Paper T+1 与 Position Management 必须复用现有 executor、
`position_origin_from_execution`、`PositionOrigin` 和 `replay_position`；Target
reach 只是状态／风险管理信息，不是机械止盈。统计只报告 trade-level normalized
R、return %、持有与 MFE/MAE；SKIPPED/OPEN 不计胜负，胜率使用 WIN/(WIN+LOSS)。
Paper Tracking 从启用日起 forward-only，不历史回填 Candidate-only；active Paper
symbols 即使掉出 Candidate / Formal / Position 仍须经现有 exact completed-session
QFQ provider 续载，缺数据时 fail closed，并显式报告 coverage gap。
计划风险只用于 T 日方案展示；一旦 T+1 模拟成交，冻结的 `PositionOrigin` 是唯一
1R 来源，固定为 `actual_entry - initial_execution_stop`。当前 R、最终 realized R
与其余 Position Management 指标必须使用同一实际成交风险，不能回退到计划入场价
对应的风险列；账本同时保留 `planned_risk_per_share` 与成交后的
`initial_risk_per_share` 以便审计。

**Reason:** 这为策略方案提供可审计的 prospective feedback loop，同时把模拟事实、
正式 state、组合风险、真实持仓和 broker 执行保持在不同权限边界内，避免把
Candidate discovery 或模拟成交误解为 production eligibility 或账户收益。

## 2026-09-14 — Cloud Daily Report V1 的内存行情边界与移动展示

**Decision:** CN 与 US 各自使用独立的 Cloud Daily Report workflow，在
`exchange_calendars` 精确 completed session（CN=`XSHG`、US=`XNYS`）通过后运行。每次
运行只从既有 provider 配置获取目标市场正式策略池、启用持仓和 active Paper
continuation 所需的 latest/QFQ rows；rows 复用现有 provider fallback、
`latest_snapshot.py` evaluator/projection 和 Production Daily Decision Chain，留在
进程内存中；Cloud path 不读取旧的 `最新行情` / `历史行情_前复权`，也不回写这些 sheet、
缓存、日志或 artifact。非交易日
返回 `SKIPPED_NON_SESSION` 且不使用上一交易日替代；provider、T、QFQ 或校验异常
fail closed，但仍生成异常 JSON/HTML 并可通知。

最终每个 market/T 只允许 `daily-report.json` 与 `daily-report.html` 两个 artifact，
JSON 只保存市场/T、git SHA、session identity、data quality、Candidate seed/as-of、轻量
CandidateRecord 筛选审计、provider status、input fingerprint、protocol versions 和只读
边界，不保存 raw/QFQ bars。新
Dashboard 是 presentation-only mobile-first projection：默认页按数据异常、持仓、
交易方案、新确认、接近确认排序，以中文交易含义呈现；内部 setup/status/provenance
和原始字段只在折叠开发者区域展示。Bark/SMTP 是通知适配器，通知失败不得改变核心
日报结果。

旧 `asia-close` / `us-close` scheduled writer 在新 workflow 完成 Secrets 配置及安全
live acceptance 前保留，防止迁移期间丢失既有手工路径；live acceptance 后移除旧
schedule、保留旧 workflow_dispatch，避免长期两套 scheduled path 并行。该 Decision
不改变 Wave、Setup、Decision、Risk、Position Management、T→T+1 或 Candidate
promotion semantics。

**Reason:** 统一内存数据边界可避免云端把当日行情变成长期状态或把 CN/US 失败相互
污染，同时复用已验证的生产语义；最终 artifact 和移动优先 human mapping 让日报可
在手机上决策阅读，但不引入第二套策略状态机或自动交易权限。

## 2026-09-14 — T1 gross target-upside gate 与 opportunity freshness diagnostics

**Decision:** SETUP_01 与 SETUP_02 的第一正式目标 T1，必须相对 T 日现有
canonical `planned_entry` 有至少 `5%` gross upside，同时继续满足既有 T1
`RR >= 2R`。唯一常量 `MIN_TARGET_UPSIDE_PCT=0.05` 与
`target_upside_pct=(T1-reference_entry_price)/reference_entry_price` 位于共享
`trading.risk`。T1 仍按既有 target-before-RR、nearest-first 规则确定；不得用
T2/T3、远端 Swing、Fib、Wave、stop、Target generation、ranking、Portfolio Risk
或 Position Management 绕过门槛。T1 upside 不足时 primary Decision reason 为
`TARGET_UPSIDE_BELOW_MINIMUM`，但既有 R/R diagnostic 继续保留。

Exact T+1 OPEN 使用相同冻结 T1 与 actual OPEN 重新计算
`remaining_target_upside_pct`；低于 5% 时为
`SKIP_TARGET_UPSIDE_BELOW_MINIMUM`。Structural invalidation、below-confirmation、
above-entry-zone 与 exact-session precedence 保持不变；T+1 仍只读取 OPEN。
`5% <= upside < 8%` 为 `LOW_UPSIDE`，`>=8%` 为 `PREFERRED_UPSIDE`，两者只作
presentation/research band，不改变资格之外的 rank、size、allocation、approval 或
promotion。

**Decision:** 同一日报增加 `OPPORTUNITY_FRESHNESS_DIAGNOSTICS_V1`，只使用当时
可获得的 T-day `planned_entry`、T1、entry-zone upper、canonical confirmation
level 与 exact T+1 OPEN，输出 target upside、entry-zone upper distance、
confirmation extension、T+1 gap、remaining T1 upside，以及以 primary reason
计数且不重叠的 freshness funnel。不得使用事后最低点、future bars、MFE/MAE、
Final OOS 或据此自动放宽/优化策略。数据不足时不发明 confirmation threshold，
诊断不改变 `ENTRY_ALLOWED` / `NO_TRADE` / final status。

Paper lifecycle 从该代码进入后 forward-only 使用新 gate；旧 append-only Paper
ledger 不回溯、不重写。新增诊断沿用既有 `payload_json`，Candidate-only 仍为
`READ_ONLY_DISCOVERY`，不产生 production state、allocation、promotion 或 broker
execution。

**Reason:** 第一目标的可交易空间是策略资格，而确认时点、入场区位置和 T+1 gap
造成的空间衰减是观察问题。把两者分开可同时执行硬性交易纪律与因果测量，避免用
事后结果改变 Wave/Setup/Entry 语义。

## 2026-09-15 — SETUP_01 分开展示阻力与 Wave3 结构目标

**Decision:** SETUP_01 的用户侧投影必须分开显示当前正式 T1 及其 source、planned_entry
上方最近已确认 `CONFIRMED_SWING_HIGH` 的保守第一障碍，以及由既有 Wave3 Fibonacci
extension 产生的结构目标（含 ratio、上涨空间与可选的后续 extension 列表）。
Dashboard、email、JSON 与 Markdown 统一消费 Decision/target provenance 或共享只读
projection，不在展示层重算交易几何。

该语义分离不改变现有 nearest-first target candidate selection、正式 T1、5% T1
upside gate、2R RR gate、Target-before-RR、Wave、Swing、Fib、Entry、Stop 或
T→T+1 规则；T2/T3 与后续 Fib extension 不能绕过当前 T1 gate。

**Reason:** 最近历史阻力是当前价格路径上的已知第一障碍，而 Wave3 extension 是
Wave2→Wave3 假设成立时的结构投射目标。两者混为一个 T1 会把“保守规则不交易”
误解为“Wave3 只有这么多空间”，但分开表达不应扩大正式交易准入。

## 2026-09-17 — Cloud partial report 的运维 exit

**Decision:** SUCCESS 与 SKIPPED_NON_SESSION 的 exit 0 含义保持；PARTIAL_DATA_QUALITY 在 exact T usable data 存在、核心计算完成且 final JSON/HTML 形成时也 exit 0，但 report quality 仍为 partial，单源 provenance 明确保留。无 exact T/stale、核心异常、artifact 失败继续 non-zero；不降低 production data gates，不改变通知失败 contract。

**Reason:** 用户明确区分一次只读报告运行完成与报告内数据质量警告；不可把 warning 伪装成 SUCCESS 或以 T-1 替代 T。

## 2026-09-17 — Post-confirmation retest hypothesis 关闭

**Decision:** `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 不进入 production
design，也不单独进行 fresh validation。confirmed→wait-for-retest 在逻辑上成立，但
当前 Development evidence 只恢复极少量 executable，且全部集中 EARLY，不足以证明
broad/time-stable improvement，不值得引入新的 production waiting lifecycle。除非未来
出现新的独立证据，不重复启动同类 retest 参数研究。

confirmation、Entry Zone、ATR multiplier、5%、2R、Swing、Wave、Target、Stop 与
T→T+1 semantics 全部保持不变。

**Reason:** 小量、时间分布不稳定的 Development 恢复不能支持生产架构扩张，也不能
证明现有 Entry Zone 错误；保留负结果比继续在同一数据上搜索 waiting 参数更可靠。
