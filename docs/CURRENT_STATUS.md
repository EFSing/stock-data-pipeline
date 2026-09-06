# CURRENT_STATUS.md — 项目当前进展

> 保持简短，用于告诉下一个 AI：项目现在到底开发到了哪里。每次开发结束都更新。

```text
Version:
V0.2
```

## Latest Engineering Event — PR_FULLY_READY_FOR_SOL_REVIEW

- Sol decision=`STRATEGY_HISTORY_RUNTIME_V1_MARKET_SPLIT_ACCEPTED`：CN 与 US 是不同
  收盘时段，必须独立 fetch/evaluate/summarize/fail；`--market all` 仅为开发便利，
  不作为 runtime acceptance 标准。当前分支仍为 `feat/candidate-strategy-shadow-bridge-v1`，
  substantive source head=`d3972cd36500ce1a090b981deef73b01177978f6`；PR #72 继续保持 open，
  current PR tip / exact-head CI 统一以 GitHub live verification 为准。
- runner 现支持 `--market cn|us|all --date YYYY-MM-DD`（`--as-of` 保留为兼容别名），
  每个市场独立返回完整/部分 summary；一个市场失败不会抹掉另一个市场的结果。报告固定
  记录 seed/metadata、candidate short-history network、candidate selector、deep raw-history
  network、adj-factor network、QFQ construction、DailyDecisionChain、report construction、
  total 九段 timing，以及每段 API requests、symbols、rows、usable/failed counts。
- CN 正式 runtime（`--market cn --date 2026-09-04`）=`CANDIDATE_SUCCESS`，总耗时
  `618.470s`（约 10.3 分钟）：seed `800`，Candidate usable `797`，included `513`；
  stage timings=`91.115/31.881/0.037/289.555/127.639/5.563/72.679/0/618.470s`；
  deep raw=`513/513`、`505,134` rows、`105` requests；adj_factor=`513/513`、
  `505,762` rows、`109` requests；exact-T anchor、factor-change validation、future/
  duplicate checks 与 DailyDecisionChain `513/513` 均通过。
- CN Strategy report：`final_status=NO_TRADE:513`；primary action=`NO_TRADE:425`、
  `WAIT_CONFIRMATION:88`；SETUP_01 `WATCH=52`、`ARMED=17`，SETUP_02 `WATCH=8`、
  `ARMED=11`；`STRATEGY_PROPOSAL=0`（合法结果，未压缩掉 WATCH/ARMED）。
- US 正式 runtime（`--market us --date 2026-09-04`）=`CANDIDATE_SUCCESS`，总耗时
  `422.718s`（约 7.0 分钟）：IWB seed `1018`，Candidate usable `1007`，included `220`；
  stage timings=`2.933/291.389/0.058/84.943/0/0/43.396/0/422.718s`；deep
  auto-adjusted QFQ=`220/220`、`217,895` rows、`3` requests，no future/duplicate/stale。
- US Strategy report：`final_status=NO_TRADE:220`；primary action=`NO_TRADE:195`、
  `WAIT_CONFIRMATION:25`；SETUP_01 `WATCH=9`、`ARMED=3`，SETUP_02 `WATCH=5`、
  `ARMED=8`；`STRATEGY_PROPOSAL=0`。US Candidate exclusions are explicit:
  `HISTORY_INSUFFICIENT=11`、`US_ONE_SHARE_NOTIONAL_OVER_1000=18`、
  `SECTOR_TOP_N_EXCEEDED=769`。
- PR #72 review corrections：US `YFINANCE_AUTO_ADJUSTED` 只允许
  `LATEST_COMPLETED_SESSION_ONLY`，`historical_replay_supported=false`；older/future/
  not-completed US T 在 yfinance deep-history 前 fail-closed，其中 older 使用
  `US_HISTORICAL_QFQ_ASOF_UNVERIFIED` / `READY_FOR_DECISION_US_HISTORICAL_QFQ_ASOF`。
  CN daily+adj_factor exact-T 语义未变。CN short-history reused 80-symbol probe 的 request
  accounting 已从 13 修正为精确 12（20/50/80 probes + remaining 720/80）。
- Tushare SDK contract 已在干净临时环境验证：`1.4.24` exact，20-symbol daily 返回
  `500` rows / `20` symbols，2-symbol adj_factor 返回 `8` rows，gateway success，
  credential output=`false`；requirements 已 pin 为 `tushare==1.4.24`。不因 pin 重跑完整
  CN runtime。
- 两个市场此前的 `2026-09-04` latest-session runtime 均 `runtime_acceptance=ACCEPTED` 且独立低于
  30 分钟；没有 production state/
  Sheets/allocation/broker/order write。CN temporary Tushare-compatible gateway 只服务本地
  read-only shadow，仍不是长期 production provider 决策；US 继续 IWB+yfinance，不接 Tushare。
- 旧文档 tip 与 live PR tip 不一致，已按 `PROJECT_GOVERNANCE_STATE_CONFLICT` 完成客观核对；
  current PR tip / exact-head CI 不再硬编码，统一以 GitHub live verification 为准。当前
  review correction implementation、focused/full tests、compileall、diff/secret checks、
  SAME PR #72 push 与新 exact-head CI 均已完成；current PR tip / exact-head CI 继续以 GitHub
  live verification 为准。

- focused bridge=`10/10`、full unittest=`623/623`、compileall、`git diff --check`、
  `local_tushare_config.py` ignored、tracked secret comparison=`0` 均通过。PR #72 保持
  `OPEN / CLEAN / MERGEABLE`，不合并。

`PR_FULLY_READY_FOR_SOL_REVIEW`

`HANDOFF_CURRENT_AND_CONSISTENT`

## Historical Engineering Event — READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME

- 当前工作分支为 `feat/candidate-strategy-shadow-bridge-v1`，基于真实远端 baseline
  `edb56d74c70415b407104f0de47ab29fca6ad506`；未创建 PR，未提交或覆盖用户已有的
  Tushare 本地工作树修改。
- 已实现两级 read-only bridge：CN Candidate 仍固定约 60 completed bars、既有
  `TOP_N_PER_SECTOR=20`；仅最终 included symbols 进入 Strategy history，CN 使用
  `daily + adj_factor` 固定 `5 symbols/request`、最多 1000 completed bars、exact T
  anchor；US 使用 official IWB holdings、yfinance batch short history，再对 included
  symbols 使用 auto-adjusted up-to-1000-bar batch history。未修改 Candidate semantics、
  Wave、Swing、Fibonacci、SETUP_01/02、Decision 或 Portfolio Risk。
- 真实 CN deep daily 曾完整返回 `513/513`、`505,134` rows、`103` requests；其中
  `438/513` 为 1000 bars，另有较短上市股票，但均达到 60-bar minimum、last bar exact
  T、无 future/duplicate。随后单个 factor chunk 的 transient request failure 按
  fail-closed 停止；加入一次固定 retry 后，另一次完整 combined runtime 在超过约 30
  分钟时仍未形成 CN+US final summary，已停止。未伪造 factor-change comparison、
  Strategy result 或 US result。
- 当前 blocker=`READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME`：现有 yfinance/Tushare
  combined full-history shadow 尚未证明在约 30 分钟内 bounded。需 Sol 决定是否接受该
  cadence 或指定经批准的固定批量/runtime 方案；本轮不引入 cache/database/concurrency
  framework，不接 production pipeline。
- 新增 bridge focused tests=`20/20 OK`；full unittest=`616/616 OK`、compileall、
  `git diff --check` 通过；`local_tushare_config.py` 保持 ignored、tracked secret matches=`0`。
  production state、Sheets、allocation、broker/order 均为 `NO`。

`READY_FOR_DECISION_STRATEGY_HISTORY_RUNTIME`

`HANDOFF_CURRENT_AND_CONSISTENT`

## Latest Engineering Event — READY_FOR_DECISION_CANDIDATE_BREADTH

- 逐 symbol history path 已停止；真实 `MULTI_SYMBOL_DAILY_BATCH` contract 在 60 个
  XSHG completed sessions 上成功：20=`1200 rows / 1.881s`，50=`3000 / 1.333s`，
  80=`4800 / 1.465s`，每次仅 1 个 API request，latest=`2026-09-04`，无 missing/error。
- CN HS300 ∪ CSI500 seed=`800` 采用固定 chunk=`80` 完成 short-history：`10` requests、
  `800` returned、`797` usable、`47,980` rows、network path 约 `16.647s`。三支少于 60
  bars 的 symbol (`002155.SZ`、`300567.SZ`、`688072.SH`) 进入既有
  `HISTORY_INSUFFICIENT`，未被伪造为 usable；未执行 date-major fallback。
- Candidate 结果保持原语义和 `TOP_N_PER_SECTOR=20`：seed=`800`、history usable=`797`、
  preferred=`682`、extended=`55`、affordability excluded=`58`、unsupported board=`2`、
  history/data-quality excluded=`3`、sector=`65`、TOP-N excluded=`224`、final included=`513`。
- included count 已知后才启动 QFQ。A `pro_bar(adj="qfq")` 被 gateway 拒绝；B
  `daily + adj_factor` 成为选定方案。`000725.SZ`、`002156.SZ`、`000333.SZ` 三支 CN
  equity 与现有 BaoStock qfq path 只读交叉验证均为 `60/60` date、`0 mismatch`，最大
  相对差=`5.86e-06`，容差=`0.002`；corporate-action boundary 已检查。正式配置参考的
  `512400.SH` 为 ETF，未返回 stock daily/adj_factor rows，未混入股票公式验证。
- included=`513` QFQ factor bulk=`7` requests、`30,780` rows、`513/513` exact-as-of
  anchors；使用 `raw_price(t) * adj_factor(t) / adj_factor(T)`。随后只读
  DailyDecisionChain=`513/513`，全部 `NO_TRADE`。production state、Sheets、allocation、
  broker/order 均为 `NO`。
- focused=`17/17 OK`，full unittest=`613/613 OK`；compileall、`git diff --check` 通过。
  当前状态=`READY_FOR_DECISION_CANDIDATE_BREADTH`，Candidate 未接入生产自动执行路径。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Latest Engineering Event — TUSHARE_GATEWAY_RUNTIME_PROBE_SUCCESS_BUT_HISTORY_RUNTIME_NOT_BOUNDED

- 已新增临时、只读 `trading/tushare_gateway.py`；配置唯一从项目根目录
  `local_tushare_config.py` 读取。该文件已加入 `.gitignore`，可提交模板为
  `local_tushare_config.example.py`；真实配置值不进入 Git、测试、日志或治理文档。
  缺失/未填写时明确 fail closed 为 `TUSHARE_LOCAL_CONFIG_REQUIRED`，不读取环境变量。
- 商家要求的 `import tushare as ts`、`ts.pro_api(TUSHARE_TOKEN)` 以及两个
  `pro._DataApi__...` 配置赋值已原样保留；新增只读 runner
  `scripts/run_candidate_strategy_shadow_bridge_v1_tushare_probe.py`。
- 真实 3 标的 smoke=`3/3 DATA_OK`、`375` rows、约 `7.641s`；CN candidate seed
  bounded sample=`20/20 DATA_OK`、`2500` rows、Tushare history request path
  `32.695s`，单标的约 `1.5–2.6s`。两次均未写 production state、Sheets 或 broker/order。
- 800 标的 full shadow 未运行、未伪造结果。按顺序请求的 20 标的实测线性外推约
  `21.8` 分钟，尚未证明日常 shadow budget 内 bounded；当前 blocker 为
  `TUSHARE_GATEWAY_RUNTIME_PROBE_SUCCESS_BUT_HISTORY_RUNTIME_NOT_BOUNDED`。
- focused=`13/13 OK`，full unittest=`609/609 OK`；`requirements.txt` 新增
  `tushare>=1.4.29,<2`。Candidate Universe 仍未接入 production Strategy Engine，策略
  路线和 production boundary 未改变。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Latest Engineering Event — READY_FOR_DECISION_CANDIDATE_RUNTIME

- `CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1` 真实 runtime audit 停止在 blocker：CN seed=`800`、
  US IWB Equity seed=`1018`。CN session-reuse probe=`20/20` 成功、`10.147s`；既有
  逐标的 CN path probe=`5/5`、`3.870s`；US yfinance batch probe=`20/20`、`3.131s`。
- CN full shadow（`--market cn --date 2026-09-04`）在 session reuse path 下运行超过 13
  分钟仍未产生完整 summary，处于 network wait，已停止；没有伪造 included/per-sector/
  strategy 结果，US full shadow 未启动。
- blocker=`CANDIDATE_HISTORY_RUNTIME_NOT_ACCEPTABLE_OR_NOT_BOUNDED`。本轮未留下 bridge
  code，未修改 provider、Candidate semantics、Strategy Engine、production state 或 broker。
  production state writes=`NO`，broker/order=`NO`。
- 最小选项：等待 Sol 接受多分钟级 bounded shadow cadence，或由 Sol 指定经批准的
  CN history runtime/batching/caching 方案；不得自行引入数据库/commercial provider、
  修改 universe/sector taxonomy、affordability/top-N 或接 production。
