# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

用户已正式批准把 SETUP_01 H1 突破后双路径独立数据设计从受阻的 D2 改为
`D1_PROSPECTIVE_TIME_ISOLATED`，并已依次放弃 Google Drive 与 Google Cloud Storage durable
storage，改用用户自有 Ubuntu VPS。Drive 404 与已合并的 GCS adapter 都保留为历史实现/测试
资产；GCS 在任何真实 bucket、activation 或 formal D1 evidence 之前停止，其 workflows 现为
disabled/non-production，运行期没有 explicit approval 时拒绝写 formal D1。当前正式 backend
是 SSH immutable store `SETUP01_D1_VPS_SSH_DURABLE_STORAGE` /
`VPS_D1_DURABLE_BACKEND_V1`：GitHub Actions 继续做全部计算，VPS 只做 immutable storage、
activation/pointer、SHA 校验、verify/export/recovery/migrate 与磁盘健康。VPS 已完成一次性
初始化（专用非 root 账户 + root-owned helper + 冻结 storage root），GitHub Secrets/Variables
已就位，真实 VPS synthetic storage validation 为 `VERIFIED`，CN/US 不可变 activation record
均已创建；当前状态是 `D1_ACTIVATION_READY`，正式事件数仍为 0，等待各市场首个自然完整
session。没有运行历史经济验证，也没有修改正式 SETUP、Risk、Daily Decision、Paper、Sheet
或 broker 语义。

总体策略唯一正式事实源仍为 `docs/TRADING_SYSTEM_SPEC.md`：Weekly State → Daily State
→ Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target
→ Risk / Position Management → Exit。四类 Setup 身份与优先级不变：`SETUP_01` = Wave 2 →
Wave 3，`SETUP_02` = Wave 3 Continuation，`SETUP_03` = Platform Breakout，`SETUP_04` =
Extreme Fear Reversal；SETUP_03 仍只是其中一个子策略。

## Current State

- storage 变更已随 PR #119 squash merge 进入 main；CN/US 各自 schedule 已随 PR #120 合并
  （CN 周一至周五 18:40 北京、US 周二至周六 09:40 北京，均保留 workflow_dispatch），正式
  采集入口是 GitHub 原生 schedule，不再需要人工触发；#110、#82、#96 未受影响。branch /
  HEAD / PR / CI 以 GitHub 实时状态为准。
- GCS durable storage 实现已随 PR #117 squash merge 进入 main；用户随后决定不部署它。
  当前 formal D1 durable backend 是 VPS SSH immutable store，GCS/Drive 仅为 retained
  adapter 与历史证据。
- GitHub `main` 已包含 #109 的 SETUP_01 early-entry 第二阶段决策节点；#110 是独立 OPEN
  research-only PR，保持不合并、不改写。#82 与 #96 仍是无关开放 PR。
- #110 的正式研究结论为 `INSUFFICIENT_EVIDENCE`：受约束 PKG_B 实验组净 R 在 CN/US
  均为负，完整现行 Decision 成交过少，比较又对删失敏感；不构成生产授权。
