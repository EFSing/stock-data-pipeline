# TRADING_SYSTEM_SPEC.md — 交易系统长期稳定规则

本文件保存长期稳定的交易规则，是所有 AI 开发工具共享的规则事实来源。**未经明确决策不得擅自改动**；任何改动必须写入 `DECISION_LOG.md`。

## 核心交易框架

```text
Sector / Industry Universe
→ Tradable Candidate Selector
→ Candidate Universe
→ 数据质量
→ 周线趋势
→ 日线趋势
→ Swing
→ 波浪候选
→ Fibonacci
→ Setup
→ Entry
→ Invalidation
→ Target
→ Risk/Reward
→ Position Size
→ Portfolio Risk
→ Position Management
→ Exit
```

## Candidate Universe 边界

Candidate Universe 是完整 Strategy Chain 之前的可交易候选筛选层。它按 sector /
industry 保留候选，并可使用 affordability、流动性、历史可用性和轻量技术可分析性
做 fail-closed gate；它只决定标的是否进入完整策略分析，不产生
`ENTRY_ALLOWED`、`STRATEGY_PROPOSAL` 或买入信号。候选层不得改变 frozen Wave、Swing、
SETUP_01、SETUP_02、Entry、Stop、Target、RR、T→T+1 或 Portfolio Risk 语义。

正式 V1 身份为 `BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1`。CN seed universe 是
`HS300 ∪ CSI500`，优先复用 BaoStock 的 `query_hs300_stocks`、
`query_zz500_stocks`、`query_stock_basic` 和 `query_stock_industry`；不构建全 A 股
security master。US seed universe 是 iShares Russell 1000 ETF (`IWB`) 官方公开
`latest-holdings.csv`，使用其中的 ticker、sector、asset-class、price、exchange 和
currency；不在 V1 构建 SEC/Nasdaq 全量 security master，也不引入 commercial provider。

V1 的 CN affordability 使用证券 board 的已证明 minimum executable quantity：真实
最小可交易单位 notional `<= 10,000 CNY` 为 preferred，`10,000 < notional <= 20,000
CNY` 可保留但降低优先级，`> 20,000 CNY` 排除。board rule 无明确官方证据时
fail closed；不得把全部 A 股统一写成 100 股。US candidate stage 排除一股 notional
`> 1,000 USD`；最终单个新 strategy position 的 `1,000 USD` hard cap 仍必须在
allocation / position sizing 边界再次验证，二者不是同一层。

Candidate selector 先做 security/sector normalization、affordability gate、history /
data-quality gate，再按 sector 内 20D/60D average traded notional（成交额缺失时用
`close × volume`）排序并应用集中可调的 `TOP_N_PER_SECTOR = 20`。该数值不进入
Strategy Engine protocol；seed 本身承担第一层流动性边界，V1 不拍脑袋新增跨市场绝对
liquidity threshold，也不伪造 bid/ask spread。candidate 输出只保存轻量 internal
rows/fixture/artifact，不写 production Google Sheets。

## 基本原则

```text
基本面决定是否值得长期做多
周线决定大级别状态
日线决定执行节奏
Swing决定结构
Fibonacci决定候选价格区域
量价决定确认
Invalidation决定哪里认错
R/R决定值不值得交易
1R决定最大计划亏损
MFE负责利润保护
```

- 不能使用单一 RSI、MACD、Fib 等指标直接产生买入信号。
- 系统必须允许输出 `NO_TRADE`。

## 波浪理论

采用「主情景 + 备选情景」，不武断输出唯一浪型。

例如：

```text
主情景：
Weekly Wave 3 Candidate

备选情景：
ABC B-Wave Candidate
```

需要记录：

- 支持证据
- 反方证据
- 置信评分
- Invalidation
- Target

如果证据不足，输出 `UPTREND_UNKNOWN_WAVE`，不要强行数浪。

## 周线与日线

必须遵循：

```text
Weekly State → Daily State
```

周线决定母级别。日线不能因为一两天价格波动随意推翻周线浪型。

## 第一版只允许四类 Setup

```text
SETUP_01  Wave 2 → Wave 3
SETUP_02  Wave 3 Continuation
SETUP_03  Platform Breakout
SETUP_04  Extreme Fear Reversal
```

RSI 超卖只能使 `SETUP_04` 进入观察状态，不能直接产生买入信号。

## Setup 状态

