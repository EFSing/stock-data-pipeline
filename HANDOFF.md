# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## PROJECT STRATEGY IDENTITY

- 本项目不是单一 Platform Breakout 系统；长期总体策略的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`。
- 总体主线：`Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 第一版四类 Setup：`SETUP_01`（Wave 2 → Wave 3）、`SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、`SETUP_04`（Extreme Fear Reversal）。
- `SETUP_03` 当前只是正在研究的一个子策略；当前开发深度、commit 数量或 Phase 数量不改变总体策略或优先级。Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 任何总体路线变化都必须先取得用户明确批准，并记录在 `docs/DECISION_LOG.md`；本快照不复制完整策略规范，避免双事实源。

## 0S. Latest Engineering Event — CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1_RUNTIME_ACCEPTED

- 当前 Sol decision=`STRATEGY_HISTORY_RUNTIME_V1_MARKET_SPLIT_ACCEPTED`：CN/US 独立
  runtime；`--market all` 仅开发便利，不是 acceptance 标准。工作分支为
  `feat/candidate-strategy-shadow-bridge-v1`，substantive source head=`da88a8481df3ef09641b8bbddf46320fbf1db931`；
  未 reset、未丢失用户已有 Tushare gateway/probe/test 修改。PR #72 `OPEN / MERGEABLE`，不合并。
- runner 已支持 `--market cn|us|all --date YYYY-MM-DD`；每个市场独立 fetch、evaluate、
  summarize、fail，并固定输出九段 stage timings：seed/metadata、candidate short-history
  network、candidate selector、deep raw-history network、adj-factor network、QFQ construction、
  DailyDecisionChain、report construction、total；各段带 API requests、symbols、rows、
  usable/failed counts。
- CN `--market cn --date 2026-09-04`：`CANDIDATE_SUCCESS`、`runtime_acceptance=ACCEPTED`、
  `618.470s`；seed/usable/included=`800/797/513`；timings=`91.115/31.881/0.037/289.555/
  127.639/5.563/72.679/0/618.470s`；deep=`513/513`、`505,134 rows`、`105 requests`；
  adj_factor=`513/513`、`505,762 rows`、`109 requests`；exact-T/QFQ factor-change validation
  与 DailyDecisionChain `513/513` 通过。`SETUP_01 WATCH/ARMED=52/17`、`SETUP_02 WATCH/ARMED=8/11`、
  `STRATEGY_PROPOSAL=0`。
- US `--market us --date 2026-09-04`：`CANDIDATE_SUCCESS`、`runtime_acceptance=ACCEPTED`、
  `422.718s`；IWB seed/usable/included=`1018/1007/220`；timings=`2.933/291.389/0.058/
  84.943/0/0/43.396/0/422.718s`；deep auto-adjusted QFQ=`220/220`、`217,895 rows`、
  `3 requests`；`SETUP_01 WATCH/ARMED=9/3`、`SETUP_02 WATCH/ARMED=5/8`、
  `STRATEGY_PROPOSAL=0`；Candidate exclusions=`HISTORY_INSUFFICIENT:11`,
  `US_ONE_SHARE_NOTIONAL_OVER_1000:18`, `SECTOR_TOP_N_EXCEEDED:769`。
- CN final status=`NO_TRADE:513`，US=`NO_TRADE:220`，但报告保留 final_status/primary_action/
  setup states/primary Wave distributions及 WATCH/ARMED/STRATEGY_PROPOSAL symbol lists；0
  proposal 是合法结果。两个 runtime 均无 future/duplicate/stale、无 production state/Sheets/
  allocation/broker/order writes。`512400.SH` 仍只是 ETF reference，未增加 fund API。
- temporary Tushare-compatible gateway 仍是本地只读 shadow 的临时实现，不构成长期 production
  provider 决策；US 仍固定 IWB+yfinance。focused=`5/5`、full unittest=`618/618`、compileall、
  diff/secret checks 均通过。PR #72 exact-head CI：CI Test Gate=`34027505639`、Daily Decision
  Chain generic shadow=`34027505622`、Portfolio Risk generic shadow=`34027505600`，均成功。
  当前最终停止点为 `PR_FULLY_READY_FOR_SOL_REVIEW`；不合并。

`PR_FULLY_READY_FOR_SOL_REVIEW`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0R. Historical Engineering Event — READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME

- 当前工作分支为 `feat/candidate-strategy-shadow-bridge-v1`，真实远端 baseline 为
  `edb56d74c70415b407104f0de47ab29fca6ad506`；工作树中的 Tushare gateway/probe/test
  修改均保留，未 reset、未 checkout 丢失、未直接提交到 main；当前没有 PR。
- 已把当前 CANDIDATE bridge 扩展为两级 history：Candidate gate 仍为约 60 bars；只有
  Candidate included symbols 才进入 Strategy deep history。CN deep path 使用 temporary
  Tushare `daily + adj_factor`，固定 chunk=`5`，最多 1000 completed bars through exact T；
  US 使用 IWB official holdings + yfinance batch，Candidate short history 与 Strategy
  up-to-1000 qfq history 分开。一次 transient failure 只增加了一次固定 retry，不引入
  cache/database/concurrency framework。
- 真实 CN deep daily 的一次完整中间证据为 `513/513` symbols、`505,134` rows、`103`
  requests；`438/513` 为 1000 bars，短历史 symbol 只要达到 60 bars、last bar exact T、
  无 future/duplicate 即保留。该次在 CN factor chunk transient failure 后 fail-closed；
  后续 retry 版 combined run 超过约 30 分钟仍没有形成完整 CN+US summary，已停止，未伪造
  factor-change comparison、DailyDecisionChain full result 或 US result。
- 新增报告设计已分别统计 `final_status`、`primary_action`、SETUP_01/02 state、primary
  Wave scenario，并输出 WATCH/ARMED/STRATEGY_PROPOSAL symbol lists；但真实 full shadow
  尚未到可报告完整结果的阶段。当前 blocker=`READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME`。
- focused bridge/Tushare/Candidate tests=`20/20 OK`；full unittest=`616/616 OK`、compileall、
  `git diff --check` 通过；`local_tushare_config.py` remains ignored、tracked secret
  matches=`0`。production state writes=`NO`、Sheets writes=`NO`、allocation=`NO`、
  broker/order=`NO`。本轮没有新的长期策略决策，因此不新增 `DECISION_LOG` 条目；
  `CANDIDATE_BREADTH_V1_ACCEPTED` 保持不变。

`READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0Q. Latest Engineering Event — READY_FOR_DECISION_CANDIDATE_BREADTH

- 已停止并替代逐 symbol history 方案；真实 multi-code `pro.daily(ts_code="...")`
  probe 在 60 个 XSHG completed sessions 上全部成功：20 symbols=`1200 rows / 1.881s`，
  50=`3000 / 1.333s`，80=`4800 / 1.465s`；每个 probe `api_request_count=1`，
  `symbols_returned=requested`，latest=`2026-09-04`，missing/errors=`0/0`。
- CN HS300 ∪ CSI500 seed=`800` 使用固定 chunk=`80` 完成 Candidate short-history：
  `10` daily requests、`800 returned`、`797 usable`、`47,980 rows`、network path 约
  `16.647s`；`002155.SZ`、`300567.SZ`、`688072.SH` 各少于 60 bars，按既有
  `HISTORY_INSUFFICIENT` fail-closed，不作为 bulk contract failure。未运行 date-major
  fallback，因为 multi-symbol contract 已稳定。
- Candidate semantics 未变：`TOP_N_PER_SECTOR=20`；seed=`800`、history usable=`797`、
  preferred=`682`、extended=`55`、affordability excluded=`58`、unsupported board=`2`、
  history/data-quality excluded=`3`、sector=`65`、TOP-N excluded=`224`、最终 included=`513`。
- QFQ 仅在 included count 已知后执行。方案 A `pro_bar(adj="qfq")` 被 gateway 拒绝；方案
  B `daily + adj_factor` 选定。三支 CN equity (`000725.SZ`、`002156.SZ`、`000333.SZ`)
  与现有 BaoStock qfq path 只读交叉验证均通过：每支 `60/60` dates、`0` mismatch、
  最大相对差=`5.86e-06`、容差=`0.002`，并检查了样本 corporate-action boundary。
  正式配置参考中的 `512400.SH` 是 ETF，未返回该 stock daily/adj_factor contract rows，
  未将其混入股票公式验证。
- included=`513` 的 QFQ factor bulk=`7` requests、`30,780` factor rows、`513/513` exact
  `adj_factor(T)` anchors；公式固定为 `raw_price(t) * adj_factor(t) / adj_factor(T)`，
  未构造 cache/database/concurrency framework。随后只读 DailyDecisionChain=`513/513`，
  final status 全为 `NO_TRADE`；production state/Sheets/allocation/broker/order=`NO`。
- 验证：focused=`17/17 OK`，full unittest=`613/613 OK`，compileall 与 `git diff --check`
  通过。当前停止点为 `READY_FOR_DECISION_CANDIDATE_BREADTH`；无策略语义、provider fallback、
  production state 或订单修改。

`READY_FOR_DECISION_CANDIDATE_BREADTH`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0P. Latest Engineering Event — TUSHARE_GATEWAY_RUNTIME_PROBE_SUCCESS_BUT_HISTORY_RUNTIME_NOT_BOUNDED

- 按用户要求新增临时、只读 Tushare gateway：`trading/tushare_gateway.py`，配置唯一从
  项目根目录 `local_tushare_config.py` 读取；缺失或未填写时 fail closed 为
  `TUSHARE_LOCAL_CONFIG_REQUIRED`，不使用 PowerShell 环境变量、不静默 fallback。
- `local_tushare_config.py` 已加入 `.gitignore`，可提交模板为
  `local_tushare_config.example.py`；真实配置值不进入 Git、测试、日志、HANDOFF 或
  CURRENT_STATUS。商家要求的 `ts.pro_api` 初始化及两个私有字段赋值已原样保留。
- 新增 runner：`scripts/run_candidate_strategy_shadow_bridge_v1_tushare_probe.py`。
  真实显式 CN smoke=`3/3 DATA_OK`、`375` rows、约 `7.641s`；CN candidate seed
  bounded sample=`20/20 DATA_OK`、`2500` rows、Tushare history request path
  `32.695s`，单标的约 `1.5–2.6s`。两次均 `read_only=true`、production state write=`NO`、
  broker/order=`NO`。
- 当前仍不宣称 800 标的 full shadow：按 20 标的顺序请求实测外推约 `21.8` 分钟，尚未
  证明日常 shadow budget 内 bounded；当前 blocker 更新为
  `TUSHARE_GATEWAY_RUNTIME_PROBE_SUCCESS_BUT_HISTORY_RUNTIME_NOT_BOUNDED`。没有伪造
  included/per-sector/strategy 结果，也没有把 Candidate Universe 接入 production Strategy
  Engine。
- 验证：Tushare/candidate focused=`13/13 OK`，full unittest=`609/609 OK`；依赖
  `tushare>=1.4.29,<2` 已加入 `requirements.txt`。本轮无 production state、Sheets、
  holdings、broker/order 或策略语义修改。

`TUSHARE_GATEWAY_RUNTIME_PROBE_SUCCESS_BUT_HISTORY_RUNTIME_NOT_BOUNDED`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0O. Latest Engineering Event — READY_FOR_DECISION_CANDIDATE_RUNTIME

- `CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1` 的真实 runtime audit 已停止在 blocker：
  CN seed=`800`、US IWB Equity seed=`1018`。CN session-reuse probe=`20/20` 成功、
  `10.147s`；既有逐标的 CN path probe=`5/5`、`3.870s`。US `yfinance.download`
  batch probe=`20/20` 有数据、`3.131s`。
- 真实 CN full shadow（`--market cn --date 2026-09-04`）在 session reuse path 下运行超过
  13 分钟仍未产生完整 summary，进程处于 network wait；为避免无限等待已停止。故本轮
  没有伪造 CN included/per-sector/strategy 结果，US full shadow 也未启动。
- 当前 blocker=`CANDIDATE_HISTORY_RUNTIME_NOT_ACCEPTABLE_OR_NOT_BOUNDED`：无法在本机
  证明 800 个 CN candidate history 能在日常 shadow/runtime budget 内完成。当前没有
  PR、没有 bridge code 留在工作树、没有 provider/Strategy Engine/Candidate semantics
  修改；production state writes=`NO`，broker/order=`NO`。
- 最小选项：Sol 明确接受该多分钟级 bounded shadow cadence 后，再授权继续；或先指定
  经批准的 CN history runtime/batching/caching 方案。不得自行引入数据库、commercial
  provider、修改 universe/sector taxonomy、修改 affordability/top-N 或接 production。

`READY_FOR_DECISION_CANDIDATE_RUNTIME`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0N. Historical Event — BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1_MERGED

- PR #71 已 squash merged。Sol approved head=`1bb2996b1ee7d750fe7d02c53067314ee23866ec`；
  真实 squash merge commit=`319bdf8a3fd950a0be70791ecd81f397aca7e9df`。
- merge-after `CI Test Gate` run=`33984153275` 对 merge commit 为 `SUCCESS`；未自动触发
  Daily Decision Chain / Portfolio Risk shadow，未人为创建 workflow。local `main` 与
  `origin/main` 均为 `319bdf8a3fd950a0be70791ecd81f397aca7e9df`。
- 正式 bounded contract 保持：CN seed=`HS300 ∪ CSI500`；US seed=`IWB official
  holdings`；CN `<=10,000 CNY` preferred、`10,000<notional<=20,000 CNY` extended、
  `>20,000 CNY` excluded；US candidate one-share `>1,000 USD` excluded；
  `TOP_N_PER_SECTOR=20`。
- Candidate layer 不产生 `ENTRY_ALLOWED`；production state writes=`NO`；broker/order=`NO`；
  Candidate Universe 尚未接入正式每日 Strategy Engine production pipeline。