- 当前 stop marker=`READY_FOR_DECISION_CANDIDATE_RUNTIME`；`HANDOFF_CURRENT_AND_CONSISTENT`。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Historical Engineering Event — BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1_MERGED

- PR #71 已 squash merged。Sol approved head=`1bb2996b1ee7d750fe7d02c53067314ee23866ec`；
  真实 squash merge commit=`319bdf8a3fd950a0be70791ecd81f397aca7e9df`。
- merge-after `CI Test Gate` run=`33984153275` 对 merge commit 为 `SUCCESS`；未自动触发
  Daily Decision Chain / Portfolio Risk shadow。local `main` 与 `origin/main` 均为
  `319bdf8a3fd950a0be70791ecd81f397aca7e9df`。
- 正式 bounded contract：CN seed=`HS300 ∪ CSI500`；US seed=`IWB official holdings`；
  CN `<=10,000 CNY` preferred、`10,000<notional<=20,000 CNY` extended、`>20,000 CNY`
  excluded；US candidate one-share `>1,000 USD` excluded；`TOP_N_PER_SECTOR=20`。
- Candidate layer 不产生 `ENTRY_ALLOWED`；production state writes=`NO`；broker/order=`NO`；
  Candidate Universe 尚未接入正式每日 Strategy Engine production pipeline。
- 当前 stop marker=`BOUNDED_SECTOR_CANDIDATE_UNIVERSE_V1_MERGED`；
  `HANDOFF_CURRENT_AND_CONSISTENT`。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Historical Engineering Event — PR_71_SOL_APPROVED_GOVERNANCE_FIX

- Sol review 发现 `PROJECT_GOVERNANCE_STATE_CONFLICT`：`docs/TRADING_SYSTEM_SPEC.md`
  1R 段落仍写 `Risk Per Trade = 0.5% NAV`，与已合并 PR #70、`DECISION_LOG.md` 和
  当前 Portfolio Risk 语义不一致。
- 最小治理修复：改为 `Risk Per Trade = 0.5% allocation_budget`，并明确
  `allocation_budget` 是用户明确授权给该账户整个策略风险账本的总策略预算，不是
  broker NAV / 账户净值。Position Size 公式未改。
- 未新增 DECISION_LOG decision；未修改 Candidate code/tests、provider、Strategy Engine、
  US `$1000` allocation hard cap 或 production state。继续 PR #71，不新建 PR、不 merge。
- 当前 stop marker=`PR_71_SOL_APPROVED_READY_FOR_MERGE`；治理修复已 push，新的 exact-head
  CI 已全部通过，final status=`HANDOFF_CURRENT_AND_CONSISTENT`。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Historical Engineering Event — PR_FULLY_READY_FOR_SOL_REVIEW

- Sol 已正式决定：CN=`HS300 ∪ CSI500` + BaoStock basic/industry；US=`IWB` 官方
  holdings；不采用完整 security-master 方案 B/C，不引入 commercial provider。
- 已验证真实 source contract：BaoStock 0.9.3 的四个调用字段和
  `query_stock_basic` 不接受 `fields=`；真实 adapter smoke=`800` CN seeds、
  `metadata_ok=800`、`sector_present=800`。官方 IWB `latest-holdings.csv` smoke=
  `source_date=2026-09-03`、`1018` Equity rows。
- 已实现 `trading/candidate_universe.py` 与
  `trading/candidate_universe_sources.py`：bounded read-only seed adapters、
  board-specific affordability、20D/60D traded-notional proxy、history/data-quality
  gate、sector-aware `TOP_N_PER_SECTOR=20`、included/excluded audit rows。
- focused candidate tests=`10/10 OK`。Candidate layer 没有 Strategy action，永远不产生
  `ENTRY_ALLOWED`；未写 Google Sheets、production state、broker/order，未修改 frozen
  Strategy Engine、SETUP_03/04 或新增回测 phase。
- substantive implementation head=`2d63fda031cda08dd2bf5bf631b9a9ea09ace415`；full
  unittest=`606/606 OK`，compileall 与 `git diff --check` 通过；implementation PR #71
  已创建并保持 `OPEN / MERGEABLE / merged=false`。PR final tip/exact-head CI 以 GitHub
  实时核验为准，不把治理 closeout commit 自引用进状态文件。
- 当前状态=`PR_FULLY_READY_FOR_SOL_REVIEW`；详见
  `docs/SECTOR_CANDIDATE_UNIVERSE_V1_FEASIBILITY.md`。不 merge，不扩大 scope。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Latest Engineering Event — STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1_MERGED

- PR #70（`fix/strategy-capital-allocation-boundary`）已 MERGED。approved exact
  head=`88b6889429d36c4d4cdb4d2f8515243f1681dcac`，base=`main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`，
  真实 squash merge commit=`898a01f3e789f15474f30e218eec53eadf34d0c5`。
- merge-after main：本地 `main` 与 `origin/main` 完全一致，均为
  `898a01f3e789f15474f30e218eec53eadf34d0c5`；`CI Test Gate` run=`33965870377`
  为 `SUCCESS`。该 merge commit 未自动触发 Daily Decision Chain 或 Portfolio Risk
  shadow，未手工创建 workflow。
- Strategy Proposal 与 NAV 已正式解耦；allocation 必须经过用户显式 proposal
  approval。`allocation_budget` 是用户授权给该账户策略风险账本的总策略预算，不是
  broker NAV、账户净值、账户总资产、P&L、入出金或本轮新增现金额度。
- 冻结 `0.005 / 0.01 / 0.02` 不变；existing positions 与 approved proposals
  共用同一总预算 denominator。production state writes=`NO`，broker/order=`NO`；
  未执行 `--run` / `--write-state`，未写策略状态或策略持仓。
- 本 closeout 不重复新增 `docs/DECISION_LOG.md` 长期架构 decision，也不写入治理
  文件自身尚不存在的 commit SHA；PR、merge commit 与 CI 事实以 GitHub 实时状态为准。
- 当前正式状态=`STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1_MERGED`；
  PR #70 closeout 无剩余 merge blocker。production state writes、broker/order 与
  自动执行仍未启用。唯一 next action：停止并等待用户下一项明确授权。

`HANDOFF_CURRENT_AND_CONSISTENT`

## Latest Engineering Event — PR_70_SOL_APPROVED_READY_FOR_MERGE

- 在现有 PR #70（`fix/strategy-capital-allocation-boundary`，base=`main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`）
  完成 Sol review 修复，并通过 Sol correctness review；本 agent 不 merge、不新建 PR。
- 显式 proposal approval：生产分配需要已发布 `STRATEGY_PROPOSAL` + 显式
  `approved_event_identities`（event identity，不按 symbol 猜）+ 有效
  `allocation_budget` + 未 pending + 未 settled + 原有 Portfolio Risk
  prerequisites。budget 本身绝不代表 approval；budget 有值但批准集为空 → 0
  reservation / 0 pending；同日多 proposal 只分配被批准 identity；未批准
  `ENTRY_ALLOWED` 保持 `STRATEGY_PROPOSAL`；不存在、未发布、已 pending、已 settled
  的批准 fail closed；`ENTRY_ALLOWED` 技术条件不变。
- `allocation_budget` 语义：用户授权给该账户整个策略风险账本的总策略资金预算；不是
  broker NAV、账户净值、账户总资产、入出金、P&L、purchasing power 或新增现金额度。
  existing system-managed positions 与同轮 approved proposals 共用其作为 Portfolio
  Risk denominator。冻结 `0.005 / 0.01 / 0.02` 不变；无 `new_cash_budget`，未重
  设计 Portfolio Risk。
- 治理：`bb8e6d9a23a175ff01790314837e24621446ce1c` 仅记录为 substantive source
  head，不再写成 current PR head；current PR head 与 exact-head CI 以 GitHub 实时
  核验为准；治理文件不自引用自身 docs closeout SHA。
- 验证：Daily Chain `31/31 OK`、Production Prerequisites `19/19 OK`、full
  unittest `596/596 OK`、Daily Chain generic shadow `17/17 SUCCESS`、Portfolio
  Risk generic shadow `17/17 SUCCESS`、compileall、protocol JSON parse、
  `git diff --check` 全部通过；未执行 `--run` / `--write-state` / 策略状态或持仓
  写入 / broker/order。
- 当前状态=`PR_70_SOL_APPROVED_READY_FOR_MERGE`。PR #70 当前 head 与 exact-head CI
  以 GitHub 实时状态为准；截至本次 closeout，Sol 独立核验 head=
  `8d2b9f76bbc2310182a47b94819adcd388385fe0`，exact-head CI 全部 SUCCESS（Test
  Gate=`33963031703`、Daily Decision Chain shadow=`33963031701`、Portfolio Risk
  shadow=`33963031705`），并已通过 Sol correctness review。当前唯一 next action
  为 merge PR #70；本 agent 不 merge、不新建 PR。

## Prior Engineering Event — STRATEGY_DECISION_AND_CAPITAL_ALLOCATION_BOUNDARY_V1

- 本任务基于真实 `main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`，工作分支为
  `fix/strategy-capital-allocation-boundary`；不改变 Wave/Swing/Setup/Entry/
  Stop/Target/RR/T→T+1/Position Management/Wave5 或冻结风险比例。
- Production strategy proposal 现在不要求账户 NAV、NAV date freshness、账户资产、
  入出金、P&L、purchasing power 或 broker balance。`策略账户.参考净值` 与
  `净值日期` 保留为可选 legacy compatibility fields；preflight 不再因其缺失或落后
  T 阻塞纯 strategy proposal。
- `ENTRY_ALLOWED` 在没有用户预算时保持可见，输出 `STRATEGY_PROPOSAL`，不计算
  Position Size、不创建 Portfolio reservation；用户批准后只能通过显式
  `allocation_budget` 进入 Portfolio Risk / Position Size。预算不从 account NAV
  或其他账户资金事实推导。
- `BASE_RISK_FRACTION=0.005`、`MAX_RISK_PER_GROUP_FRACTION=0.01`、
  `MAX_TOTAL_OPEN_RISK_FRACTION=0.02` 保持不变；无 broker/order/UI/自动 workflow
  接入，无 live strategy-state write。
- substantive source head=`bb8e6d9a23a175ff01790314837e24621446ce1c`（历史
  substantive head，不是 current PR head）；当时 PR #70=
  `https://github.com/EFSing/stock-data-pipeline/pull/70`，base=`main`，state=`OPEN`,
  `MERGEABLE`, `merged=false`；当时 exact-head checks：CI Test Gate run=`33952922439`,
  Daily Chain shadow run=`33952922429`, Portfolio Risk shadow run=`33952922432`，均
  `SUCCESS`。
- live workbook connector-backed read-only preflight T=`2026-09-04`：2 个 enabled
  account，正式 universe 5 个 symbol，CN `DATA_OK=3/3`、US `DATA_OK=2/2`，QFQ
  blockers=`0`，NAV blockers=`0`，risk-group blockers=`0`，state-store=`OK`；结果
  `READY`，`READ_ONLY`、`NO STATE WRITE=true`、`NO Sheets mutation=true`。本机原生
  CLI 因未注入 `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` 在连接前退出；未
  输出、记录或写入任何凭证，connector 读取与 adapter 复核均为只读。
- 当时状态=`PR_FULLY_READY_AND_PREFLIGHT_READY_FOR_SOL_REVIEW`；不启用 state writes，
  不合并 PR。治理文件不自引用其自身 docs-only commit SHA。

## Prior Production Verification — CN_US_SCHEDULED_QFQ_VERIFIED_AND_PREFLIGHT

- verified baseline=`main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`。Asia run `33879573985`=`SUCCESS`：主行情 `9/9`，QFQ `requested=3, updated=3, rows_written=3000, SUCCESS`。
- US run `33932473603` 仅 rerun failed jobs 一次：attempt=`2`、job=`101264486493`、run/job=`SUCCESS`；checkout log 仍为 exact `main@2ce2711f4994f31c167bbe4961ecd0b34e90c476`。`main.py --group us --mode latest` 正常完成，`requested=4`、`freshest_rows_written=4`、`failed_symbols=0`、`history_rows_written=0`、`decision_rows_written=0`；QFQ `requested=2, updated=2, stale_or_failed_symbols=[], rows_written=2000, SUCCESS`。
- 因此 CN+US 已达 `CN_US_SCHEDULED_QFQ_VERIFIED`；BABA/RKLB 原 QFQ failure 为 `TRANSIENT_YFINANCE_PUBLICATION_LAG`，无 schedule/retry/provider/freshness contract 或代码改动，无 PR。仅允许行情/QFQ 范围，未写策略决策状态、策略持仓、legacy 交易决策或 broker/order。
- live workbook read-only preflight（现有 CLI `--preflight --date 2026-09-04`）T=`2026-09-04`：formal 5 symbols 的 latest/QFQ 均到 T；state-store=`OK`、`READ_ONLY`、`NO STATE WRITE=true`、`NO Sheets mutation=true`，结果=`NOT_READY`。两账户 `CN_MAIN`/`US_MAIN` 的 live NAV date 均为 `2026-09-03`，故有效 blocker 是 `PRODUCTION_NAV_DATE_REQUIRED`（preflight 先输出 `CN_MAIN`，并有 fail-closed 的 universe/account cascade）；QFQ stale blocker 已清除，NAV freshness 不得误判为 QFQ failure。
- 这是本次架构修正前的 production verification snapshot；NAV freshness 不再是
  strategy proposal prerequisite。原始 QFQ 与 live workbook 事实保留作 provenance。

