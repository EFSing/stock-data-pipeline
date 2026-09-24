# SETUP_01 H1 突破后双路径入场研究协议草案

Status: `READY_FOR_DECISION`

Protocol draft: `SETUP01_POST_BREAKOUT_DUAL_PATH_ENTRY_RESEARCH_V1_DRAFT`

本文件只授权架构与预注册准备，不授权回放、经济结果读取、生产规则修改、Paper、
Sheet/state 写入或 broker 行为。现行 SETUP_01/02/03/04、Risk、Daily Decision、
Position Management 与 Final OOS 边界保持不变。

## 1. 事实恢复与既有结论边界

- 本草案基于 `main` 的 #109 基线；#110 是独立 OPEN research-only PR，保持不合并、
  不改写。#110 的第二阶段结论是 `INSUFFICIENT_EVIDENCE`，不是新框架的基线结果。
- `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 仍是已关闭负研究。它研究的是
  “确认后重新进入原冻结 Entry Zone，再套用旧门槛”，本草案研究的是 H1 突破后重新
  定义的两类价格行为信号 K、路径止损和执行计划；两者不是同义替代。
- #104 的 `PROSPECTIVE_EXACT_T_FUNNEL_V1` 只提供前瞻 exact-T 事件观察能力，不产生新
  入场、不回填历史事件，也不能替代独立验证样本。
- 现有 5% 与 2R 继续是正式生产规则。本草案只登记它们在新研究机制中的两个互斥角色，
  不删除、不修改正式常量。

## 2. 现有模块复用审计

| 能力 | 分类 | 真实契约与位置 | 新框架处理 |
|---|---|---|---|
| LOW0 / H1 / Wave2 Low 与因果 Swing | `REUSE` | `trading/swing.py` 的 `confirmed_index <= t`；`trading/wave.py` 的 confirmed Swing-only Wave 情景；`trading/setup01.py::_candidate_from_wave` | 直接消费冻结锚点，不重写 Swing/Wave |
| SETUP_01 首次 H1 突破 | `REUSE` | `trading/setup01.py::_state_for_candidate`：首次 `close > H1` 为 `CONFIRMED`；`trading/setup01_replay.py` 提供 exactly-once event identity | 作为双路径 overlay 的唯一出生事件 `B` |
| 突破后观察生命周期 | `MISSING` | 正式 SETUP_01 在 `CONFIRMED` 后为 terminal，不跟踪确认后的入场机会 | 只在 research overlay 中新增，不改变正式 lifecycle |
| Wave1 Fibonacci 回撤/扩展 | `REUSE` | `trading/fibonacci.py` 的 ratio catalogue、`fibonacci_levels*()`、`project_extension()`；`trading/setup01_decision.py` 的 Wave1 target provenance | 继续作为 Wave2 背景与 Wave3 target source |
| H1 后上涨段的因果 Fib 回踩 | `ADAPT_RESEARCH_ONLY` | 通用 Fib 算法可复用，但没有 post-breakout running-leg 契约 | 只用截至 `t-1` 的 running high；不得称为 confirmed Swing high |
| 突破后已确认 Swing 支撑 | `REUSE` | `find_swings()` 已能按确认日提供 post-breakout confirmed low | 只有 `confirmed_index <= t-1` 才能进入当日区域 |
| OHLCV / ATR / 日线状态 | `REUSE` | `core.Quote`；`trading/indicators.py::atr`；Wave evaluation 的 weekly/daily state | 信号日只读 `data <= T` |
| 通用相对量指标 | `MISSING` | 有 raw volume，Position Management 有高量 advisory，但没有 Entry signal 的 RVOL SSOT | 草案仅登记 causal RVOL20 diagnostic；若选择量能包再做 research helper |
| 正式 Entry Zone / Stop / invalidation | `ADAPT_RESEARCH_ONLY` | `trading/setup01_decision.py` 固定 `[H1, H1+0.5ATR]`、Wave2 low、Wave2 low−0.5ATR | 正式几何不可充当新路径同义词；只复用结构边界与 ATR 原语 |
| T1/T2/T3 与 provenance | `REUSE` | confirmed Swing high + Wave1 Fib extension，nearest-first、target-before-RR | 只用 T-known candidates；H1 在突破后是支撑，不伪造成上方目标 |
| exact T+1 OPEN / session identity | `REUSE` | `research/market_sessions.py`（冻结研究）；production exchange calendar（生产） | 计划仅在信号 K 收盘后生成，最早下一 exact session 执行 |
| 次日 signal-high buy-stop | `MISSING` | 现行 executor 只观察 exact T+1 OPEN，不模拟日内触发 | 新研究必须显式冻结 OHLC buy-stop 与同日歧义口径 |
| 事件去重与 replay | `REUSE` | SETUP_01 replay identity、严格 prefix replay、frozen replay loaders | overlay identity 派生自原 CONFIRMED identity，不另造 Wave 身份 |
| 交易成本模型 | `BLOCKED` | #110 有 research-only 模型但仍在 OPEN PR，且费率中包含假设；`main` 无可复用正式成本 SSOT | 新验证需独立冻结成本快照；不得把 #110 假设说成已验证账户费率 |
| 正式 Exit | `REUSE`（边界） | `trading/position_management.py`：stop/structural next-session、MFE/HL trailing；target reach 仅状态，不自动卖出 | 可作为候选退出包，不能宣称已有自动 T1 exit |
| 研究专用 T1 exit | `BLOCKED` | #110 OPEN PR 实现 full exit at T1，且明确不同于正式 Exit | 只登记为候选研究假设；不从 #110 分支复制实现或结果 |
| CN/US lot、限价、队列、spread | `BLOCKED` | frozen daily OHLCV 不足以证明队列/点差；board/ST 与账户费率需要 point-in-time 来源 | 缺失时只能 `NOT_MODEL_EXECUTABLE`，不能伪造 broker fill |

结论：核心结构计算可复用；真正缺失的是 post-breakout research overlay 及其执行/退出
契约。禁止为本研究重写 `wave.py`、`swing.py` 或 `fibonacci.py`。

## 3. 统一双路径状态机

```text
WAVE2_CONTEXT
  -> H1_BREAKOUT_CONFIRMED (existing first close > H1, date B)
  -> POST_BREAKOUT_OBSERVATION (starts B+1)
       -> CONTINUATION_SIGNAL
       -> RETEST_PENDING -> RETEST_SIGNAL
  -> ENTRY_PLAN
  -> exact next-session BUY_STOP_EXECUTION
  -> RESEARCH_POSITION_MANAGEMENT / EXIT
  -> COMPLETED | CENSORED