- 唯一 next action：等待下一项明确用户/Sol 授权；不启动每日 production pipeline 接入，
  不接 broker/order，不扩大 Candidate scope。

`BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1_MERGED`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0M. Historical Event — PR_71_SOL_APPROVED_GOVERNANCE_FIX

- Sol review 发现并确认 `PROJECT_GOVERNANCE_STATE_CONFLICT`：
  `docs/TRADING_SYSTEM_SPEC.md` 的 1R 段落仍写 `Risk Per Trade = 0.5% NAV`，与已合并
  PR #70、`docs/DECISION_LOG.md` 和实际 Portfolio Risk 语义冲突。
- 最小修复已完成：1R 改为 `Risk Per Trade = 0.5% allocation_budget`，并明确
  `allocation_budget` 是用户明确授权给该账户整个策略风险账本的总策略预算，不是
  broker NAV / 账户净值；Position Size 公式保持不变。
- 本次未新增 DECISION_LOG decision，未修改 Candidate Universe code/tests、provider、
  Strategy Engine、US `$1000` allocation hard cap 或任何 production state。
- 继续使用 PR #71，不新建 PR、不 merge。治理修复已 push，新的 exact-head CI 已全部通过；
  stop marker=`PR_71_SOL_APPROVED_READY_FOR_MERGE`，并确认
  `HANDOFF_CURRENT_AND_CONSISTENT`。

## 0L. Historical Event — PR_FULLY_READY_FOR_SOL_REVIEW

- 用户/Sol 已正式冻结 `BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1`：CN=`HS300 ∪ CSI500`
  via BaoStock HS300/ZZ500/basic/industry；US=`IWB` official
  `latest-holdings.csv`。不采用完整 public security master B，不采用 commercial C，
  不新增 Finnhub、SEC/Nasdaq full master、database、Sheets production writes、broker/
  order、SETUP_03/04 或新回测 phase。
- 真实 source proof：BaoStock 0.9.3 signatures/fields 已核对，`fields=` 对
  `query_stock_basic` 明确不支持；真实 bounded adapter smoke=`800` CN seeds、
  `metadata_ok=800`、`sector_present=800`。IWB official adapter smoke=
  `source_date=2026-09-03`、`1018` Equity rows；旧 `.ajax` URL 返回 HTML，未作为 CSV
  contract。
- 已实现 `trading/candidate_universe.py` 与
  `trading/candidate_universe_sources.py`，以及 focused tests `10/10 OK`。Selector
  输出 included/excluded、sector、rank、affordability tier、minimum quantity/notional、
  20D/60D traded-notional proxy、history quality、inclusion/exclusion reason；无
  Strategy action 字段，不能产生 `ENTRY_ALLOWED`。
- substantive implementation source head=`2d63fda031cda08dd2bf5bf631b9a9ea09ace415`；
  full unittest=`606/606 OK`、compileall、`git diff --check` 通过。当前 branch 已 push，
  implementation PR #71=`https://github.com/EFSing/stock-data-pipeline/pull/71`，base=`main`，
  `OPEN / MERGEABLE / merged=false`；本 agent 不 merge。PR final tip 与 exact-head CI
  是 GitHub 实时事实，不在治理文件中自引用 closeout commit SHA。
- 当前停止节点=`PR_FULLY_READY_FOR_SOL_REVIEW`。Sol review 前不再改 scope，不创建新的
  docs-only PR，不写 production Sheets/state，不接 broker/order。

`PR_FULLY_READY_FOR_SOL_REVIEW`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0K. Historical Event — BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1_IMPLEMENTED_PENDING_VERIFICATION

- 当前任务基于 live `main@f65f76eb06592a17a897e4a27560e3d5db2c04f9`；审计开始时本地
  `main`=`origin/main`，远端无 open PR，baseline `CI Test Gate` run=`33966049377`
  为 `SUCCESS`。当前本地工作分支为
  `codex/sector-candidate-universe-v1-feasibility`。
- 已批准并登记的长期主线为：`Sector / Industry Universe → Tradable Candidate
  Selector → Candidate Universe → existing Data Quality / Weekly / Daily / Swing /
  Wave / Fibonacci / Setup chain`。Candidate layer 只做是否进入完整分析的 gate，
  不产生 `ENTRY_ALLOWED`、`STRATEGY_PROPOSAL` 或买入信号。
- CN affordability：真实 minimum-unit notional `<=10,000 CNY` preferred，
  `10,000<notional<=20,000 CNY` retained/lower priority，`>20,000 CNY` excluded；
  缺少 lot evidence 时 fail closed 或限制支持范围。US candidate 排除 price `>1,000
  USD`，最终 `1,000 USD` hard cap 在 allocation/position sizing 再验证。
- feasibility audit 发现现有 production provider 没有可扩展 CN/US security master、
  security type、sector/industry、可靠 CN lot metadata 或 candidate-stage 批量
  history gate；现有 Hithink/指数 snapshots 不能直接升级为 production source。
- 停止状态=`READY_FOR_DECISION_DATA_SOURCE`。未改 strategy/provider code，未添加
  dependency/provider/database/cache/registry，未写 Google Sheets、production state、
  broker/order，未启动 `SETUP_03`/`SETUP_04`。完整审计见
  `docs/SECTOR_CANDIDATE_UNIVERSE_V1_FEASIBILITY.md`。
- 唯一 next action：用户选择方案 B（BaoStock + SEC/Nasdaq + existing yfinance，并
  明确 CN 支持板块）或方案 C（具体统一 reference-data provider/entitlement）；选定
  前停止实现。

`SECTOR_CANDIDATE_UNIVERSE_V1_READY_FOR_DECISION`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0I. Latest Engineering Event — STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1_MERGED

- PR #70（`fix/strategy-capital-allocation-boundary`）已依据 Sol approval 完成
  squash merge。approved exact head=`88b6889429d36c4d4cdb4d2f8515243f1681dcac`，
  base=`main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`；GitHub final state=
  `MERGED / merged=true`，真实 squash merge commit=
  `898a01f3e789f15474f30e218eec53eadf34d0c5`。
- merge-after main 已实时核验：本地 `main` 与 `origin/main` 均为
  `898a01f3e789f15474f30e218eec53eadf34d0c5`；`CI Test Gate` run=`33965870377`
  为 `SUCCESS`。该 merge commit 未自动触发 Daily Decision Chain 或 Portfolio Risk
  shadow；未手工创建不必要的 workflow。
- 正式边界保持为：`STRATEGY_PROPOSAL` 与 NAV 正式解耦；Strategy Proposal 不读取
  broker NAV、账户净值、账户资产、P&L、入出金或 purchasing power。allocation 必须
  经过用户显式 proposal approval；`allocation_budget` 是用户授权给该账户策略风险
  账本的总策略预算，不是 NAV、账户总资产或本轮新增现金额度。
- `BASE_RISK_FRACTION=0.005`、`MAX_RISK_PER_GROUP_FRACTION=0.01`、
  `MAX_TOTAL_OPEN_RISK_FRACTION=0.02` 冻结不变；existing positions 与 approved
  proposals 共用同一总预算 denominator。
- 本次 closeout 未执行 `--run` / `--write-state`，未写 production strategy state
  或策略持仓，未访问 broker/order；production state writes=`NO`，broker/order=`NO`。
- 本治理同步不新增 `DECISION_LOG.md` decision，也不把 HANDOFF/CURRENT_STATUS
  自身尚不存在的 commit SHA 写入文件。PR、merge commit 与 CI 事实以 GitHub 实时
  核验为准。
- 剩余 blocker：PR #70 merge closeout 无 blocker；production state writes、broker/
  order 与自动执行仍按边界禁用。唯一 next action：停止并等待用户下一项明确授权，
  不启动新的策略开发或生产操作。

`STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1_MERGED`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 0H. Latest Engineering Event — PR_70_SOL_APPROVED_READY_FOR_MERGE

- 在现有 PR #70（`fix/strategy-capital-allocation-boundary`，base=`main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`）
  上完成 Sol review 修复，并通过 Sol correctness review；本 agent 不 merge、不新建 PR，
  继续沿用本分支，等待用户/Sol 执行 merge。
- **A. 显式 proposal approval：** `DailyDecisionChain.evaluate` 新增
  `approved_event_identities`（仅接受 event identity，拒绝 symbol 猜测）与
  `STRATEGY_PROPOSAL_APPROVAL_REQUIRED`。生产分配必须同时满足：event 已是已发布
  `STRATEGY_PROPOSAL`、identity 被用户显式批准、`allocation_budget` 有效、未
  pending、未 settled、原有 Portfolio Risk prerequisites 成立。`allocation_budget`
  本身绝不代表 approval；budget 有值但批准集为空 → 0 reservation / 0 pending；同日
  多 proposal 只分配被明确批准的 identity；未批准 `ENTRY_ALLOWED` 保持
  `STRATEGY_PROPOSAL`；不存在、未发布、已 pending、已 settled 的批准 fail closed；
  `ENTRY_ALLOWED` 技术条件未改变。
- **B. `allocation_budget` 正式语义：** 用户明确授权给该账户整个策略风险账本使用的
  总策略资金预算；不是 broker NAV、账户净值、账户总资产、入出金、P&L、purchasing
  power 或本轮新增现金额度。已有 system-managed positions 与同轮 approved proposals
  共用该预算作为 Portfolio Risk denominator。冻结
  `BASE_RISK_FRACTION=0.005` / `MAX_RISK_PER_GROUP_FRACTION=0.01` /
  `MAX_TOTAL_OPEN_RISK_FRACTION=0.02` 不变；未引入 `new_cash_budget`，未重设计
  Portfolio Risk。
- **C. Governance conflict 修复：** substantive validation head 与 current PR head
  分离记录。`bb8e6d9a23a175ff01790314837e24621446ce1c` 是 substantive source
  head，不再写成 current PR head；current PR head 一律以 GitHub 实时核验为准；治理
  文件不自引用自身 docs closeout commit SHA。
- 新增回归覆盖：选择性批准（2 ENTRY_ALLOWED 只批准 A）、budget 非 approval、
  approval 需 prior published proposal、有 approval 无 budget fail closed、
  T+1 不重传 budget 仍按 frozen `risk_capital` settlement、existing positions 与
  approved proposal 共用总预算 denominator、pending/settled 身份重复批准不重复
  reserve、NAV 不重新进入 proposal prerequisite。
- 验证：Daily Chain focused `31/31 OK`；Production Prerequisites focused `19/19 OK`；
  full unittest `596/596 OK`；Daily Chain generic shadow `17/17 SUCCESS`；Portfolio
  Risk generic shadow `17/17 checks SUCCESS`；`compileall`、protocol JSON parse、
  `git diff --check` 均通过。未执行 `--run` / `--write-state`，未写策略决策状态 /
  策略持仓，未访问 broker/order。
- 协议/文档：`research/protocols/portfolio_risk_v1.json` 的 `allocation_boundary`
  已扩展 approval contract 与 budget 语义（`protocol_version` 未变）；`docs/
  PROSPECTIVE_DAILY_DECISION_CHAIN_V1.md` 与 `docs/PORTFOLIO_RISK_V1.md` 已同步。
  本 closeout 不修改 protocol JSON。
- PR #70 当前 head 与 exact-head CI 以 GitHub 实时状态为准；截至本次 closeout，Sol
  独立核验 head=`8d2b9f76bbc2310182a47b94819adcd388385fe0`，exact-head CI 全部
  SUCCESS（Test Gate=`33963031703`、Daily Decision Chain shadow=`33963031701`、
  Portfolio Risk shadow=`33963031705`），并已通过 Sol correctness review。stop
  marker=`PR_70_SOL_APPROVED_READY_FOR_MERGE`；当前唯一 next action 为 merge PR
  #70；本 agent 不 merge、不新建 PR。

## 0G. Prior Engineering Event — STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1

- 本任务基于真实 `main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`，当前工作分支为
  `fix/strategy-capital-allocation-boundary`；创建 PR 但不 merge。
- 正式边界为：`Market Data → Data Quality → Weekly/Daily State → Swing → Wave
  Scenario → Fibonacci → Setup → Entry/Stop/Target/RR → STRATEGY_PROPOSAL →
  用户批准 → allocation_budget → Portfolio Risk/Position Size → 后续执行`。
- Strategy Decision 不读取或依赖 broker NAV、账户资产、每日权益、入出金、P&L、
  purchasing power 或 broker balance。`策略账户.参考净值` / `净值日期` 保留为可选
  legacy fields，但已退出 proposal preflight；缺少或落后 T 不再构成纯 proposal blocker。
- 没有 `allocation_budget` 时，`ENTRY_ALLOWED` 仍输出为 `STRATEGY_PROPOSAL`，不
  计算 Position Size、不 reserve、不写入 pending T+1 allocation。用户批准后仅以
  显式预算进入 Portfolio Risk；冻结风险比例 `0.005 / 0.01 / 0.02` 未改变。
- 无 broker/order/UI/自动 workflow 接入；本任务未执行 `--run`、`--write-state`，不
  写 `策略决策状态` 或 `策略持仓`。substantive source head=`bb8e6d9a23a175ff01790314837e24621446ce1c`；
  PR #70=`https://github.com/EFSing/stock-data-pipeline/pull/70`，base=`main`，
  `OPEN / MERGEABLE / merged=false`；exact-head CI：Test Gate=`33952922439`、
  Daily Chain shadow=`33952922429`、Portfolio Risk shadow=`33952922432`，均成功。
- connector-backed live read-only preflight T=`2026-09-04`=`READY`：CN `DATA_OK=3/3`、
  US `DATA_OK=2/2`，QFQ blockers=`0`、NAV blockers=`0`、risk-group blockers=`0`、
  state-store=`OK`、`NO STATE WRITE=true`、`NO Sheets mutation=true`。本机 CLI 未注入
  `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON`，仅在 client 初始化前失败；未
  输出或记录凭证。stop marker=`PR_FULLY_READY_AND_PREFLIGHT_READY_FOR_SOL_REVIEW`；
  本文件不自引用 docs-only commit SHA。