## Prior Operational Event — PRODUCTION_CONFIG_ACTIVATION_AND_READ_ONLY_PREFLIGHT_V1

- status=`PRODUCTION_CONFIG_ACTIVATED`；live workbook=`持仓股股票行情数据中台` (`1M6VvFaBNCkaS7N32afDqsHBn2CGie-WrOmPqOhDHuws`)；pre-merge live `main`/baseline=`e4a58a7a1b2c53a76abf190cff8d3a39d737cf9b`；current main is recorded in the latest engineering event below。
- 已写入并复核：`策略账户` 启用 `CN_MAIN/CNY/NAV 75000`、`US_MAIN/USD/NAV 4500`，两者 `净值日期=2026-09-03`；`策略股票池` 启用 CN=`000725.SZ`、`002156.SZ`、`512400.SH`，US=`BABA`、`RKLB`；`DRAM` 保留 disabled candidate；`策略风险分组` 5 个显式映射，均非 `UNKNOWN`。
- `策略持仓` rows=`0`；`策略决策状态` rows `0→0`；只写目标三张配置表，旧行情/决策/自选 tab 未改。
- exact read-only preflight T=`2026-09-03`=`NOT_READY`。CN/US exact calendars 已通过（`XSHG`/`XNYS`，next session `2026-09-04`）；静态配置核验通过。唯一 blockers 为五个 enabled symbol 的 QFQ `DATA_STALE:qfq last date < T`（CN latest 至 `2026-09-02`；US latest 至 `2026-09-03`，QFQ 至 `2026-08-28`）。
- state-store=`OK`；`READ_ONLY`；`NO STATE WRITE=true`；`NO Sheets mutation=true`。最终状态=`PRODUCTION_CONFIG_ACTIVATED / READ_ONLY_PREFLIGHT_NOT_READY_DATA_STALE`；无 broker、订单、FX、cron 或自动生产状态写入。`HANDOFF_CURRENT_AND_CONSISTENT`。

## Prior Engineering Event — PRODUCTION_QFQ_DAILY_REFRESH_V1_MERGED

- 根因 marker=`PRODUCTION_QFQ_NOT_REFRESHED_BY_SCHEDULED_LATEST_MODE`：scheduled `main.py --mode latest` 不进入现有 QFQ history branch；`full` 虽可刷新 QFQ，但会进入 legacy SETUP_03/Decision path。
- 已实现窄脚本 `scripts/refresh_production_qfq.py`，formal enabled universe 由 enabled linked `策略账户` + `策略股票池` 决定；`自选清单` 与 `最新行情` 均按 `(市场,统一代码)` 严格唯一匹配；target trade date 原样取 `最新行情.交易日期`。
- 只允许 `BaoStock`/`yfinance` QFQ，复用现有 `fetch_with_retry`、`history_days`、`quote_row`；所有 formal target fetch/validation 成功后，通过 scoped `SheetsClient.replace_history_series` 删除 target identity 的全部旧 rows、写入 authoritative window，并原样保留 non-target rows。成功 mutation boundary 仅为 `历史行情_前复权`，失败时不做 partial write。
- scheduled Asia/US cron 未改变；`RUN_MODE=latest` 在 main latest 成功后调用 refresher，manual `full` 不调用。摘要为 `PRODUCTION_QFQ_SUMMARY`，任何 formal symbol stale/missing/config duplicate 都 fail closed；scheduled latest 现在具备自动 QFQ refresh 能力。
- live workbook 配置仍为真实已激活配置；旧 read-only preflight 的五个 QFQ stale blockers 未被隐瞒。PR #68 已 squash merge，但 manual live QFQ refresher smoke=`NOT_RUN`；strategy state writes=`NO`；broker/orders/FX=`DISABLED`。
- 当前分支=`main`；formal pre-merge baseline=`e4a58a7a1b2c53a76abf190cff8d3a39d737cf9b`；current `main`/`origin/main` exact SHA=`4034c87c354fc552496202e7004848ecfbfef6b3`；Sol-approved PR #68 exact head=`ffc753baf784f8af4bb702db7c6799371dcd3693`；squash merge commit=`4034c87c354fc552496202e7004848ecfbfef6b3`。focused tests=`16/16`、full unittest=`587/587`、compileall 与 `git diff --check` 均通过；approved head CI Test Gate=`33841344943 SUCCESS`、Daily Decision Chain generic shadow=`33841344884 SUCCESS`、Portfolio Risk generic shadow=`33841344891 SUCCESS`；merge-after main `CI Test Gate`=`33842189224 SUCCESS`。状态=`PRODUCTION_QFQ_DAILY_REFRESH_V1_MERGED`，停止，不自动启动新的 production decision phase。

## Prior Operational Event — PRODUCTION_SHEETS_BOOTSTRAP_AND_PREFLIGHT_V1

- milestone status=`PRODUCTION_SHEETS_BOOTSTRAPPED`；本节覆盖当前 live workbook objective facts；旧 `REAL_SHEETS_NOT_CREATED` 仅属于历史治理事件。
- Repo baseline verified：`main`/`origin/main`=`85f5aad40c300a5446a3610ce4daccfbc08c75bf`；PR #66=`MERGED / merged=true`；latest main `CI Test Gate` run=`33745503856` success。当前 checkout=`codex/production-prerequisites-governance-closeout`。
- 目标 workbook 已验证：ID=`1M6VvFaBNCkaS7N32afDqsHBn2CGie-WrOmPqOhDHuws`，title=`持仓股股票行情数据中台`，time zone=`Asia/Shanghai`。
- 已在真实 workbook 创建并核验 5 个 exact-contract worksheet：`策略账户`、`策略股票池`、`策略风险分组`、`策略持仓`、`策略决策状态`；旧 `自选清单`、`最新行情`、`历史行情_前复权`、`参数设置`、`交易决策` 未修改。
- `策略账户`=`2` 行 disabled scaffold（`CN_MAIN/CNY`、`US_MAIN/USD`，NAV/date 空）；`策略股票池`=`6` 行 disabled candidate bootstrap（CN 3、US 3）；`策略风险分组`=`0`；`策略持仓`=`0`；`策略决策状态`=`0`。
- 候选来自 live `自选清单` 中 `启用=TRUE` 且市场为 CN/US 的 6 行；HK/SE 未加入 production strategy universe。`自选清单` 不等同于 `策略股票池`。
- 真实 read-only preflight（无 `--run`、无 `--write-state`）=`NOT_READY`；blockers=`PRODUCTION_STRATEGY_UNIVERSE_REQUIRED`、`PRODUCTION_ACCOUNT_REQUIRED`。preflight 前后 state rows=`0 → 0`，输出确认 `READ_ONLY`、`NO STATE WRITE=true`、`NO Sheets mutation=true`。
- 当前状态：`READY_FOR_DECISION_REAL_PRODUCTION_CONFIG`；待用户决定正式 universe、拟启用账户 NAV/date、risk groups，以及确实纳入系统管理的 existing positions。`REAL_PRODUCTION_STATE_NOT_ENABLED`、`BROKER_NOT_CONNECTED`；无 FX、orders、cron。
- 本轮没有新的长期架构决策，`docs/DECISION_LOG.md` 不变。治理同步完成目标：`HANDOFF_CURRENT_AND_CONSISTENT`。

## Prior Governance Event — PRODUCTION_PREREQUISITES_V1

- 正式起点为 `main@95eec374c3ef48877d45a4bfb2794f6df3cf0ae2`；该 exact head 的 `CI Test Gate` run=`33712447481`，result=`success`。
- substantive/validation head=`4548563249ad8f61656f09d5bca2c3f7761cc718`；PR #66 final live head=`ca21bd7ea2925d30d101550cb5d088b848ebff4d`，已 squash merged 为 `11f78c88a2e43ae1a136ffd2bd31246e4a6823ef`。后续 governance-only docs commit 不把自身或前一个 docs commit冒充 source validation head。
- PR #66=`https://github.com/EFSing/stock-data-pipeline/pull/66`，base=`main@95eec374c3ef48877d45a4bfb2794f6df3cf0ae2`，state=`MERGED / merged=true`；merge-after `main`=`11f78c88a2e43ae1a136ffd2bd31246e4a6823ef`。
- substantive head exact-head CI：`CI Test Gate` run=`33739123688` success；Daily Chain generic shadow run=`33739123690` success；Portfolio Risk generic shadow run=`33739123721` success。
- 本阶段新增 production prerequisites correctness hardening：缺 PositionOrigin 仅阻断 PM；state identity 为 `(account_id, record_type, primary_key)` 且 adapter 为每个 enabled account 提供只读 scoped store；T 完成由可注入、带时区 clock 证明；settlement position 在同轮风险前合并；未决 PENDING_T1 reservation 保守阻断新 reservation；published/pending/settlement/daily compound state reload 断裂 fail closed；system-owned `POSITION_ORIGIN` 无对应 `SETTLEMENT` 时以 `PERSISTED_STATE_INCOMPLETE:origin_without_settlement:<identity>` fail closed；latest/QFQ 币种必须显式；QFQ 缺失为 `DATA_UNAVAILABLE`；空 enabled account 无正式 strategy universe 时 fail closed。
- 本地验证：full unittest=`571/571`；production prerequisites=`19/19`；Daily Chain=`23/23`；Portfolio Risk=`24/24`；Position Management=`18/18`；Daily generic shadow=`17/17 SUCCESS`；Portfolio generic shadow=`17/17 SUCCESS`；compileall 与 `git diff --check` 通过。
- `--preflight` 只读；真实 Sheets、broker/IBKR、订单、FX 和 cron 均未触及。冻结的 SETUP、Wave、Risk、Position Management、Wave5、T+1 语义未修改。
- merge-after main `CI Test Gate` run=`33745503856` success。
- 五个 production Sheet contracts、account-isolated risk books、persistent state / exact calendar / production adapter 已进入正式 engineering baseline；`REAL_SHEETS_NOT_CREATED`、`REAL_PRODUCTION_STATE_NOT_ENABLED`、`BROKER_NOT_CONNECTED`。
- 最终状态=`PRODUCTION_PREREQUISITES_V1_MERGED`；`HANDOFF_CURRENT_AND_CONSISTENT`；停止，不再执行本阶段工作。

## Historical Governance Event — PROSPECTIVE_DAILY_DECISION_CHAIN_V1_MERGED
- 本轮 Sol correctness hardening 已完成本地实现：Data Quality 先于 Wave/Setup/Individual Decision/Position Management；global 与 per-symbol authoritative positions canonical merge + conflict fail-closed；双 first-entry `CONFIRMED` upstream invariant guard；protocol-only settlement；mixed as-of fail-fast；Position Management prerequisite errors 归入数据/生产前置条件异常。
- 双 `CONFIRMED` 经正式 contract 审计为当前不可达：Wave 只有一个 primary scenario，SETUP_01/02 只接受各自 primary family；本轮未增加交易优先级或修改冻结策略语义。
- T+1 closeout：`DATA_BAD` / `DATA_STALE` / `DATA_UNAVAILABLE` 或 expected T+1 bar 缺失时，Daily Chain 不调用 execution / Portfolio Risk settlement，不生成 `EXECUTED` 或策略 `SKIP`，不 release reservation，不创建 PositionOrigin；`DATA_OK` 且 exact bar 存在时沿用原 settlement 语义。
- Portfolio Risk closeout：已知 `OpenPositionState.has_position=true` 但 `portfolio_position=None` 时，新的 `ENTRY_ALLOWED` fail closed，reason=`PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED`；不从 PositionOrigin、current price、holdings average cost 或 chart history 猜测 risk state。
- 多标的 batch closeout：SYMBOL_A 的上述 blocker 与 SYMBOL_B 的正常 reservation mapping 同时保留；SYMBOL_A 不产生 reservation/pending，SYMBOL_B 正常走原 Portfolio Risk batch。

## Prior Latest Governance Event — FROZEN_DEVELOPMENT_DATASET_PORTABLE_ARCHIVE

