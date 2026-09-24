# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

用户已正式批准把 SETUP_01 H1 突破后双路径独立数据设计从受阻的 D2 改为
`D1_PROSPECTIVE_TIME_ISOLATED`。独立 D1 协议、collector/reference store、Drive durable
backend、完整性/恢复、causal 双路径 observer、CN/US 独立 workflow 与中文只读报告已实现；
专用 Drive folder 已由用户账号创建，`D1_RESEARCH_DRIVE_FOLDER_ID` GitHub Actions Secret
已配置，但既有 service account 尚未共享该 folder，真实 write/read-back/recovery 与首次
自然 session 均未完成。因此 CN/US
仍为 `D1_READY_NOT_ACTIVE`，正式事件数为 0。没有运行历史经济验证，也
没有修改正式 SETUP、Risk、Daily Decision、Paper、Sheet 或 broker 语义。

总体策略唯一正式事实源仍为 `docs/TRADING_SYSTEM_SPEC.md`：Weekly State → Daily State
→ Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target
→ Risk / Position Management → Exit。四类 Setup 身份与优先级不变：`SETUP_01` = Wave 2 →
Wave 3，`SETUP_02` = Wave 3 Continuation，`SETUP_03` = Platform Breakout，`SETUP_04` =
Extreme Fear Reversal；SETUP_03 仍只是其中一个子策略。

## Current State

- GitHub `main` 已包含 #109 的 SETUP_01 early-entry 第二阶段决策节点；#110 是独立 OPEN
  research-only PR，保持不合并、不改写。#82 与 #96 仍是无关开放 PR。
- #110 的正式研究结论为 `INSUFFICIENT_EVIDENCE`：受约束 PKG_B 实验组净 R 在 CN/US
  均为负，完整现行 Decision 成交过少，比较又对删失敏感；不构成生产授权。
- 已关闭的 `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 继续关闭。新双路径不是
  “进入旧 Entry Zone 后再套旧 5%/2R”的重命名版本，而是新的 research overlay 契约。
- 新分支 `research/setup01-post-breakout-dual-path-protocol-v1` 从 `origin/main` 独立建立，
  PR #111 保持 OPEN，未混入 #82/#96/#110，不自动合并。
- 架构文档：`docs/research/SETUP01_POST_BREAKOUT_DUAL_PATH_ENTRY_PROTOCOL_DRAFT.md`。
- 机器草案：`research/protocols/setup01_post_breakout_dual_path_entry_v1_draft.json`；独立
  architecture freeze record 已绑定其 hash，研究仍不可执行。
- D2 审计：`docs/research/SETUP01_D2_DATA_FEASIBILITY_AUDIT.md` 与
  `research/protocols/setup01_d2_data_feasibility_audit_v1.json`。现有免费栈结论为
  `BLOCKED_EXISTING_FREE_STACK_NO_COMPLIANT_POINT_IN_TIME_SOURCE`。
- D1 修订：`research/protocols/setup01_post_breakout_d1_prospective_v1.json` 及独立 freeze
  record；旧 D2 audit/draft/freeze 均保留，D1 与 D2 不被表述为同一协议。
- 新分支 `research/setup01-d1-prospective-time-isolated-v1` 基于 PR #111 head，已创建
  独立堆叠 PR #112（base 为 #111 分支）；#110/#111/#112 均保持 OPEN，不自动合并。
- D1 专用 folder `EFSing stock-data-pipeline — D1 Research` 已创建；folder identity 只用于
  `D1_RESEARCH_DRIVE_FOLDER_ID`，不得扩大到整个 My Drive。当前仍未向 service account
  授权，未做真实写入。

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
  fail-closed、全图 verify 与 clean-directory 跨设备恢复；CN/US workflow 独立调度，人工指定
  日期一律标为 diagnostic backfill，不得成为前瞻证据。
- 用户普通股票收益偏好已登记为独立只读诊断：报告分别呈现最近合法 T1 gross headroom、
  后续结构目标及不确定性、止损距离/1R/RR/成本，以及仅在合法最终结果存在时呈现 net
  return/net R/持有期/资金占用；不新增绝对收益硬阈值，不改变 D1/5%/2R/T1 全退或准入。

## Blocker / Decision

`D1_DRIVE_FOLDER_SHARE_REQUIRED`：durable backend、专用 folder 与 folder ID GitHub Secret
已完成；仍需用户把该 folder 以 writer 身份仅共享给既有 service account。PR #112 未获
合并授权，workflow 尚不在 main；真实 access
probe、write/read-back、clean recovery 和首次自然 session 尚未运行。完成这些条件前不得
激活或报告 `D1_COLLECTION_ACTIVE`。除此之外没有需要用户决定的策略参数。

## Next Action

- 获取既有 service account 的 `client_email`，由用户只共享专用 Drive folder 并配置 folder
  ID secret；#112 经正常 review/merge 后运行真实 access/write/read-back/recovery 验收，再按
  CN/US 自然 schedule 分别记录 activation timestamp 与首个完整 session。不得用人工指定日期
  或旧日报补为首个合法 session。
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
