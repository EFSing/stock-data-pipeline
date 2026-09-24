# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

已按用户授权完成 SETUP_01 较早入场第二阶段（受约束 `PKG_B_ATR_EXECUTION_STOP`）的冻结协议与只读经济验证：结论 `INSUFFICIENT_EVIDENCE`，实验组净 R 在 CN/US 均为负，现行 incumbent 因成交过少不可评估。第二阶段 PR 保持 OPEN，不自动合并；当前等待用户决定是否以及如何进行下一轮独立执行验证。US 修复仍在下一次自然 schedule 的生产验收边界内。

总体策略不是单一 Platform Breakout；唯一正式事实源为 `docs/TRADING_SYSTEM_SPEC.md`。主线是 Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。第一版四类 Setup 为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`；`SETUP_03` 只是其中一个子策略。

## Current State

- main 已依次包含 squash merged PR #101（US 修复）、#102（CN 描述审计）、#103（CN/US 联合审计与协议草案）、#104（前瞻 exact-T 紧凑事件记录）、#105（冻结 Development T1/Entry Zone/执行止损几何归因）、#107（较早入场独立样本第一阶段 research）与 #108（PR 104/105 收尾与第一阶段记录）。PR #82（Actions Node 24）与 #96（Dashboard card）仍独立开放，未混入或合并。
- US 9/23 日报 BABA/RKLB QFQ T-1、Candidate seed 1023 但仅 1 可用；US writer latest 4 只均待复核且正式 QFQ 0 更新。CN 9/23 日报 516 只 DATA_OK，Asia writer 正式 QFQ 3/3。
- US 修复已在 main：Stage A 请求 70 个 completed sessions，保留 60-bar 和 exact-T 门槛；增加 stale/partial batch 有界重试、极低覆盖告警、IWB share-class 代码标准化。定时 Cloud workflow 在形成诊断 HTML/JSON/通知后对 `PARTIAL_DATA_QUALITY` 返回非零。US writer / Cloud 日报调度分别为北京时间 08:30 / 09:00。归因和不确定性见 `docs/US_DATA_QUALITY_2026-09-23.md`。
- CN 与 US 都存在可执行机会稀缺，US 数据质量修复不等于策略有效性恢复。CN 近期两日正式方案和 `ENTRY_ALLOWED` 均为零；冻结 Development 中 CN 376 次首次确认/0 准入，US 623/8，US exact T+1 机械执行 4 次。已关闭 confirmed→wait-for-retest 研究；更早入场 Development 研究已完成但无生产授权。
- PR #107（`SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1`，research-only）已独立 squash merge 进入 main，随后 main CI `test` 通过：预注册的唯一实验组是既有正式 SETUP_01 ARMED 里程碑（`SETUP01_RECOVERY_RATIO=0.5`）作为入场触发，对照组为首次 `close > H1` CONFIRMED 入场；样本为已冻结 clean-holdout roster（20 CN + 20 US，2017-01-01..2026-08-26）。共同分母 2,291 个 Wave2 anchor contexts；CN/US paired median headroom 改善 +0.275R / +0.238R，结构失效率 20.4% / 23.4%、确认率 33.2% / 33.5% → `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`。
- PR #109（第二阶段执行可行性决策节点 `SETUP01_EARLY_ENTRY_SECOND_STAGE_DECISION_V1`）已独立 squash merge 进入 main，main CI `test` 通过；其原始决策记录（三个互斥 package、A/B/C 定义与几何暴露事实）保持不可改写。
- 第二阶段经济验证（`SETUP01_EARLY_ENTRY_STAGE2_ECONOMIC_VALIDATION_V1`，research-only，独立 PR 保持 OPEN）已按用户选择执行受约束 `PKG_B_ATR_EXECUTION_STOP`：协议先于任何经济结果提交（`sha256:19a5fe3f…`），同一冻结样本、同一 2,291 cohort。结果 `INSUFFICIENT_EVIDENCE`：实验组 C 实现净 R 均值 CN −0.231 / US −0.115（绝对为负，基准 10bp；压力 25bp 下 −0.216 pooled），对照 B（同确认时点、无准入门槛）−0.525，C−B pooled +0.356（符号聚类 bootstrap 95% [0.299, 0.416]）；完整现行 Decision A 在 790 次首次确认中仅成交 3 次（低于预注册 per-market floor），C−A 不可评估（原始点估计 −0.295）。删失不对称：C 96% 实现，B 仅 82%，期末估值敏感性会把 C−B 排序反转，因此经济结论对删失不稳健。

## Completed

- 已按真实 main、各 PR 最终 HEAD/diff、exact-head CI 与 mergeability 依次 squash merge #101/#102/#103，本次再依次 squash merge #104（merge commit `bfe5960`）与 #105（merge commit `32cbe48`）；每次合并后核对新的 main、merge commit、main CI 与剩余 PR 状态，#82/#96 未受影响。
- 原始 Actions 聚合日志及其未知边界已记录于独立审计；正式池／动态候选事件级机会率没有从聚合数推造。
- 已先提交不可变预注册协议，再完成独立样本 payload 冻结与第一阶段验证；确定性重复运行得到 byte-identical JSON，`python -m unittest discover -s tests` 844 项通过（exact-head CI 为准）。
- 已审计 PR #107：改动仅落在 `research/` 与 `tests/`，协议先于样本信号提交，exact-head CI 全绿且 mergeable clean；本地用同一冻结 payload（`sha256:8caf05e2…`）重跑第一阶段得到 byte-identical JSON/Markdown（协议与 manifest 哈希一致）后才独立 squash merge，随后核对 main CI。
- 第二阶段决策节点证据：A/B/C 准入 984 / 986 / 0（986 个可执行信号）；C 的 0 准入中 831 个先被 5% 目标上行门槛阻断；每笔 1R 距离中位数 A 5.7% / B 7.1%（占 entry），0.5% 风险下名义金额中位数 A 8.8% / B 7.0%（占 allocation_budget）；93.2% 的早入场 OPEN 低于确认价 H1（现行 Entry Zone 会判 `SKIP_GAP_BELOW_CONFIRMATION`）。
- 未访问 Final OOS、真实持仓、生产 Sheet 写入、Paper 或 broker；未做执行成本、净收益、胜率或仓位研究。
- 本地工作树当前检出第二阶段研究分支（已提交并推送，无未提交改动）；`main` 未被直接修改，第一阶段与第二阶段都通过独立 PR 进入或等待合并。
- 第二阶段执行事实：`python -m unittest discover -s tests` 890 项通过；生成器重复运行 byte-identical；协议哈希在 artifact 中固定校验（协议变化即 fail closed）；CN 涨跌停仅 1 次入场触限标记、3 次退出触限标记，3 个 CN 信号因入场日 volume≤0（停牌口径）跳过；组合回撤标记 `NOT_ESTIMABLE`，未拼造净值曲线。

## Blocker / Decision

- `READY_FOR_DECISION`：需要用户决定是否以及如何继续早入场研究。已注册结论为 `INSUFFICIENT_EVIDENCE`，实验组绝对净期望为负，现行 incumbent 对照因成交过少不可评估，且结论对删失不稳健 —— 按预注册规则不得改写阈值、样本、退出假设或成本情景后重跑。
- 未经用户新的明确授权，不得把早入场用于生产、Paper、Sheet、状态或 broker；不得改动 Wave、Setup、Entry、Target、Stop、5%、2R、Risk、T→T+1；不得访问 Final OOS 或真实持仓。
- `PRODUCTION_ACCEPTANCE_PENDING`：US 修复仍需下一次自然 schedule 只读验收；代码测试与 main CI 不能替代此项。
- 不得重启已关闭的 post-confirmation retest 研究；不得在本独立样本或已暴露 Development 样本上重新搜索 milestone、组合新过滤器、延长窗口或按结果重设阈值。

## Next Action

- 保持第二阶段经济验证 PR OPEN，等待用户决定是否申请下一轮独立执行验证；不合并、不追加参数搜索、不替换样本、不访问 Final OOS。
- 下一次自然 US/CN schedule 只读验收 US latest 跟踪标的 4/4 与正式 QFQ BABA/RKLB 2/2（分开计数）、Candidate Stage A/B 实际覆盖、DATA_OK/DATA_BLOCKED、日报分析完整性、JSON/HTML/email 一致性及 CN 回归；不手动触发生产写入。

## Constraints

- 不改 Wave、Setup、Entry、Target、Risk、5%、2R、T→T+1，不用 Tencent/Sina 快照替代正式 QFQ。
- Candidate-only 保持 `READ_ONLY_DISCOVERY`，不能自动晋级；数据不到 exact-T 必须 fail closed。
- `REAL_HOLDINGS_SHADOW` 为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`。