## 0F. Prior Production Verification — CN_US_SCHEDULED_QFQ_VERIFIED_AND_PREFLIGHT

- 本轮真实 GitHub Actions 均核验为 `main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`。Asia scheduled run `33879573985`（event=`schedule`）为 `SUCCESS`；主行情 `symbols_requested=9`、`freshest_rows_written=9`、`failed_symbols=0`；`PRODUCTION_QFQ_SUMMARY` 为 `group=asia`、`symbols_requested=3`、`symbols_updated=3`、`rows_written=3000`、`status=SUCCESS`。
- 对同一 US scheduled run `33932473603` 仅执行一次 `Re-run failed jobs`；未创建新 workflow。attempt=`2`，job=`101264486493`，job/run=`SUCCESS`，completed=`2026-09-05T06:44:01Z` / run updated=`2026-09-05T06:44:02Z`；checkout log 明确 fetch/checkout `2ce2711f4994f31c167bbe4961ecd0b34e90c476`。
- US attempt 2 的 `python main.py --group us --mode latest` 正常完成：`symbols_requested=4`、`freshest_rows_written=4`、`failed_symbols=0`、`history_rows_written=0`、`decision_rows_written=0`、`status=PARTIAL_DATA_QUALITY`（非正式 universe 的 single-source/pending 诊断仍在摘要中）。随后 `PRODUCTION_QFQ_SUMMARY`=`group=us`、`symbols_requested=2`、`symbols_updated=2`、`rows_written=2000`、`stale_or_failed_symbols=[]`、`status=SUCCESS`；BABA/RKLB 均完成 target=`2026-09-04`。
- 因此 Asia + US 已形成 `CN_US_SCHEDULED_QFQ_VERIFIED` 生产证据。workflow/log scope 仅为行情 latest 与 `历史行情_前复权` QFQ；日志无 `策略决策状态`、`策略持仓`、legacy `交易决策` 或 broker/order 写入，production state write=`NO`。
- live workbook 只读复核显示正式 5 个 symbol 的 `最新行情` 与 `历史行情_前复权` 均为 `2026-09-04`，包括 BABA/RKLB；`策略持仓` 与 `策略决策状态` 均无数据。严格 read-only production preflight（现有 CLI `--preflight --date 2026-09-04`，无 `--run`/`--write-state`，使用 live connector snapshot）为 `NOT_READY`，state-store=`OK`，`NO STATE WRITE=true`，`NO Sheets mutation=true`。
- preflight 的有效根因是 NAV freshness：live `CN_MAIN` 与 `US_MAIN` 的 `净值日期` 都仍为 `2026-09-03`，落后 T=`2026-09-04`；适配器先报 `PRODUCTION_NAV_DATE_REQUIRED:CN_MAIN`，并因 fail-closed 解析产生 `PRODUCTION_STRATEGY_UNIVERSE_REQUIRED` / `PRODUCTION_ACCOUNT_REQUIRED` cascade。QFQ freshness blocker 已全部消失；不能将 NAV blocker 归类为 QFQ failure。
- 本轮不改代码、provider、retry、schedule、freshness contract、strategy/state/broker/order；不产生 PR，不进入 production state write。当前 stop marker=`PRODUCTION_PREFLIGHT_NOT_READY_NAV_FRESHNESS`；唯一 next action 是在用户决定并使两账户 NAV date 满足 T 后，重新执行一次同样的严格 read-only `--preflight`。`HANDOFF_CURRENT_AND_CONSISTENT`。

## 0C. Prior Operational Milestone — PRODUCTION_CONFIG_ACTIVATION_AND_READ_ONLY_PREFLIGHT_V1

- milestone status=`PRODUCTION_CONFIG_ACTIVATED`；live workbook ID=`1M6VvFaBNCkaS7N32afDqsHBn2CGie-WrOmPqOhDHuws`，title=`持仓股股票行情数据中台`，time zone=`Asia/Shanghai`；live GitHub `main` / baseline=`e4a58a7a1b2c53a76abf190cff8d3a39d737cf9b`。
- PR #66 / #67=`MERGED / merged=true`；latest main `CI Test Gate` run=`33767187219` success。该里程碑完成时 checkout=`codex/production-prerequisites-governance-closeout`，其本地开发基线尚未快进到 live main；本节中的 workbook 与 live GitHub facts 以当时核验为准。
- `策略账户` final rows：`TRUE | CN_MAIN | CN | CNY | 75000 | 2026-09-03`；`TRUE | US_MAIN | US | USD | 4500 | 2026-09-03`；备注为用户确认的 V1 启动参考净值，明确不表示券商自动同步。
- `策略股票池` final enabled rows：`000725.SZ`、`002156.SZ`、`512400.SH` under `CN_MAIN`；`BABA`、`RKLB` under `US_MAIN`。`DRAM` remains `FALSE | US_MAIN | US | DRAM | Roundhill Memory ETF`，备注明确保留为 disabled candidate；enabled total=`5`。
- `策略风险分组` final explicit mappings：`CN/000725.SZ→DISPLAY_TECH`、`CN/002156.SZ→SEMICONDUCTOR`、`CN/512400.SH→METALS`、`US/BABA→CHINA_INTERNET`、`US/RKLB→SPACE_AEROSPACE`；无 DRAM risk row。
- `EXISTING_POSITIONS_MANAGED=NO`；`策略持仓` row count=`0`。`策略决策状态` row count before→after=`0→0`；未写入 system-owned state records。
- exact preflight T=`2026-09-03`，result=`NOT_READY`；CN calendar=`XSHG`、US calendar=`XNYS` 均完成 exact session proof，next session=`2026-09-04`；静态配置核验全部通过。live market data：CN latest/QFQ 至 `2026-09-02`；US latest 至 `2026-09-03`，但 QFQ 至 `2026-08-28`。
- exact data blockers：`PRODUCTION_DATA_QUALITY_REQUIRED:000725.SZ:DATA_STALE:qfq last date < T`；`PRODUCTION_DATA_QUALITY_REQUIRED:002156.SZ:DATA_STALE:qfq last date < T`；`PRODUCTION_DATA_QUALITY_REQUIRED:512400.SH:DATA_STALE:qfq last date < T`；`PRODUCTION_DATA_QUALITY_REQUIRED:BABA:DATA_STALE:qfq last date < T`；`PRODUCTION_DATA_QUALITY_REQUIRED:RKLB:DATA_STALE:qfq last date < T`。
- preflight 为 read-only；state-store status=`OK`；`NO STATE WRITE=true`；`NO Sheets mutation=true`。已执行 `--preflight --date 2026-09-03` 的同一 runner；本地原生 CLI 环境缺 `gspread`，最终报告使用 live connector records 经 adapter injection 完成，未写入任何状态或 Sheet。
- outside target tabs changed=`NO`；strategy positions/state writes=`NO`；`BROKER_NOT_CONNECTED`；`PRODUCTION_STATE_WRITES_NOT_ENABLED`；`ORDERS_NOT_ENABLED`；`FX_NOT_IMPLEMENTED`；`cron=NO`。
- final stop state=`PRODUCTION_CONFIG_ACTIVATED / READ_ONLY_PREFLIGHT_NOT_READY_DATA_STALE`；不自动写生产状态，不修改 T、NAV date、假收盘或 weekday guard。
- `DECISION_LOG.md` 未修改：本轮执行已批准的 production config，不是新的长期架构决策。`HANDOFF_CURRENT_AND_CONSISTENT`。

## 0D. Latest Engineering Milestone — PRODUCTION_QFQ_DAILY_REFRESH_V1_MERGED

- 根因已确认并保留 machine-readable marker=`PRODUCTION_QFQ_NOT_REFRESHED_BY_SCHEDULED_LATEST_MODE`：scheduled `main.py --mode latest` 只更新 latest/validation/log，既有 QFQ upsert 位于 `mode == "full"`，而 `full` 会进入 legacy SETUP_03/Decision path。
- 新增窄入口 `scripts/refresh_production_qfq.py`：formal enabled `策略股票池` 仅通过 enabled linked `策略账户` 进入；严格按 `(市场,统一代码)` 唯一匹配 `自选清单` source config 与 `最新行情` target `交易日期`；只允许 `BaoStock`/`yfinance` QFQ；复用 `history_days`、existing retry/provider、`quote_row`，并通过 scoped `SheetsClient.replace_history_series` 替换 target 的完整 QFQ series。
- mutation boundary=`历史行情_前复权` only；不写 `策略账户`、`策略股票池`、`策略风险分组`、`策略持仓`、`策略决策状态`、`交易决策`、`最新行情`、`自选清单` 或 `历史行情_未复权`，不创建新 workflow/cron，不改策略语义。
- Asia/US scheduled workflow 保持 cron 不变，并在 `main.py --mode latest` 成功后按 `RUN_MODE == latest` 调用 refresher；manual `full` 不调用 refresher。refresher 失败或任何 formal symbol stale/missing 时 fail closed，禁止 partial stale success，并输出 `PRODUCTION_QFQ_SUMMARY`。
- 当前 live workbook 仍是真实已激活配置；现有 read-only preflight 的 QFQ stale blockers 仍有效，但本次没有手动 live refresher smoke。PR #68 已 squash merge；合并后的 scheduled `latest` 已具备自动 QFQ refresh 能力。strategy state writes、broker/orders、FX 均未启用。
- 当前 checkout=`main`，`main`/`origin/main` exact SHA=`4034c87c354fc552496202e7004848ecfbfef6b3`；formal pre-merge baseline=`e4a58a7a1b2c53a76abf190cff8d3a39d737cf9b`；Sol-approved exact head=`ffc753baf784f8af4bb702db7c6799371dcd3693`，PR #68 merge commit=`4034c87c354fc552496202e7004848ecfbfef6b3`。focused refresher tests=`16/16`、full unittest=`587/587`、compileall 与 `git diff --check` 均通过；approved head 的 CI Test Gate=`33841344943`、Daily Decision Chain generic shadow=`33841344884`、Portfolio Risk generic shadow=`33841344891` 均 success；merge-after main `CI Test Gate`=`33842189224` success。当前状态=`PRODUCTION_QFQ_DAILY_REFRESH_V1_MERGED`，停止，不自动启动新的 production decision phase。
## 0. Prior Governance Event — PRODUCTION_PREREQUISITES_V1

- 正式起点为 `main@95eec374c3ef48877d45a4bfb2794f6df3cf0ae2`；该 exact head 的 `CI Test Gate` run=`33712447481`，result=`success`。
- substantive/validation head=`4548563249ad8f61656f09d5bca2c3f7761cc718`；PR #66 final live head=`ca21bd7ea2925d30d101550cb5d088b848ebff4d`，已 squash merged 为 `11f78c88a2e43ae1a136ffd2bd31246e4a6823ef`。后续 governance-only docs commit 不把自身或前一个 docs commit冒充 source validation head。
- PR #66=`https://github.com/EFSing/stock-data-pipeline/pull/66`，base=`main@95eec374c3ef48877d45a4bfb2794f6df3cf0ae2`，state=`MERGED / merged=true`；merge-after `main`=`11f78c88a2e43ae1a136ffd2bd31246e4a6823ef`。
- substantive head exact-head CI：`CI Test Gate` run=`33739123688` success；Daily Chain generic shadow run=`33739123690` success；Portfolio Risk generic shadow run=`33739123721` success。
- 本阶段实现并 harden 五个 production Sheet contracts、account-isolated adapter、`SheetsDecisionStateStore`、exact exchange calendar 和只读 `--preflight`：缺 PositionOrigin 仅阻断 PM；同轮 settlement exposure、未决 reservation、compound state 与显式行情币种均 fail closed；system-owned `POSITION_ORIGIN` 无对应 `SETTLEMENT` 时以 `PERSISTED_STATE_INCOMPLETE:origin_without_settlement:<identity>` fail closed；QFQ 缺失恢复为 `DATA_UNAVAILABLE`；空 enabled account 无正式 strategy universe 时 fail closed。
- 本地验证：full unittest=`571/571`；production prerequisites=`19/19`；Daily Chain=`23/23`；Portfolio Risk=`24/24`；Position Management=`18/18`；Daily generic shadow=`17/17 SUCCESS`；Portfolio generic shadow=`17/17 SUCCESS`；compileall 与 `git diff --check` 通过。
- Portfolio Risk 继续复用 frozen constants/formula；CN/US 为独立 CNY/USD risk books；不实现 FX，不访问 broker/IBKR，不修改真实 Sheets。
- merge-after main `CI Test Gate` run=`33745503856` success。
- 五个 production Sheet contracts、account-isolated risk books、persistent state / exact calendar / production adapter 已进入正式 engineering baseline；`REAL_SHEETS_NOT_CREATED`、`REAL_PRODUCTION_STATE_NOT_ENABLED`、`BROKER_NOT_CONNECTED`。
- 最终状态=`PRODUCTION_PREREQUISITES_V1_MERGED`；`HANDOFF_CURRENT_AND_CONSISTENT`；停止，不再执行本阶段工作。

## 0B. Prior Operational Milestone — PRODUCTION_SHEETS_BOOTSTRAP_AND_PREFLIGHT_V1

