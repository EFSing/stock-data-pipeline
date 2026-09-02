# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## PROJECT STRATEGY IDENTITY

- 本项目不是单一 Platform Breakout 系统；长期总体策略的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`。
- 总体主线：`Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 第一版四类 Setup：`SETUP_01`（Wave 2 → Wave 3）、`SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、`SETUP_04`（Extreme Fear Reversal）。
- `SETUP_03` 当前只是正在研究的一个子策略；当前开发深度、commit 数量或 Phase 数量不改变总体策略或优先级。Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 任何总体路线变化都必须先取得用户明确批准，并记录在 `docs/DECISION_LOG.md`；本快照不复制完整策略规范，避免双事实源。

## 1. Current Objective

- **当前 Phase / task:** `VOLUME_VALIDATION_NOISE_FIX`（最小语义 bugfix，已完成并 squash merged）。
- **真实状态 reconciliation:** stale snapshot 中关于 PR #51 的 `OPEN` 状态已按真实 GitHub 刷新为已 squash merged，merge commit=`993d03e428b7eb11da791a608940c9d77a608f96`；本任务 PR #61 已 squash merged，merge commit=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`；当前真实 `main`=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`，其 exact-head `CI Test Gate`=`33618759657` success。历史 provenance 不改。
- **唯一目标:** 让日期和收盘价通过时，成交量 mismatch/missing 仅作为 QC 提示，不阻断核心行情验证；只改现有 `validate_quotes()`、必要回归测试和本次治理 freshness，不启动新 Phase 或研究。
- **实现范围:** `core.py`、相关 validation/latest/holdings 回归测试、最小治理状态更新；不改 tolerance、provider、latest/history lifecycle、command-bus schema、Position Management、SETUP、Wave 或 OOS。
- **操作边界:** 不执行真实 holdings ADD/REENTER；不修改现有 HK ticker normalization，仅确认其回归继续通过。
- **停止条件:** holdings focused、command-bus focused、full unittest、compileall、`git diff --check`、PR exact-head CI 与 merge 后 main exact-head CI 全部成功；本任务已完成，不启动下一任务。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub `main`=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`；PR #51 已 merged，真实 merge commit=`993d03e428b7eb11da791a608940c9d77a608f96`；本任务 PR #61 已 merged，当前 main exact-head CI=`33618759657` success。
- **working checkout:** 当前 checkout 为 `main`，已从 `origin/main` fast-forward，工作树干净。
- **open PR / governance:** PR #50/#51/#60/#61 已 merged；当前唯一 open PR #59 (`PORTFOLIO_RISK_V1`) 与本任务无关，不触碰；本任务无遗留 PR。
- **base CI:** `main@9a6432ffbf4271942bbdf7e169a46fce29776ffe` merge-after exact-head `CI Test Gate` run=`33618759657` success。
- **working tree expected state:** 代码、测试和 protocol docs 进入本分支；ignored `artifacts/` 不进入 commit；不写 Sheets、不访问账户/券商/Secrets。
- **current project/phase status:** SETUP_03 仍保持 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`；SETUP_01/SETUP_02、Position Management/Exit semantics frozen；本任务仅调整 validation 对 volume mismatch/missing 的状态语义，未开启新的 production path，已完成 closeout。

## 3. Completed Work

### Current SETUP_02 structural implementation

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

## 4. Pending Work

### Required Next

- [x] 从现场核对的 clean `main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7` 建立 `codex/setup02-wave3-continuation-v1`，并确认启动前无 open PR。
- [x] 实现独立 SETUP_02 structural evaluator/replay；只接受 primary `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`，不修改 Wave Engine 或 SETUP_01。
- [x] 固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED`、严格高点确认、Wave Engine structural invalidation、weekly/daily/primary failure blocks、terminal once-only event identity 与 future append invariance。
- [x] 完成冻结 DEVELOPMENT_EXPOSED structure-only replay：40/40 symbols、84,284 days、494 terminal events、0 errors、identity audit exactly-once。
- [x] 更新 protocol/status/decision docs，完成 focused/full unittest、compileall、`git diff --check`，并提交本地 source commit `ac63bd7`。
- [x] 创建 PR #45，base=`main@2f56cd0697592c5815dbfea84bf328abe6c4c8c7`，等待 exact-head CI，核对 `OPEN / CLEAN / MERGEABLE`；不 merge。

### Deferred

- SETUP_02 Entry/Exit/holdings/production integration、任何 outcome/backtest/OOS 与 production calendar 仍须等待后续明确授权；当前 Decision/Risk development 仅限本快照所述的 development-only、structure/decision/risk evidence。
- SETUP_01 production integration 与任何 SETUP_01 语义修改不属于本任务。
- 如需继续 SETUP_03，等待新的明确研究决策并注册新 protocol/version；当前结果不授权任何 threshold 或 production 选择。
- Final OOS、formal Phase 5K-B1、IBKR readiness 和任何 production parameter/strategy change。

### Prohibited For Now

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

## 8. Known Issues / Blockers

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