- `FROZEN_DEVELOPMENT_DATASET_CLOUD_ARCHIVED_AND_PORTABLE` 已完成：私有 GitHub Release tag=`frozen-development-dataset-2026-08-28-v2`，URL=<https://github.com/EFSing/stock-data-pipeline/releases/tag/frozen-development-dataset-2026-08-28-v2>。
- Archive=`stock-data-pipeline-frozen-development-v2.zip`，5,900,672 bytes，SHA-256=`sha256:15e3c63da65cd1eba52ecd6d441be22d6556e9ae2008f70c652a01bb7b0eaeb2`；独立 sums 与 metadata 同时作为 Release assets 上传。
- Frozen identity=`SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2`，40 symbols / 84,284 bars，manifest SHA-256=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`。
- 输入仅为 manifest、manifest 引用的 40 个 raw CSV 和 40 个 normalized JSONL；archive integrity=`PASS`，临时解压恢复 `81/81` hashes/sizes match；未重新抓取、normalize、生成或 replay。
- Release target 为真实 `main@12a9e2aa175a90c5ff1db8556190c6db23d2bb64`；PR #59 已完成 `d1016f2` push 但保持 `OPEN / merged=false`，未 merge，策略代码未改变。Restore instructions=`docs/FROZEN_DATASET_RESTORE.md`。
- Git remains source-code SSOT；Release asset 是 frozen binary/data archive；manifest/hash 是 dataset identity SSOT。预期恢复目录：`artifacts/development_strategy_stability_v2/`。

## Historical Verified Repository State

- Repository: `EFSing/stock-data-pipeline`; default branch: `main`。
- GitHub `main` exact HEAD=`74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`，为 PR #64 的真实 squash merge commit；merge-after `CI Test Gate` run=`33711976436` success。
- Current checkout: `main`，本地与 `origin/main` 一致；prospective chain implementation、tests、shadow、workflow 与 docs 已进入 merged engineering baseline，replay output 保持在 ignored `artifacts/`。
- PR #50/#51/#59/#60/#61/#64 已 `MERGED`；PR #64 的批准 head 与 merge-after main 状态已完成交叉核验。
- PR #45 已成功 squash merged，PR #38 也已正式 MERGED；其历史 exact-head 证据保留不变。
- 当前项目正式状态：SETUP_03 仍为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`，SETUP_01/SETUP_02 与 Position Management/Exit/Wave5 semantics frozen；Portfolio Risk V1 已 merged；当前授权任务为 `PROSPECTIVE_DAILY_DECISION_CHAIN_V1`，停止节点为 `PROSPECTIVE_DAILY_DECISION_CHAIN_V1_READY_FOR_SOL_REVIEW`。总体策略身份与路线以 `docs/TRADING_SYSTEM_SPEC.md` 为准。
- PR #45 已成功 squash merged：pre-merge HEAD=`19c6e0eaa8841b757e6359e897ab559e31d39f65`、base=`2f56cd0697592c5815dbfea84bf328abe6c4c8c7`、exact-head CI=`33493027270` success；merge state 为 CLEAN/MERGEABLE。
- PR #38 已正式 MERGED（merged=true），真实 merge commit 为 `e21935d17392a37ee9795e32a562e875dd741bfb`；合并前 tip `6abc8ebcde5635d4bf05b085e331fa15eb9b3f48` 的 exact-head CI `33355893831` success，merge 后 main exact-head CI `33362271501` success。
- 当前项目正式状态：SETUP_03 仍为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`，SETUP_01/SETUP_02 Decision 与 Position Management/Exit/Wave5 layers frozen；`POSITION_MANAGEMENT_EXIT_V1_MERGED`；当前授权任务为 `PORTFOLIO_RISK_V1`，停止节点为 `PORTFOLIO_RISK_V1_REBASED_AND_READY_FOR_SOL_REVIEW`。总体策略身份与路线以 `docs/TRADING_SYSTEM_SPEC.md` 为准。
- v5 protocol `research/protocols/setup03_atr_boundary_structural_qualification_protocol.json` 的 canonical SHA-256 为 `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`，状态为 `ATR_BOUNDARY_PROTOCOL_FROZEN_NOT_EXECUTED`；40/40 frozen clean symbols 已完成结构性 qualification。
- v5 qualification 的 candidate-level gates 全部通过，但 adjacent/lifecycle gates 使 `qualified_candidates=[]`、`selected_candidate_atr=null`；结果为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`，未选择 ATR threshold、未修改 production、未读取 Final OOS。
- 当前 worktree 的 frozen backup ZIP 已本地生成并通过字节 hash 验证；Google Drive persistent backup 与独立 cloud reread 由外部 ChatGPT 审计完成，状态为 `FULLY_RECOVERABLE`。raw/normalized/replay payload 仍位于 ignored `artifacts/`，未修改其 bytes。
- 本文件中的治理初始化保留了已有 backup staging 记录；初始检查时观察到的 `.hotfix-worktree/` 在 post-commit 检查时已不再存在，本任务未执行删除且未纳入 commit。

## Historical Task: PROSPECTIVE_DAILY_DECISION_CHAIN_V1（已 merged，停止在 engineering baseline）

- 分支：`codex/prospective-daily-decision-chain-v1` 已 squash merged 到 `main`；PR #64=`https://github.com/EFSing/stock-data-pipeline/pull/64`，approved exact head=`58dfb1448fa73efd50856d989c42801664eb9419`，merge commit=`74eed4b80f29d9dc96ceec555b7cf3a64d0f65e4`，状态=`MERGED / merged=true`。
- 新增 `trading/daily_decision_chain.py`、`tests/test_daily_decision_chain.py`、`scripts/run_daily_decision_chain_generic_operational_shadow.py`、`.github/workflows/daily-decision-chain-generic-operational-shadow.yml` 与 `docs/PROSPECTIVE_DAILY_DECISION_CHAIN_V1.md`；`docs/DECISION_LOG.md` 已记录范围与 production prerequisite decisions。
- T 日链路只消费 `data <= T` 的 immutable inputs；只接受同日、首次、明确标记 `is_new_confirmed_event_as_of=true` 的 SETUP_01/SETUP_02 `CONFIRMED` event；event identity 沿用现有 deterministic identity；T close 只形成 Decision/plan，T+1 execution 只在 exact exchange-calendar session identity 可用时进行观察性 settlement。
- `DecisionStateStore`/`InMemoryDecisionStateStore`、injected `UniverseProvider`、Portfolio Risk frozen constants `0.005 / 0.02 / 0.01`、缺失 NAV/risk group/position origin/calendar/persistence 的 fail-closed reason 与六段中文优先报告已实现；无 broker/order/Sheets strategy write。
- 实际 production strategy universe、可靠 NAV、accepted risk-group metadata、authoritative position origin、exact calendar 和 persistent store 尚无正式 SSOT；因此 real-data shadow=`NOT_RUN_PRODUCTION_STRATEGY_UNIVERSE_REQUIRED`，不能用当前 watchlist 或真实 holdings 替代。
- 本地验证：Daily Chain=`20/20`、Portfolio Risk=`24/24`、Position Management=`18/18`、Daily Chain generic shadow=`17/17`、Portfolio Risk generic shadow=`18/18 checks`、full unittest=`549/549`、compileall 与 `git diff --check` 通过；approved exact-head=`58dfb1448fa73efd50856d989c42801664eb9419` 的 CI Test Gate=`33709065926`、Daily Chain shadow=`33709065929`、Portfolio Risk shadow=`33709065934` 均 success；merge-after main CI=`33711976436 SUCCESS`。
- 本轮新增 Daily Chain regression=`20/20`（multi-symbol blocker preservation；既有 T+1 data guard、missing expected bar、known open position risk-state 与其他 hardening cases 保持绿色）；目标状态为 `PROSPECTIVE_DAILY_DECISION_CHAIN_V1_MERGED`。
- 合并后不重跑 frozen research replay；不启动 production wiring 或下一阶段架构决策。

## Previous Task: PORTFOLIO_RISK_V1（已 squash merged）

- Sol approval=`APPROVE_POSITION_MANAGEMENT_EXIT_V1_MERGE_AND_PROCEED_PORTFOLIO_RISK_V1`；PR #51 source head=`2dbb7a751916921a29360b28467de92e150683e3` 已 squash merged 为 `993d03e428b7eb11da791a608940c9d77a608f96`，merge-after main CI `33607481962` success；治理状态=`POSITION_MANAGEMENT_EXIT_V1_MERGED`。
- 分支：`codex/portfolio-risk-v1`，base=`main@f53ae42b85ca9e3e5a3bd6e8b91d919b1de0aa24`；本轮实现独立 Portfolio Risk PR，保持待 Sol review，不自动 merge。
- PR #59 的本地 rebase 后 substantive source head=`96d3d52ef7baf6dacc0f464a07ca7a1c8b9ca1c0`；validation tip=`e80c61bd72953754802290ee09e8171b5ffd447c`，exact-head `CI Test Gate`=`33645523150`、generic shadow=`33645523141` 均 success；后续 docs-only tip 不自引用，live GitHub head/checks 为最终事实。
- 新增 `trading/portfolio_risk.py`、`research/portfolio_risk_replay.py`、synthetic shadow runner/workflow、对应 tests、`research/protocols/portfolio_risk_v1.json` 与 `docs/PORTFOLIO_RISK_V1.md`；既有 Setup/Wave/Decision/Position Management/Exit semantics 保持不变。
- 冻结 risk unit：`BASE_RISK_FRACTION=0.005`；development `reference_nav=1.0`；total cap=`0.02`；known risk-group cap=`0.01`；production missing NAV=`PORTFOLIO_NAV_REQUIRED`，production UNKNOWN group=`BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION`。
- frozen v2 replay（corrected）：40/40 symbols、84,284 bars；individual `ENTRY_ALLOWED=8`，portfolio proposals/reservations=`8`，approved=`8`，blocked=`0`，failed T+1 released=`5`，final `EXECUTED=3`；maximum observed open capital-loss risk=`0.005`；UNKNOWN advisory=`8`。
- Position Management invariance：3 positions / 134 position-days / 30 stop raises；actions=`EXIT 3 / HOLD 11 / NO_ADD 96 / PROFIT_PROTECTION 24`；Wave5 contexts=`NO_WAVE5_CONTEXT 19 / WAVE4_PULLBACK_CONTEXT 19 / WAVE5_CANDIDATE 96`；cache semantic parity=`SUCCESS`, `first_mismatch=null`。
- synthetic Portfolio Risk boundary=`17/17` success；覆盖 total/group/symbol/UNKNOWN/stop raise/exit/T+1/order/exact-once/future-append/immutability cases。
- pre-merge geometry defect 已记录并修正：旧 `structural_invalidation → HIGH3` continuation projection 与 minimum `RR=2` 数学不兼容；新 protocol identity 为 `SETUP-02-DECISION-RISK-2026-09-02-v2`，只使用 `LOW2 + (HIGH1-LOW0)*existing EXTENSION_RATIO`，source=`WAVE3_FIB_EXTENSION`。
- 冻结语义：只消费首个 `CONFIRMED`（`event_type == CONFIRMED`、`is_new_confirmed_event_as_of == true`、event identity exactly-once）；T close 只形成 plan；Entry Zone=`[HIGH3, HIGH3+0.5*ATR14(T)]`；structural invalidation 直接复制 event；Execution Stop=`structural_invalidation-0.5*ATR14(T)`；targets first→R/R；exact T+1 session OPEN only。
- Frozen `DEVELOPMENT_EXPOSED` v2 corrected funnel：213 CONFIRMED → 213 Decision；`ENTRY_ALLOWED=1`；gate=`ABOVE_ENTRY_ZONE 97 / STALE_CONFIRMATION_GEOMETRY 12 / NO_VALID_TARGET 1 / RR_BELOW_MINIMUM 102 / others 0`；T+1 attempts/executed=`1/0`，唯一 skip=`SKIP_GAP_BELOW_CONFIRMATION=1`；target candidates=`CONFIRMED_SWING_HIGH 771`、`WAVE3_FIB_EXTENSION 321`、1 merged dual-source；extension ratios=`1.272 61 / 1.618 75 / 2.0 84 / 2.618 102`；T1 source=`CONFIRMED_SWING_HIGH 44 / WAVE3_FIB_EXTENSION 59`；>5R=`0`；missing T+1=`0`。
- Funnel invariants：CN/US first CONFIRMED=`74/139`；all 494 structural event identities unique/matched；first CONFIRMED exact-once=`213/213`；decision/entry/execution ledger conservation passed；`risk_capital` 未提供且不猜 NAV；production calendar 未实现。
- Generic operational shadow synthetic-only passed exactly-once、terminal filtering、T→T+1 OPEN、gap/RR branches、fail-closed、reporting 与 ledger invariant。
- 12 条原 `INVALID_STRUCTURE` 已逐一输出 LOW0/HIGH1/LOW2/HIGH3、structural_invalidation、T close 与 invariant reason；12/12 均为 `STALE_CONFIRMATION_GEOMETRY: structural_invalidation >= HIGH3`，未发现 upstream structural contract inconsistency。
- 当前 frozen replay（v2 dataset）：3 positions / 134 position-days；SETUP_01 `EXECUTED=3`、SETUP_02 `EXECUTED=0`，30 stop raises；exit=`EXIT_GAP_BELOW_STOP=1 / EXIT_STOP_TRIGGERED=1 / STRUCTURAL_EXIT_PENDING=1`；Wave5=`NO_WAVE5_CONTEXT=19 / WAVE4_PULLBACK_CONTEXT=19 / WAVE5_CANDIDATE=96`；causal/conservation/future-append invariants 全部通过。
- replay machine report 已改为准确字段 `structural_event_identity_unique={SETUP_01:true, SETUP_02:true}` 与 `strict_cached_semantic_parity=true`；`future_append_invariance=true`、`governance_consistency=true`；本地 focused/replay=`27/27`、cache parity=`3/3`、full unittest=`529/529`，compileall 与 `git diff --check` 通过。
- 已完成一次性 `FROZEN_REPLAY_CACHE_SEMANTIC_PARITY_AUDIT`：40 symbols / 84,284 bars，Wave、SETUP01 snapshots/events、SETUP02 snapshots/events 的 strict/cached row counts 与 canonical SHA-256 全部相等，`first_mismatch=null`；manifest 保持 `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`，cache 保留，并记录 `FROZEN_REPLAY_CACHE_SEMANTIC_PARITY_CONFIRMED`。
- `PositionTarget` 已将 Decision 的前 3 个 target candidate 的 price/order/source/provenance 原样冻结进 immutable `PositionOrigin`，不重算 target；risk advisory 只按 provenance 发出 Fib/confirmed-swing 标签，dual-source 可同时发出。旧→新 target-label delta 仅为 `CONFIRMED_SWING_TARGET_REACHED +1`，action counts 保持 `EXIT=3 / HOLD=11 / NO_ADD=96 / PROFIT_PROTECTION=24`。
- 边界：Position Management 只消费 `outcome == EXECUTED`，不重筛 entry、不生成新 entry；不读取或计算 win rate、aggregate P&L、expectancy、profit factor、Sharpe、optimized thresholds、Final OOS；不访问 holdings/broker/account/Secrets/Sheets；不自动 merge 新 PR。
- Generic operational shadow 为 synthetic-only SUCCESS：1 position / 3 position-days；初始 1R 冻结、target 只追踪不自动退出、stop 不下移、causal day count 全通过；returns/P&L/broker/holdings/Sheets 均未访问。
- PR #51 的 hardening source=`e289281c7860615ca44bd402db6051756d56b357` 已随文档 closeout 推至 exact head=`7c02ca08abab467f8fe0bc6bd43ff158196992d8`；该 head 的 `CI Test Gate` run=`33604216629` 与 `SETUP_02 generic operational shadow` run=`33604268141` 均 success，PR live state=`OPEN / CLEAN / MERGEABLE`、`merged=false`。
- Machine-readable protocol=`research/protocols/position_management_exit_v1.json`；中文协议=`docs/POSITION_MANAGEMENT_EXIT_V1.md`；停止节点为 `POSITION_MANAGEMENT_EXIT_V1_PREMERGE_HARDENED_READY_FOR_SOL_REVIEW`，PR #51 保持 OPEN，禁止 merge。

