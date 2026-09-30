# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

当前逻辑任务是收敛 PR #127 的 docs-only governance closeout：D1 V2 activation 已全部完成，
helper visibility blocker 已关闭，branch/full、独立 main/full 与最终 main 只读校验均已通过，
CN/US V2 均已正式 activation，formal session 仍为 `0/0`。PR #127
（`docs: record D1 V2 activation completion`）已创建并保持 OPEN/mergeable，changed files
仅为 `HANDOFF.md` 与 `docs/CURRENT_STATUS.md`，exact-head CI 已通过。当前唯一用户决策是
是否 squash merge PR #127；不自动 merge。当前 operational 状态为
`D1_V2_ACTIVATION_COMPLETE`、`D1_V2_WAITING_FOR_FIRST_NATURAL_ELIGIBLE_SESSION`；部署身份
硬化仍为 `D1_VPS_HELPER_DEPLOYMENT_IDENTITY_HARDENING_PENDING`。不得改变冻结交易策略、
Paper、broker、Final OOS 或整体 Wave/Setup 路线；本轮不运行 natural collector、不回填、
不修改 production state。

当前 main 的生产数据架构为：CN 唯一 `HITHINK_FINANCIAL_API`，US 唯一 `YAHOO_CHART`；
CN Candidate 为 HITHINK 官方 `000300.SH`/`000905.SH` 成分的确定性 union/dedupe；BaoStock
只保留 legacy/research 职责。Candidate component status 与 formal data status 分离，
`RUN_STATUS`/`DATA_STATUS`/`CANDIDATE_STATUS` 语义保持不变。此前已合并的 CN/US schedule、
close reconciliation、Cloudflare Worker Cron 与 Ubuntu VPS trigger-only watchdog 保持不动。

用户已正式批准把 SETUP_01 H1 突破后双路径独立数据设计从受阻的 D2 改为
`D1_PROSPECTIVE_TIME_ISOLATED`，并已依次放弃 Google Drive 与 Google Cloud Storage durable
storage，改用用户自有 Ubuntu VPS。Drive 404 与已合并的 GCS adapter 都保留为历史实现/测试
资产；GCS 在任何真实 bucket、activation 或 formal D1 evidence 之前停止，其 workflows 现为
disabled/non-production，运行期没有 explicit approval 时拒绝写 formal D1。当前正式 backend
是 SSH immutable store `SETUP01_D1_VPS_SSH_DURABLE_STORAGE` /
`VPS_D1_DURABLE_BACKEND_V1`：GitHub Actions 继续做全部计算，VPS 只做 immutable storage、
activation/pointer、SHA 校验、verify/export/recovery/migrate 与磁盘健康。分支维护流程证明
远端 helper 是不再扫描 `system/activation_epochs/` 的已知旧版本，并只原子替换
`/srv/d1-research/system/d1_vps_store_helper.py`；没有写入 D1 evidence、activation 或
formal session 路径。随后 branch full verify、独立 main full verify 与最终 main full verify
均通过；没有运行 natural collector、没有 backfill，也没有修改正式 SETUP、Risk、Daily
Decision、Paper、Sheet 或 broker 语义。

总体策略唯一正式事实源仍为 `docs/TRADING_SYSTEM_SPEC.md`：Weekly State → Daily State
→ Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target
→ Risk / Position Management → Exit。四类 Setup 身份与优先级不变：`SETUP_01` = Wave 2 →
Wave 3，`SETUP_02` = Wave 3 Continuation，`SETUP_03` = Platform Breakout，`SETUP_04` =
Extreme Fear Reversal；SETUP_03 仍只是其中一个子策略。

## Current State

- `SINGLE_SOURCE_MARKET_DATA_V1` 已随 PR #124 进入 production main。CN price/history 使用
  `HITHINK_FINANCIAL_API`；CN Candidate 使用 HITHINK 官方 HS300 `000300.SH` ∪ CSI500
  `000905.SH`，确定性 union/dedupe；BaoStock 不进入 CN production Candidate。US price/history
  使用 `YAHOO_CHART`，不增加第二 price vendor。当前正式 main、branch、PR、CI 均以 GitHub
  实时事实为准。
