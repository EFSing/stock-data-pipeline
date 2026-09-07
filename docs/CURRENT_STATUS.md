# CURRENT_STATUS.md — 系统当前能力地图

> 职责：回答“系统目前已经具备什么能力，哪些仍在研究／未接入生产”，让新设备或新
> Codex 会话在读完本文件后快速建立整个系统的能力画面。
> 本文件不保存历史 PR 过程、blocker 演变、测试数量、CI run ID、commit SHA 或
> Engineering Event 流水账；动态工程事实以 Git / GitHub 实时状态为准。
> 最后实质更新：2026-09-06（治理体系瘦身）。

## 项目身份

- 长期总体交易框架的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`，主线为：
  `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup →
  Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 项目版本基线：`V0.2`（行情抓取、双源校验、Sheets 写入已完成；决策与
  production 链仍在分阶段推进）。
- 本项目不是单一 Platform Breakout 系统。第一版四类 Setup：
  `SETUP_01` = Wave 2 → Wave 3；`SETUP_02` = Wave 3 Continuation；
  `SETUP_03` = Platform Breakout；`SETUP_04` = Extreme Fear Reversal。
  `SETUP_03` 只是其中一个子策略，其开发深度或研究阶段不改变总体路线；
  Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 跨设备恢复现场、治理文件职责与 docs-only 验证规则见 `AGENTS.md` 与根目录
  `HANDOFF.md`。

## 能力清单

### 行情与数据质量（已生产运行）

- 定时行情流水线：`asia-close`（CN/HK/JP）与 `us-close`（US/SE）两个 GitHub
  Actions workflow 按市场收盘时间调度，运行 `main.py --mode latest`。
- `latest` 模式只抓取短窗口最新行情、执行 source-date evidence、双源校验与
  ordinary-calendar freshness guard，写入 `最新行情`、`校验记录`、`运行日志`；
  不抓取多年历史／qfq，不运行策略路径，`history_rows_written=0`。
- 数据源回退链稳定：主源 yfinance（含无 cookie Yahoo Chart 回退）、BaoStock
  （CN）、Tencent / Sina 快照回退；AKShare 已从生产依赖移除，仅保留遗留别名路由。
- 收盘语义固定：`交易日期` = 市场真实 session date，`抓取时间` = 北京时间，
  两者不可互换；未来日期 fail closed；未完成 session / 非正式收盘不得标记已验证。
- 前复权（qfq）只允许 yfinance / BaoStock；生产 QFQ 刷新由
  `scripts/refresh_production_qfq.py` 在 scheduled latest 成功后执行，失败 fail
  closed。
- 数据质量核心（`core.py`）提供 Quote / ValidationResult、双源容差校验、freshness
  guard、session-date 推导、OHLCV sanity；只依赖标准库，供所有上层复用。

### 持仓数据生命周期与 holdings 操作（已生产运行）

- `latest_snapshot.py` 是 scheduled latest 与持仓生命周期共享的 evaluator /
  row-projection 单一事实源，禁止维护第二套 latest pipeline。
- `skills/holdings-data-manager`（薄 contract）+ `holdings_data_manager.py`：
  单一标的 `ADD` / `REENTER` / `CLOSE` / `SYNC`，自然语言只解析为唯一操作；
  以最近已完成 market session 为界补 raw/qfq 缺口；enable-last、幂等重试、
  `CLOSE` 不删除历史；覆盖/QC 只依赖 observed session dates。
- GitHub Issue command bus（`[HOLDINGS_COMMAND]`，严格 JSON v1）已启用 live
  route：job-level repository/actor/sender/Issue-user guard、非取消并发组、live
  step 才注入既有 Google Secrets；已记录首条真实 `ADD 512400`（CN，
  `history_rows_written=480`）成功。该路径只操作行情覆盖与 watchlist 身份，
  不进入策略 / 决策 / 研究语义。

### Candidate Universe（已实现，未接入生产策略链）

- `trading/candidate_universe_sources.py` + `candidate_universe.py`：
  CN seed = `HS300 ∪ CSI500`（BaoStock basic/industry）；US seed = iShares
  Russell 1000（IWB）official holdings。
- 输出 affordability tier（CN `<=10,000` preferred / `<=20,000` retained；
  US 一股 `>1,000 USD` 排除）、20D/60D traded-notional 流动性 proxy、
  history/data-quality gate、sector-aware `TOP_N_PER_SECTOR=20` 与
  included/excluded 审计行。
- Candidate 层不产生 `ENTRY_ALLOWED`、`STRATEGY_PROPOSAL` 或买入信号；尚未接入
  正式每日 production Strategy / Daily Decision Chain。

### 策略核心计算层（Wave / Swing / Structure / Fibonacci）

- Swing：causal confirmed / provisional pivot 状态机，禁止事后 ZigZag 回填；
  历史决策只能使用 `confirmed_index <= t` 的 Swing。
- Weekly / Daily：Wave Scenario Engine v1 内部以严格 as-of 聚合 weekly parent
  与 daily context，不把未完成 ISO 周计入母级状态；未来 bar 追加不改写历史结果。