- milestone status=`PRODUCTION_SHEETS_BOOTSTRAPPED`；本节为当前 live workbook objective facts 的治理事实源；旧 `REAL_SHEETS_NOT_CREATED` 仅保留在历史事件中。
- 目标 workbook 已通过 live identity guard：ID=`1M6VvFaBNCkaS7N32afDqsHBn2CGie-WrOmPqOhDHuws`，title=`持仓股股票行情数据中台`，time zone=`Asia/Shanghai`。
- 真实 workbook 原有 `自选清单`、`最新行情`、`历史行情_前复权`、`参数设置`、`交易决策`；5 个目标 worksheet 原先不存在，已创建且未删除或覆盖任何旧 worksheet。
- 已创建并核验 exact headers：`策略账户`、`策略股票池`、`策略风险分组`、`策略持仓`、`策略决策状态`；sheetId 依次为 `880646742`、`1476125198`、`1355912165`、`2087824484`、`1675295518`。
- `策略账户` 现有 2 行 disabled scaffold：`CN_MAIN/CN/CNY`、`US_MAIN/US/USD`；参考净值与净值日期均留空，未推算 NAV。
- `策略股票池` 现有 6 行 disabled candidate bootstrap：CN=`000725.SZ` 京东方A、`002156.SZ` 通富微电、`512400.SH` 南方中证申万有色金属ETF；US=`BABA` 阿里巴巴、`DRAM` Roundhill Memory ETF、`RKLB` Rocket Lab USA。备注均为候选 bootstrap，未批准进入正式策略股票池。
- `策略风险分组` row count=`0`；`策略持仓` row count=`0`；`策略决策状态` row count=`0`，未写入任何 `PUBLISHED_EVENT`、`PENDING_T1`、`SETTLEMENT`、`POSITION_ORIGIN` 或 `DAILY_RESULT`。
- live read-only preflight（`--preflight`，无 `--run`、无 `--write-state`）结果=`NOT_READY`；runner/adapter 输出 blocker=`PRODUCTION_STRATEGY_UNIVERSE_REQUIRED`、`PRODUCTION_ACCOUNT_REQUIRED`，并确认 `READ_ONLY`、`NO STATE WRITE=true`、`NO Sheets mutation=true`。由于所有账户和候选仍 disabled，这是预期结果。
- preflight 前后 `策略决策状态` row count=`0 → 0`；旧 market-data/config/decision worksheet 的 sheetId 与 header verification 保持不变，outside target tabs changed=`NO`。
- 本地 shell 未注入 `GOOGLE_SERVICE_ACCOUNT_JSON`，因此 preflight 使用刚从目标 workbook 读取的 live records 经 merged runner/adapter 注入路径执行；未读取、记录或输出任何 secret/credential。后续若需本地原生 `SheetsClient` CLI 进程，需在运行环境注入现有凭证。
- 当前真正需要用户决定/填写：正式策略股票池（6 个候选逐项纳入与否）、拟启用账户的 reference NAV/NAV date、拟启用 symbol 的 risk group，以及确实要纳入管理的现有持仓事实（quantity、actual entry、protective stop、entry date、source event ID 可为空）。不伪造 PositionOrigin。
- `DECISION_LOG.md` 未修改：本轮只是执行已批准的 production contract，不是新的长期架构决策。治理同步目标为 `HANDOFF_CURRENT_AND_CONSISTENT`；当前状态=`READY_FOR_DECISION_REAL_PRODUCTION_CONFIG`；`REAL_PRODUCTION_STATE_NOT_ENABLED`、`BROKER_NOT_CONNECTED`。
- repo verification：`main` exact HEAD=`85f5aad40c300a5446a3610ce4daccfbc08c75bf`，`origin/main` 同 SHA；当前 checkout=`codex/production-prerequisites-governance-closeout`，working tree 在本次 docs sync 前 clean；PR #66=`MERGED / merged=true`；latest main `CI Test Gate` run=`33745503856` success。

## 0A. Prior Governance Event — FROZEN_DEVELOPMENT_DATASET_PORTABLE_ARCHIVE

- 已完成已授权的 `d1016f2` fast-forward push 到现有 PR #59 分支；PR #59 仍为 `OPEN / merged=false`，未 merge。
- 以真实最新 `main@12a9e2aa175a90c5ff1db8556190c6db23d2bb64` 为 target，创建私有 prerelease/data archive：`frozen-development-dataset-2026-08-28-v2`。
- Release URL：<https://github.com/EFSing/stock-data-pipeline/releases/tag/frozen-development-dataset-2026-08-28-v2>；asset 为 `stock-data-pipeline-frozen-development-v2.zip`，`5,900,672` bytes，archive SHA-256=`sha256:15e3c63da65cd1eba52ecd6d441be22d6556e9ae2008f70c652a01bb7b0eaeb2`。
- Frozen identity：`SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2`，40 symbols / 84,284 bars，manifest SHA-256=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`。
- Archive input 为 manifest 加 40 个 raw CSV 和 40 个 normalized JSONL；派生 research evidence 未纳入。ZIP integrity test=`PASS`，独立临时目录恢复后 `ALL_FILE_HASHES_MATCH=true`（81/81）。
- Git remains source-code SSOT；GitHub Release asset 是 frozen binary/data archive；manifest/hash 是 dataset identity SSOT。Restore doc 为 `docs/FROZEN_DATASET_RESTORE.md`，预期恢复目录为 `artifacts/development_strategy_stability_v2/`。
- 不重新抓取、normalize、生成或 replay；不包含 secrets、credentials、account/broker data、Sheets credentials、personal holdings、`.env` 或 Git credential files。
- 最终状态：`FROZEN_DEVELOPMENT_DATASET_CLOUD_ARCHIVED_AND_PORTABLE`；`HANDOFF_CURRENT_AND_CONSISTENT`。

## 1. Current Objective

- **当前 Phase / task:** `BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1`；工作分支为
  `codex/sector-candidate-universe-v1-feasibility`，继续沿用，不从 main 新开任务。
- **唯一目标:** 完成 bounded CN/US seed adapter、candidate domain/selector、focused
  regression、治理同步、implementation PR 和 exact-head CI；不 merge，停在
  `PR_FULLY_READY_FOR_SOL_REVIEW`。
- **实现边界:** CN=`HS300 ∪ CSI500` / BaoStock；US=`IWB` official holdings；不构建
  全市场 master，不接 commercial provider；不写 Google Sheets/production state，不接
  broker/order，不改 frozen Strategy Engine、SETUP_01/02、SETUP_03/04 或新回测 phase。
- **停止条件:** source contract、focused/full tests、compileall、`git diff --check`、
  PR exact-head CI 均成功；若 BaoStock/IWB 实际 contract 不能稳定机器读取，停止在
  `READY_FOR_DECISION_DATA_SOURCE_RUNTIME_BLOCKER` 并给出真实证据，不自行换 provider。

## 1A. Historical Objective — PORTFOLIO_RISK_V1

- **当时 Phase / task:** `PORTFOLIO_RISK_V1`（独立 downstream capacity gate，等待 Sol review）。
- **Sol approval / previous closeout:** `APPROVE_POSITION_MANAGEMENT_EXIT_V1_MERGE_AND_PROCEED_PORTFOLIO_RISK_V1`；PR #51 已 squash merged，真实 merge commit=`993d03e428b7eb11da791a608940c9d77a608f96`；merge-after main exact-head CI=`33607481962` success。
- **唯一目标:** 从最新 clean merged main 实现独立 `PORTFOLIO-RISK-2026-09-02-v1`，只消费冻结 SETUP_01/SETUP_02 `ENTRY_ALLOWED`，完成 conservative/fail-closed portfolio reservation、T+1 settlement、synthetic boundary、frozen mechanical replay、回归与治理核验；创建 PR #59 供 Sol review，不 merge。
- **实现范围:** `trading/portfolio_risk.py`、`research/portfolio_risk_replay.py`、synthetic shadow runner/workflow、tests、`research/protocols/portfolio_risk_v1.json` 与 `docs/PORTFOLIO_RISK_V1.md`；不改 Entry/Wave/Swing/Target/RR/Position Management/Exit/Wave5 semantics。
- **当时 replay pin:** frozen `DEVELOPMENT_EXPOSED` dataset `SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2`，40 symbols / 84,284 bars，manifest SHA=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`；仅作 development mechanical evidence，不是 formal validation 或 Final OOS。
- **操作边界:** no broker/holdings/account/Secrets/Sheets access or writes; no performance metrics/OOS; no production execution wiring; no automatic merge of PR #59。
- **SETUP_02 corrected funnel retained:** 213 first-entry CONFIRMED → 213 Decision；`ENTRY_ALLOWED=1`；gate=`ABOVE_ENTRY_ZONE 97 / STALE_CONFIRMATION_GEOMETRY 12 / NO_VALID_TARGET 1 / RR_BELOW_MINIMUM 102`；T+1 attempts/executed=`1/0`；所有上游 identity 与 cache semantic parity 保持通过。
- **停止条件:** focused/full unittest、compileall、`git diff --check`、17/17 synthetic shadow、frozen replay causal/conservation/identity/governance checks、strict-vs-cached semantic parity、PR #59 final exact-head CI 与 generic shadow success 完成后，停止在 `PORTFOLIO_RISK_V1_REBASED_AND_READY_FOR_SOL_REVIEW`；禁止 merge 新 PR。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`; 当前 branch=`codex/sector-candidate-universe-v1-feasibility`。
- **baseline:** branch 当前 substantive implementation head=`2d63fda031cda08dd2bf5bf631b9a9ea09ace415`；
  implementation 已提交并推送，PR #71 已创建；PR final tip/exact-head CI 以 GitHub 实时核验为准。
- **working tree scope:** 新增 candidate domain/source adapters/tests，并同步
  `TRADING_SYSTEM_SPEC.md`、`DECISION_LOG.md`、`CURRENT_STATUS.md`、`HANDOFF.md`、
  `ARCHITECTURE.md` 与 feasibility audit；未改 production provider chain 或 frozen
  strategy implementation。
- **production boundary:** no Google Sheets mutation, production state write, broker/order,
  holdings read, SETUP_03/04 or new research phase。当前 adapter smoke 仅为 public,
  read-only source validation。