- CN stock qfq 使用 HITHINK raw `adjust=none` + HITHINK corporate actions +
  `CN_FORWARD_ADJUSTMENT_ENGINE_V1`；ETF/fund 使用同一 HITHINK fund historical endpoint
  与 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1`。sector metadata 与 `TOP_N_PER_SECTOR` 不再是
  production Candidate 硬依赖。
- symbol failure、Candidate component failure 与 formal strategy analysis 已隔离；Candidate
  不可用时，formal rows 仍可为 `RUN_STATUS=COMPLETED`、`DATA_STATUS=PARTIAL`、
  `CANDIDATE_STATUS=UNAVAILABLE`，不得渲染为 `NO_SIGNAL`。
- `SINGLE_SOURCE_MARKET_DATA_V1` 代码已进入 main，但 `NATURAL_PRODUCTION_RUN_ACCEPTANCE_PENDING`：
  本轮不把尚未发生的 post-merge natural CN/US 日报写成已验收。
- PR #124 与 PR #125 均已 squash merge；当前治理分支只包含 HANDOFF/CURRENT_STATUS
  的最小 docs-only closeout，动态 main/PR/CI 事实仍以 GitHub 为准。
- D1 V1 legacy activation 保留；V2 append-only activation epoch 已按
  `source_contract_version` 精确绑定 snapshot 写入 CN/US，V1 未覆盖 V2。CN record 为
  `321179a6beed10f8786a1cc27e43676085b04b344483426d708c74246304a067`，activation timestamp
  为 `2026-09-30T03:46:23+00:00`；US record 为
  `bb3409ddb1059a34e18375495b5bf976dab31b289b92f7a77ccbb21966bc1f51`，activation timestamp
  为 `2026-09-30T07:02:56+00:00`。两者均为 immutable V2 activation；本轮没有 formal
  evidence 或 formal natural session。
- 旧 US reconciliation run `36657403069` 使用 merge 前旧 main，在 `Reconcile US market close`
  的 VPS formal commit 完整性校验处失败：`D1 formal VPS commit requires a complete natural
  session`。失败发生在 object/pointer 写入之前，不能据此推导 VPS 当前 orphan 状态；没有执行
  cleanup。
- `D1_VPS_REMOTE_HELPER_ACTIVATION_EPOCH_SCAN_STALE` 已关闭：远端旧 helper hash 为
  `cee43b1314a18cb1cd9ff4352e35fd991aa69b1b6fb252a8c0f598cc02aa9690`，授权 main helper
  hash 为 `e2d57ce4e011825a2eee3f2005216d0ff12032e7d2a0140aaf8dd043c6d46334`；原子更新后
  read-back 与 mode 保持一致，`.part`/backup residue 均为 `false`。更新使用
  `StrictHostKeyChecking=yes` 与 pinned host fingerprint，且只触及单一 helper path。
- 最终 main 只读 summary 为 `VERIFIED`：backend 为
  `SETUP01_D1_VPS_SSH_DURABLE_STORAGE / VPS_D1_DURABLE_BACKEND_V1`，storage identity 为
  `43815f2754928dc7be5e58e409a6d0c61493040fbe9f56f6050a93e374675116`，CN/US formal
  session 为 `0/0`，V1 hash 保持 `01d339d52732966d50a33245321b1dc873a7f200f801e887e166d290ea83cb81`
  与 `a1a97dabfa01adeaab964c4ebecc6f686497c1ac1fafa5c399a937d8fb35f85e`，CN/US V2 均为
  present，unreferenced object 与 errors 均为 `0`，`continuation_ready=true`。
- US scheduled reconciliation run `36683686702` 针对 session `2026-09-29` 返回
  `NOOP_BEFORE_ACTIVATION`；没有新增 formal session，CN/US formal counts 仍为 `0/0`，
  不影响 US first eligible session `2026-09-30`。CN first eligible session 为 `2026-10-08`。
- 既有 CN/US schedule、exact resolver、reconciliation、日报 reliability/notification marker、
  Cloudflare/VPS trigger-only fallback 保持不变；#110、#82、#96 继续独立不动。

## Completed

- `SINGLE_SOURCE_MARKET_DATA_V1` 已完成真实 provider acceptance 并随 PR #124 进入 main：
  CN `HITHINK_FINANCIAL_API`、US `YAHOO_CHART`，CN stock raw+corporate-actions internal
  qfq，HITHINK metadata 驱动的 fund/ETF endpoint，统一单源合同校验、provenance、symbol
  status、partial Daily Report 语义和 `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 代码路径；
  交易策略核心未改。代码已进入 main，但自然生产运行验收仍 pending。