- 已关闭的 `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 继续关闭。新双路径不是
  “进入旧 Entry Zone 后再套旧 5%/2R”的重命名版本，而是新的 research overlay 契约。
- 双路径架构 PR #111 已合并进入 main，未混入 #82/#96/#110。
- 架构文档：`docs/research/SETUP01_POST_BREAKOUT_DUAL_PATH_ENTRY_PROTOCOL_DRAFT.md`。
- 机器草案：`research/protocols/setup01_post_breakout_dual_path_entry_v1_draft.json`；独立
  architecture freeze record 已绑定其 hash，研究仍不可执行。
- D2 审计：`docs/research/SETUP01_D2_DATA_FEASIBILITY_AUDIT.md` 与
  `research/protocols/setup01_d2_data_feasibility_audit_v1.json`。现有免费栈结论为
  `BLOCKED_EXISTING_FREE_STACK_NO_COMPLIANT_POINT_IN_TIME_SOURCE`。
- D1 修订：`research/protocols/setup01_post_breakout_d1_prospective_v1.json` 及独立 freeze
  record；旧 D2 audit/draft/freeze 均保留，D1 与 D2 不被表述为同一协议。
- D1 PR #112 已重基于 #111 合并后的 main，exact-head CI 通过并已合并；Actions 启动路径
  修复 PR #113 与 folder ID 身份校验 PR #115 随后合并。#110 保持独立 OPEN。
- Drive 专用 folder 路线已停止：正确 folder ID 的 service-account API `files.get` 仍返回 404，
  未创建对象；不扩大 Drive scope。GCS 路线已实现（`SETUP01_D1_GCS_DURABLE_STORAGE` /
  `GCS_D1_DURABLE_BACKEND_V1`）但未部署，现降级为 disabled/future adapter。

## Completed

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
  读取真实持仓的生产日报，已移除；正式 schedule 尚未启用。
- 新增 VPS durable backend：通过 SSH 公钥运行单一 repository-owned、stdlib-only、流式 remote
  helper（不使用 nginx/数据库/Docker/Redis/S3 gateway/FTP/常驻 Web API）。目录固定为
  `objects/`、`sessions/CN/`、`sessions/US/`、`system/activation|validation/`、`manifests/`；
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
- 用户普通股票收益偏好已登记为独立只读诊断：报告分别呈现最近合法 T1 gross headroom、
  后续结构目标及不确定性、止损距离/1R/RR/成本，以及仅在合法最终结果存在时呈现 net
  return/net R/持有期/资金占用；不新增绝对收益硬阈值，不改变 D1/5%/2R/T1 全退或准入。

## Blocker / Decision

`D1_FIRST_NATURAL_SESSION_PENDING`：VPS durable storage 已 provision 并通过真实 synthetic
validation，CN/US activation record 均已创建，因此没有外部 blocker，只剩市场自然时间依赖：
US 首个合格 session 是 2026-09-29 ET（北京时间 2026-09-30 04:00 收盘），CN 首个合格
session 是 2026-09-30（北京时间 15:00 收盘）。在对应市场完成首个合法 natural session 的
durable commit + read-back + verify 之前，该市场不得报告 `D1_COLLECTION_ACTIVE`。

注意：VPS 实例曾被重建，host key 已变更，当前冻结 fingerprint 以 GitHub Secret
`D1_VPS_HOST_KEY_FINGERPRINT` 与 `D1_VPS_KNOWN_HOSTS` 为准；旧指纹文件已作废。VPS 仍禁止
部署 nginx/数据库/Docker/Redis/S3 gateway/FTP/Web API，也不承担计算。

## Next Action

- US：2026-09-29 ET session 收盘后由 `setup01-d1-vps-natural-collector-us` 自动采集
  （也可 workflow_dispatch 手动补跑），核对 receipt、event hash、object read-back、
  `vps-verify --full-objects`；通过后 US 进入 `D1_COLLECTION_ACTIVE`。
- CN：在 2026-09-30 收盘后运行 `setup01-d1-vps-natural-collector-cn`，同样验收后 CN 进入
  `D1_COLLECTION_ACTIVE`。
- 两市场都 ACTIVE 后：本次 `research/setup01-d1-vps-natural-schedule` PR 的 schedule 即为
  正式自动采集入口；日常只需观察失败与 `D1_STORAGE_LOW_SPACE`，不得人工构造 session。
- 不得用人工指定日期或旧日报补为首个合法 session。
- #110 保持 OPEN，不自动合并；不得用其已暴露结果选择本草案的 signal/stop/exit/gate。
- US production acceptance 仍按既有自然 schedule 边界独立进行，不与本研究绑定。

## Constraints

- 不改 Wave/Swing/Fibonacci 核心实现，不访问 Final OOS，不读取真实持仓。
- 不把 H1 后 running high 标成 confirmed Swing；不在看到收益后逐笔选择 stop、target 或 exit。
- Target-before-RR；不得用 T2/T3 绕过 T1，不得为过 2R 延伸 T1 或缩小 stop。
- `ECONOMIC_ATTRACTIVENESS` 与 `SIGNAL_VALID`、`RISK_VALID`、`TARGET_GEOMETRY`、
  `RESEARCH_ADMISSION` 分离；低 gross/net 收益偏好先只读记录，未批准前不得恢复或新设门槛。
- 不得用 `entry_ceiling` 预过滤 `entry_trigger` 上方的合法近 T1。
- 路径 A/B、CN/US 分别报告；不得合并掩盖失败或凑证据下限。
- Candidate-only、Paper、production state、Sheet、broker 边界不变。

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