## 2A. Historical Repository State — PORTFOLIO_RISK_V1 pre-merge

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** 真实 GitHub `main` 当前为 `f53ae42b85ca9e3e5a3bd6e8b91d919b1de0aa24`；PR #59 已在本地完成对齐。
- **historical working checkout:** 当时 checkout 为 `codex/portfolio-risk-v1`，本地 rebase 后 substantive source head=`96d3d52ef7baf6dacc0f464a07ca7a1c8b9ca1c0`；冲突仅为治理文档，Portfolio Risk 核心代码未与最新 main 冲突；replay output 位于 ignored `artifacts/`。
- **historical open PR / governance:** PR #59=`https://github.com/EFSing/stock-data-pipeline/pull/59` 当时为 OPEN / CLEAN / MERGEABLE / merged=false，不创建新 PR，不自动 merge。
- **base CI:** latest main exact-head `CI Test Gate`=`33625526648` success；rebased validation tip=`e80c61bd72953754802290ee09e8171b5ffd447c` 的 `CI Test Gate`=`33645523150` 与 `Portfolio Risk generic operational shadow`=`33645523141` 均 success。
- **working tree expected state:** 代码、测试和 protocol docs 进入本分支；ignored `artifacts/` 不进入 commit；不写 Sheets、不访问账户/券商/Secrets。
- **historical project/phase status:** SETUP_03 当时保持 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`；SETUP_01/SETUP_02、Position Management/Exit/Wave5 semantics frozen；当时只推进 Portfolio Risk downstream gate，未开启 production path。

## 3. Completed Work

### Completed SETUP_02 structural implementation

- Added an independent immutable SETUP_02 evaluator and strict-prefix replay layer. The evaluator consumes only the existing Wave Engine primary `WAVE_3_CONTINUATION_CANDIDATE` with `setup02_context_eligible=true`; it does not alter Wave Engine semantics.
- Context eligibility is causal `LOW0 → HIGH1 → LOW2 → HIGH3`, with `HIGH3 > HIGH1`, `LOW2 > LOW0`, confirmed daily/weekly `UPTREND`, and the Wave Engine's existing latest confirmed higher-low `structural_invalidation`. `continuation_high=HIGH3`.
- Lifecycle is `NONE → WATCH ↔ ARMED → CONFIRMED`, with `WATCH/ARMED → FAILED`; recovery is `invalidation + 0.5 × (HIGH3 - invalidation)`, equality at `HIGH3` is not confirmation, and confirmation requires the first daily close strictly above `HIGH3`.
- Terminal failures are fail-closed for structural invalidation, weekly/daily structure loss, primary ABC/downtrend/invalid context, and loss of primary eligibility. Ordinary context refresh does not fabricate a failure; terminal lifecycles do not emit a second event.
- Fibonacci uses existing canonical levels/regions descriptively only. Event identities are deterministic in the `SETUP_02` namespace and emitted only on first-entry terminal `CONFIRMED`/`FAILED`.
- Added structural-only `DEVELOPMENT_EXPOSED` reporting: state-day counts, terminal counts, CN/US split, per-symbol counts, primary-wave distribution, current candidates, failure/block reasons, Fib regions, and identity audit. No outcome, return, P&L, or OOS field is produced.

### Previous holdings lifecycle closure implementation

- Added `latest_snapshot.py` as the minimal shared latest evaluator/contract and row projection used by scheduled `main.run(mode="latest")` and `HoldingsDataManager`; scheduled latest fixture semantics remain green.
- ADD/REENTER now normalize identity, obtain the latest completed session, reuse latest validation/freshness/sanity semantics, use that exact trade date for raw/qfq coverage/QC, publish latest, append validation, and enable the watchlist row last. Failures leave a new identity disabled; legal history is retained for idempotent retry.
- Enabled repeated ADD now reconciles history, latest, and validation before returning IDEMPOTENT; complete history is not refetched while missing/latest-lagging state is repaired. CLOSE and SYNC retain their existing boundaries.
- `SheetsClient.upsert_watchlist()` discovers the actual worksheet/table metadata, expands the real table through all headers/new row including P `历史数据源`, copies existing row format, preserves unmanaged columns, and writes normalized codes with literal-safe RAW input.
- Added regression coverage for first ADD/REENTER closure, enable-last, shared completed date, provider/latest/history failures, future/stale/sanity fail-closed, repeated ADD repair, scheduled parity, and WatchlistTable metadata/format preservation.
- Added explicit retry regressions: a failed final watchlist enable retries with only the identity write, a complete disabled REENTER only restores enablement, and a failed validation append retries only validation plus final enable. Existing repeated ADD idempotency, CLOSE, SYNC, and scheduled latest parity remain covered.

- Holdings manager implementation: deterministic symbol/market/source normalization; natural-language parsing for single-symbol `ADD`/`REENTER`/`CLOSE`/`SYNC`; observed-session raw/qfq latest-completed-session one-year initialization and gap-only sync; deterministic 180-bar / 7-day boundary / 14-day observed-gap / exact date-set QC; fail-closed provider/QC/duplicate-date gates; idempotent `自选清单` update; CLOSE history preservation; Beijing-time append-only audit.
- Repository-local Skill specification and capability documentation are tracked. `SheetsClient.upsert_watchlist()` updates only known headers and preserves unverified `自选清单` columns; no schema/registry change.
- Holdings regression suite is `22/22`: first ADD with near-real US session fixture, repeated ADD, CLOSE/repeated CLOSE, ADD-after-CLOSE automatic re-entry, REENTER gap/full coverage, US/CN holiday sessions, sparse/truncated/mismatched raw/qfq fail-closed cases, SYNC state preservation, ambiguity, provider failure, duplicate dates, natural-language examples, and unknown Sheet columns. Existing scheduled latest tests remain green in full `393/393`.
- Read-only live provider smoke wrote no Sheets: `512400.SH` raw/qfq `242/242` bars from `2025-08-27` to `2026-08-27`, duplicate `0`, date-set difference `0`, coverage/QC passed; yfinance was behind ordinary freshness guard `2026-08-28`, so lifecycle readiness stayed false. Optional `MU` raw/qfq `252/252` bars from `2025-08-28` to `2026-08-28`, duplicate `0`, date-set difference `0`, coverage/QC and lifecycle readiness passed.
- PR #38 已获 `APPROVE_HOLDINGS_DATA_MANAGER_SKILL_V1` 并 squash merge 为 `e21935d17392a37ee9795e32a562e875dd741bfb`；merge 后 main exact-head CI `33362271501` success。未运行真实 holdings ADD/CLOSE，未写 Google Sheets，未访问账户或券商。
- Command bus v1 安全 closeout 已在 `ec38471` 完成：workflow job-level governed-repository/non-PR/EFSing actor-sender-issue-user guard、无 Google credentials injection；Python parser 的 sender/Issue-user/actor allowlist 保留为第二道 authoritative validation。
- Command bus focused `12/12`、holdings lifecycle focused `24/24`、full unittest `407/407` 通过；changed-file compileall 与 `git diff --check` 通过。dry-run 未实例化 `SheetsClient` 或 `HoldingsDataManager`，未写 Sheets、访问账户/券商或触发策略/研究；`dry_run=false` 在 manager construction 前 fail closed。
- PR #39 已 squash merge：source head `d970d554eabd2001b980822d85ca6958ba5acc34`，merge commit `c40e278e307ce64c126ef899b4db9fa26c47bb61`；main exact-head CI `33371721311` success。
- 真实 transport smoke Issue #40 的 workflow run `33371774444` success；结果为 `DRY_RUN`、normalized symbol `MU`、market `US`、`history_rows_written=0`、`enabled=null`；machine-readable/human-readable comment、success/dry-run labels、Issue close 全部成功。未写 Google Sheets，未执行 `HoldingsDataManager.execute(...)`。
- LIVE_WRITE_ENABLEMENT_V1 source head `65651b4af10df321adf444bb25fd838e0df4b085`：无 Secret route step 只解析严格 v1 command 与既有 identity；dry-run/invalid route 无 Secret 且 gate disabled；live route 仅从既有 GitHub Secrets 注入并调用 `HoldingsDataManager.execute(...)`；workflow 以 non-canceling concurrency group 串行 command jobs；FAILED 回执不声称启用标的。
- LIVE_WRITE_ENABLEMENT_V1 closeout 的 focused `19/19`、full unittest `414/414`、changed-file compileall 和 `git diff --check` 均通过；该 closeout 当时未执行真实 ADD/CLOSE/REENTER/SYNC，之后 Issue #42 已记录首条真实 `ADD 512400` 成功，见当前事实区。
- PR #41 final head `919cbfc7be531d42ffdfbda508bd9c86ab1902c9` 的 exact-head CI `33377922272` success；经 Sol 授权 squash merge 为 `74dc7d2fc1ef26d27b663eba7b3321a64e801ead`，merge 后 main exact-head CI `33381760054` success。closeout 未执行真实 holdings command，未开始任何后续 Phase。

- SETUP_01 Decision/Risk v1 已从旧 PR #37 最小 reconciliation：独立 evaluator、strict first-confirmed identity/terminal semantics、T→T+1 OPEN execution、target-before-RR、fixed invalidations、development funnel、generic synthetic operational shadow 与相关 regression 已移植。`actual_entry != None iff outcome == EXECUTED`；RR skip 保留 `t1_open`/`actual_rr`，不保留 `actual_entry`。
- Development session identity 正式为 `DEVELOPMENT_SESSION_IDENTITY=FROZEN_DATASET_MARKET_SESSION_SET`；未来 production prerequisite 为 `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION`。本轮不接第三方 calendar，不改变 development funnel。
- Issue #42 production command evidence：`ADD 512400` / `CN` / `dry_run=false` / `512400.SH` / `SUCCESS` / `enabled=true` / `history_rows_written=480`。该事实已取自 GitHub machine-readable result comment；不访问真实账户或 Secrets。
- PR #43 merge closeout：Sol approval=`APPROVE_SETUP_01_DECISION_RISK_V1_RECONCILIATION`；squash merge commit=`3b300975e999a934533398a951e7ec34e80a17bd`；merge-after main exact-head CI `33404615092=success`；未添加 GitHub self-approval review。

- PR #35 已从最新 main squash merge 为 `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`，main CI `33298510168` success；PR #31 已关闭并记录 `superseded by #34`。
- Wave Scenario Engine v1 已实现：严格 `data <= as_of_date`、完整周边界、weekly parent → daily context、confirmed Swing、现有 Fibonacci regions、primary/alternate、证据/反证/规则计分、结构失效、context eligibility 与 fail-closed UNKNOWN/NO_VALID families。
- Wave Engine v1 测试覆盖 canonical/synthetic 场景、future append invariance、不完整当前周、weekly/daily state、confirmed/provisional、Fib region、primary/alternate coexistence 与 read-only shadow；focused `tests.test_wave` 为 `12/12` 通过。
- PR #36 previous review head `ca9ec6e93518e7e47c13f8f41a7f5751c9fd24d0` 的 exact-head CI `33300273163` 与只读 shadow `33300273180` success；当前 substantive head 为 `eed768bec92365615b05b0a8314cf555e44b22ac`，必须重新完成相同检查。previous shadow 对真实 10 个启用持仓生成 JSON/CSV artifact，未写 Sheets、历史、Decision 或交易字段。
- Final shadow summary：`symbols_requested=10`、`evaluated=9`、`errors=1`、`unknown_primary=5`、`unknown_primary_ratio=0.5`；primary counts 为 `DOWNTREND_OR_INVALID_FOR_LONG=3`、`WAVE_2_TO_3_CANDIDATE=1`、`UPTREND_UNKNOWN_WAVE=4`、`ABC_CORRECTION_CANDIDATE=1`、`NO_VALID_SCENARIO=1`；状态 `PARTIAL_DATA_QUALITY`。MU 的 `历史数据源` 为空，按 fail-closed 记录错误。
- SETUP_01 v1 已完成：独立 immutable model/evaluator、固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED` lifecycle、primary-only Wave Engine context、ABC/downtrend counter-scenario blocks、两类独立 invalidation、canonical Fib diagnostics、strict prefix replay 与 deterministic CONFIRMED/FAILED event identity。Wave 2 low 额外要求低于 Wave 1 peak，避免非 retracement 误判。
- Development structural replay 已完成：40/40 symbols、86,305 days、0 errors、1,404 events（745 CONFIRMED / 659 FAILED）；CN event distribution 299/313，US 446/346；唯一未终结 development candidate 为 STX/US ARMED。
- Real holdings shadow 已完成：10 requested / 8 evaluated / 2 errors；SETUP_01 states FAILED=5、WATCH=1、CONFIRMED=2；000725.SZ/CN 为当前 WATCH candidate；SIVE.SE freshness stale、MU empty historical source 均 fail-closed。
- Correctness closeout shadow summary：`symbols_requested=10`、`evaluated=8`、`errors=2`；8 个成功行的 qfq `history_last_date` 均与 `latest_completed_session` 对齐，5 个 US 标的均到 `2026-08-28`；SIVE.SE 因 `2026-08-27 < 2026-08-28` 为 `DATA_STALE`，MU 因空 `历史数据源` fail-closed；`returns_accessed=false`、`oos_accessed=false`、`sheets_written=false`。
- Phase 5J-v3 protocol、independent universe、holdout dataset、structure-only replay/parity 与 qualification 已完成并由 PR #30 合并；exact identities 见第 7 节和 `docs/CURRENT_STATUS.md`。
- loader 已修复 dataset → replay wrapper 的 provisional-hash cross-binding 顺序问题；现有 frozen identities 与研究结果不变，tracked wrapper integrity 为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。
- 本地 recovery bundle 已生成：`artifacts/frozen_backups/SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，3,086,881 bytes，ZIP SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；bundle 含 5 个文件，成员 hash 见 registry/recovery manifest。
- 外部 ChatGPT 审计已将 exact ZIP bytes 上传 Google Drive `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`，file ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`；独立重新读取后的 recovered ZIP SHA-256 与上传前完全一致。该 session 不重复访问 Google Drive。
- 本次治理初始化与本轮 cloud recovery correction：新增/更新治理文件与 governance test；不改变业务逻辑和 frozen artifact bytes。治理修正 commit 的 SHA 以 Git/PR 最终核对为准。
- Phase 5J-v4 exact Sol specification 已落为 machine-readable protocol、中文说明、hash-pinned loader 与 protocol regression tests；canonical protocol SHA-256 为 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`。本独立 freeze task 未运行真实 holdout attribution。
- Phase 5J-v4 在 40 symbols / 86,305 bars 上生成 258,915 trace rows、1,031 lifecycles、177 real first-divergence episodes；对 `origin/main@142b7345…` 完成 120 cells / 258,915 Setup bar comparisons / 1,028 terminal-event comparisons，Setup/event mismatches 均为 0。capsule file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，deterministic trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`；tracked provenance hashes 使用 Git-normalized LF bytes，跨 Windows/Linux 稳定。
- v5 clean holdout acquisition：冻结 universe 的 40/40 symbols 均 `VALID_ACCEPTED`，CN 42,355 + US 45,720 = 88,075 bars；dataset manifest `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29`，normalized aggregate `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`，replay aggregate `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76`；provider/QC exceptions=0，未使用 formal B1/IBKR。
- v5 ATR structure-only qualification：4 candidates 的 124-row matrix 中 candidate-level gates 全部通过，但 adjacent/lifecycle gates 使 `qualified_candidates=[]`、`selected_candidate_atr=null`；parity 为 280 cells / 616,525 bars / 3,253 terminal-event comparisons / 0 mismatches，deterministic repeat `PASS`。capsule canonical payload `sha256:5c799f5f9b2d2655c0dd1ff4fd773af32e3e05d805175d696791c80fe767a42b`，最终状态 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。
- `trading/setup.py` 的 `ATR_NORMALIZED_BOUNDARY_MODE` 保留用于研究复现，并明确标记为 `RESEARCH_ONLY` / `NOT_PRODUCTION_AUTHORIZED` / `FAILED_STRUCTURAL_CANDIDATE_FAMILY`；`main.py`、Sheets 参数解析、workflow 与 Decision 入口均不选择该 mode，percentage production default 与既有交易行为不变。
- PR #33 已完成远端 squash merge，merge commit 为 `b27f6c9052fe44bcec3d7ea4c3a05ac2efcb6d11`，main exact-head CI `33264260330` success；未启动 Wave Engine。
- PR #31 全部 diff 已审计：旧治理文件基于 `main@142b7345a5640b1e87932e41f3dc9311172bf54c`，不直接移植；本分支只重新实现 latest/full 隔离、source-date freshness、ordinary-calendar guard、future-date rejection 和时区归一化。
- 已完成生产根因链审计：`main.run()` 构造 latest row 时的 `交易日期` 只允许来自 `chosen.trade_date`，`抓取时间` 只来自北京时间 `fetched_at`；真实 Sheet 元数据与 `自选清单`/`最新行情` 已只读核对，目标表为「持仓股股票行情数据中台」。
- 已完成最终验证：全量 unittest `343/343`、focused validation/latest `64/64`、compile、`git diff --check` 与 PR #34 exact-head CI `33265845873` 均成功；实现 head 为 `a9a7a06d546412d4de390029baaa5ff4d44ee263`。
- 最终 production smoke：Asia `33265877563` 与 US `33265875055` 均为 workflow_dispatch/latest、成功，summary 分别为 `3/3 verified` 与 `6 verified + 1 single-source current/pending`，两者 `history_rows_written=0`、`decision_rows_written=0`。真实 Sheet 中 10/10 启用持仓交易日期均为 `2026-08-28`，SIVE 的 Friday 行来自 bounded Yahoo Chart；日期列为 DATE、运行时间列为北京时间 DATE_TIME。
- 最终状态：`PRODUCTION_HOLDINGS_DATE_BUG_FIXED_AND_LIVE_VERIFIED`；SIVE 保留单源待复核，未伪造双源验证。`HANDOFF_CURRENT_AND_CONSISTENT`。

## 4. Pending Work — Historical SETUP_02

### Historical Required Next

- [x] 从现场核对的 clean `main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7` 建立 `codex/setup02-wave3-continuation-v1`，并确认启动前无 open PR。
- [x] 实现独立 SETUP_02 structural evaluator/replay；只接受 primary `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`，不修改 Wave Engine 或 SETUP_01。
- [x] 固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED`、严格高点确认、Wave Engine structural invalidation、weekly/daily/primary failure blocks、terminal once-only event identity 与 future append invariance。
- [x] 完成冻结 DEVELOPMENT_EXPOSED structure-only replay：40/40 symbols、84,284 days、494 terminal events、0 errors、identity audit exactly-once。
- [x] 更新 protocol/status/decision docs，完成 focused/full unittest、compileall、`git diff --check`，并提交本地 source commit `ac63bd7`。
- [x] 创建 PR #45，base=`main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7`，等待 exact-head CI，核对 `OPEN / CLEAN / MERGEABLE`；不 merge。