- 完成 Wave/Swing/Fibonacci/SETUP_01/Decision/Risk/Position Management/Exit、冻结数据、
  #104 exact-T、关闭回踩研究及 #110 research-only exit/cost 边界审计。
- 冻结统一状态机：H1 突破日 B 可直接成为 continuation signal K，最早 B+1 执行；B 与
  后续 continuation 共用一次路径 A 机会。路径 B 只接受 B 后真实 touch/reclaim。
- 冻结因果边界：当日回踩区只用 `data <= t-1`；running high 不是 confirmed Swing；未来
  Swing 不得回填；信号 K 只在收盘后成立。
- 冻结 `PRICE_ACTION_ONLY`、`ONE_PER_PATH_UNTIL_FILL`（20 sessions）、
  `SIGNAL_SUPPORT_ATR_STOP`、X1 primary / X2 sensitivity、G1 primary / G0 nested attribution。
- 目标候选固定为截至 T 已知且 `price > entry_trigger`，nearest-first 冻结 T1/T2/T3；
  `entry_ceiling` 不预过滤近 T1，actual entry >= T1 时直接 skip，不得替换为 T2。
- 明确所有已暴露 Development / holdout / early-entry / SETUP_03 资产不可重新命名为新独立
  样本，并登记 prospective time-isolated 与新 symbol-disjoint historical 两个数据选项。
- 新增 D1 五组件不可变 session snapshot、content-addressed object/session commit、幂等重跑、
  缺日/hash/protocol/component 检测、clean recovery、private holdings/account key fail-closed、
  Path A/B 生命周期、next-session 模型、CN T+1、同日歧义与独立中文研究报告/CLI；全部仅以
  frozen synthetic fixture 验证，未形成正式 D1 事件。
- 新增 folder-scoped Google Drive backend：只按配置 folder ID 访问，使用 `drive.file` scope，
  支持最小 writer capability 检查、write/read-back probe、immutable create-if-absent、冲突
  fail-closed、全图 verify 与 clean-directory 跨设备恢复；独立 synthetic validation workflow
  已在 main 上执行，但受 folder `files.get` 404 阻断。原 CN/US 诊断 workflow 会调用可能
  读取真实持仓的生产日报，已移除；正式自动 schedule 由 GitHub native schedule 承担，
  D1 首个自然 session 仍未形成。
- 新增 VPS durable backend：通过 SSH 公钥运行单一 repository-owned、stdlib-only、流式 remote
  helper（不使用 nginx/数据库/Docker/Redis/S3 gateway/FTP/常驻 Web API）。目录固定为
  `objects/`、`sessions/CN/`、`sessions/US/`、`system/activation/`、
  `system/activation_epochs/{CN,US}/`、`system/validation/`、`manifests/`；
  写入为 create-only（`O_CREAT|O_EXCL`）+ fsync + 落盘后重算 SHA-256 + pointer/object
  read-back 交叉校验；相同 bytes 返回 `IDEMPOTENT_REPLAY`，同一 identity 不同 bytes、partial/
  interrupted transfer、missing/corrupt object、pointer 篡改、duplicate session 一律 fail
  closed；formal evidence 无 update/delete 路径。SSH 必须校验 host key 与冻结 fingerprint
  （`StrictHostKeyChecking=yes`，禁止 `no`），运行期只用专用非 root 账户，private key 仅经
  Secret 注入临时文件。另含磁盘 free-space 安全/危险阈值（危险阈值 fail closed，绝不自动
  删除 evidence）、root manifest、VPS → 空目录 verified export/recovery，以及
  旧 VPS → export → 新 VPS import → full verify 迁移路径。