## Previous Task Correction: PREMERGE_PORTFOLIO_RISK_DEFINITION_CORRECTION

- Defect recorded as `PREMERGE_REMAINING_RISK_DEFINITION_DEFECT`：旧 `current_price - active_stop` 同时混合 mark-to-stop giveback 与 capital-loss risk，已从正式 Portfolio Risk contract 移除。
- Frozen SSOT：`remaining_loss_risk_per_share = max(actual_entry - active_protective_stop, 0)`；`remaining_loss_risk_fraction = quantity * remaining_loss_risk_per_share / reference_nav`。Current price 不参与 capacity；MFE/MFE Drawdown 仍由 Position Management 管理。
- `OpenPortfolioPosition` 缺失 `actual_entry` 时 risk calculation fail closed，错误 contract=`PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING`；EXECUTED settlement 缺失 entry basis 不创建 position。T+1 executed sizing 仍以 actual entry 调用 `position_size(reference_nav*0.005, actual_entry, execution_stop)`，不改 stop。
- Stop/exit diagnostics 已与同一 SSOT 对齐：stop raise `after <= before`，exit 后 remaining portfolio risk=`0`；`GAP/SLIPPAGE TAIL RISK NOT MODELED IN PORTFOLIO_RISK_V1`。
- Frozen v2 corrected delta artifact=`artifacts/portfolio_risk_definition_correction_delta.json`（ignored）：counts `8 proposals / 8 approved / 0 blocked / 5 released / 3 executed` unchanged；full open-risk maximum old=`0.010021099674141698` → corrected=`0.005`；stop-raise release old=`0.03216566733623613` → corrected=`0.01`；exit release old=`0.0004660670854315734` → corrected=`0.005`；131/131 observed open-risk sessions are reported in the corrected ledger。
- Deterministic verification：Portfolio Risk focused/replay=`27/27` with local restored dataset；generic synthetic shadow=`17/17`；full unittest=`529/529`；all upstream source identity, Position Management `3 positions / 134 position-days / 30 stop raises`, action counts, Wave5 counts and cache semantic parity remain unchanged。
- Clean-checkout policy：the 3 dataset-dependent integration assertions remain `skipUnless(dataset available)` with explicit reason; self-contained Portfolio Risk tests and generic shadow always run. Frozen manifest remains `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`。

## Previous Task: SETUP_02_WAVE3_CONTINUATION_STRUCTURAL_V1（已 squash merged）

- 分支：`codex/setup02-wave3-continuation-v1`；base：`main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7`；不复用旧 PR，不自动 merge。
- 新增 `trading/setup02.py`、`trading/setup02_replay.py`、`scripts/run_setup02_structural_replay.py`、`tests/test_setup02.py` 与 `docs/SETUP_02_WAVE3_CONTINUATION_STRUCTURAL_V1.md`。
- 只接受 primary `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`；要求因果 `LOW0 → HIGH1 → LOW2 → HIGH3`、`HIGH3>HIGH1`、`LOW2>LOW0`、daily/weekly `UPTREND`，并复用 Wave Engine 既有 structural invalidation。
- lifecycle 固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED`；recovery=`invalidation + 0.5*(HIGH3-invalidation)`；`close == HIGH3` 不确认，首个 `close > HIGH3` 才确认；终态事件仅首次进入发出一次。
- replay 严格按历史 prefix，禁止未来 confirmed Swing 泄漏；Fib 仅描述性；报告只含 structural state/event/failure/CN-US/per-symbol/primary-wave/candidate/identity 统计，不含 outcome/returns/MFE/MAE/P&L/expectancy/OOS。
- 同一 v2 输入上的 overlap 审计：SETUP_01 有 1,389 个终态事件、SETUP_02 有 494 个；相同 symbol+date 的终态日期交集为 11（9 个 symbols），相同 symbol+date+event type 为 0；candidate state-day 交集为 0（SETUP_01 5,195 天、SETUP_02 2,689 天）；两者 primary Wave context 在 84,284/84,284 日一致。
- frozen `DEVELOPMENT_EXPOSED` v2：40/40 symbols、84,284 bars、manifest SHA=`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`、replay aggregate SHA=`sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18`；0 errors、213 CONFIRMED、281 FAILED、identity duplicate/mismatch=`0/0`。
- 当前 replay state-day：`NONE=20,433`、`WATCH=1,288`、`ARMED=1,401`、`CONFIRMED=10,930`、`FAILED=50,232`；唯一当前候选为 US `AMAT` / `WATCH` / `2026-08-26` / Fib `0.618-0.786`。
- PR #45 已在 Sol approval 后 squash merged；真实 merge commit=`f679443d52d767841c0df3ff2e0179648b536fb0`，merge-after main exact-head CI run=`33494893693` success。
- structural lifecycle、replay 与 213 CONFIRMED 事件身份保持冻结；本轮 Decision/Risk 仅消费该结构层的 first-entry CONFIRMED。

## Previous Task: HOLDINGS_DATA_MANAGER_LIFECYCLE_CLOSURE_V2（已完成并 squash merged）

- 生命周期实现 source head=`25c89056ba3f3d38df62b7f4c990c2127e2ae10c`；共享 `latest_snapshot.py` evaluator/row projection 已接入 scheduled latest 与 holdings manager。
- PR #44：`https://github.com/EFSing/stock-data-pipeline/pull/44`，base=`main@dde70661ae0848fda4aad2361dc4f9ef9375bf9c`，已 squash merged；真实 merge commit=`a64102a9f222029a3079bd231790c842e074f372`。merge 后 main exact-head `CI Test Gate` run=`33485998503` / `test` check=`99786090755` success；文档不自引用自身 SHA。
- ADD/REENTER 已实现 normalization → 最近已完成 session latest snapshot → 同一 completed trade_date 的 raw/qfq history QC → latest upsert → validation append → enable-last；current single-source/pending 语义与 scheduled latest 保持一致。重试按 history/latest/validation component-wise repair，只有 identity absent/disabled 才最后 enable；全部组件完整且已启用才幂等。
- 新增回归覆盖：watchlist enable 失败后 ADD retry 只补身份；disabled 且完整的 REENTER 不重复 validation；validation append 失败后 retry 只补 validation + final enable。既有 repeated ADD/CLOSE/SYNC 与 scheduled latest parity 保持通过。
- WatchlistTable 新行通过真实 spreadsheet metadata 动态扩展到所有表头/新行（含正式 P 列 `历史数据源`），复制既有格式且保留未知列；不硬编码 sheet/table/range，不创建额外 banding。
- 本任务边界：只做 holdings lifecycle closure；未执行真实 ADD/CLOSE/REENTER/SYNC，未写 production Sheet，未读取账户/券商，不启动 SETUP_02/03、Wave/Decision/Final OOS 或 outcome 研究。

## Previous Completed Task: repository-local holdings-data-manager Skill

本任务为单一标的持仓数据生命周期能力，不改变总体策略身份或任何 SETUP/Wave/Decision/Risk/Position/Exit/研究协议。

- Skill specification：`skills/holdings-data-manager/SKILL.md`；业务实现：`holdings_data_manager.py`。
- 核心接口：确定性 `ADD`、`REENTER`、`CLOSE`、`SYNC`；支持 “添加 MU”“我买了 512400”“重新买回 INTC”“NOK 已清仓”等自然语言输入；停用身份收到 ADD 自动按 REENTER 语义补缺口后恢复。
- 当前持仓事实源继续是 `自选清单.启用`；证券身份/数据源映射仍在同一行；raw/qfq 历史及审计与当前持仓视图分离。
- 新身份先规范化并用现有 latest provider 确定最近已完成市场交易日，再用现有 history provider 只写 raw/qfq 缺口；coverage 只使用 observed session dates，raw/qfq 日期集必须一致、无重复、至少 180 bars、末日到达目标、起点最多落后 7 天且异常 observed gap 不超过 14 天；两套历史和质量门控成功后才启用。REENTER 完整覆盖时不重抓一年；CLOSE 永不删除历史；重复操作幂等。
- provider、历史日期/OHLCV 质量、身份/市场歧义或覆盖不足均 fail closed；不创建第二套 registry，不读取账户信息，不访问真实券商，不调用完整 `full` pipeline。
- 本地 focused holdings `22/22`、full unittest `393/393`、compileall、`git diff --check` 和 Skill validator 已通过；PR #38 merge 后 main exact-head CI `33362271501` success；本轮不再有待 merge 动作。
- Read-only live provider smoke：`512400.SH` raw/qfq 各 `242` bars（`2025-08-27..2026-08-27`），duplicates `0`，date-set difference `0`，coverage/QC passed；provider 落后 freshness guard `2026-08-28`，故 lifecycle readiness=false。`MU` raw/qfq 各 `252` bars（`2025-08-28..2026-08-28`），同样无重复/日期差异，coverage/QC 与 lifecycle readiness passed；两者均 `sheets_written=false`。
- 当前 holdings task 状态：`HOLDINGS_DATA_MANAGER_SKILL_V1_MERGED`；Issue #42 已完成首条真实 production command：`ADD 512400`、`market=CN`、`dry_run=false`、normalized=`512400.SH`、`status=SUCCESS`、`enabled=true`、`history_rows_written=480`。该事实来自 GitHub machine-readable result comment；不改变 manager/command bus/Sheets 业务逻辑。

## Previous Completed Task: LIVE_WRITE_ENABLEMENT_V1

- 该任务已完成并 merge：实现严格 dry/live routing、conditional GitHub Secrets、workflow concurrency 与现有 manager delegation；随后 Issue #42 已完成一次真实 production `ADD` 成功，结果见上方当前 holdings 事实。
- command title 必须精确为 `[HOLDINGS_COMMAND]`；body 是严格 JSON v1，仅允许 `version`、`operation`、`symbol`、`request_id`、`dry_run` 与可选 `market`，operation 仅 `ADD`/`REENTER`/`CLOSE`/`SYNC`，单 command 仅一个 symbol。
- `.github/workflows/holdings-command.yml` 仅由 `issues.opened` 触发；job-level 先 fail closed 校验 governed repository、non-PR、`github.actor == 'EFSing'`、event sender login 和 Issue user login 均为 `EFSing`，Python 再执行 authoritative allowlist/title/schema/event guard；Issue body 只由 bridge 从 `GITHUB_EVENT_PATH` 读取，不插入 shell/Python 字符串。
- `holdings_command_bus.py` 负责协议/回执；`scripts/holdings_command_bridge.py` 负责 event → schema → 既有 identity normalization → result receipt，并只在显式 live gate 与 credential presence gate 同时满足时调用 `HoldingsDataManager.execute(...)`；不复制 holdings 业务逻辑。
- workflow 先运行无 Secret route step；`dry_run=true` 或 invalid route 进入 gate-disabled、无 Google credentials 的步骤，保持 `DRY_RUN_COMMAND_BUS_HAS_NO_GOOGLE_SECRETS`；仅严格校验通过的 `dry_run=false` route 进入 live step，并只从既有 GitHub Secrets 注入凭证。workflow-level `concurrency` 串行 command jobs，bridge 默认 gate 仍 fail closed。
- 回执包含 `request_id`、operation、normalized symbol、market、status、enabled、`history_rows_written`、message，并由 workflow 写 comment、加结果 label、关闭 Issue；不输出账户数量、成本、NAV、P&L 或 broker 信息。
- command-bus focused tests 为 `19/19`，holdings lifecycle focused tests 既有 `24/24`，full unittest 为 `414/414`；changed-file compileall 与 `git diff --check` 通过。此前 closeout 未执行真实 command；Issue #42 是之后已核实的首条真实 command。
- live regression 覆盖 live ADD delegation、dry-run no-client、unauthorized/malformed fail closed、manager FAILED receipt、rerun/idempotency propagation、conditional Secrets、concurrency 与 secret non-disclosure；FAILED receipt 的 `enabled` 被防御性归一为 `null`。