- Wave Scenario Engine v1：有限 primary/alternate 情景（`WAVE_2_TO_3_CANDIDATE`、
  `WAVE_3_CONTINUATION_CANDIDATE`、`ABC_CORRECTION_CANDIDATE`、
  `UPTREND_UNKNOWN_WAVE`、`DOWNTREND_OR_INVALID_FOR_LONG`、`NO_VALID_SCENARIO`），
  带证据 / 反证、结构失效与 SETUP_01/02 context eligibility；
  `scripts/run_wave_shadow.py` 提供只读 holdings shadow。
- Fibonacci：`trading/fibonacci.py` 是纯几何 single source；引擎只将其转为描述性
  候选区域，不作为独立信号。

### SETUP_01（Wave 2 → Wave 3）

- 独立 structural evaluator + strict as-of replay（`trading/setup01*.py`）：
  `NONE → WATCH → ARMED → CONFIRMED/FAILED`；只接受 primary
  `WAVE_2_TO_3_CANDIDATE`，确认需日线 close 严格高于 Wave 1 peak；
  结构性失效与 trade-structure 失效分开。
- Decision/Risk v1 已实现并合并：first-entry `CONFIRMED` exactly-once、
  T close 只形成 plan、最早 T+1 session `OPEN` 执行、Target-before-RR、
  `actual_entry != None ⇔ outcome == EXECUTED`。
- 有 generic synthetic operational shadow 与 development-only replay evidence；
  尚未接入生产自动执行（生产日历集成是已登记前置条件）。

### SETUP_02（Wave 3 Continuation）

- 独立 structural evaluator + replay（`trading/setup02*.py`）：只接受 primary
  `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`，要求因果
  `LOW0→HIGH1→LOW2→HIGH3`、`HIGH3>HIGH1`、`LOW2>LOW0`、weekly/daily UPTREND；
  recovery 与确认阈值固定，终态事件仅首次进入发出一次。
- Decision/Risk v2 已实现并合并：target 几何固定为
  `LOW2 + (HIGH1−LOW0) × EXTENSION_RATIO`（source=`WAVE3_FIB_EXTENSION`），
  filter `target > planned_entry` 后按升序 T1/T2/T3 再做 R/R；
  旧 `structural_invalidation → HIGH3` 投影因数学上与最小 R/R 不兼容已被废弃。
- 有 generic synthetic operational shadow 与 development replay；尚未接入生产
  自动执行。

### SETUP_03（Platform Breakout）

- 现状一句话：**研究主线已停止在
  `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`，formal validation 未执行，未选择任何
  production tolerance；legacy 手动 full 路径仍保留**。
- Legacy / 研究路径：`main.py --mode full`（仅 workflow_dispatch 手动选择）保留
  SETUP_03 replay/Decision 与 `交易决策` Sheet 事件发布；`trading.events` 统一
  终态事件语义，仅发布首次 `CONFIRMED`。
