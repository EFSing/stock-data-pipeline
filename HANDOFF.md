# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

分别交付 US exact-T QFQ / Candidate 数据质量及调度修复、CN/US 可执行机会稀缺联合只读归因。生产修复与策略研究分支独立。

总体策略不是单一 Platform Breakout；唯一正式事实源为 `docs/TRADING_SYSTEM_SPEC.md`。主线是 Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。第一版四类 Setup 为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`；`SETUP_03` 只是其中一个子策略。

## Current State

- main 已含 PR #100；PR #82（Actions Node 24）与 #96（Dashboard card）保持独立、开放、未合并。
- US 9/23 日报 BABA/RKLB QFQ T-1、Candidate seed 1023 但仅 1 可用；US writer latest 4 只均待复核且正式 QFQ 0 更新。CN 9/23 日报 516 只 DATA_OK，Asia writer 正式 QFQ 3/3。
- US 修复 PR #101 请求 Stage A 70 个 completed sessions，保留 60-bar 和 exact-T 门槛；增加 stale/partial batch 有界重试、极低覆盖告警、IWB share-class 代码标准化。定时 Cloud workflow 在形成诊断 HTML/JSON/通知后对 `PARTIAL_DATA_QUALITY` 返回非零。US writer / Cloud 日报调度分别改为北京时间 08:30 / 09:00。归因和不确定性见 `docs/US_DATA_QUALITY_2026-09-23.md`。
- CN 与 US 都存在可执行机会稀缺，US 数据质量修复不等于策略有效性恢复。CN 近期两日正式方案和 `ENTRY_ALLOWED` 均为零；冻结 Development 中 CN 376 次首次确认/0 准入，US 623/8，US exact T+1 机械执行 4 次。已关闭 confirmed→wait-for-retest 研究；更早入场 Development 研究已完成但无生产授权。

## Completed

- 已核对 main、HEAD、open PR、近期 CN/US runs、Yahoo 日期边界与现有研究协议。
- US 修复针对性测试与 exact-head CI 已通过；CN 描述性审计已提交独立 PR #102。
- 未访问 Final OOS、真实持仓、生产 Sheet 写入、Paper 或 broker。

## Blocker / Decision

- US 修复仍需合并后的自然 schedule 只读生产验收；当前重新可得的 Yahoo 数据不能替代当时或未来验收。
- CN PR #102 和联合诊断 PR #103 均保持开放。两套独立只读协议草案分别覆盖 prospective exact-T 事件漏斗及已冻结 Development 的 T1/Entry Zone/执行止损几何；新的独立样本、较早入场验证和执行成本研究仍须用户后续批准。不得重启已关闭的回踩研究。

## Next Action

保持 PR #101/#102/#103 独立且未合并。合并前核验各自 exact-head CI；#101 合并后下一次自然 US/CN schedule 只读验收 latest 4/4 与正式 QFQ BABA/RKLB 2/2、Candidate Stage A/B、日报完整性及 HTML/JSON/email 一致性。无需等待未来定时任务才交付。

## Constraints

- 不改 Wave、Setup、Entry、Target、Risk、5%、2R、T→T+1，不用 Tencent/Sina 快照替代正式 QFQ。
- Candidate-only 保持 `READ_ONLY_DISCOVERY`，不能自动晋级；数据不到 exact-T 必须 fail closed。
- `REAL_HOLDINGS_SHADOW` 为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`。

## Known Pitfalls

- Yahoo Chart 是 yfinance 内部 fallback，不是独立正式 QFQ 来源；原 US 运行未保存 raw payload，不能完全区分接口发布延迟与瞬时解析/请求故障。
- 单个正式池结果成功不能证明 Candidate 市场扫描完整；Green Actions 也不能再代表 `PARTIAL_DATA_QUALITY` 分析完整。

`HANDOFF_CURRENT_AND_CONSISTENT`