```

### 3.1 身份与信息集

- `overlay_lifecycle_id = existing_confirmed_event_identity + protocol_version`。
- LOW0、H1、Wave2 Low 取自 B 日已有 confirmed anchor tuple，并在 overlay 内冻结。
- 每日先用 `data <= t-1` 构造当日有效支撑区域，再用 t 日完整 OHLCV 判断是否触及及
  是否形成信号 K。信号只能在 t 日收盘后成立。
- 同一 overlay 最多一笔已执行持仓；执行后两条路径同时终止。
- 后来是否回踩不得反向改变更早的 continuation 信号或成交。

### 3.2 路径路由与同日优先级

1. B 日只创建观察，不允许同日作为新框架信号 K。
2. 从 B+1 起，若截至当日尚未触及当日冻结的 `active_retest_zone`，可以评估路径 A。
3. 某日价格区间首次触及 `active_retest_zone` 后，生命周期进入 `RETEST_PENDING`；从该日
   起不再产生新的 continuation signal。
4. 同一 K 同时满足 continuation 价格条件和 retest touch/reclaim 时，按路径 B 归属，
   因为“实际触及支撑”是可观测事实，不允许事后择优标签。
5. continuation 计划已生成但未成交后是否仍允许一次 retest 机会，是待用户决定的
   `OPPORTUNITY_POLICY`；任何选项都不允许已成交后再入场或加仓。

### 3.3 失败、替换与超时

观察在以下最早事件终止：

- `close <= Wave2 Low`：SETUP_01 trade structure invalidated；
- `close <= LOW0`：Wave scenario invalidated；
- 新 SETUP_01 lifecycle 使用不同 anchor tuple 替换当前上下文；
- 已有计划成交；
- 达到预注册 observation window；
- 数据结束：`RIGHT_CENSORED_OBSERVATION`，不得当作无信号失败或成功。

建议预注册窗口为 20 个 completed sessions（约一个交易月），但它属于
`OPPORTUNITY_POLICY` 决策，不从已暴露收益中选择。

## 4. Fibonacci 与有效回踩区域

### 4.1 三类锚点严格分离

1. `WAVE1_CONFIRMED_ANCHORS`：LOW0→H1→Wave2 Low，B 日前已确认；继续提供既有 Wave1
   retracement context 与 Wave3 extension targets。
2. `POST_BREAKOUT_RUNNING_LEG`：H1→`running_high(t-1)`；running high 只是截至前一日
   已观察到的极值，不得标记为 Swing，也不得用 t 日 high 重算 t 日回踩区。
3. `POST_BREAKOUT_CONFIRMED_SWING`：pivot 与 confirmation 均发生后，且
   `confirmed_index <= t-1`，才可作为 t 日支撑输入。事后确认的新高/低不得回填。

### 4.2 每日预先冻结的候选区域

在 t 日开盘前，用截至 t-1 的信息构造：

- `H1_SHELF = [H1 - 0.25*ATR_B, H1 + 0.25*ATR_B]`；ATR_B 固定为突破日 ATR14。
- 若 `running_high(t-1)-H1 >= 0.5*ATR_B`，则
  `RUNNING_LEG_FIB = [U-0.618*(U-H1), U-0.382*(U-H1)]`。
- 每个合法 post-breakout confirmed swing low 形成
  `[swing_low-0.25*ATR_confirmed, swing_low+0.25*ATR_confirmed]`。

`active_retest_zone` 是前一日收盘下方、下界仍高于 Wave2 Low 的候选中价格最高者；
同价重叠时固定优先级 `CONFIRMED_SWING > RUNNING_LEG_FIB > H1_SHELF`。这不是把多个
形态任意 OR 后事后挑赢家，而是每天开盘前唯一选定“最近支撑”。若当日 gap 直接跌穿
该区，不允许在同一日改选更低区；下一日再用新 prefix 计算。

## 5. 两类信号 K 候选定义

设 `range = high-low > 0`、`body_fraction = abs(close-open)/range`、
`close_location = (close-low)/range`。doji/zero-range 不合格。

### 5.1 路径 A：`BREAKOUT_CONTINUATION`

`PRICE_ACTION_ONLY` 定义：

- 此前及本日均未触及 active retest zone；
- `close > H1`；
- `close > previous_high`；
- `close > open`；
- `body_fraction >= 0.50`；
- `close_location >= 0.75`。

含义是突破后仍在支撑上方，以实体扩张穿越前一日高点并收在当日上四分之一；它不是
“大阳线/吞没/放量”任一满足即可的并联系统。

### 5.2 路径 B：`BREAKOUT_RETEST`

`PRICE_ACTION_ONLY` 定义：

- 当日开盘前已有唯一 `active_retest_zone`；
- `[low, high]` 与该区域相交；
- `close > zone.upper`（收复区域上沿）；
- `close > open` 且 `close > previous_close`；
- `body_fraction >= 0.35`；
- `close_location >= 0.70`。

含义是先实际测试预定支撑，再以正实体收复上沿并收在当日高位。单纯触及、锤子形状、
吞没或放量都不能独立产生计划。

### 5.3 量价的唯一候选扩展

`PRICE_PLUS_RVOL` 不是并联形态，而是给上述同一价格定义追加
`volume_T / median(volume[T-20:T-1]) >= 1.20`。volume 缺失或非正时 fail closed。
必须在运行任何新经济回放前，从 `PRICE_ACTION_ONLY` 与 `PRICE_PLUS_RVOL` 中选一个；
不得在同一暴露样本上比较后选择胜者。默认建议 `PRICE_ACTION_ONLY`，RVOL20 仅作诊断，
因为现有跨市场 volume 质量与口径没有 Entry 层 SSOT。

## 6. 从信号到实际成交

### 6.1 计划与 T+1 buy-stop

信号日 T 收盘后冻结：

```text
entry_trigger = signal_high
entry_ceiling = signal_high + 0.5 * ATR14(T)
valid_session = exact next completed market session only
```

执行日 E：

- `open > entry_ceiling`：`SKIP_GAP_ABOVE_CEILING`；
- `entry_trigger <= open <= entry_ceiling`：`actual_entry = open`；
- `open < entry_trigger` 且 `high >= entry_trigger`：`actual_entry = entry_trigger`；
- `high < entry_trigger`：`NOT_TRIGGERED`；
- 缺 exact E bar、非正/非有限 OHLCV、开盘已在 stop 以下：分别保留明确 skip reason；
- 不向 E+1 顺延，不假设信号 K 收盘成交，也不以信号 K 低点成交。

当 E 日同时出现 buy-stop、stop 与 target 触及而日线无法排序时，保守口径为“先视为
成交，再按 stop-first”；此歧义单独计数。

### 6.2 结构失效与执行止损

两类失效永远独立：

- `SETUP_STRUCTURAL_INVALIDATION = confirmed Wave2 Low`（close-based）；
- `WAVE_SCENARIO_INVALIDATION = LOW0`（close-based）。

执行止损候选包二选一：

`SIGNAL_SUPPORT_ATR_STOP`

- A：`min(signal_low, H1) - 0.25*ATR14(T)`；
- B：`min(signal_low, active_zone.lower) - 0.25*ATR14(T)`。

`WAVE2_STRUCTURAL_ATR_STOP`

- A/B：`Wave2 Low - 0.5*ATR14(T)`。

前者检验“信号 K / 被测试支撑失效就退出”，风险更紧但更易受噪声/跳空影响；后者给
价格更大空间但 1R、资金占用和尾部 gap 风险更高。两者不可在看到收益后逐笔择优。

### 6.3 止损距离与最小手数

- `stop >= actual_entry`、risk/share 非有限或非正：不可执行。
- 记录 `stop_distance_pct` 与 `stop_distance_ATR`；`<0.5 ATR`、`0.5–1.5 ATR`、
  `1.5–3 ATR`、`>3 ATR` 只作预注册 strata，不在本轮暗设新门槛。
- 使用冻结 research budget 与市场合法最小数量向下取整；不足一手/一股为
  `NOT_EXECUTABLE_MIN_QUANTITY`。不得缩小 stop 来制造仓位。
- CN 必须使用 point-in-time board/ST/lot/price-limit 元数据；不能把全 A 股统一假设成
  100 股。US 默认 whole share，除非协议另有 broker-specific fractional-share 证据。

### 6.4 市场执行差异

- CN：买入当日不可卖出。E 日若模型判定 stop/target 同日触及，只记录
  `ENTRY_DAY_STOP_BREACH_PENDING`，最早下一 session OPEN 处理；涨跌停、停牌、队列不可
  由 daily OHLCV 证明，缺 point-in-time 证据时为 `BLOCKED_MARKET_MICROSTRUCTURE_DATA`。
- US：允许同日退出，但 daily OHLC 无法排序时仍使用 stop-first；halt、spread、slippage
  必须来自预注册数据或情景假设，不能声称是真实 fill。

## 7. Target 与退出

### 7.1 T 日冻结目标

先生成目标，再计算任何 R/R。候选仅包括：

1. 截至 T 已确认、价格高于 `entry_ceiling` 的 Swing highs（包括合法的 post-breakout
   confirmed swing high）；
2. 既有 Wave1 range 从 Wave2 Low 投射的 1.272/1.618/2.0/2.618 extensions，且价格
   高于 `entry_ceiling`。

按价格升序、同价合并 provenance，前三个为 T1/T2/T3。H1 在突破后是支撑/路径路由
水平，不是上方 target。running high 不是 confirmed Swing，不能用其事后 Fib extension
制造目标。执行日若实际入场已不低于冻结 T1，直接 `SKIP_NO_REMAINING_TARGET`，不得改用
T2 绕过最近目标。

### 7.2 研究退出候选包

必须在经济验证前二选一：

- `X1_MECHANICAL_T1_EXIT`：active stop 优先；T1 intraday touch 后按 T1 全退；gap above
  T1 仍按 T1；结构 close failure 下一 OPEN；60-session time exit 下一 OPEN；同日 stop
  与 target 为 stop-first。这是 research-only，明确不同于正式 Position Management。
- `X2_FORMAL_PM_COMPATIBLE_EXIT`：把实际 entry/initial stop/targets 映射为冻结
  `PositionOrigin`，复用正式 higher-low/MFE/structural exit；targets 只作状态、不自动卖。
  60-session 只形成右删失，不强退。它更接近正式语义，但更容易产生不对称删失。

两者不得在结果出现后选择；若协议同时报告另一包，只能作为预注册 sensitivity，不能
替换 primary classification。数据末端未完成的一律右删失，单独报告 final-close valuation，
不得混入 realized primary metric。

## 8. 5% / 2R 机制审查

任何事件必须按五层记录，避免把“形态成立”和“最终可交易”混为一体：

```text
A  price_action_signal_valid
B  executable_stop_valid
C  nearest_valid_target_headroom
D  costs / stop distance / RR / quantity feasibility
E  research_trade_admitted
```

### `G0_INCUMBENT_HARD_GATES`

- A/B/C 形成后，以最坏允许入场价 `entry_ceiling` 检查 T1 gross upside >=5% 和 T1
  RR>=2；执行日再以 actual entry 重检；任一失败不交易。
- 优点：与现行纪律可比、拒绝空间小或 stop 过宽的计划。
- 风险：5% 是绝对价格百分比而非波动/成本尺度；2R 强依赖所选 stop；两者可能把
  “信号是否有效”与“几何是否合适”混成同一个稀疏门槛。

### `G1_SIGNAL_FIRST_DIAGNOSTIC_GATES`

- 固定 5% 与 2R 只作为 diagnostic/strata，不阻断 A/B；最终准入仅要求结构未失效、
  stop 有效、T1 高于 actual entry、成本/数量可计算及市场可执行。
- 优点：能独立测量信号质量、stop 经济性和剩余 target space，不会为了过门槛延伸 T1
  或缩小 stop。
- 风险：会纳入低 headroom/低 RR 交易，成本后可能缺乏经济空间；若未来用于生产，必然
  需要另一个长期 Risk/Decision 治理决策。

本次不得删除正式 5%/2R。独立验证前必须选一个 primary gate role；另一个若保留，只能
作预注册嵌套归因，路径 A/B 仍分别报告，禁止比较多套阈值后挑赢家。

## 9. 样本暴露审计与独立验证边界

### 9.1 已暴露、不得重新命名为独立样本

| 样本/资产 | 已用于 | 身份 |
|---|---|---|
| Development dataset v2（40 symbols / 84,284 bars） | SETUP_03 structural development；SETUP_01/02 development 相关能力 | `DEVELOPMENT_EXPOSED`, `NOT_FINAL_OOS` |
| Phase 5J-v3 development holdout（40 / 86,305） | SETUP_03 event/lifecycle；SETUP_01/02 signal-scarcity、post-confirmation retest、pre-confirmation early-entry 等 | `DEVELOPMENT_EXPOSED`, `NOT_FINAL_OOS` |
| early-entry clean-holdout roster（20 CN + 20 US / 88,075 bars，2017-01-01..2026-08-26） | ARMED early-entry 第一阶段、第二阶段决策，且 #110 第二阶段经济验证 | 已暴露 independent-by-symbol 样本，不再 fresh |
| A1 formal 120 roster / SETUP_03 manifests | universe/structural protocol 设计与边界核对 | 不得自动转作本机制独立经济样本 |
| #104 prospective daily reports | exact-T 前瞻 funnel 与日常观察 | 观察数据；除非协议锁定后前瞻收集，否则不是历史独立回放 |

Final OOS 未建立、未访问，本协议也不授权建立或访问。

### 9.2 独立数据选项

运行前必须二选一，不得在看到信号数后换样本：

- `D1_PROSPECTIVE_TIME_ISOLATED`：先冻结 CN/US roster、所有决策与成本快照，从协议批准后
  的首个完整交易日开始前瞻收集固定 12 个月。时间隔离最强，但等待时间长、事件数可能
  不足；不足只得 `INSUFFICIENT_EVIDENCE`。
- `D2_NEW_SYMBOL_DISJOINT_HISTORICAL`：新建各至少 60 symbols 的 CN/US roster，与上述
  所有已暴露 roster 做 symbol-level 空交集；固定 2017-01-01..2026-08-26 窗口，先冻结
  roster/hash 再抓取 OHLCV。可较快完成，但市场 regime 与已暴露研究重叠，且免费源存在
  survivorship/point-in-time board metadata 风险。

如选择 D2 但不能取得 point-in-time constituent、board/ST、corporate action、交易日和
费用数据，应升级为“付费 point-in-time 数据需求”，而不是降低完整性。任何购买供应商的
选择与预算需用户另行批准。

数据与快照要求：

- CN OHLCV/QFQ：BaoStock 或经独立批准的 point-in-time vendor；US OHLCV：yfinance 仅
  可作免费 research feed，corporate-action/退市覆盖不足必须披露。
- universe snapshot、symbol normalization、raw payload、normalized bars、session set、
  cost schedule 均在读取信号前冻结；canonical JSON 使用 LF-normalized SHA-256；payload
  与 manifest cross-bind，禁止失败后替换 symbol/provider/window。
- CN/US 分母独立，市场不得互相补足；成本快照按有效日期记录官方税费与用户 broker
  rate。无 broker rate 时只能使用预注册 baseline/stress bp 情景并标记 assumption。

## 10. 预注册漏斗、指标与判定

每个市场、每条路径独立保留：

```text
all causal Wave2 contexts
 -> first H1 breakout
 -> observable after breakout
 -> A/B legal signal K
 -> Entry Plan
 -> exact next-session model-executable
 -> completed exit | right-censored
 -> gross and net economic result