### Historical Deferred

- SETUP_02 Entry/Exit/holdings/production integration、任何 outcome/backtest/OOS 与 production calendar 仍须等待后续明确授权；当前 Decision/Risk development 仅限本快照所述的 development-only、structure/decision/risk evidence。
- SETUP_01 production integration 与任何 SETUP_01 语义修改不属于本任务。
- 如需继续 SETUP_03，等待新的明确研究决策并注册新 protocol/version；当前结果不授权任何 threshold 或 production 选择。
- Final OOS、formal Phase 5K-B1、IBKR readiness 和任何 production parameter/strategy change。

### Historical Prohibited For Now

- 不实现 SETUP_02 Entry、Exit、holdings、production 或 outcome research；不进入 Final OOS。当前获授权的 Decision/Risk v1 仍不得扩展到这些路径。
- 不修改现有 Wave Engine、SETUP_01、Fibonacci canonical definitions、SETUP_01 Decision/Risk、SETUP_03 或 production calendars。
- 不危险 rebase 旧 PR；本任务只能创建本分支的单一 SETUP_02 PR，不自动 merge。
- 不读取真实持仓、账户数量、成本、NAV、盈亏、broker、Google Secrets 或 holdings-derived private data；不运行 private holdings shadow。
- 不改变 Google Sheets schema 或 holdings manager/command bus 业务逻辑。
- `CLOSE` 物理删除历史行情、校验记录、数据源映射或证券身份；任何 provider/history/QC 失败时错误启用标的。

## 5. Key Decisions And Rationale

### Decision

- 以 `HANDOFF.md` 管当前快照、`CURRENT_STATUS.md` 管正式状态、`DECISION_LOG.md` 管长期理由；artifact 的可恢复性单独由 policy + registry 管理。
- 重要 bytes 未进 Git 时，只有 `LOCAL_PRESENT`、`HASH_VERIFIED`、`PERSISTENT_BACKUP_PRESENT`、`RECOVERY_VERIFIED` 全部满足，才允许 `FULLY_RECOVERABLE`。
- Phase 5J-v3 当前结果保持 development-only / structure-only；没有新的授权前，不将其解释为生产参数决定。
- 持仓数据管理采用薄 Skill + 可测试 Python 编排；沿用 `自选清单.启用` 和现有历史/provider/QC/schema，不新增 registry；CLOSE 永久禁止删除历史，失败时 fail closed。

### Why

这样能把“下一步怎么接手”“正式状态是什么”“为什么这么决定”和“frozen bytes 怎么恢复”分开；旧聊天、本地目录或临时 CI artifact 都不能单独承担 correctness-critical provenance。

### Rejected Alternatives

- 仅复制完整 Git history 或继续依赖聊天记录：不能提供当前 exact PR/CI/artifact 对账。
- 把 ignored 大文件重新生成一份“相同逻辑”的文件：不能证明 exact bytes，违反 frozen identity。
- 仅记录 local ZIP：不能证明跨设备持久化和独立恢复。

### Revisit Condition

只有出现客观的新 Git/PR/CI/artifact evidence、approved storage policy 变化或明确授权扩大 research/production scope，才允许重审；identity 变化必须新建版本并保留旧版本。

## 6. Important Files Changed

| path | purpose | semantic impact / nature |
|---|---|---|
| `trading/setup02.py` | SETUP_02 Wave 3 continuation structural evaluator | independent structural lifecycle; no Decision/Risk or production behavior |
| `trading/setup02_replay.py` | strict-prefix replay and terminal event projection | deterministic structural evidence; no outcome fields |
| `scripts/run_setup02_structural_replay.py` | frozen DEVELOPMENT_EXPOSED replay runner | structure-only Sol review report; ignored derived artifacts |
| `tests/test_setup02.py` | lifecycle, causal, block, terminal-once and invariance regressions | SETUP_02 correctness coverage |
| `docs/SETUP_02_WAVE3_CONTINUATION_STRUCTURAL_V1.md` | SETUP_02 protocol and review boundary | protocol / governance |
| `trading/setup02_decision.py` | independent SETUP_02 Decision/Risk, target provenance, exact T+1 OPEN classification | T-day plan + read-only execution feasibility; no production path |
| `research/setup02_decision_funnel.py` | structure-only Decision/Risk conservation, provenance, quality and identity reporting | DEVELOPMENT_EXPOSED funnel; no outcome/OOS |
| `scripts/run_setup02_decision_funnel.py` | frozen v2 Decision/Risk funnel runner | 213 CONFIRMED development evidence; ignored derived artifacts |
| `scripts/run_setup02_generic_operational_shadow.py` | controlled synthetic-only operational validation | exactly-once/terminal/gap/open/RR/fail-closed/ledger gate |
| `.github/workflows/setup02-generic-operational-shadow.yml` | PR/manual synthetic-only operational gate | no credentials, holdings or Sheets |
| `tests/test_setup02_decision.py` / `tests/test_setup02_generic_operational_shadow.py` | Decision/Risk, provenance, exact-session, open-only and generic gate regressions | SETUP_02 Decision/Risk correctness coverage |
| `docs/SETUP_02_DECISION_RISK_V1.md` | Decision/Risk v1 protocol, frozen formulas and scope boundary | protocol / governance |
| `HANDOFF.md` | 当前操作交接快照 | governance；下一次会话的第一入口 |
| `AGENTS.md` | 新会话启动、冲突和更新 gate | governance；不改变交易规则 |
| `README.md` | 公开发现入口，链接治理文件 | documentation / governance |
| `holdings_data_manager.py` | 单标的身份规范化、ADD/REENTER/CLOSE/SYNC、历史缺口与审计编排 | 新持仓数据能力；不进入策略/账户路径 |
| `skills/holdings-data-manager/SKILL.md` | 上层自然语言 Skill specification、contract、示例与禁止动作 | 薄编排入口；不承载业务实现 |
| `docs/HOLDINGS_DATA_MANAGER.md` | 持仓生命周期、历史分离、schema 与 fail-closed 说明 | capability documentation |
| `tests/test_holdings_data_manager.py` | 持仓生命周期、自然语言、provider/QC、日期幂等和 unknown column regression | 新能力回归 |
| `holdings_command_bus.py` | v1 command schema、Issue envelope guard、result schema 和安全回执渲染 | transport contract；不承载 holdings 业务 |
| `scripts/holdings_command_bridge.py` | 从 `GITHUB_EVENT_PATH` 读取 event，执行 schema/identity guard，并委托现有 manager | dry-run/live gate bridge；不复制业务逻辑 |
| `.github/workflows/holdings-command.yml` | `issues.opened` command bus、最小权限、conditional live Secrets、串行门控、comment/label/close relay | live enablement；真实写入等待 Sol review |
| `tests/test_holdings_command_bus.py` | schema/actor guard、dry-run no-Sheets、live ADD delegation、FAILED/idempotency/secret/workflow contract | command bus/live-write regression |
| `docs/HOLDINGS_COMMAND_BUS.md` | architecture、schema、权限、fail-closed、conditional credentials、幂等和 review stop | protocol / governance |
| `sheets_client.py` | 增加保留未知列的单行 `自选清单` upsert | additive Sheet adapter；无 schema 变化 |
| `docs/CURRENT_STATUS.md` | 正式状态、PR/CI 对账和下一步 | governance/status；修正已核实的 stale PR labels |
| `docs/DECISION_LOG.md` | 记录本次治理设计的长期理由 | governance / decision history |
| `docs/FROZEN_ARTIFACT_POLICY.md` | artifact 恢复与状态规则 | governance / protocol |
| `docs/FROZEN_ARTIFACT_REGISTRY.json` | 当前重要 artifact 的机器可读 identity/status | governance / registry |
| `research/protocols/setup03_phase5j_v4_lifecycle_attribution_protocol.json` | Phase 5J-v4 machine-readable frozen protocol | research protocol；真实 attribution 前冻结 |
| `research/protocols/setup03_phase5j_v4_lifecycle_attribution_protocol.md` | Phase 5J-v4 中文协议说明 | research protocol documentation |
| `research/phase5j_v4_protocol.py` | version/hash/invariant loader | research-only integrity gate |
| `tests/test_phase5j_v4_protocol.py` | protocol immutability regression | research protocol tests |
| `trading/setup.py` | additive read-only lifecycle operands | production Setup/event outputs unchanged by exact-main parity |
| `research/phase5j_v4_lifecycle_attribution.py` | trace, FIRST_DIVERGENCE_BAR, root/propagation/lineage/counterfactual | research-only |
| `research/phase5j_v4_evidence.py` | mechanical aggregation, parity, concordance, hashes/report | research-only |
| `scripts/run_phase5j_v4_lifecycle_attribution.py` | frozen end-to-end runner | no provider/outcome/OOS path |
| `research/development/phase5j_v4_*` | capsule/report/per-symbol/root/cascade/counterfactual/concordance artifacts | tracked development-only evidence |
| `research/atr_boundary_protocol.py` / `research/protocols/setup03_atr_boundary_structural_qualification_protocol.json` | v5 ATR boundary protocol/hash gate | research-only frozen contract |
| `research/atr_boundary_universe.py` / `research/atr_boundary_universe_manifest.json` | metadata-only final clean roster | selection before OHLCV; result-independent |
| `research/atr_boundary_dataset.py` / `research/atr_boundary_clean_holdout/*` | new clean-holdout acquisition and tracked manifests | BaoStock/yfinance development data identity |
| `research/atr_boundary_qualification.py` / `research/atr_boundary_qualification/*` | structure-only candidate/adjacent/lifecycle matrix, parity and repeat | no Decision/outcome/OOS path |
| `scripts/acquire_atr_boundary_holdout.py` / `scripts/run_atr_boundary_qualification.py` | bounded acquisition and qualification runners | explicit stop-state output |
| `core.py` / `providers.py` / `main.py` | production latest quote date, source freshness and execution-mode isolation | P0 hotfix; trade behavior unchanged |
| `.github/workflows/asia-close.yml` / `.github/workflows/us-close.yml` | scheduled latest-only and manual full mode routing | production workflow boundary |
| `tests/test_validation.py` / `tests/test_decision_sheet.py` / `tests/test_governance.py` | market-local date, source mismatch, future-date and latest-only regression | regression coverage |
| `trading/models.py` / `trading/fibonacci.py` / `trading/wave.py` | Wave Scenario Engine v1 models, Fibonacci regions and strict causal evaluator | additive read-only structural context |
| `scripts/run_wave_shadow.py` | private/local real-holdings JSON/CSV shadow capability | not invoked; no GitHub Actions workflow; no holdings-derived output |
| `tests/test_wave.py` / `docs/WAVE_SCENARIO_ENGINE_V1.md` | Wave Engine regression contract and protocol documentation | v1 semantics / governance |
| `trading/setup01.py` / `trading/setup01_replay.py` | SETUP_01 immutable lifecycle evaluator, strict prefix replay and terminal event identity | separate SETUP_01 structural layer; no SETUP_03 behavior change |
| `trading/setup01_decision.py` / `research/setup01_decision_funnel.py` | independent SETUP_01 Decision/Risk v1 and DEVELOPMENT_EXPOSED funnel | T-day plan + exact T+1 OPEN; no outcome/OOS |
| `scripts/run_setup01_decision_funnel.py` / `scripts/run_setup01_generic_operational_shadow.py` | development funnel and synthetic-only generic operational shadow | generic gate; no real holdings, Secrets or Sheets |
| `scripts/run_setup01_decision_shadow.py` | optional private/local Decision shadow capability | `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY` |
| `.github/workflows/setup01-generic-operational-shadow.yml` | synthetic-only generic operational shadow workflow | no credentials; no holdings-derived data |
| `tests/test_setup01_decision.py` / `tests/test_setup01_generic_operational_shadow.py` | Decision/Risk, execution ledger, provenance, session, generic gate regressions | no rule changes |
| `docs/SETUP_01_DECISION_RISK_V1.md` | Decision/Risk v1 protocol, ledger invariant and session identity | protocol / governance |
| `docs/SETUP_01_WAVE2_TO_WAVE3_V1.md` | SETUP_01 v1 protocol, lifecycle, invalidation, Fib and as-of contract | protocol / governance |
| `scripts/run_setup01_structural_replay.py` / `research/development/setup01_wave2_to_wave3_v1_structural_diagnostic.*` | development-only structure replay and compact Sol evidence | no outcomes/OOS/Decision/Sheets |
| `tests/test_setup01.py` | synthetic lifecycle, invalidation, ABC/downtrend, confirmed/provisional and future invariance regression | SETUP_01 correctness |

## 7. Frozen Identities And Invariants

