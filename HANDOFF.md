# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

完成 PR #104 / #105 的合并与治理收尾；已按预注册协议执行一次独立于冻结 Development 样本的 CN/US 较早入场第一阶段验证（PR #107，保持 OPEN），等待用户决定是否授权第二阶段。US 修复仍在下一次自然 schedule 的生产验收边界内。

总体策略不是单一 Platform Breakout；唯一正式事实源为 `docs/TRADING_SYSTEM_SPEC.md`。主线是 Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。第一版四类 Setup 为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`；`SETUP_03` 只是其中一个子策略。

## Current State

- main 已依次包含 squash merged PR #101（US 修复）、#102（CN 描述审计）、#103（CN/US 联合审计与协议草案）、#104（前瞻 exact-T 紧凑事件记录）、#105（冻结 Development T1/Entry Zone/执行止损几何归因）。PR #82（Actions Node 24）与 #96（Dashboard card）仍独立开放，未混入或合并。
- US 9/23 日报 BABA/RKLB QFQ T-1、Candidate seed 1023 但仅 1 可用；US writer latest 4 只均待复核且正式 QFQ 0 更新。CN 9/23 日报 516 只 DATA_OK，Asia writer 正式 QFQ 3/3。
- US 修复已在 main：Stage A 请求 70 个 completed sessions，保留 60-bar 和 exact-T 门槛；增加 stale/partial batch 有界重试、极低覆盖告警、IWB share-class 代码标准化。定时 Cloud workflow 在形成诊断 HTML/JSON/通知后对 `PARTIAL_DATA_QUALITY` 返回非零。US writer / Cloud 日报调度分别为北京时间 08:30 / 09:00。归因和不确定性见 `docs/US_DATA_QUALITY_2026-09-23.md`。
- CN 与 US 都存在可执行机会稀缺，US 数据质量修复不等于策略有效性恢复。CN 近期两日正式方案和 `ENTRY_ALLOWED` 均为零；冻结 Development 中 CN 376 次首次确认/0 准入，US 623/8，US exact T+1 机械执行 4 次。已关闭 confirmed→wait-for-retest 研究；更早入场 Development 研究已完成但无生产授权。
- PR #107（`SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1`，research-only）保持 OPEN：预注册的唯一实验组是既有正式 SETUP_01 ARMED 里程碑（`SETUP01_RECOVERY_RATIO=0.5`）作为入场触发，对照组为首次 `close > H1` CONFIRMED 入场；样本为已冻结 clean-holdout roster（20 CN + 20 US，2017-01-01..2026-08-26），与 Development 40 只及 A1 formal 120 symbol-level 交集为空。共同分母 2,291 个 Wave2 anchor contexts；CN/US paired median headroom 改善 +0.275R / +0.238R，结构失效率 20.4% / 23.4%、确认率 33.2% / 33.5%，均在预注册界内 → `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`。该结论只支持申请第二阶段执行成本／净收益验证，不含成本、净收益、胜率、期望或仓位，不构成生产授权。

## Completed

- 已按真实 main、各 PR 最终 HEAD/diff、exact-head CI 与 mergeability 依次 squash merge #101/#102/#103，本次再依次 squash merge #104（merge commit `bfe5960`）与 #105（merge commit `32cbe48`）；每次合并后核对新的 main、merge commit、main CI 与剩余 PR 状态，#82/#96 未受影响。
- 原始 Actions 聚合日志及其未知边界已记录于独立审计；正式池／动态候选事件级机会率没有从聚合数推造。
- 已先提交不可变预注册协议，再完成独立样本 payload 冻结与第一阶段验证；确定性重复运行得到 byte-identical JSON，`python -m unittest discover -s tests` 844 项通过（exact-head CI 为准）。
- 未访问 Final OOS、真实持仓、生产 Sheet 写入、Paper 或 broker；未做执行成本、净收益、胜率或仓位研究。

## Blocker / Decision

- 需要用户决定：是否授权第二阶段执行成本／净收益验证（PR #107 的结论仅支持“申请”）。在此之前不得把早入场用于生产，也不得改动 Wave、Setup、Entry、Target、Stop、5%、2R、T→T+1。
- `PRODUCTION_ACCEPTANCE_PENDING`：US 修复仍需下一次自然 schedule 只读验收；代码测试与 main CI 不能替代此项。
- 不得重启已关闭的 post-confirmation retest 研究；不得在本独立样本或已暴露 Development 样本上重新搜索 milestone、组合新过滤器、延长窗口或按结果重设阈值。

## Next Action

- 保持 PR #107 OPEN，等待用户对第二阶段与生产边界的决定；不合并、不追加参数搜索、不替换样本。
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

`HANDOFF_CURRENT_AND_CONSISTENT`