1. [x] PR #51 closeout 已完成：head=`2dbb7a751916921a29360b28467de92e150683e3`，base=`main@07e267bdcae32e8fb4bbc8ee07f9758703feaa09`，squash merge=`993d03e428b7eb11da791a608940c9d77a608f96`。
2. [x] merge-after main exact-head `CI Test Gate`=`33607481962` success；治理状态已刷新为 PR #51 已合并。
3. [x] 已从 clean merged `main@993d03e428b7eb11da791a608940c9d77a608f96` 建立 `codex/hk-yfinance-ticker-normalization-fix`。
4. [x] 修复 HK Yahoo ticker normalization：`00700.HK→0700.HK`、`09618.HK→9618.HK`、`03690.HK→3690.HK`、`09888.HK→9888.HK`、`00005.HK→0005.HK`；非补位零代码保持不变，CN/US normalization 回归通过。
5. [x] 本地 gates 通过：holdings/validation/governance focused=`91/91`，command-bus focused=`19/19`，full unittest=`500/500`，compileall 与 `git diff --check` 通过。
6. [x] 已创建并完成 PR #60；merge 前 head=`c3398fbf38287bd7a438bcf59f32ab97c1949cfc`，live state=`OPEN / CLEAN / MERGEABLE`，exact-head `CI Test Gate`=`33611328193` success。
7. [x] PR #60 已 squash merged，真实 merge commit=`0789fdfb898b9edcf99ee5aaa3450f467889d67f`；merge-after main exact-head `CI Test Gate`=`33611436462` success。
8. [x] local `main` 已刷新为 `origin/main`；治理 closeout 提交与最终 main exact-head CI 均已完成。

## 11. Handoff Checklist

- [x] Current Objective 已更新为 volume validation noise bugfix
- [x] governance conflict 已最小 reconciliation：PR #51 merged=`993d03e...`，真实 main=`6ed3234...`，main CI=`33617194589` success；历史 provenance 保持不变
- [x] scope boundary 明确：只改现有 validation 语义与必要回归；不改 tolerance/provider/lifecycle/command bus/Position/SETUP/Wave/OOS
- [x] volume mismatch/missing、scheduled latest、holdings ADD/REENTER、HK mapping 回归与 focused/full unittest、compileall、`git diff --check` 已完成：focused `104/104`、full `502/502`
- [x] PR #61 head=`d3f5ccf89e7a4f5c912ffec7b70042324ef0f463` exact-head `CI Test Gate`=`33618647932` success、live `CLEAN / MERGEABLE`；已 squash merged 为 `9a6432ffbf4271942bbdf7e169a46fce29776ffe`
- [x] merge 后 main exact-head `CI Test Gate`=`33618759657` success；local `main`=`origin/main`=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`
- [x] 本任务不新增 DECISION_LOG 设计条目；历史 provenance 保持不变

## 12. Last Verified

- `last_updated_at`: `2026-09-02`
- `verified_origin_main_sha`: `9a6432ffbf4271942bbdf7e169a46fce29776ffe`; PR #51 merge commit=`993d03e428b7eb11da791a608940c9d77a608f96`; main exact-head CI=`33618759657` success
- `latest_substantive_implementation_sha`: `d3f5ccf89e7a4f5c912ffec7b70042324ef0f463` (PR #61 source head)
- `merged_pr`: PR #61 `https://github.com/EFSing/stock-data-pipeline/pull/61`; source head=`d3f5ccf89e7a4f5c912ffec7b70042324ef0f463`; merge commit=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`; merge-after CI=`33618759657` success
- `current_branch`: `main`; local `main`=`origin/main`=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`
- `latest_hk_ticker_mapping`: verified; `00700.HK→0700.HK`、`09618.HK→9618.HK`、`03690.HK→3690.HK`、`09888.HK→9888.HK`、`00005.HK→0005.HK`，`12345.HK` unchanged
- `latest_setup02_corrected_funnel`: 213 CONFIRMED → 213 Decision; `ENTRY_ALLOWED=1`; gate=`ABOVE_ENTRY_ZONE 97 / STALE_CONFIRMATION_GEOMETRY 12 / NO_VALID_TARGET 1 / RR_BELOW_MINIMUM 102`; T+1 attempts/executed=`1/0`; skip=`SKIP_GAP_BELOW_CONFIRMATION 1`; 12/12 old INVALID_STRUCTURE root causes are stale confirmation geometry
- `latest_test_result`: focused=`104/104`; full unittest=`502/502`; compileall=`PASS`; `git diff --check`=`PASS`; merge-after main CI=`33618759657` success
- `scope_boundary`: only existing `validate_quotes()` volume status semantics, tests, and minimal governance freshness; no holdings ADD/REENTER, lifecycle/schema/provider abstraction/SETUP/Wave/OOS changes
- `live_ci`: PR #61 source head=`d3f5ccf89e7a4f5c912ffec7b70042324ef0f463`; exact-head `CI Test Gate`=`33618647932` success; merge main head=`9a6432ffbf4271942bbdf7e169a46fce29776ffe`; merge-after exact-head `CI Test Gate`=`33618759657` success
- `next_action`: stop; do not start another task or execute holdings ADD/REENTER

`HANDOFF_CURRENT_AND_CONSISTENT`
