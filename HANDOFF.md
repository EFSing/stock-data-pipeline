# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

SETUP_01 新一代 H1 突破后双路径入场研究已完成架构审计与可预注册草案，当前状态
`READY_FOR_DECISION`。本任务只到 research architecture/protocol 决策节点；没有运行新
经济回测，也没有修改正式 SETUP、Risk、Daily Decision、Paper、Sheet 或 broker 语义。

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
- 机器草案：`research/protocols/setup01_post_breakout_dual_path_entry_v1_draft.json`，状态
  `DRAFT_NOT_EXECUTABLE_READY_FOR_DECISION`。

## Completed

- 完成 Wave/Swing/Fibonacci/SETUP_01/Decision/Risk/Position Management/Exit、冻结数据、
  #104 exact-T、关闭回踩研究及 #110 research-only exit/cost 边界审计。
- 登记统一状态机：existing H1 first-breakout event → post-breakout observation →
  continuation 或 retest signal K → next-session buy-stop → research PM/Exit。
- 冻结因果边界：当日回踩区只用 `data <= t-1`；running high 不是 confirmed Swing；未来
  Swing 不得回填；信号 K 只在收盘后成立。
- 登记两类机械信号、唯一 active support zone、T+1 gap/trigger 处理、结构失效与 execution
  stop 分离、T1/T2/T3 provenance、CN T+1 卖出限制、US same-day conservative ordering。
- 将 5%/2R 拆为 hard-gate 与 diagnostic-gate 两种互斥研究角色，未更改正式常量。
- 明确所有已暴露 Development / holdout / early-entry / SETUP_03 资产不可重新命名为新独立
  样本，并登记 prospective time-isolated 与新 symbol-disjoint historical 两个数据选项。

## Blocker / Decision

用户需在读取任何新样本信号或收益前选择并冻结：

1. `PRICE_ACTION_ONLY` 或 `PRICE_PLUS_RVOL`；
2. 最早信号 one-shot，或 A 未成交后允许 B 一次机会（总窗口不重置）；
3. signal/support ATR stop 或 Wave2 structural ATR stop；
4. research-only mechanical T1 exit 或 formal-PM-compatible exit；
5. 5%/2R 保持硬门槛或仅作诊断；
6. prospective 12-month time-isolated 或新 symbol-disjoint historical 数据，以及 verified
   fee/market metadata 或预注册成本情景。

未选择前协议不得从 `DRAFT_NOT_EXECUTABLE` 升级，不得运行经济回放。任何未来正式
Risk/Decision 修改都需要独立长期治理决策。

## Next Action

- 等待用户选择上述少量互斥 package；随后在独立 pre-outcome commit 中填入选择、数据与
  成本来源，计算并记录 protocol hash，再申请是否执行独立验证。
- #110 保持 OPEN，不自动合并；不得用其已暴露结果选择本草案的 signal/stop/exit/gate。
- US production acceptance 仍按既有自然 schedule 边界独立进行，不与本研究绑定。

## Constraints

- 不改 Wave/Swing/Fibonacci 核心实现，不访问 Final OOS，不读取真实持仓。
- 不把 H1 后 running high 标成 confirmed Swing；不在看到收益后逐笔选择 stop、target 或 exit。
- Target-before-RR；不得用 T2/T3 绕过 T1，不得为过 2R 延伸 T1 或缩小 stop。
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