- 保留的 GCS backend（历史实现）：使用 GCS JSON API `ifGenerationMatch=0` create-only 写入，校验
  `STANDARD`、uniform bucket-level access、Public Access Prevention enforced、关闭 Object
  Versioning、无不可逆 retention lock；对象布局为 `objects/`、`sessions/CN/`、`sessions/US/`、
  `system/` prefix。对象和 session pointer 都绑定 protocol、market、session、classification、
  SHA-256 与 GCS generation；activation record 在 `system/activation/{CN,US}.json`，formal
  commit 在 activation/window/source contract 全部满足前 fail closed；现为 disabled/future
  adapter，运行期未获 explicit approval 时拒绝写 formal D1。
- D1 source/observer contract 不再从普通 Cloud 日报摘要反推：独立 natural collector 只消费
  public Candidate runtime 的当日 seed、raw Stage-A prefix、exact-T QFQ prefix，并运行既有
  causal SETUP_01 replay + dual-path observer；不读取真实 holdings、Paper 或生产 Sheet state。
  observer 输出包含 signal/touch/no-signal、trigger/ceiling/stop/T1-T3、G1/G0 与 5%/2R/
  `ECONOMIC_ATTRACTIVENESS` diagnostics、next-session model boundary、follow-up set 和中文报告。
- D1 V1 activation bytes/hash 继续绑定 legacy `system/activation/{CN,US}.json`；V2
  activation 只能使用 append-only `system/activation_epochs/{CN,US}/
  SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2.json`，commit 按 snapshot source-contract version
  精确绑定，不使用 `current`/`latest` fallback。本轮 CN/US V2 均已创建且保持 immutable；
  US record 绑定 `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2`、observer
  `SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1`、protocol
  `SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1`（SHA-256
  `ee55ec82959be510a8d9a2d84a99143de3638e550f88527536dad9fd5546d0e0`），首个 eligible
  session 为 `2026-09-30`，last eligible session 为 `2027-09-29`，end boundary 为
  `2027-09-30`，final cutoff 为 `2027-09-30T04:00:00+08:00`。其
  `formal_entry_allowed=false`、`research_only=true`、`paper_write=false`、
  `production_state_write=false`。
- 用户普通股票收益偏好已登记为独立只读诊断：报告分别呈现最近合法 T1 gross headroom、
  后续结构目标及不确定性、止损距离/1R/RR/成本，以及仅在合法最终结果存在时呈现 net
  return/net R/持有期/资金占用；不新增绝对收益硬阈值，不改变 D1/5%/2R/T1 全退或准入。
- 已审计 activation `code_sha`：当前实现校验其 Git SHA 格式并将 activation hash 绑定到
  snapshot source contract，但不把每次运行的 `GITHUB_SHA` 当作硬门槛。本次仅是 scheduler/
  reconciliation operational hardening，保留既有 CN/US activation timestamp、window 与
  code_sha，不重建 activation、不选择性补历史 evidence。

## Blocker / Decision

`D1_V2_ACTIVATION_COMPLETE`：helper stale diagnosis/update、branch/main/final read-only
verify 与 CN/US V2 activation 均已完成；V1 activation 保持不变，formal session 仍为 `0/0`。
`D1_V2_GOVERNANCE_PR_READY_FOR_MERGE`：PR #127 已 OPEN/mergeable，changed files 仅为
`HANDOFF.md` 与 `docs/CURRENT_STATUS.md`，exact-head CI 已通过；不自动 merge，等待用户明确
squash merge 授权。
`D1_V2_WAITING_FOR_FIRST_NATURAL_ELIGIBLE_SESSION`：下一步只能等待 activation record
规定的首个自然 eligible session；不得人工指定日期、collector/backfill 或补写 formal evidence。
`D1_VPS_HELPER_DEPLOYMENT_IDENTITY_HARDENING_PENDING`：后续另行加强 deployed helper 与
授权 main release 的身份绑定，本轮不扩大 scope。

注意：VPS 实例曾被重建，host key 已变更，当前冻结 fingerprint 以 GitHub Secret
`D1_VPS_HOST_KEY_FINGERPRINT` 与 `D1_VPS_KNOWN_HOSTS` 为准；旧指纹文件已作废。VPS 仍禁止
部署 nginx/数据库/Docker/Redis/S3 gateway/FTP/Web API，也不承担计算。