## Known Pitfalls

- Yahoo Chart 是 yfinance 内部 fallback，不是独立正式 QFQ 来源；原 US 运行未保存 raw payload，不能完全区分接口发布延迟与瞬时解析/请求故障。
- 单个正式池结果成功不能证明 Candidate 市场扫描完整；Green Actions 也不能再代表 `PARTIAL_DATA_QUALITY` 分析完整。
- 独立样本的复权价格 payload 是重新抓取并冻结的新 dataset identity：40 只中 18 只相对 2026-08-29 冻结抓取发生复权重述（session 覆盖与 bar 数完全一致）。同一 dataset identity 内部两组一致，但不得把它当作 2026-08-29 的 frozen bytes。
- 独立样本的独立性是 symbol / lifecycle 级；日历窗口与 Development 相同，因此市场 regime overlap 是已披露限制，不是被控制的因素。
- 三个 package 只能整包选择，不能按维度拼装；确认日才存在的目标集、Entry Zone 与执行止损不得回填到较早入场日。
- package C 的 0 准入是机制性结论（早入场时点 H1 必然成为最近目标候选），不是样本不足；不得据此改写 5%、2R 或目标构造。
- 第二阶段 A 臂只有 3 笔成交（US），C−A 的 bootstrap 区间不可解释；B 臂有 138 笔右删失且删失样本多为长期浮盈，期末估值敏感性会把 C−B 排序反转。任何后续研究必须先处理删失口径，不得只引用 realized-only 的 +0.356R。
- 协议内 T1 止盈退出是 research-only 假设（冻结 Position Management 视目标为诊断、从不自动卖出）；无目标退化（`NO_VALID_TARGET_AT_CONFIRMATION` 134 笔）与无目标退出的次政策结果（C −0.454）都必须在引用结论时一并说明。

`HANDOFF_CURRENT_AND_CONSISTENT`