```text
NONE
WATCH
ARMED
CONFIRMED
ACTIVE
FAILED
COMPLETED
```

未确认的 Setup 不得输出 `ENTRY_ALLOWED`。

## Entry

至少输出：

```text
Entry Zone
Probe Entry
Confirmation Entry
Confirmation Conditions
```

## Invalidation

区分：

```text
Structural Invalidation
Execution Stop
```

- 结构失效来自 Swing、Wave Low、突破结构等。
- Execution Stop 可以加入 ATR Buffer。

## Target

至少：

```text
T1
T2
T3
```

目标来自：

- 前高
- 关键压力
- 周线结构
- Fibonacci Extension

必须：**先计算合理 Target，再计算 R/R。** 禁止为了满足 3R 倒推目标价格。

## Risk / Reward

多头：

```text
RR = (Target - Entry) / (Entry - Stop)
```

初始规则：

```text
RR < 2     → NO_TRADE
2～3R      → NORMAL
3～5R      → HIGH_QUALITY
>5R        → HIGH_ASYMMETRY
```

大于 5R 时必须检查目标合理性。

## 1R

1R 不是止盈。1R 是「单笔最大计划损失」。

冻结语义：`allocation_budget` 是用户明确授权给该账户整个策略风险账本的总策略预算，
不是 broker NAV / 账户净值。

```text
Risk Per Trade = 0.5% allocation_budget
```

仓位：

```text
Position Size = Risk Capital / |Entry - Execution Stop|
```

## 持仓管理

至少记录：

```text
Current R
MFE
MAE
MFE Drawdown
```

动作：

```text
NO_TRADE
WATCH
WAIT_CONFIRMATION
PROBE_ALLOWED
ENTRY_ALLOWED
ADD_ALLOWED
HOLD
NO_ADD
PROFIT_PROTECTION
REDUCE
EXIT
```

必须专门识别高位风险：

```text
Wave 5 Candidate
+ Fib Target
+ 异常高成交量
+ 价格滞涨
+ 长上影
+ Momentum Divergence
```

高位异常放量不能默认解释为洗盘。

## 前瞻模拟交易跟踪 V1

Paper Tracking 是 production Decision 之上的独立、前瞻、逐事件投影层，不改变
总体策略主线，也不把 Candidate-only 晋级为正式策略池。只有新 `CONFIRMED` event
与既有 SETUP_01/SETUP_02 `ENTRY_ALLOWED` Decision 才能在显式 `--paper-track` 下
创建 Paper plan。`AUTO_APPROVE_FOR_PAPER_TRACKING` 和
`AUTO_APPROVE_TECHNICAL_ENTRY_ALLOWED` 只代表技术条件满足模拟纳入，不代表正式
批准、组合风险授权、账户资金收益或券商执行。

Paper 生命周期必须使用 exact T+1 OPEN、已有 `PositionOrigin` 与现有
Position Management replay；Target reached 只表示目标状态与风险管理上下文，
不等于自动止盈。`策略模拟账本` 独立于策略决策状态、策略股票池、策略持仓和行情
Sheets，以 append-only lifecycle events 记录计划、执行／跳过、结束与覆盖。统计以
单笔 normalized R、return %、持有天数、MFE/MAE 为主，不计算组合 P&L；Paper
Tracking forward-only，Candidate-only 计划在掉出 Candidate 后仍需由既有 exact QFQ
路径续载，若缺少连续数据则 fail closed 并提示 coverage gap。

## 未来函数（最高等级技术风险）

严格保证：

```text
signal(t) 只能使用 data <= t
```

尤其注意：ZigZag、Swing High、Swing Low、Pivot、Weekly Resampling、Close、Volume。

Swing 必须区分：

```text
PROVISIONAL
CONFIRMED
```

回测时禁止拿未来确认的 Swing 回填过去交易信号。

## 开发优先级

```text
Phase 0  Repository Audit
Phase 1  Data Quality / Indicators / Swing / Market Structure / Fibonacci / R/R / Position Size
Phase 2  Setup Engine
Phase 3  Decision Engine
Phase 4  Google Sheets Decision Tables
Phase 5  Wave Scenario Engine
Phase 6  MFE / MAE / Position Management
Phase 7  Backtest / Expectancy
```

Swing、Market Structure、Risk Engine 必须首先稳定；不要先花大量时间做复杂 Elliott Wave。
