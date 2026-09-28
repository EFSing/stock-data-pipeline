# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

用户已正式批准把 SETUP_01 H1 突破后双路径独立数据设计从受阻的 D2 改为
`D1_PROSPECTIVE_TIME_ISOLATED`。独立 D1 协议、collector/reference store、Drive durable
backend、完整性/恢复、causal 双路径 observer 与中文只读报告已实现；
专用 Drive folder 已由用户账号创建，`D1_RESEARCH_DRIVE_FOLDER_ID` GitHub Actions Secret
已配置，用户侧权限元数据确认既有 service account 已获该 folder 的 writer 权限；main 上
实际 service-account `files.get` 返回 404，未发生真实写入/回读/恢复。Cloud 日报当前不包含可持久化的
raw/QFQ prefix 和实际 Path A/B observer 输出，且不可变 activation record 尚未实现；正式
Drive commit 因此 fail closed，CN/US 自动 collector schedule 尚未启用。因此 CN/US
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
- D1 专用 folder `EFSing stock-data-pipeline — D1 Research` 已创建；folder identity 只用于
  `D1_RESEARCH_DRIVE_FOLDER_ID`，不得扩大到整个 My Drive。service account 已获该 folder
  的 writer 权限；service-account API 实测对配置 ID 返回 404，未创建对象。

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
- 用户普通股票收益偏好已登记为独立只读诊断：报告分别呈现最近合法 T1 gross headroom、
  后续结构目标及不确定性、止损距离/1R/RR/成本，以及仅在合法最终结果存在时呈现 net
  return/net R/持有期/资金占用；不新增绝对收益硬阈值，不改变 D1/5%/2R/T1 全退或准入。

## Blocker / Decision

`D1_DURABLE_STORAGE_ACCESS_FAILED`：main 上 synthetic validation 已使用既有 service account
与配置的 folder ID；该 ID 与用户提供的专用 folder 链接已通过 SHA-256 一致性校验，排除
Secret ID 不匹配。随后 `files.get` 仍返回 HTTP 404，在任何写入前停止。用户侧共享权限
元数据与实际 service-account API 可见性不一致；`drive.file` 对用户共享文件夹的可见性
限制是可能原因，尚未证明唯一根因。不得扩大 Drive 权限或遍历 folder 外内容。
另有
`D1_SOURCE_ACTIVATION_CONTRACT_PENDING`：Cloud 日报只提供摘要，缺 raw/QFQ prefix 与
Path A/B observer 的可验证输入/输出；不可变 activation record 和 CN/US 正式 schedule
尚未具备。正式 Drive commit 已 fail closed。完成这些条件及首次自然 session 前
不得激活或报告 `D1_COLLECTION_ACTIVE`。没有需要用户选择的新策略参数。

## Next Action

- 由用户决定不扩大现有 Drive 权限的 durable storage 身份/位置；现有 service-account
  `drive.file` + 用户自有 folder 路线已在正确 ID 上遭遇 API 404。之后重跑 synthetic validation，
  再完成 source/observer、
  不可变 activation 与 CN/US 正式 schedule contract，按自然 session 分别启动。不得用
  人工指定日期或旧日报补为首个合法 session。
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