## Next Action

1. 用户决定是否 squash merge PR #127（`USER_DECISION_REQUIRED_FOR_PR_127_MERGE`）。
2. 若授权，squash merge，并核对 post-merge main SHA / main CI。
3. 不运行人工 collector，不 backfill。
4. 等待各市场自然 eligible session：US first eligible = `2026-09-30`；CN first eligible =
   `2026-10-08`。
5. 首次自然 session 后再验收 formal evidence。
6. helper deployment identity hardening 保持独立后续：
   `D1_VPS_HELPER_DEPLOYMENT_IDENTITY_HARDENING_PENDING`。

#110/#82/#96 继续独立不动。

## Constraints

- 不改 Wave/Swing/Fibonacci 核心实现，不访问 Final OOS，不读取真实持仓。
- 不把 H1 后 running high 标成 confirmed Swing；不在看到收益后逐笔选择 stop、target 或 exit。
- Target-before-RR；不得用 T2/T3 绕过 T1，不得为过 2R 延伸 T1 或缩小 stop。
- `ECONOMIC_ATTRACTIVENESS` 与 `SIGNAL_VALID`、`RISK_VALID`、`TARGET_GEOMETRY`、
  `RESEARCH_ADMISSION` 分离；低 gross/net 收益偏好先只读记录，未批准前不得恢复或新设门槛。
- 不得用 `entry_ceiling` 预过滤 `entry_trigger` 上方的合法近 T1。
- 路径 A/B、CN/US 分别报告；不得合并掩盖失败或凑证据下限。
- Candidate-only、Paper、production state、Sheet、broker 边界不变。
- CN production price path 只能是 `HITHINK_FINANCIAL_API`，US 只能是 `YAHOO_CHART`；
  retry 不得换 vendor。CN stock qfq 必须是 HITHINK raw + same-vendor corporate actions +
  internal adjustment engine；HITHINK metadata 明确为 `fund-etf` 的样本使用同一 vendor 的
  fund historical endpoint，并记录 provider-forward-adjusted provenance；任一 adjustment
  contract 无法证明时只能 `DATA_ADJUSTMENT_UNVERIFIED`。
- CN production Candidate 不使用 BaoStock、sector hard dependency 或 `TOP_N_PER_SECTOR`；
  HITHINK current-only index snapshot 晚于 requested `as_of` 时 fail closed。Candidate
  component failure 不得变成 `NO_SIGNAL`；formal rows 可完成为 `RUN_STATUS=COMPLETED`、
  `DATA_STATUS=PARTIAL`、`CANDIDATE_STATUS=UNAVAILABLE`。整个 universe snapshot 不可用时，
  D1 V2 不得 formal commit；已知 universe 下的 symbol-level partial 可以保留。
- `DATA_MISSING` / `DATA_STALE` / `DATA_INVALID` / adjustment or symbol provider errors
  只阻断自身，不得写作 `NO_SIGNAL`，不得以 coverage ratio 作为 market hard gate；provider-wide
  auth/schema/outage 才是 global failure。
- 真实 VPS、真实 holdings、production credential 与新 D1 V2 activation 未经用户明确节点
  批准不得读取、写入或创建；本次不把 generic synthetic shadow 当作真实 holdings validation。

## Known Pitfalls

- 现行 SETUP_01 在 `CONFIRMED` 后 terminal；post-breakout observation 必须是 research
  overlay，不能直接改正式 lifecycle。
- 现行 executor 只有 exact T+1 OPEN；signal-high buy-stop 需要新 research-only OHLC
  顺序契约。daily OHLC 不能证明 queue、spread 或 intraday path。
- 正式 Position Management 的 target 只作状态、不自动卖；mechanical T1 exit 是不同的
  research assumption。
- 免费历史源不能可靠提供完整 point-in-time board/ST/退市/队列/点差数据；数据不足应
  `BLOCKED` 或 `INSUFFICIENT_EVIDENCE`，不能用固定全市场假设补齐。

`HANDOFF_CURRENT_AND_CONSISTENT`