- Wave Engine protocol: `WAVE-SCENARIO-ENGINE-2026-08-30-v1`；fixed as-of uses only `data <= as_of_date`，weekly aggregation excludes Monday–Thursday incomplete ISO week，and daily continuation requires current daily `UPTREND`。
- SETUP_01 protocol: `SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`；eligible primary context is confirmed LOW→HIGH→LOW with `peak > origin`, `wave2_low > origin`, `wave2_low < peak`, weekly parent not DOWNTREND, and `setup01_context_eligible=true`。
- SETUP_01 lifecycle invariant: `NONE/WATCH/ARMED/CONFIRMED/FAILED`; ARMED uses fixed causal 0.5 recovery, CONFIRMED requires close strictly above Wave 1 peak, and origin versus confirmed Wave 2 low remain separate invalidations. No ACTIVE/COMPLETED state, no Fib hard gate, no production ENTRY/Decision.
- SETUP_02 protocol: `SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1`；only primary `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`, causal LOW0→HIGH1→LOW2→HIGH3, `HIGH3>HIGH1`, `LOW2>LOW0`, daily/weekly `UPTREND`, and existing Wave Engine `structural_invalidation`.
- SETUP_02 lifecycle invariant: `NONE/WATCH/ARMED/CONFIRMED/FAILED`; recovery is `invalidation + 0.5 × (HIGH3-invalidation)`, ARMED is bounded through HIGH3, confirmation is the first daily close strictly above HIGH3, and terminal event identity is first-entry only. Historical terminal state persists across refresh; no Decision/Risk/Entry/Exit.
- SETUP_02 replay evidence: frozen dataset v2 manifest SHA=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`, 40 symbols / 84,284 bars; replay aggregate SHA=`sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18`; 494 unique terminal events, identity duplicates/mismatches `0/0`。
- SETUP_02 Decision/Risk corrected protocol: `SETUP-02-DECISION-RISK-2026-09-02-v2`; first-entry CONFIRMED only, T close plan, `[HIGH3, HIGH3+0.5*ATR14(T)]`, event-carried invalidation, `invalidation-0.5*ATR14(T)` execution stop, Wave3 target `LOW2 + (HIGH1-LOW0)*existing ratio`, target-first/RR-second, exact T+1 OPEN only, and `actual_entry != None iff outcome == EXECUTED`。旧 invalidation→HIGH3 projection 已撤回，不是正式冻结语义。
- SETUP_02 corrected Decision funnel evidence: 213 first CONFIRMED → 213 Decision; `ENTRY_ALLOWED=1`; `ABOVE_ENTRY_ZONE=97`, `STALE_CONFIRMATION_GEOMETRY=12`, `NO_VALID_TARGET=1`, `RR_BELOW_MINIMUM=102`; CN/US=`74/139`; T+1 attempts/executed=`1/0`, with `SKIP_GAP_BELOW_CONFIRMATION=1`; T1 source=`CONFIRMED_SWING_HIGH 44 / WAVE3_FIB_EXTENSION 59`; extension ratios=`1.272 61 / 1.618 75 / 2.0 84 / 2.618 102`; >5R=`0`; missing T+1=`0`; exact-once/conservation/ledger all pass。
- Development evidence: 40 symbols / 86,305 days / 1,404 events (745 CONFIRMED / 659 FAILED) / 0 errors; real shadow run `33300273180`: 10 enabled / 8 evaluated / 2 fail-closed errors, no returns/OOS/Sheets writes。
- SETUP_01 Decision/Risk v1 identity: `SETUP-01-DECISION-RISK-2026-08-30-v1`; first T-day `CONFIRMED` identity only, exactly-once, T close plan, exact T+1 OPEN, fixed Entry Zone/stop, target-before-RR, and no same-bar execution。
- Execution-ledger invariant: `actual_entry != None` if and only if `outcome == EXECUTED`; `t1_open` is observed T+1 OPEN and remains populated for diagnostics; skipped outcomes keep `actual_entry=None`。
- Development session identity: `DEVELOPMENT_SESSION_IDENTITY = FROZEN_DATASET_MARKET_SESSION_SET`; production prerequisite: `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION`; no third-party calendar is added in this task。
- SETUP_02 corrected target provenance: T1 source=`CONFIRMED_SWING_HIGH 44 / WAVE3_FIB_EXTENSION 59`; all legal Wave3 candidates use `LOW2 + (HIGH1-LOW0)*ratio`, ratios=`1.272 61 / 1.618 75 / 2.0 84 / 2.618 102`; >5R count `0`, missing T+1 `0`。

- Phase 5J-v3 event-matching protocol: `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`, canonical SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。
- Phase 5J-v4 lifecycle-attribution protocol: `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`, canonical SHA-256 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`；state `LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED`。
- Phase 5J-v4 attribution capsule: file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，canonical payload `sha256:a2e9a48cac483bca6aae9aeec4d5405634118632e7c34170aef863f24991e797`；ignored derived trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`。
- Holdout universe: `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2`, manifest SHA-256 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`；symbol-list SHA-256 `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`。
- Dataset: `SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1`，canonical manifest SHA-256 `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`，normalized aggregate `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`，replay aggregate `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`。
- Dataset coverage: CN 20 / 41,274 bars；US 20 / 45,031 bars；total 40 symbols / 86,305 bars；provider split is `BAOSTOCK_DEVELOPMENT_QFQ` / `YFINANCE_DEVELOPMENT_HISTORICAL`。
- Backup container: 3,086,881 bytes, SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；Google Drive persistent backup and independent cloud reread are externally verified, current status `FULLY_RECOVERABLE`。
- Recovery manifest records source artifact commit `3a2c6699559074161b56281dd16084264f7dc717` as a historical local-ref-only provenance pin；this is not the current remote `main` SHA and must not be silently rewritten.
- Invariants: no provider fallback/history splice/date fill/synthetic bar/OHLC mutation/result-driven symbol replacement；no future data; `signal(t)` only uses `data <= t`；frozen protocol, manifests, roster, hashes and exact replay bytes cannot be silently changed。
- v5 ATR protocol: `SETUP_03-ATR-BOUNDARY-STRUCTURAL-QUALIFICATION-2026-08-29-v1`, SHA-256 `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`；clean universe `SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1`, manifest SHA-256 `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b`。
- v5 dataset: 40 symbols / 88,075 bars；manifest SHA-256 `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29`，normalized aggregate `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`，replay aggregate `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76`。
- v5 qualification: candidates `1.0/1.5/2.0/2.5` all candidate-level PASS；adjacent/lifecycle gates leave `qualified_candidates=[]`，selected candidate `null`，parity/repro PASS；final status `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。Capsule canonical payload `sha256:5c799f5f9b2d2655c0dd1ff4fd773af32e3e05d805175d696791c80fe767a42b`。
- Production date invariants: `交易日期 = chosen quote 的市场真实 session trade_date`；`运行时间 = 北京时间 fetched_at`。US 交易日期保持 US local session date，不因北京时间跨日加一天；A股交易日期保持 A股市场日期；两者不得互相替代。

## 8. Known Issues / Blockers — Historical

| category | status / impact | workaround | blocks continuation? |
|---|---|---|---|
| current task verification | corrected SETUP_02 code/tests/replay are locally complete; PR #50 corrected source head and exact-head CI/mergeability are verified | keep PR #50 open for Sol review; do not merge | No |
| development evidence boundary | replay uses frozen local DEVELOPMENT_EXPOSED v2 (40/40, 84,284 bars), not formal validation or Final OOS | keep all reports structure/decision/risk-only and retain dataset/manifest pins | Yes for any production/formal-validation claim |
| artifact/data availability | second-holdout bundle is `FULLY_RECOVERABLE`; Google Drive object ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS` and recovered ZIP SHA-256 are recorded from external audit | do not repeat cloud network verification; use registry identity and existing loader evidence | No |
| environment / verification | PR #43 merged at squash commit `3b300975e999a934533398a951e7ec34e80a17bd`; pre-merge exact-head CI `33402171900` and generic shadow `33402171991` success; merge-after main exact-head CI `33404615092` success | keep the post-merge main SHA and CI as live GitHub evidence; docs-only governance commit does not self-reference its own SHA | No |
| research/design blocker | v5 预注册 ATR family 已完成；candidate-level 全通过但 adjacent/lifecycle qualification 未通过，结果为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` | 不选择 threshold，不改 terminal/rearm；后续需新的明确研究决策和新 protocol/version | Yes for any further SETUP_03 research or production/strategy change |
| protocol persistence | v5 protocol 已冻结，SHA `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`；clean universe manifest SHA `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b` | 先提交/push freeze checkpoint，再获取 OHLCV；任何 identity 变化新建版本 | No after freeze commit |
| Sol / user decision node | SETUP_03 remains `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`; Issue #42 production `ADD 512400` succeeded; PR #43 is merged | stop at `SETUP_01_DECISION_RISK_V1_MERGED`; wait for the next Sol decision and do not start another Phase | Yes for continuation |
| shadow data quality | 10 个启用持仓中 8 个完成评估；SIVE.SE qfq `2026-08-27` 相对 freshness 下限 `2026-08-28` 为 `DATA_STALE`，MU 的 `历史数据源` 为空，均 fail-closed，整体 `PARTIAL_DATA_QUALITY` | 补齐明确历史源后另行运行 shadow；禁止默认猜测 provider 或写入 Sheets | Yes for claiming full 10/10 evaluation |
| project coordination | PR #37 was old-base `OPEN / CONFLICTING / DIRTY`, closed without merge and superseded by PR #43; #43 is based on current main | do not merge #37; Sol reviews/decides #43; no unrelated PR or next Phase | No, if kept separate |
| environment | 初始检查时存在的 `.hotfix-worktree/` 在 post-commit 检查时已不再存在；未执行删除命令 | 若重新出现，保持隔离并排除 governance commit | No |

## 9. Lessons / Pitfalls — DO NOT REPEAT

### Pitfall 1

**What happened:** 文档中的 PR 状态曾落后于真实 GitHub 状态，例如已合并 PR 仍写成待审阅/待合并。

**Root cause:** 只依赖旧文档，没有在交接时按 exact head 查询远端 PR。

**Consequence:** 新会话可能重复工作或错误判断 base/stacked branch。

**Permanent prevention rule:** 每次独立任务结束和新会话开始都核对远端 PR number/state/head SHA/merge SHA，并在 HANDOFF 中记录。

### Pitfall 2

**What happened:** 本地 `origin/main` 仍为旧 SHA，而 GitHub `main` 已推进。

**Root cause:** remote-tracking ref 没有刷新，且旧 ref 看起来像有效基线。

**Consequence:** 本地 merge-base、diff 和 PR 预判可能错误。

**Permanent prevention rule:** 关键决策前必须 `git fetch origin main`，并将本地 ref 与 GitHub API/PR base SHA 对账；无法对账时标记 `PROJECT_GOVERNANCE_STATE_CONFLICT`。

### Pitfall 3

**What happened:** frozen replay wrapper 曾绑定 provisional dataset SHA，而不是包含 replay aggregate 的 final dataset SHA。

**Root cause:** 生成顺序为 wrapper 先于 final dataset manifest。

**Consequence:** provenance cross-binding 错误，虽未改变 bars，但破坏了恢复身份的可信度。

**Permanent prevention rule:** 固定顺序为 normalized data → replay input/aggregate → final dataset manifest → replay wrapper；loader 必须 fail closed 验证所有 cross-bindings。

### Pitfall 4

**What happened:** correctness-critical payload 只存在 ignored `artifacts/` 或短期 CI artifact。

**Root cause:** Git 中只保留 manifest/report，未登记持久化备份与恢复证据。

**Consequence:** 新电脑无法按 hash 恢复 exact input，不能声称 fully recoverable。

**Permanent prevention rule:** 每个重要 artifact 必须进入 registry；未满足 local/hash/persistent/recovery 四项时，状态明确不是 `FULLY_RECOVERABLE`，禁止用近似重生成替代。

### Pitfall 5

**What happened:** branch 名称暗示 Phase 5J-v4，而治理快照曾只证明 v3 holdout 与 backup staging；本轮用户已明确确认 v4 frozen task 可继续。

**Root cause:** branch naming 曾被误当作正式 objective/protocol；本轮必须以用户确认和仓库可核对的 protocol/evidence 共同落地。

**Consequence:** 可能在 backup prerequisite 未完成或 scope 未核实前启动未授权研究。

**Permanent prevention rule:** branch name 只能作为线索；正式任务必须由 HANDOFF/CURRENT_STATUS、用户本轮授权、protocol、PR/commit 和客观 artifact evidence 共同确认。

## 10. Next Action

1. [x] `git fetch origin`，核验真实基线 `origin/main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`，并在其上创建本任务分支。
2. [x] 完成 production prerequisites、Daily Chain、Portfolio Risk 真实调用关系审计；未改变冻结策略几何与风险比例。
3. [x] 实现无 NAV strategy proposal 与显式 `allocation_budget` 后的 Portfolio Risk / Position Size 边界。
4. [x] 完成 focused/full unittest、compileall、`git diff --check`、Daily Chain 17/17 shadow 与 Portfolio Risk synthetic shadow。
5. [x] 提交、push、创建 PR #70 并核对 PR exact head、mergeability 与 exact-head CI；三个 checks 均 success。
6. [x] 执行严格只读 `--preflight --date 2026-09-04`；connector-backed adapter result=`READY`，QFQ/NAV blockers=`0`；未执行 `--run`/`--write-state`，未触及 broker/order 或 live strategy-state write。
7. [x] 已依据真实 CI/preflight 结果更新本节；停止在 `PR_FULLY_READY_AND_PREFLIGHT_READY_FOR_SOL_REVIEW`，不 merge PR，等待用户 review。
8. [x] Sol review 修复 A/B/C：显式 `approved_event_identities` approval contract、`allocation_budget` 正式总预算语义、substantive/current PR head 治理分离；未改 `ENTRY_ALLOWED` 技术条件与冻结风险比例。
9. [x] 新增 8 个 approval/budget 回归并完成 focused/full unittest、两个 generic shadow、compileall、protocol JSON parse 与 `git diff --check`。
10. [x] 更新治理文件与协议后 commit 并 push 到现有 PR #70；不新建 PR、不 merge；current PR head 与 exact-head CI 以 GitHub 实时核验为准。
11. [x] Sol correctness review 已 APPROVED；PR #70 exact-head CI 全部 SUCCESS；已记录 `PR_70_SOL_APPROVED_READY_FOR_MERGE`；本 agent 不 merge，当前唯一 next action 为 merge PR #70。

## 11. Handoff Checklist

- [x] Current state names formal task baseline `main@2ce2711f4994f31c167bbe4961ecd0b34e90c476` and current branch `fix/strategy-capital-allocation-boundary`；substantive source head=`bb8e6d9a23a175ff01790314837e24621446ce1c`。
- [x] Real Asia/US scheduled run IDs and QFQ evidence remain recorded in prior section 0F；latest governance PR #69 is merged。
- [x] Scoped replacement proves target rolling series stays at `history_days` and removes the old adjustment basis；non-target history is preserved。
- [x] Any target fetch/validation failure produces zero workbook writes；only `历史行情_前复权` is in the mutation boundary。
- [x] Focused/full tests, compileall, `git diff --check`, and synthetic boundary shadows are complete。
- [x] Scheduled latest automatic QFQ refresh capability remains unchanged；manual live QFQ refresher smoke=`NOT_RUN`；live Sheets/state/broker/order mutation=`NO`；production state writes=`NO`。
- [x] Provider smoke and one authorized US rerun passed for both formal US symbols at target `2026-09-04`；CN+US QFQ is verified；the prior NAV freshness blocker is retired for proposal preflight by this task's boundary decision。
- [x] PR #70 exact-head CI checks `33952922439` / `33952922429` / `33952922432` all success；PR remains OPEN/MERGEABLE/merged=false。
- [x] Connector-backed live read-only preflight T=`2026-09-04` is READY with CN `3/3` and US `2/2` DATA_OK, QFQ/NAV/risk-group blockers=`0`, state-store=`OK`, and no writes。
- [x] Sol review 修复后 `allocation_budget` 不再是 approval；批准仅按已发布 proposal 的 event identity，且 pending/settled 重复批准 fail closed；未批准 `ENTRY_ALLOWED` 保持 `STRATEGY_PROPOSAL`。
- [x] `allocation_budget` 语义固化为账户整个策略风险账本的用户总预算，denominator 与 existing positions 共用；NAV/资产/入出金/P&L/purchasing power 均不是该预算。
- [x] `bb8e6d9a23a175ff01790314837e24621446ce1c` 仅作为 substantive source head 记录；current PR head 以 GitHub 实时核验为准；本文件不自引用 docs closeout SHA。
- [x] 修复回归与全量验证完成：Daily Chain `31/31`、Production Prerequisites `19/19`、full `596/596 OK`、Daily Chain shadow `17/17 SUCCESS`、Portfolio Risk shadow `17/17 SUCCESS`、compileall/protocol JSON/`git diff --check` 通过。

## 12. Last Verified

- `last_updated_at`: `2026-09-06`
- `formal_main_baseline`: `f65f76eb06592a17a897e4a27560e3d5db2c04f9`
- `current_branch`: `codex/sector-candidate-universe-v1-feasibility`
- `current_main_exact_sha`: `f65f76eb06592a17a897e4a27560e3d5db2c04f9` (verified `origin/main`)
- `substantive_implementation_head`: `2d63fda031cda08dd2bf5bf631b9a9ea09ace415`
- `current_pr`: PR #71=`https://github.com/EFSing/stock-data-pipeline/pull/71`；base=`main`；
  `OPEN / MERGEABLE / merged=false`；PR final tip and exact-head CI remain live GitHub facts，
  not a self-referenced governance SHA。