## Previous Completed Task: SETUP_01 Decision/Risk v1 reconciliation

- 当前节点：`SETUP_01_DECISION_RISK_V1_MERGED`。Sol approval=`APPROVE_SETUP_01_DECISION_RISK_V1_RECONCILIATION`；PR #43 已 squash merged，merge commit=`3b300975e999a934533398a951e7ec34e80a17bd`；原 PR #37 因旧 base `CONFLICTING/DIRTY` 已关闭且未合并，关闭说明明确指向 #43。
- 只移植 PR #37 尚未进入当前 main 的 Decision/Risk implementation、protocol、generic synthetic shadow 与 regression；不修改 holdings manager/command bus/Sheets 逻辑，不改变 Wave Engine、canonical Fibonacci、SETUP_03 或既有 strategy semantics。
- 冻结语义：首个 T 日 `CONFIRMED` identity exactly-once、T close 只形成 plan、最早 T+1 exact session `OPEN`、fixed Entry Zone/entry/stop、structural invalidations、target-before-RR、历史 terminal no-redecision、WATCH/ARMED context-only、OPEN-only execution。
- `actual_entry != None iff outcome == EXECUTED`；`t1_open` 是观察价格，RR skip 保留 `t1_open`/`actual_rr` 但 `actual_entry=None`。Development session identity 为 `DEVELOPMENT_SESSION_IDENTITY = FROZEN_DATASET_MARKET_SESSION_SET`；production prerequisite 为 `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION`，本轮不接第三方 calendar。
- 预期 DEVELOPMENT_EXPOSED baseline：745 CONFIRMED / 745 Decision / 5 ENTRY_ALLOWED / 5 T+1 attempts / 4 EXECUTED / 1 `SKIP_GAP_BELOW_CONFIRMATION`；Decision gates `ABOVE_ENTRY_ZONE=464`、`RR_BELOW_MINIMUM=276`、`ENTRY_ALLOWED=5`、其余为 0；execution `SKIP_RR_BELOW_MINIMUM_AT_OPEN=0`。Target provenance 预期 5/5 既有 `WAVE3_FIB_EXTENSION / 1.272`、historical swing-high T1=0、>5R=0、geometry pass。

### Project Strategy Identity (unchanged; historical context)

总体策略以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一正式事实源，主线为 `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。第一版四类 Setup 为：`SETUP_01`（Wave 2 → Wave 3）、`SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、`SETUP_04`（Extreme Fear Reversal）。`SETUP_03` 只是一个子策略；当前工作实现 Wave Scenario context，不改变总体策略路线。

- PR #35 已 squash merge，merge commit `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`；main exact-head CI `33298510168` success。其 Wave Engine v1 semantics 未修改，研究结论仍保持 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。
- PR #31 已关闭并记录 `superseded by #34`；没有直接 merge/rebase 旧 base diff。
- 当前生产根因已定位：旧 `main.run()` 用 wall-clock `expected_latest_trade_date()` 作为最新性判断，且 scheduled path 与 full history/qfq/SETUP_03/Decision 共用编排；虽然 `最新行情.交易日期` 当前由 `chosen.trade_date` 映射，日期选择、延迟周末、未来日期和 US session-date 边界缺少独立 fail-closed 保护。
- 当前修复已加入 source-date evidence、ordinary-calendar freshness guard、future-date rejection、market-local timestamp normalization，以及显式 `latest/full` 隔离。长期不变量：`交易日期 = 市场真实 session trade_date`；`运行时间 = 北京时间 fetched_at`；二者不得互相替代。
- 首次真实 latest-only smoke 发现 `SIVE.ST` 的 yfinance `period=5d` 尾行存在 OHLC `close=null`；已改为显式 bounded 日期窗口并逐日回退至 bounded Yahoo Chart，禁止填补或伪造价格。
- 最终真实 latest-only smoke：Asia run `33265877563` 成功（3/3 verified）；US run `33265875055` 成功（6 verified、SIVE 1 single-source current/pending）。10/10 启用持仓的 `最新行情.交易日期` 均为市场真实 `2026-08-28`；SIVE 的 `2026-08-28` 来自 bounded Yahoo Chart，未再落后到 8/27。所有 `抓取时间` 为北京时间 `2026-08-30 01:28:31` 或 `01:32:25`，Sheet 格式分别为 DATE 与 DATE_TIME；两次 workflow 均 `history_rows_written=0`、`decision_rows_written=0`。
- 上述 SETUP_01 structural closeout 是历史上下文；其协议与 lifecycle semantics 保持冻结。本轮新增的 Decision/Risk 只消费其 first-entry event，不重算 structural event。
- SETUP_01 development structural replay：40/40 symbols、86,305 replay days、0 errors、1,404 lifecycle events（745 `CONFIRMED` / 659 `FAILED`）；CN event distribution 299/313，US 446/346。primary Wave family counts 为 `WAVE_2_TO_3_CANDIDATE=21,439`、`UPTREND_UNKNOWN_WAVE=28,644`、`ABC_CORRECTION_CANDIDATE=3,644`、`DOWNTREND_OR_INVALID_FOR_LONG=21,137`、`NO_VALID_SCENARIO=2,128`、`WAVE_3_CONTINUATION_CANDIDATE=9,313`。
- development 当前未终结候选只有 US `STX` (`ARMED`，as-of `2026-08-26`，Fib `0.618-0.786`)；real holdings shadow 当前候选为 CN `000725.SZ` (`WATCH`，as-of `2026-08-28`，Fib `0.5-0.618`)。Real shadow 10 requested / 8 evaluated / 2 errors，SETUP_01 states `FAILED=5`、`WATCH=1`、`CONFIRMED=2`；SIVE.SE freshness stale、MU 历史源为空，均 fail-closed。报告输出 `primary_wave`/`alternate_wave`、SETUP_01 legs/Fib/levels/reason、freshness/error。
- merge 后 closeout 不启动 SETUP_02、不重新打开 SETUP_03、不访问 real holdings/private Secrets，不读取 returns/MFE/MAE/P&L/Final OOS，不写 production Sheets，不开始 production execution/calendar implementation，不创建新的开发 PR；generic shadow 仅为 synthetic public fixture。

- Merge verification：PR #43 合并前 head=`f63617d70a2bd498f7fd2777221f162fb4264417`、base=`e5d967d3936ba7731c8bd3b0bb8212833733f2bd`，状态 `OPEN / CLEAN / MERGEABLE`；exact-head CI `33402171900` 与 generic shadow `33402171991` 均 success。合并后 main exact-head CI `33404615092` 以 head=`3b300975e999a934533398a951e7ec34e80a17bd` success。

## Completed

- 多市场行情抓取（A股/港股/美股/日股/瑞典股）
- 数据源回退链（yfinance → YahooChart / BaoStock → Tencent/Sina 快照）
- 双源校验（日期、收盘价、成交量容差）
- 行情来源质量选择：同日主源 OHLCV 异常、校验源正常时，整根行情采用校验源，并同步替换未复权历史末根 K 线；两源均异常时继续待复核
- Google Sheets 写入（最新行情 / 历史行情_未复权 / 历史行情_前复权 / 校验记录 / 运行日志）
- GitHub Actions 定时任务（亚洲 / 欧美两个工作流）
- CI Test Gate：`.github/workflows/ci.yml`，PR 与 main push 自动跑 unittest
- Trading Core Phase 1（`trading/` 包，已合并到 main）：models（数据模型 + 输入校验）/ indicators（Wilder ATR·RSI·EMA）/ swing（causal pivot 状态机 + PROVISIONAL·CONFIRMED）/ structure（Market Structure）/ fibonacci / risk（R&R + Position Size）
- Phase 1 hardening + repaint 修复（已合并）：补测试缺口 + swing 状态机修复 confirmed repaint，全量 83/83 通过
- Phase 2 SETUP_03 Platform Breakout（已合并到 main）：`setup.py` 状态机（NONE/WATCH⇄ARMED/CONFIRMED/FAILED）+ `Setup` 数据模型，平台边界一致性 + terminal lock + 直接突破；全量 93/93 通过
- Phase 3 Decision Engine（SETUP_03 最小闭环，PR #9 已合并到 main）：Entry → Structural Invalidation → Execution Stop → Target → R/R → Position Size → Decision Action；future Setup 防泄漏 + 真实 ENTRY_ALLOWED 回归案例；全量 104/104 通过
- Phase 4 第一批：SETUP_03 Decision 只读投影到 `交易决策` 表；正式收盘 + qfq 日期双门控、显式历史源、参数透传与单标的异常隔离；全量 116/116 通过
- Phase 5A：SETUP_03 Historical Replay & Diagnostics（只读）：`trading/replay.py` 按历史交易日前缀 `quotes[:i+1]` 严格 as-of 回放，复用现有 Setup / Decision Engine，明确区分状态日与 CONFIRMED/FAILED 事件，仅在 CONFIRMED 事件日运行 Decision；新增 workflow_dispatch-only 真实前复权回放 workflow（只读 artifact，不写生产 Sheet）；全量 122/122 通过
- SETUP_03 审计整改：生产与回放共用 `trading/events.py` 终态事件语义；`交易决策` 改为仅发布新 CONFIRMED 事件并以已有事件键阻止同日重算；补齐真实多生命周期回放、数据质量门控、calculable/enabled 覆盖率失败条件、只读事件明细 artifact 及 replay/生产一致性测试；全量 136/136 通过
- SETUP_03 审计整改 PR #12 已合并；带真实 Secrets 的 3 年只读 replay 在生产参数 `platform_tolerance_pct=0` 下客观为 `events=0`
- Phase 5B SETUP_03 Research Backtest & Parameter Diagnostics（PR #13 已合并）：直接消费统一 CONFIRMED 事件流水；T 日生产 Decision gate 后，仅 `ENTRY_ALLOWED` 在 T+1 Open 尝试三分支执行。真实 Core → ReplayEvent → EXECUTED 集成测试、CONFIRMED → Decision → T+1 守恒漏斗、退出 bar 保守 MFE/MAE 与实际 `observation_days` 口径均已冻结；真实 3 年只读 workflow `32747728644`（9 标的/6037 bars）：生产参数 `0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`；固定 54 组累计 `206 CONFIRMED → 4 ENTRY_ALLOWED → 3 SKIP_GAP_BELOW + 1 SKIP_GAP_ABOVE + 0 EXECUTED`，计数守恒且不排名、不优化、不改生产参数
- Development Strategy Stability Evidence（当前 development branch）：以 A1 v2 保存的官方 source snapshots 为唯一候选来源，先排除全部 120 个 A1 formal identities，再按新的固定 SHA-256 非信号规则冻结 CN/US 各 20 个 development symbols；universe manifest `sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046`、symbol list `sha256:03f9d0973340d27c04e9d53c86722100c0b0e6c42d7249147409781a73e904d5`，计算交集为空。未使用 IBKR、final OOS 或 formal Phase 5K 数据。

## Completed / Recorded Research Outcomes

> Remote PR reconciliation at initialization: PRs #14–#22, #25–#27 and #29–#30 are merged; PRs #23, #24 and #28 are closed without merge; PR #31 remains an old-base independent hotfix and current PR #34 is the active production date hotfix. Individual bullets below preserve research outcomes and are not a substitute for current PR state.