- 正式研究：参数冻结审计结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`；
  Phase 5J 结构验证 protocol（v1/v2/v3/v4/v5 相关 machine-readable JSON）已注册
  并冻结，正式 production tolerance 候选仅 `3.0% / 4.0% / 5.0%`，
  `lookback=5`、`window=40` 只作为 incumbent constants；
  qualification matrix 已冻结但未执行 formal validation；第二套
  development holdout 与 lifecycle attribution 均为 `RESEARCH_ONLY`，
  `qualified_candidates=[]`。
- ATR-normalized boundary 实现保留为 `RESEARCH_ONLY` /
  `NOT_PRODUCTION_AUTHORIZED` / `FAILED_STRUCTURAL_CANDIDATE_FAMILY`，不进任何
  production 入口。
- Formal validation dataset 获取 contract（Phase 5K-B0 v2）已冻结但未获取；
  Final OOS 未建立、未读取。Frozen artifact 恢复治理见
  `docs/FROZEN_ARTIFACT_POLICY.md` 与 `docs/FROZEN_ARTIFACT_REGISTRY.json`。

### SETUP_04（Extreme Fear Reversal）

- 未实现。

### Daily Decision Chain（已实现，人工触发只读生产报告）

- `trading/daily_decision_chain.py` 是只读 prospective orchestration：将 frozen
  Wave、SETUP_01/02 Decision/Risk、Portfolio Risk、Position Management、Wave5
  组合为单账户日决策链，可发 T 日 prospective Decision，但不下 broker order，
  也不把机械 T+1 ledger 观察当成真实成交。
- 生产运行要求正式 `策略股票池` universe、显式 `allocation_budget`（不读取 NAV
  替代）、risk-group metadata、authoritative position origin、exact
  exchange-calendar session 与持久
  `DecisionStateStore`；缺失时 fail closed。`scripts/run_production_daily_decision.py`
  提供 `--preflight` 与默认只读 `--run`；只有显式 `--write-state` 才追加
  系统-owned `策略决策状态`，并可用显式 `--approve-event`、
  `--allocation-budget ACCOUNT_ID=AMOUNT` 完成人工在环输入。

### Portfolio Risk（已实现并合并，未自动生产运行）

- `PORTFOLIO-RISK-2026-09-02-v1`：独立、conservative、fail-closed 的 downstream
  capacity gate，只消费 individual `ENTRY_ALLOWED`。
- 冻结常量：`BASE_RISK_FRACTION=0.005`、`MAX_TOTAL_OPEN_RISK_FRACTION=0.02`、
  `MAX_RISK_PER_GROUP_FRACTION=0.01`；risk group 只来自可靠 metadata，不猜 NAV、
  不做相关性推断、不缩放 stop。
- 风险语义修正为 remaining capital-loss risk：
  `max(actual_entry − active_protective_stop, 0) × quantity / reference_nav`；
  `current_price` 不参与 capacity；stop-raise / exit 释放 capacity；
  gap/slippage tail risk 明确不在框架内。
- `allocation_budget` 是用户授权给该账户整个策略风险账本的总预算，不是 NAV /
  账户资产 / P&L；预算不等于 approval，approval 只按已发布 proposal 的 event
  identity 匹配。
- 有 generic synthetic operational shadow 与 frozen development replay；
  account-isolated production run 未自动启用。

### Position Management / Exit / Wave5（已实现并合并）

- `trading/position_management.py` 只消费 SETUP_01/02 的 `EXECUTED` rows；origin
  geometry、actual entry、initial stop、targets、Wave anchors、one-R 不可变。
- 提供 current R/MFE/MAE、MFE drawdown、confirmed-higher-low trailing、monotonic
  2R/1R MFE floor、next-session mechanical stop/structural exit、target reach、
  Wave4/Wave5 context 与 advisory actions；Wave5 不能强制全退或新建 entry。
- Exit 语义在 `trading/events` / position replay 中与 Portfolio Risk 分开；
  不计算 win rate / aggregate P&L / expectancy / Sharpe，不读取 Final OOS。

### Production wiring（部分运行）

- Google Sheets V1 五个正式契约已落地：`策略账户`、`策略股票池`、`策略风险分组`、
  `策略持仓`、系统-owned `策略决策状态`；`自选清单` 仍只是行情覆盖事实源。
  `策略股票池` 才是 formal strategy universe。
- `SheetsDecisionStateStore` 是 V1 persistent store（typed canonical JSON、
  account-scoped、append-only compound protocol、默认 read-only）；production
  adapter 支持 account-isolated risk books（CN=CNY/XSHG、US=USD/XNYS）与 exact
  session proof（`exchange_calendars`）。
- 已具备严格只读 `--preflight` 与默认只读的人工 `--run` 报告；正式 daily
  chain 的 stateful `--run` 需要显式 `--write-state`，且当前没有自动 workflow
  调用。生产 strategy state 写入、scheduled decision chain、broker order 尚未
  自动启用；holdings 行情路径（上表）是已运行的例外。

- 现有 `HiThink Financial API（同花顺金融数据服务）` 仅完成有界 CN transport
  smoke：ticker/index constituents、market-dump signing、corporate-action
  adjustment events、calendar；尚未证明财务报表字段契约、复权公式/as-of
  语义或长历史覆盖。因此本 V1 不依赖、不接入 HiThink；后续可在单独验证后
  作为 CN fundamentals/metadata 或 Candidate 辅助源，不能把它描述成已验证的
  iFinD 替代品。当前生产链仍使用正式 `策略股票池` 与现有已验证的 QFQ 数据边界。

### Broker execution

- 未连接券商；无 order submission、IBKR、自动下单路径。任何“机械回放成交”不得
  声称是 broker execution。

## 研究中的能力 / 明确未接入生产

- Candidate Universe：未接入 production strategy chain。
- SETUP_03：structural development stopped；formal validation 未执行；无 production
  tolerance 选择；Phase 5K-B0 dataset 未获取；Final OOS 未建立。
- SETUP_04：未实现。
- Daily Decision Chain / Portfolio Risk / Position Management：策略语义已实现并
  frozen，已支持人工触发的 account-isolated 只读生产报告，但未作为每日自动
  production 决策链运行。
- 真实账户持仓 shadow 属 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时
  status=`NOT_RUN_USER_PRIVACY`；缺少真实持仓不是 SETUP_01 等核心开发 blocker。

## 长期不变量（任何开发不得违反）

- `signal(t)` 只用 `data <= t`；禁止未来 Swing / ZigZag 回填、look-ahead、OOS
  泄漏、按结果改样本或人为制造 Target / R/R。
- T→T+1 execution semantics；Target-before-RR；Wave 主／备情景；
  CN / US runtime 独立。
- 凭证只经 GitHub / Codespaces Secrets 或本机环境变量注入；真实持仓与
  holdings-derived 数据不进 GitHub Actions；不自动连接券商下单。
- 策略公式与 risk 常数的 Single Source of Truth 在 `trading/` 代码与 protocol
  文件中；生产展示层与研究层不得复制交易逻辑。
