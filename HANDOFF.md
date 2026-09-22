# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI、mergeability 的实时事实源；不依赖聊天或旧的本地 remote-tracking 状态。

## Current Task

`DAILY_QFQ_DIAGNOSTICS_REPAIR_V1`：处理 2026-09-21 CN/US 日报与行情更新故障，保持
exact-T、正式收盘、来源 provenance、因果边界和全部交易系统语义不变。当前在独立
`codex/fix-daily-qfq-diagnostics-v1` 分支工作；PR / exact-head CI 状态以 GitHub 实时结果为准，未合并。

## Current State

- `main` 已核对为当前远端真实基线；PR #96（Cloud dashboard card）与 PR #82（Actions Node 24）保持独立，不混入、不 rebase、不合并。
- 正式推送时间保持不变：Asia `30 9 UTC`（CN/HK/JP），US `30 22 UTC`（US/SE）；latest 成功后才运行正式 CN/US exact-T QFQ companion，`full` 仍只允许手动触发。
- 2026-09-21 只读生产证据显示：CN 日报本身成功、3 个标的 DATA_OK 且无交易信号；CN writer 的 latest 成功，但 QFQ 最终 worksheet 元数据读取遇到 Sheets 429。US 日报的 BABA/RKLB yfinance/Yahoo Chart QFQ 尾部只到 9/18，exact-T=9/21 因此 fail closed；US writer 的 latest 为待复核，正式 QFQ 被正确阻断。CN/US 日报与相应 writer 在相近时间运行，增加了 Sheets 读取竞争。
- 本任务代码修复：US exact-T QFQ 对非空 stale provider tail 使用既有有限重试，仍绝不返回 T-1；SheetsClient 在单次运行内复用 worksheet，并对读取型 429 做有限退避，不重试写入；Dashboard/email 共用诊断投影，展示候选漏斗、实际分析数量、过滤原因和逐标的异常原因。
- 未改变 Wave、Setup、Entry、Risk、Target、Exit、5%、2R、T→T+1、Candidate 晋级、Paper、broker 或状态写入语义。

## Completed

- 已读取并核对 `AGENTS.md`、`docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`、相关 provider / Sheets / QFQ / Candidate / 日报代码与测试。
- 已确认 Yahoo Chart 是 yfinance QFQ 的内部 keyless fallback；故障不是用 T-1 替代 T，而是 fallback 返回了非空但落后的尾部，旧逻辑在 stale 检查处提前结束了重试。
- 已确认 QFQ writer 先读取历史快照、所有目标 provider 成功后才替换目标身份；非目标历史继续保留，失败时不写入。
- 针对性回归与完整测试已通过：`python -m unittest discover -s tests -v` 为 806 passed、3 skipped。

## Production Acceptance

- 代码测试通过不等于真实生产验收。当前未访问或写入真实 Google Sheet，未做历史补抓、生产状态写入、Paper、真实 holdings、真实交易或 Final OOS。
- 尚未证明修复后的真实 US QFQ 已到 exact T、CN writer 已绕过 429 并完成正式 QFQ，亦未证明相邻任务在下一次 schedule 的延迟/并发下可稳定完成。需在合并后的自然 schedule 运行后只读核验 latest、正式收盘、验证状态、QFQ 尾日、日报状态和通知。
- Cloud Daily Report 仍是独立 read-only 内存路径，不读取或回写旧 `最新行情` / `历史行情_前复权`；不得把 Cloud 成功当作 Sheet writer 恢复验收。

## Next Action

完成 docs 轻量检查后提交并推送独立 PR；创建 PR 后等待当前 exact-head CI 完成并处理必要的代码反馈，不自行合并。CI 通过后保持 `PRODUCTION_ACCEPTANCE_PENDING`，等待下一次正式 schedule 做只读生产核验。

## Constraints

- 总体主线唯一事实源为 `docs/TRADING_SYSTEM_SPEC.md`：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- 禁止 look-ahead、未来 Swing/ZigZag、T-1 冒充 T、伪造目标价或机会；Candidate 只作筛选/分析输入，不自动晋级、写策略池或生成买入信号。
- latest / QFQ 必须 exact completed session、正式收盘和正确 provenance；缺失或 stale 必须 DATA_* fail closed。
- 不改生产推送时间；不读取真实 holdings；不运行真实交易、Paper、broker、Final OOS 或历史补抓；凭证只来自既定环境变量/Secrets。
- `REAL_HOLDINGS_SHADOW` 固定为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`，不是本任务 blocker。

## Known Pitfalls

- US QFQ 的 Yahoo Chart 是 yfinance provider 内部 fallback，不是独立正式 QFQ source；只有 exact-T 完成后才可返回。
- Sheets 读取可有限重试 429，写入不做自动重试；历史替换必须保留非目标身份，且 provider 全部成功后才允许写。
- 日报首页和邮件应使用同一诊断事实；异常时列出标的和原因，正常无信号时列出真实 coverage/filter 统计，不把缺少候选误写成没有机会。

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`