- Phase 5C SETUP_03 Decision Gate Diagnostics（PR #14 已合并）：Decision 同一次生产计算返回原 `Decision` 与只读 `DecisionDiagnostics`，ReplayEvent 原样携带 diagnostics，research 固定 54 组只投影、不重算交易条件；新增逐事件/逐参数组合 CSV，并强制 reason 守恒；全量 164/164 通过。真实 3 年只读 workflow `32821290764` 成功（9/9 标的、6032 bars、skipped=0）：生产参数仍为 `0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`；54 组为 `197 CONFIRMED → 4 ENTRY_ALLOWED → 3 SKIP_GAP_BELOW + 1 SKIP_GAP_ABOVE + 0 EXECUTED`，27 组有 CONFIRMED、3 组有 ENTRY_ALLOWED。Decision gate 为 `139 ABOVE_ENTRY_ZONE + 54 RR_BELOW_MINIMUM + 4 ENTRY_ALLOWED`，其余 reason（含 OTHER/invalid context）均为 0；不排名、不选 best、不修改生产参数或交易行为
- Phase 5D Replay Input Reproducibility（PR #15 已合并，基于 PR #14 的堆叠开发）：对实际进入 replay 的完整 Quote 生成逐 symbol/全数据集 SHA-256 manifest；支持六类显式 manifest diff、确定性 frozen input、跳过 live fetch 的 frozen replay 与 artifact 间自动比较。任何 frozen 内容与嵌入 manifest 不一致时 fail fast；`artifacts/` 已加入 gitignore。全量 172/172 通过。真实 live runs `32826696259` / `32828129539` 均成功：均为 9 symbols / 6032 bars、bar count 与日期范围相同，但 aggregate hash 由 `sha256:2b8203…c54703` 变为 `sha256:8166e1…09e36`，6 symbols 为 `CONTENT_CHANGED_WITH_SAME_BAR_COUNT`，grid funnel 由 `207 CONFIRMED → 4 ENTRY_ALLOWED → 0 EXECUTED` 变为 `200 → 4 ENTRY_ALLOWED → 0 EXECUTED`。frozen run `32829662164` 从首轮 artifact 重放成功：9/9 `IDENTICAL`，aggregate/frozen bytes/六份核心报告 hash 与 funnel 全部一致，验证 same input + same config/code 可重复
- Phase 5E Frozen Dataset Validation（PR #16，基于 PR #15 的堆叠开发）：固定 Phase 5D 首轮 run `32826696259`（9 标的/6032 bars，dataset hash `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`）及生产参数版本 `sha256:abe4d3026892`；Phase 5E 入口禁止 live history，任何 dataset/参数漂移 fail fast，并跳过 54 组参数网格。只读输出中文漏斗、Decision reason、标的/市场/年份/季度、集中度及信号后 5/10/20D forward return/MFE/MAE；全量 176/176 与 PR CI 通过。真实 frozen workflow `32853329965` 成功且 9/9 manifest `IDENTICAL`：`0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`，6032 个状态日全部为 NONE，因此收益、MAE/MFE、集中度与初步 Edge 均不可评估；不优化参数，不启动最终样本外验证
- Phase 5F SETUP_03 Confirmation Gate Diagnostics（PR #17，基于 PR #16 的堆叠开发）：production Setup 同一次计算返回原 `Setup` 与只读 `SetupDiagnostics`，兼容 API 和交易行为不变；Replay 只携带 diagnostics，research 仅投影互斥守恒 terminal reason、逐 gate 漏斗、辅助多重失败与 near-miss 分布。全量 179/179 与 PR CI `32855313853` 通过；真实 frozen workflow `32855822844` 成功，9 标的/6032 bars 且 dataset hash 仍为 `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`。terminal reason 守恒为 `438 NO_NEW_CONFIRMED_SWING + 3474 INSUFFICIENT_HIGH_SWINGS + 837 INSUFFICIENT_LOW_SWINGS + 823 STRUCTURE_NOT_RANGE_OR_TRANSITION + 460 HIGH_SPAN_EXCEEDS_TOLERANCE = 6032`；顺序漏斗中最后 460/460 在零容差 high-span gate 全部淘汰，因此无任何平台被识别，后续 WATCH/ARMED/CONFIRMED 全为 0。不改生产参数/规则，不优化，不启动 OOS。
- Phase 5G Platform Tolerance Sensitivity Study（PR #18，基于 PR #17 的堆叠开发）：锁定同一 9 标的/6032 bars frozen dataset（`sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`）与 production 参数版本，仅按固定顺序改变 `platform_tolerance_pct`（0% 至 10% 共 9 档）；全量 181/181 与 PR CI `32858220007` 通过，最终 frozen workflow `32858348894` 成功。平台识别/WATCH/CONFIRMED/ENTRY_ALLOWED/EXECUTED 依次为：0%=0/0/0/0/0，0.5%=0/0/0/0/0，1%=1/0/1/0/0，1.5%=4/35/1/0/0，2%=5/41/2/0/0，3%=8/58/5/0/0，5%=19/119/12/0/0，7.5%=29/199/18/1/0，10%=39/354/22/2/1；全部 ARMED=0。CONFIRMED 的 Decision reason 仅有 `ABOVE_ENTRY_ZONE`、`RR_BELOW_MINIMUM`、`ENTRY_ALLOWED` 且逐档守恒。绝对数量未见爆炸，但 high/low span 随 tolerance 扩大而上升，10% 的 high-span 中位/P90 已达 5.13%/8.53%、low-span 中位/P90 为 3.28%/8.28%，结构边界明显变宽；3%~5% 首次形成跨多个标的/市场/年份的非单点样本，可作为下一阶段“结构定义与稳定性”研究区域，但不是候选生产参数或收益排名结论。不改 production、不启动 OOS。
- Phase 5H Platform Structure Calibration（PR #19，独立堆叠于 PR #18）：固定研究 2.5%~5.5%，7.5%/10% 仅作压力边界；新增真实市场的每千 bar 发生率、span/持续时间/Swing 数量/不对称、集中度、相邻 tolerance Jaccard/retention/新增消失/date drift，以及严格 as-of Wilder ATR/20 日实现波动率标准化。全量 183/183 与 PR CI `32863009081` 通过；frozen workflow `32863067261` 成功，dataset 仍为 9 标的/6032 bars、`sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`。frozen universe 实际市场为 US 3099 bars、CN 1450、SE 749、HK 734，无 JP。2.5%→5.5% 全样本平台/CONFIRMED 从 7/4 增至 21/14；主研究区相邻 CONFIRMED Jaccard 为 57.14%~85.71%，retention 为 80%~100%，两处同标的日期漂移为 20/17 个日历日；7.5%/10% 压力边界稳定性明显下降。市场间 platform-width percentage median 的 max/min 为 1.79~2.77，而 ATR 标准化后为 1.14~1.54、20 日波动率标准化后为 1.11~1.41，结构差异明显收敛。US bars 占 51.37%，解释绝对 CONFIRMED 占比的大部；4.5%~5.5% US 每千 bar CONFIRMED 仍略高于 CN/SE，但不持续高于 HK，固定百分比市场偏置证据有限且与波动结构混合。只识别市场异质性，不读取收益指标、不选择市场参数、不改 production、不启动 OOS；因 universe 小、市场/标的集中且无 JP，尚不具备 market-specific 定义或参数冻结条件。
- Phase 5I Parameter Freeze Audit（基于已合并 PR #19 的独立分支）：新增机器可读 `setup03_frozen_spec.json`、完整 parameter inventory、critical-values hash 合同和中文冻结前审计。只接受 Phase 5G／5H 已有 artifact 与固定 Phase 5E dataset，不新增指标／分层／stress／网格，不读取 OOS。冻结的是 dataset/证据序列/严格 as-of 诊断协议和 OOS 前禁止继续调参的治理边界；既有 terminal/confirmation/structure 规则保持固定但不由 Phase 5I 改动。正式参数冻结结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`：`platform_tolerance_pct`、setup lookback/window/proximity、market/regime/波动率 production 定义全部明确为 `UNRESOLVED`。
- Phase 5J SETUP_03 Structural Validation Protocol Freeze（PR #22 已合并）：新增版本化机器可读 `setup03_structural_validation_protocol.json` 与只读 loader/static AST audit；protocol version 仍为 `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v1`，canonical integrity hash 更新为 `sha256:b0fe288b66ff5a86b127d57c1cb2493b583d252dcb169edbc86fab52830948bd`，并由不可变 version/hash contract 锁定，同一 v1 即使修改内容后同步重算 hash 仍会失败。parent identity 同时从实际 `research/setup03_frozen_spec.json` 校验 `freeze_version=SETUP_03-FREEZE-2026-08-26-v1`、`freeze_decision=NOT_READY_FOR_FORMAL_PARAMETER_FREEZE` 与 `critical_values_sha256=sha256:447b20182f54b8c994042227bbfbaf94c50b2a9b4ade7332058a014915390a15`。正式候选仅 3.0%/4.0%/5.0%，2.5%/5.5%/7.5%/10.0% 仅诊断边界；lookback=5、window=40 仅保留 incumbent design constant，不声明最优，market/regime/波动率 production 规则禁用。market/symbol concentration 改为每个 candidate 独立计算，不合并三候选事件；qualification matrix 明确 3% 绑定自身 thresholds+3%→4%、4% 绑定自身 thresholds+两侧 pair、5% 绑定自身 thresholds+4%→5%。已预注册 CN/HK/US/JP/SE、每市场≥8/总计≥40 标的及每市场约 6000 有效日 K bars 的 development-validation manifest 规则，但本阶段不执行 validation、不选择正式参数、不抓取数据、不接触最终 OOS。最终状态：`VALIDATION_PROTOCOL_REGISTERED_NOT_EXECUTED`。
- PR #24 收尾审计：PR #24 已关闭且未合并，`research/phase5k-a0-metadata-provenance-foundation` branch 与 head `497bf541e5b92454d4866a066e09364ecdbede4c` 保留为历史治理证据；五市场 metadata framework 不进入新的生产路径。
- Phase 5J-v2 CN/US scope revision（PR #25 已合并）：以 `research/setup03_structural_validation_protocol_v2.json` 注册 CN/US scope、CN Main Board active / STAR-ChiNext inactive、CN/US quota/dedup、独立 qualification 与移除 market concentration gate；v1 protocol 不改，最终状态为 `SCOPE_REVISION_REGISTERED_NOT_EXECUTED`。
- HiThink CN API capability/provenance smoke test（本独立分支）：2026-08-27 18:34:47 +08:00 在网络可用执行上下文重跑代码表、CSI300/500/1000 成分、market-dump 签名端点、复权因子和交易日历；7/7 HTTP 200 且 `code=0`，三条指数端点实际返回 300/500/1000 条当前成分，dump 签名地址可取得但未下载。复权接口仅观察到 `ex_date_ms` 事件字段，未证明预计算 factor 公式；交易日历返回 243 个交易日（2025-08-27 至 2026-08-27），不足以单独覆盖 protocol 要求的每市场约 6000 根有效日 K。结论：`HITHINK_CN_RESEARCH_DATA_PROVIDER_NOT_READY`，不启动 Phase 5K-A1。
- Phase 5K-A1 CN/US Official Universe Snapshot & Manifest Freeze（PR #26 已合并）：v1 bundle/manifest 保留为历史审计证据，原 v1 manifest `sha256:4a33391d57488937bcdd7e501ca65a2ae3dc1c5475e41203f22bbe2e03c057eb` 未修改；v2 使用实际当前抓取保存 HiThink CSI300/500/1000、Nasdaq NDX/SOX、iShares IGV holdings 与 iShares IVV holdings 七份 raw snapshots 及 provenance。已尝试 S&P DJI 公共页，但 bounded retrieval 没有完整机器可读 constituent table，故生产 S&P500 provenance 改为明确的 `S&P500_UNIVERSE_PROXY_IVV_OFFICIAL_HOLDINGS`，IVV raw holdings hash 为 `sha256:633cc4df8492582d847030b3aaf10134792cbb2de1722088bb6dfb2c967bb7b5`、504 equity rows、as-of 2026-08-25；不得称为 official S&P500 constituents。沿用 A1 selection spec 的 SHA-256 seed/ranking、v2 cohort 顺序、canonical identity dedup、CN/US quota 与 80 PRIMARY + 40 RESERVE，生成新 manifest `SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2`，canonical hash `sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433`，状态 `MANIFEST_FROZEN_NOT_FETCHED`；新增 v1 immutability、approved source class、v2 pinning、proxy provenance 与 active-bundle-only rebuild tests。未读取 validation OHLCV、未调用 SETUP_03、未访问收益指标/OOS、未修改 v1/v2 protocol、production 或 Sheets。
- Phase 5K-B0 Development Validation Dataset Acquisition Contract Hardening（PR #27 已合并，active v2）：v1 contract `SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v1` 与 canonical hash `sha256:daed425278bf7b2cca00ede87b56dddc3bc9d47be51508a6800369105f2da039` 保留为 historical audit evidence；active v2 `SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v2` 的 canonical hash 为 `sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588`，状态仍为 `DATASET_ACQUISITION_CONTRACT_FROZEN_NOT_ACQUIRED`。CN exact wire 为 `thscode/interval/start/end/adjust`，其中 Asia/Shanghai 边界固定为 Unix ms `1483200000000` / `1787759999999`；US exact IBKR Contract/`reqHistoricalData` 参数、1 Y calendar chunks、local-date filter、`formatDate=1` 与 `chartOptions=[]` 均已冻结。final roster 只包含 provider/QC/warmup `VALID_ACCEPTED` symbols，`final_roster_count == valid_symbols` fail closed；8/40/6000 hard minimum 与 40 valid CN/40 valid US dataset-readiness target 独立，target shortfall 使用 `TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW`。本轮只做 pure research contract/validator/test hardening，未获取正式 OHLCV、未运行 SETUP_03、未开始 Phase 5K-B1、未访问 CONFIRMED/收益指标/OOS、未修改 production/Sheets。
- PR #29 continuation：先完整审计 immutable v1 的 14 个 OHLC-ordering failure symbols（30 violating bars / 30 violation records；CN 28、US 2；`close > high` 18、`open < low` 6、`close < low` 6），逐 bar 保存 adjusted/raw OHLC、raw validity、raw/adjusted Close、implied factor、IEEE-754 ULP 与 yfinance float explanation。4 bars classified as `NUMERIC_ADJUSTMENT_ROUNDING_ONLY`，其余 26 bars 为 `MATERIAL_PROVIDER_OR_RAW_OHLC`；注册的 QC-only rule 为 binary64 `<=8 ULP`，不修改价格。v1 dataset manifest/hash 与 normalized aggregate 未修改。
- PR #29 development dataset v2：CN 20 个标的统一使用 BaoStock `query_history_k_data_plus`、`frequency=d`、`adjustflag=2` qfq；US 20 个标的继续使用 yfinance auto-adjusted history；窗口为 2017-01-01 至 2026-08-26 local trading date。40/40 symbols、84,284/84,284 bars 通过 QC，CN 40,873 bars、US 43,411 bars；未使用 Tencent/Sina 历史、未补日期、未插值、未生成 synthetic bar、未按信号换股。BaoStock 现有 blank-activity suspension rows 仅在 OHLC 有效且四价相等时规范为 volume=0（不新建 bar），共 16 rows。
- PR #29 structure-only evidence：dataset `SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2`，dataset manifest `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`，aggregate hash `sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356`；CN/US 各 20 symbols，固定 lookback=5/window=40/arm=0，production 3%/4%/5% 与 stress-only 2.5%/5.5%/7.5%/10%，输出 coverage、state/terminal reason、funnel、边界、相邻稳定性、集中度与 sparse/zero evidence。全量 `precompute_swings=False` vs `True` parity 为 40×7=280 cells / every bar / 0 mismatch；状态为 `READY_FOR_STRATEGY_RESEARCH_DECISION`。证据仍明确 `DEVELOPMENT_ONLY` / `NOT_FORMAL_VALIDATION` / `NOT_FINAL_OOS`，不读取 returns/MFE/MAE/P&L/winrate，不运行 final OOS。
- HITHINK environment isolation：smoke test 在测试中显式 unset/patched `HITHINK_FINANCE_API_KEY`，并补充 configured-key 不泄漏回归；真实 HiThink runtime semantics 与 API capability 未修改。
- PR #29 decision gate：新增 tracked structure-only capsule `research/development/development_strategy_decision_capsule_v2.json` 与 Markdown 报告；冻结 v2 pins 未变（CN 20/40,873 bars、US 20/43,411 bars、ALL 40/84,284 bars），BaoStock/yfinance split 保持不变。以 `main@40a3e5f980bf82a85717748ae106847793d1469f` 的逐 prefix `quotes[:i+1]` replay semantics 做 40×7=280 cells、589,988 bars、3,120 events 的全量 parity audit，`LEGACY_MAIN_PARITY_MISMATCHES=0`，shared/precomputed current paths 同样为 0。capsule file SHA-256 为 `sha256:5a0726dccc0bbe273e32b05a71434bec8dde85859483cc9e3f1745d630b17458`，状态为 `READY_FOR_SOL_STRATEGY_DECISION`；只输出 structure-only statistics，不选择 tolerance、不改 SETUP_03、不运行 formal validation/final OOS。
- PR #29 final qualification closeout：保留 v2 capsule/evidence identity 不变，新增 `research/development/development_strategy_decision_capsule_v3.json` / `.md`，继续绑定同一 universe、dataset manifest、normalized aggregate 与 replay input。v3 从冻结 v2 replay input 按 CN/US 各自 valid local `trade_date` 的 union 构造 market session ordinal；同标的一对一 nearest-date matching 算法不变，calendar-day drift 保留为 descriptive field，qualification 只使用 `trading_day_drift`。完整 52-row machine-readable matrix 严格执行 Phase 5J-v2 thresholds 与 3%→4%/4%→5% matrix；candidate-level、Jaccard、retention、concentration、rate thresholds 均通过，drift failures 为 CN 3%→4% median `7.0` / P90 `8.6`、US `10.0` / `19.8`，CN 4%→5% `9.5` / `456.5`、US `5.0` / `279.6` trading days。`qualified_candidates=[]`，`lexicographic_candidate=null`，最终状态为 `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`；v3 capsule file SHA-256 为 `sha256:3fa511fa43b146fae9d1a17799b1ae17ce44ba4915ec4813d7120e53eef5b24c`，canonical payload SHA-256 为 `sha256:e9ec07fa5c1d5fede6b87c5ee0f453fc8a47a786c6725458e98e741faf6dbcee`。failure breakdown、matched-pair buckets、extreme Top 20 与 margin 全部保存在 v3；parity 仍为 280 cells / 589,988 bars / 3,120 events / `LEGACY_MAIN_PARITY_MISMATCHES=0`，不修改 production parameter、SETUP_03、冻结输入或启动新 tolerance research。
- Phase 5J-v3 event matching protocol（本分支，holdout 前已冻结）：新增 `research/setup03_phase5j_v3_event_matching_protocol.json` 与 `research/phase5j_v3_event_matching.py`，protocol version `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`，canonical SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。协议固定 exact `(market, symbol, confirmed_date)` retained、同 market/symbol 的最多 40 trading sessions、最大基数后最小总 session distance、lexicographic deterministic tie-break、one-to-one/non-crossing 及 unmatched 完整计入 Jaccard/retention/added/disappeared；绑定 3%/4%/5%、既有 qualification matrix 与全部禁止事项。旧 PR #29 v3 仅保留历史 evidence，当前研究状态仍为 `NOT_READY_FOR_FORMAL_FREEZE_DUE_TO_EVENT_MATCHING_PROTOCOL_UNDERSPECIFICATION`；第二套 holdout 已在该 protocol freeze 之后完成。
- 第二套 independent development holdout universe（本分支，已在 protocol freeze commit 后冻结）：仅从 A1 v2 七份保存的 official/proxy snapshots 读取 metadata，先排除 A1 formal 120 与 development universe v1 的 40，再用新 seed `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-FIXED-SHA256-SEED-2026-08-29-v1` 做 result-independent SHA-256 ranking，冻结 CN 20 + US 20。universe `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2`，symbol-list SHA-256 `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`，manifest SHA-256 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`；与 A1 formal 120、development v1 40 的 intersection 均为 `[]`。
- Phase 5J-v3 second independent development holdout（本分支）：按冻结 CN BaoStock qfq / US yfinance adjusted contract 获取并冻结 40/40 symbols、86,305 bars（CN 20/41,274；US 20/45,031），provider/QC exceptions=0；dataset manifest `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`、normalized aggregate `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`、replay input `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`。tracked manifests 为 `research/development_holdout/dataset_manifest.json` / `replay_manifest.json`，tracked capsule/report 为 `research/development/development_holdout_decision_capsule_v1.json` / `.md`；raw/normalized bars 与 frozen JSONL 仍仅在 ignored artifacts。structure-only replay/parity 为 280 cells、604,135 bar comparisons、3,008 event comparisons、0 mismatch；冻结 v3 qualification matrix 为 52 rows，`qualified_candidates=[]`、`lexicographic_candidate=null`，最终状态为 `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`。完整 capsule/report 只保留 event identity drift、Jaccard、retention、coverage/QC 与结构字段；未读取 returns/MFE/MAE/P&L/winrate/expectancy，未访问 Final OOS、未启动 Phase 5K-B1、未使用 IBKR、未修改 SETUP_03。审计发现并修复了 dataset→replay wrapper 的 provisional-hash cross-binding 顺序错误；修复只重生成 wrapper integrity，不改变上述 frozen identities 或研究结果。
- FROZEN_ARTIFACT_BACKUP_RECOVERY（当前 branch `research/phase5j-v4-lifecycle-attribution`）：repository loader 已验证 frozen holdout 为 40 symbols / 86,305 bars，按字节复制 replay input、replay manifest、dataset manifest、universe manifest 并生成 recovery manifest；ZIP 传输容器为 `SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，SHA-256 为 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`，3,086,881 bytes，5 个 bundle 文件。Google Drive logical path 为 `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`，file ID 为 `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`；外部审计已独立重新读取云端 ZIP，recovered SHA-256 与上传前一致，状态为 `FULLY_RECOVERABLE`。未重复访问 Google Drive、未访问 provider、未运行 Phase 5J-v4 / SETUP_03、未访问 Final OOS、未创建 PR。
- Phase 5J-v4 lifecycle attribution protocol freeze（当前分支，真实 attribution 前独立提交）：新增 machine-readable protocol、中文说明、version/hash-pinned loader 与 regression tests。protocol version 为 `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`，canonical SHA-256 为 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`，冻结 exact second holdout、3%→4%/4%→5%、FIRST_DIVERGENCE_BAR、root/propagation taxonomy、research-only lineage、四个单机制 counterfactual、historical symptom concordance、parity、output 与 stop states。状态 `LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED`；未运行真实 holdout attribution、未读取 outcome、未访问 Final OOS、未修改 SETUP_03/v3 matching/qualification。
- Phase 5J-v4 attribution execution（当前分支）：在 exact 40 / 86,305 second holdout 上生成 258,915 every-bar trace rows、1,031 lifecycle identities、177 个真实 first-divergence episodes。root pooled ranking 为 low-span `88/177`、high-span `69/177`、both-span `20/177`；3%→4% pooled 为 low/high/both `53/28/9`，4%→5% 为 `35/41/11`。3→4 CN/US 均由 low-span 主导；4→5 CN high-span、US low-span，跨市场不一致；两 adjacent pair 的 pooled dominant root 也不一致。因此 `LARGEST_ROOT_CAUSE=LOW_SPAN_THRESHOLD_CROSSING` 但 evidence status 为 `MIXED_CAUSAL_STRUCTURE`。
- Phase 5J-v4 propagation/counterfactual：3→4 roots/downstream `90/76`（ratio `0.8444`，max depth `4`），4→5 `87/69`（`0.7931`，max depth `4`），downstream 均机械归为 terminal-index cascade 或 no cascade。固定 lower `last_terminal_index` / 抑制 terminal-index propagation 的 diagnostic seam 分别消除或恢复 `76`、`69` downstream lifecycles；固定 detection/anchors 在现有 same-root lineage 上没有额外恢复，terminal divergence remains count 为 0。全部标记 `RESEARCH_CAUSAL_DIAGNOSTIC_ONLY` / `NOT_A_CANDIDATE_RULE`。
- Phase 5J-v4 parity/integrity：对 `origin/main@142b7345a5640b1e87932e41f3dc9311172bf54c` 比较 120 cells / 258,915 Setup bars / 1,028 CONFIRMED/FAILED events，Setup/event mismatches 均为 0；Phase 5J-v3 qualification 和 prior frozen tracked content 未变，Final OOS untouched。capsule file SHA `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，canonical payload `sha256:a2e9a48cac483bca6aae9aeec4d5405634118632e7c34170aef863f24991e797`，trace `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`；tracked provenance hashes 使用 Git-normalized LF bytes，跨 Windows/Linux checkout 稳定。
- Historical symptom concordance（PR #29 tracked capsule only，`NOT_CAUSAL_REPLICATION`）：CN 3→4 `PARTIALLY_CONCORDANT`，US 3→4 `CONCORDANT`，CN 4→5 `PARTIALLY_CONCORDANT`，US 4→5 `PARTIALLY_CONCORDANT`。没有使用旧 residual drift median/P90 或 extreme nearest pairs 作为 causal evidence。

## Closeout / Next

- `SETUP_02_WAVE3_CONTINUATION_STRUCTURAL_V1` 已完成本地实现与 DEVELOPMENT_EXPOSED structural replay，并已 squash merged；当前 Decision/Risk v1 在独立分支继续。
- 历史 structural closeout：branch=`codex/setup02-wave3-continuation-v1`，base=`main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7`，implementation source head=`ac63bd7`；PR #45 已由 Sol 授权 squash merge，merge commit=`f679443d52d767841c0df3ff2e0179648b536fb0`，merge-after main CI=`33494893693` success。
- focused Wave + SETUP_02=`26/26`、full unittest=`455/455`、compileall 与 `git diff --check` 已通过。replay 为 40/40 symbols、84,284 bars、0 errors、213 CONFIRMED / 281 FAILED、identity duplicate/mismatch=`0/0`。
- 唯一当前候选为 US `AMAT` / `WATCH` / as-of `2026-08-26`；state-day counts：`NONE=20,433`、`WATCH=1,288`、`ARMED=1,401`、`CONFIRMED=10,930`、`FAILED=50,232`。
- PR #45 `https://github.com/EFSing/stock-data-pipeline/pull/45` 已创建，base=`main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7`；当前为 `OPEN / CLEAN / MERGEABLE`，exact-head CI 已成功。最终 live head/CI 以 GitHub closeout 核对为准；不 merge。
- overlap 审计已完成：同一 v2 输入上 SETUP_01/SETUP_02 的终态日期交集为 11 个 symbol-date、同类型交集为 0，candidate state-day 交集为 0；primary Wave context 84,284/84,284 日一致。
- 该历史 structural task 已停止并合并；当前 Decision/Risk task 仍不进入 production/holdings/position-management/exit/outcome/OOS 路径。