- `source_runtime_proof`: BaoStock adapter=`800` CN union seeds with `800/800` basic+sector
  metadata；IWB official adapter=`1018` Equity rows, source date=`2026-09-03`。
- `latest_test_result`: candidate focused `10/10 OK`；full unittest `606/606 OK`；
  `compileall` and `git diff --check` pass；final PR checks must be read from GitHub exact tip。
- `scope_boundary`: bounded read-only candidate rows only；no production Sheets/state writes,
  broker/order, holdings read, SETUP_03/04 or new research phase；不自动 merge。

`PR_FULLY_READY_FOR_SOL_REVIEW`

`HANDOFF_CURRENT_AND_CONSISTENT`

## 10A. Historical Next Action — PORTFOLIO_RISK_V1

1. [x] PR #51 closeout 已完成：source head=`2dbb7a751916921a29360b28467de92e150683e3`，squash merge=`993d03e428b7eb11da791a608940c9d77a608f96`；merge-after CI=`33607481962` success。
2. [x] PR #59 四个 implementation commits 已从远端恢复；frozen archive 81/81 hash/size 与 loader 的 40 symbols/84,284 bars 已验证。
3. [x] 已完成本地 rebase 到真实最新 `main@f53ae42b85ca9e3e5a3bd6e8b91d919b1de0aa24`；冲突仅为治理文档，核心策略/risk 文件无冲突。
4. [x] 完成 corrected formula、constants、upstream invariance、focused/full test、compileall 与 `git diff --check` gates。
5. [x] 已安全推送并核对 PR #59 exact-head CI/generic shadow；不 merge PR #59。
6. [ ] 等待 Sol review；不得自动 merge。

## 11A. Historical Handoff Checklist — PORTFOLIO_RISK_V1

- [x] 当时 Objective 已更新为 Portfolio Risk V1 rebase/review closeout
- [x] 真实远端 main/head/tag 与 PR #59 状态已核对
- [x] frozen archive SHA、81/81 payload hashes/sizes、40 symbols/84,284 bars 已验证
- [x] scope boundary 明确：不改 upstream strategy semantics，不访问 holdings/account/Secrets/Sheets，不运行 outcome/OOS
- [x] rebase 仅遇治理文档冲突，未触碰 Portfolio Risk 或上游策略核心文件
- [x] corrected semantic invariance、focused/full tests、compileall 与 `git diff --check` 已完成
- [x] rebased validation tip 的 exact-head `CI Test Gate` 与 generic shadow 均 success；PR 保持 OPEN / CLEAN / MERGEABLE / merged=false

## 12A. Historical Last Verified — PORTFOLIO_RISK_V1

- `last_updated_at`: `2026-09-02`
- `verified_origin_main_sha`: `f53ae42b85ca9e3e5a3bd6e8b91d919b1de0aa24` (live GitHub)
- `latest_substantive_implementation_sha`: `96d3d52ef7baf6dacc0f464a07ca7a1c8b9ca1c0`; remote pre-rebase head=`d1016f217eb34108776d8c73b317ce47ed077025`
- `historical_branch`: `codex/portfolio-risk-v1`; PR #59 remains OPEN and unmerged
- `portfolio_risk_protocol`: `PORTFOLIO-RISK-2026-09-02-v1`; constants `0.005 / 0.02 / 0.01`; development NAV=`1.0`
- `frozen_dataset`: 40 symbols / 84,284 bars; archive SHA=`sha256:15e3c63da65cd1eba52ecd6d441be22d6556e9ae2008f70c652a01bb7b0eaeb2`; manifest SHA=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`
- `latest_test_result`: full unittest `529/529 OK`; Portfolio Risk focused/replay `27/27 OK`; generic operational shadow `17/17 SUCCESS`; Position Management `22/22 OK`; SETUP_01/02 `57/57 OK`; cache parity `3/3 OK`; compileall and `git diff --check` pass; validation tip `e80c61bd72953754802290ee09e8171b5ffd447c` exact-head CI runs `33645523150` / `33645523141` success
- `scope_boundary`: downstream Portfolio Risk only; no upstream strategy, holdings, broker, account, Secrets, Sheets, outcome, or OOS access
- `next_action`: Sol review handoff; do not merge

`HANDOFF_CURRENT_AND_CONSISTENT`

## 10B. Historical Next Action — PROSPECTIVE_DAILY_DECISION_CHAIN_V1

1. [x] PR #59 Portfolio Risk V1 已完成授权 closeout：squash merge=`dc03631b80c6118e0ef088739de277ab50f17220`；merge-after `CI Test Gate`=`33647739171` success。
2. [x] 已从真实 merged main 创建 `codex/prospective-daily-decision-chain-v1`，完成 Daily Chain V1 implementation、Sol finding hardening、focused/full tests、compileall、diff-check 与 17-case generic shadow。
3. [x] 本轮多标的 blocker-preservation narrow fix 与 regression 已在 substantive source commit=`90dffa5c311a24abeadbd472a35e77f40b754828` 完成并 push；既有三项 closeout 未重做语义改动。
4. [x] Sol-approved exact PR head=`58dfb1448fa73efd50856d989c42801664eb9419` 的 exact-head CI Test Gate=`33709065926`、Daily Chain shadow=`33709065929`、Portfolio Risk shadow=`33709065934` 均 success。
5. [x] PR #64 已 squash merged：真实 merge commit=`74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`；merge-after main CI Test Gate=`33711976436` success。
6. [x] 已 fetch / switch main 并确认本地 `main` 与 `origin/main` 均为 `74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`，且 merge commit 已包含在远端 main；不重跑 frozen research replay。
7. [ ] 在 main protection 允许的最小范围内完成本治理同步；不夹带代码/新功能，不启动 production wiring 或新 Phase。

## 11B. Historical Handoff Checklist

- [x] 当时 Objective 已切换为 Prospective Daily Decision Chain V1。
- [x] 真实 merged main、Portfolio Risk PR #59 merge SHA 与 merge-after CI 已核对。
- [x] Daily Chain contract 明确 T 日 `data <= T`、same-day new CONFIRMED、exact identity、T/T+1 phase、Portfolio Risk constants 与 fail-closed prerequisites。
- [x] Sol hardening 已覆盖 data-before-PM、canonical open-position merge/conflict、dual-CONFIRMED invariant guard、protocol-only settlement、mixed as-of 与 prerequisite report classification；未改冻结策略语义。
- [x] 生产 audit 已完成：strategy universe、NAV、risk group、position origin、exact calendar、persistent store 均没有现成 authoritative SSOT；未用 watchlist/holdings/weekday guard 偷换。
- [x] focused/full unittest、17/17 synthetic shadow、compileall 与 `git diff --check` 已完成；未访问 broker/holdings/Secrets/Sheets，未做 real-data shadow。
- [x] 新 PR #64 已创建；implementation tip 的 final exact-head CI/shadow 已 success；docs-only governance closeout 不自引用其自身 SHA。
- [x] Sol review hardening 已完成；双-CONFIRMED 经 Wave/Setup formal contract 审计为不可达，新增 guard 仅 fail-closed，不改变策略优先级或其他冻结语义。
- [x] T+1 `DATA_BAD` / `DATA_STALE` / `DATA_UNAVAILABLE` 与 missing expected bar 均保持 pending、无 execution/settlement/release/PositionOrigin；`DATA_OK` + exact bar 保持原 settlement 语义。
- [x] 已知 `OpenPositionState` 缺少 `portfolio_position` 时，新的 `ENTRY_ALLOWED` 被 `PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED` 阻断，不把它视为无持仓。
- [x] 多标的 batch 中，预先保存的 blocker 与其他 symbol 的正常 reservation mapping 同时保留；SYMBOL_A 无 reservation/pending，SYMBOL_B 正常获得自身 reservation。

## 12B. Historical Last Verified

- `last_updated_at`: `2026-09-03`
- `verified_origin_main_sha`: `74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4` (live GitHub)
- `current_branch`: `main`; `main` and `origin/main`=`74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`; PR #64 MERGED / merged=true; approved PR head=`58dfb1448fa73efd50856d989c42801664eb9419`; substantive source=`90dffa5c311a24abeadbd472a35e77f40b754828`
- `latest_test_result`: Daily Chain=`20/20`; Portfolio Risk=`24/24`; Position Management=`18/18`; Daily Chain generic shadow=`17/17 SUCCESS`; Portfolio Risk generic shadow=`18/18 checks`; full unittest=`549/549 OK`; compileall and `git diff --check` pass; approved-head runs=`33709065926 / 33709065929 / 33709065934` success; merge-after main CI Test Gate=`33711976436 SUCCESS`
- `scope_boundary`: Sol review correctness hardening only; no SETUP_03/04, new Phase, broker/order, holdings mutation, Sheets strategy write, real-data shadow, parameter tuning, or OOS
- `next_action`: `PROSPECTIVE_DAILY_DECISION_CHAIN_V1_MERGED`; sync governance files, then stop; no new Phase

`HANDOFF_CURRENT_AND_CONSISTENT`
- `final_remote_head_and_exact_checks`: approved PR head=`58dfb1448fa73efd50856d989c42801664eb9419` passed CI=`33709065926`, Daily Chain shadow=`33709065929`, and Portfolio Risk shadow=`33709065934`; squash merge=`74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`; merge-after main CI=`33711976436 SUCCESS`.
- `portfolio_risk_merge`: PR #59 -> `dc03631b80c6118e0ef088739de277ab50f17220`; merge-after CI=`33647739171` success
- `daily_chain_protocol`: `PROSPECTIVE-DAILY-DECISION-CHAIN-2026-09-02-v1`
- `latest_test_result`: Daily Chain focused `20/20 OK`; Portfolio Risk focused `24/24 OK`; Position Management focused `18/18 OK`; Daily Chain generic shadow `17/17 SUCCESS`; Portfolio Risk generic shadow `18/18 checks`; full unittest `549/549 OK`; compileall and `git diff --check` pass; approved exact-head CI=`33709065926`, Daily Chain shadow=`33709065929`, Portfolio Risk shadow=`33709065934` success; merge-after main CI=`33711976436 SUCCESS`
- `production_shadow`: `NOT_RUN_PRODUCTION_STRATEGY_UNIVERSE_REQUIRED`
- `scope_boundary`: prospective read-only daily decision support only; no upstream semantics change, broker/order, holdings, account, Secrets, Sheets strategy write, outcome, or OOS
- `next_action`: governance sync only, then stop; `PROSPECTIVE_DAILY_DECISION_CHAIN_V1_MERGED`; no strategy development or production wiring

`HANDOFF_CURRENT_AND_CONSISTENT`
