# HANDOFF — 当前开发现场

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

并行但独立交付：修复 2026-09-23 US exact-T QFQ / Candidate 覆盖故障；只读审计 CN 可执行机会稀缺。生产修复与策略研究不得混合，也不改变正式交易规则。

## Current State

- main 已含 PR #100；PR #82（Actions Node 24）和 #96（Dashboard card）保持独立、开放、未合并。
- US 9/23 自然日报返回 BABA/RKLB QFQ T-1、Candidate seed 1023 但仅 1 可用；US writer latest 4 只均待复核且正式 QFQ 0 更新。CN 9/23 日报 516 只 DATA_OK，Asia writer 正式 QFQ 3/3。
- US 修复分支请求 Stage A 70 个 completed sessions、保留 60-bar 和 exact-T 门槛，加入 stale/partial batch 有界重试、极低覆盖告警、IWB share-class 代码标准化。定时 Cloud workflow 在形成诊断 HTML/JSON/通知后，对 PARTIAL_DATA_QUALITY 返回非零。详细归因与未证实部分见 `docs/US_DATA_QUALITY_2026-09-23.md`。
- CN 研究仅限近期真实日报及已批准 Development 材料。历史 confirmed→wait-for-retest 研究已经关闭；更早入场 Development 研究已注册并完成，尚无正式验证或生产授权。近期两日正式方案为零，不能将 WATCH/ARMED 当作可执行信号。

## Blocker / Decision

- US 新修复尚需 PR exact-head CI 与后续自然 schedule 只读生产验收；不得手动生产写入或以当前重新可得的 Yahoo 数据冒充当时验收。
- CN 描述性审计可独立完成；任何新策略假设、冻结协议、额外数据或生产规则变更须先形成具体可比较的 `READY_FOR_DECISION` 事项。不重启已关闭的回踩研究。

## Next Action

完成 US 修复 PR 测试和 CI，保持未合并；完成独立 CN 研究交付并给出定量漏斗、first-fail 与重叠、现有研究结论和明确的用户决策点。后续自然 US/CN schedule 只读核对 exact-T、正式 writer、Stage A/B、HTML/JSON/email 一致性。

## Constraints

- `docs/TRADING_SYSTEM_SPEC.md` 是总体策略唯一正式事实源；不改 Wave、Setup、Entry、Target、Risk、5%、2R、T→T+1。
- 不访问 Final OOS、真实持仓，不运行 Paper 或真实交易，不写生产 Sheets/策略状态，不用 Tencent/Sina 快照代替正式 QFQ。
- Candidate-only 仍是 `READ_ONLY_DISCOVERY`，不能自动晋级；exact-T 不满足必须 fail closed。
- `REAL_HOLDINGS_SHADOW` 为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`。

`HANDOFF_CURRENT_AND_CONSISTENT`
