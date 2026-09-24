# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

分别交付 2026-09-23 US exact-T QFQ / Candidate 数据质量修复与 CN 可执行机会稀缺的只读审计。生产修复与策略研究分支独立。

总体策略不是单一 Platform Breakout；唯一正式事实源为 `docs/TRADING_SYSTEM_SPEC.md`。主线是 Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。第一版四类 Setup 为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`；`SETUP_03` 只是其中一个子策略。

## Current State

- main 已含 PR #100；PR #82（Actions Node 24）与 #96（Dashboard card）保持独立、开放、未合并。
- US 9/23 日报 BABA/RKLB QFQ T-1、Candidate seed 1023 但仅 1 可用；US writer latest 4 只均待复核且正式 QFQ 0 更新。CN 9/23 日报 516 只 DATA_OK，Asia writer 正式 QFQ 3/3。
- US 修复 PR #101 请求 Stage A 70 个 completed sessions，保留 60-bar 和 exact-T 门槛；增加 stale/partial batch 有界重试、极低覆盖告警、IWB share-class 代码标准化。定时 Cloud workflow 在形成诊断 HTML/JSON/通知后对 `PARTIAL_DATA_QUALITY` 返回非零。归因和不确定性见 `docs/US_DATA_QUALITY_2026-09-23.md`。
- CN 近期两日正式方案和 `ENTRY_ALLOWED` 均为零。已关闭 confirmed→wait-for-retest 研究；更早入场 Development 研究已完成但无生产授权。

## Completed

- 已核对 main、HEAD、open PR、近期 CN/US runs、Yahoo 日期边界与现有研究协议。
- US 修复针对性测试与 exact-head CI 已通过；CN 描述性审计已提交独立 PR #102。
- 未访问 Final OOS、真实持仓、生产 Sheet 写入、Paper 或 broker。

## Blocker / Decision

- US 修复仍需合并后的自然 schedule 只读生产验收；当前重新可得的 Yahoo 数据不能替代当时或未来验收。
- CN PR #102 已完成描述性审计，下一步新研究处于 `READY_FOR_DECISION`：须选择假设、冻结协议及允许的数据边界。不得重启已关闭的回踩研究。

## Next Action

保持 US PR #101 与 CN PR #102 独立且未合并。用户决定 CN 后续研究方向；US 修复合并后的自然 US/CN schedule 只读核对 exact-T、writer、Candidate Stage A/B、HTML/JSON/email 一致性。

## Constraints

- 不改 Wave、Setup、Entry、Target、Risk、5%、2R、T→T+1，不用 Tencent/Sina 快照替代正式 QFQ。
- Candidate-only 保持 `READ_ONLY_DISCOVERY`，不能自动晋级；数据不到 exact-T 必须 fail closed。
- `REAL_HOLDINGS_SHADOW` 为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`。

## Known Pitfalls

- Yahoo Chart 是 yfinance 内部 fallback，不是独立正式 QFQ 来源；原 US 运行未保存 raw payload，不能完全区分接口发布延迟与瞬时解析/请求故障。
- 单个正式池结果成功不能证明 Candidate 市场扫描完整；Green Actions 也不能再代表 `PARTIAL_DATA_QUALITY` 分析完整。

`HANDOFF_CURRENT_AND_CONSISTENT`