```

必须保留 no breakout、no observation、no retest、touch-without-signal、signal-without-trigger、
gap skip、market-data blocked、stop invalid、min-quantity blocked、failed、timeout 与 censored。

预注册 primary metrics（A/B 各自按 CN、US、pooled 报告）：

- lifecycle opportunity count、signal count、plan count、execution count、complete/censored；
- gross/net R 与 gross/net return 的 mean、median、p10/p25/p75/p90、worst；
- losing share、`<=-1R` share、gap loss、holding sessions、notional 与 capital-time；
- stop-distance pct/ATR、T1 headroom、RR、5% flag、cost/R；
- symbol/sector/time-half concentration，drop-leading-symbol sensitivity；
- baseline/stress costs、same-bar ambiguity 与 final-close censoring sensitivity。

证据下限建议预注册为：每条路径每市场至少 40 completed trades、至少 8 contributing
symbols、censored share <=10%、单一 symbol share <=25%。低于任何 floor 为
`INSUFFICIENT_EVIDENCE`，不得把两条路径合并凑分母。

路径结论分别为 `SUPPORTED`、`NOT_SUPPORTED` 或 `INSUFFICIENT_EVIDENCE`。双路径总状态只可
是 `BOTH_SUPPORTED`、`CONTINUATION_ONLY_SUPPORTED`、`RETEST_ONLY_SUPPORTED`、
`NEITHER_SUPPORTED` 或 `INSUFFICIENT_EVIDENCE`；合并统计不能掩盖任一路径失败。

## 11. READY_FOR_DECISION：需要用户选择的五项

1. `SIGNAL_PACKAGE`
   - A: `PRICE_ACTION_ONLY`（建议；量能仅 diagnostic）
   - B: `PRICE_PLUS_RVOL`（相同价格条件 + RVOL20>=1.20）
2. `OPPORTUNITY_POLICY`
   - A: `ONE_SHOT_EARLIEST_SIGNAL`：最早合法信号产生一次计划，未成交也结束观察；最干净。
   - B: `ONE_PER_PATH_UNTIL_FILL`：A 未成交后仍可在实际回踩时给 B 一次机会；最多两个计划、
     仍最多一笔成交，20-session 总窗口不重置。
3. `EXECUTION_STOP_PACKAGE`
   - A: `SIGNAL_SUPPORT_ATR_STOP`：路径语义最完整、风险较紧、噪声敏感。
   - B: `WAVE2_STRUCTURAL_ATR_STOP`：结构容忍更大、资金占用和尾部风险更高。
4. `PRIMARY_EXIT_PACKAGE`
   - A: `X1_MECHANICAL_T1_EXIT`：完整可实现经济结果，但与正式 target-only-diagnostic 不同。
   - B: `X2_FORMAL_PM_COMPATIBLE_EXIT`：更接近正式管理，但 censoring 风险更高。
5. `GATE_ROLE_AND_DATA`
   - A: `G0_INCUMBENT_HARD_GATES` + D1/D2；保持 5%/2R 硬门槛。
   - B: `G1_SIGNAL_FIRST_DIAGNOSTIC_GATES` + D1/D2；5%/2R 仅诊断，任何未来生产化需新长期决策。

在这五项被明确选择、成本/市场数据来源可用、JSON 状态从 `DRAFT_NOT_EXECUTABLE` 升级前，
不得运行新经济回测。选择必须先提交并冻结，再读取新样本信号或收益。
