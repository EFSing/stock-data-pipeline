# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

当前逻辑任务是完成 `SINGLE_SOURCE_MARKET_DATA_V1` 在 PR #124 squash merge 后的正式治理
closeout。PR #124 已进入 main；本分支只修正 `HANDOFF.md` 与
`docs/CURRENT_STATUS.md` 的现场事实，使其与 GitHub 真实状态一致，目标节点为
`POST_SINGLE_SOURCE_MERGE_GOVERNANCE_PR_FULLY_READY`。不得改变冻结交易策略、Paper、
broker、Final OOS 或整体 Wave/Setup 路线；本轮不写 D1 V2 activation、不运行 formal
natural collector、不修改 production state。

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
activation/pointer、SHA 校验、verify/export/recovery/migrate 与磁盘健康。当前环境没有授权的
`D1_VPS_*` 运行时变量，因此本轮没有进行合并后的 VPS read-only verify，正式记录为
`POST_MERGE_VPS_STATE_NOT_REVERIFIED`；此前受控核对的 0/0 只作为历史值，不能冒充本轮实时
事实。没有运行 natural collector、没有创建或覆盖 V2 activation，也没有修改正式 SETUP、
Risk、Daily Decision、Paper、Sheet 或 broker 语义。

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
- D1 V1 legacy activation 保留；V2 append-only activation epoch 代码已进入 main，按
  `source_contract_version` 精确绑定 snapshot，V1 不可覆盖 V2，且
  `D1_V2_ACTIVATION_WRITTEN=False`。本轮没有真实 V2 activation，也没有允许 V2 natural
  collector 提交 formal evidence。
- 旧 US reconciliation run `36657403069` 使用 merge 前旧 main，在 `Reconcile US market close`
  的 VPS formal commit 完整性校验处失败：`D1 formal VPS commit requires a complete natural
  session`。失败发生在 object/pointer 写入之前，不能据此推导 VPS 当前 orphan 状态；没有执行
  cleanup。
- `POST_MERGE_VPS_STATE_NOT_REVERIFIED`：本环境没有 `D1_VPS_*`，因此 CN/US formal count、
  V1 activation hash、orphan/unreferenced object 列表与 V2 activation 是否存在均未作本轮实时
  核对。此前历史核对的 CN/US `0/0` 不替代本轮证据。
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
  精确绑定，不使用 `current`/`latest` fallback。当前代码已准备该路径，但本轮未创建真实
  V2 activation。
- 用户普通股票收益偏好已登记为独立只读诊断：报告分别呈现最近合法 T1 gross headroom、
  后续结构目标及不确定性、止损距离/1R/RR/成本，以及仅在合法最终结果存在时呈现 net
  return/net R/持有期/资金占用；不新增绝对收益硬阈值，不改变 D1/5%/2R/T1 全退或准入。
- 已审计 activation `code_sha`：当前实现校验其 Git SHA 格式并将 activation hash 绑定到
  snapshot source contract，但不把每次运行的 `GITHUB_SHA` 当作硬门槛。本次仅是 scheduler/
  reconciliation operational hardening，保留既有 CN/US activation timestamp、window 与
  code_sha，不重建 activation、不选择性补历史 evidence。

## Blocker / Decision

`POST_SINGLE_SOURCE_MERGE_GOVERNANCE_PR_FULLY_READY`：PR #124 已进入 main，当前治理 PR
只同步 merge 后的现场事实，不改运行代码。`POST_MERGE_VPS_STATE_NOT_REVERIFIED` 仍然成立：
本环境无 `D1_VPS_*`，所以本轮不宣称 formal count、activation hash、V2 presence 或 orphan
状态。V1 activation 保持不变，V2 immutable activation 与 formal evidence 均未写入。

注意：VPS 实例曾被重建，host key 已变更，当前冻结 fingerprint 以 GitHub Secret
`D1_VPS_HOST_KEY_FINGERPRINT` 与 `D1_VPS_KNOWN_HOSTS` 为准；旧指纹文件已作废。VPS 仍禁止
部署 nginx/数据库/Docker/Redis/S3 gateway/FTP/Web API，也不承担计算。

## Next Action

1. 用户决定是否 squash merge 本 docs-only governance closeout PR；本轮不自动 merge。
2. merge 后重新获取最终 main SHA。
3. merge 后再次确认 VPS durable state，并保留 read-only verify 的实时边界。
4. 以最终 main SHA 生成 CN/US `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` activation preview/hash。
5. 用户审核并单独授权 V2 activation write。
6. 完成 write/read-back/full verify；未授权前不写 activation、不提交 formal D1 session。
7. 等待下一自然 eligible session。
8. 验收首次新单源 natural CN/US production run；不得人工指定日期或 backfill。

合并该治理 PR 后的下一正式节点是
`FINAL_MAIN_SHA_BOUND_D1_V2_ACTIVATION_PREVIEW`；#110/#82/#96 继续独立不动。

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
