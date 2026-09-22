# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI、mergeability 的实时事实源；不依赖聊天或旧的本地 remote-tracking 状态。

## Current Task

`DAILY_CANDIDATE_QFQ_REPORT_REPAIR_V2`：处理 2026-09-21 CN/US 日报、候选覆盖、完整
HTML 展示与行情更新故障，保持 exact-T、正式收盘、来源 provenance、因果边界和全部
交易系统语义不变。PR #100 已完成 squash merge，本次合并收尾已完成；当前现场仅保留
合并后的自然 CN/US schedule 只读生产验收，不启动新的开发 Phase。

总体策略不是单一 Platform Breakout，唯一正式主线为 `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。第一版四类 Setup 为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`；`SETUP_03` 只是四类 Setup 之一的子策略。

## Current State

- `main` 已包含 PR #100 的 QFQ/Candidate→Daily/日报诊断修复；PR #96（Cloud dashboard card）与 PR #82（Actions Node 24）保持独立，不混入、不 rebase、不合并。
- 正式推送时间保持不变：Asia `30 9 UTC`（CN/HK/JP），US `30 22 UTC`（US/SE）；latest 成功后才运行正式 CN/US exact-T QFQ companion，`full` 仍只允许手动触发。
- 2026-09-21 只读生产证据显示：CN 日报本身成功、仅 3 个正式池标的 DATA_OK 且无交易信号；旧日报 JSON/日志没有输出 Candidate Seed/Stage A/Stage B 数量，不能据此证明 Candidate=0 是正常筛选结果。CN writer 的 latest 成功，但 QFQ 最终 worksheet 元数据读取遇到 Sheets 429。US 日报的 BABA/RKLB yfinance/Yahoo Chart QFQ 尾部只到 9/18，exact-T=9/21 因此 fail closed；US writer 的 latest 为待复核，正式 QFQ 被正确阻断。CN/US 日报与相应 writer 在相近时间运行，增加了 Sheets 读取竞争。
- 本任务代码修复：Stage A 空或无可用历史批次做一次有界重试，仍无可用行时 fail closed 并区分 `DISCOVERY_FAILED` 与真实 `NO_CANDIDATES`；Stage B、Cloud exact-T 与正式 QFQ writer 对 yfinance/Yahoo Chart stale 尾部至少保留一次有限重试，仍绝不返回 T-1。SheetsClient 在单次运行内复用 worksheet/records，并对读取型 429 做有限退避，不重试写入；Dashboard/email 共用诊断投影，展示 CN/US 候选漏斗、正式池/动态候选/实际分析数量、过滤原因和逐标的异常原因。
- HTML 日报默认展示当前 payload 中全部实际分析结果，包含动态候选、WATCH、NO_TRADE、FAILED/DATA_BLOCKED；静态 HTML 无 JavaScript 也可阅读逐标的摘要与详情，邮件继续重点摘要但报告真实覆盖数量和候选异常。
- 未改变 Wave、Setup、Entry、Risk、Target、Exit、5%、2R、T→T+1、Candidate 晋级、Paper、broker 或状态写入语义。

## Completed

- 已读取并核对 `AGENTS.md`、`docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`、相关 provider / Sheets / QFQ / Candidate / 日报代码与测试。
- 已确认 Yahoo Chart 是 yfinance QFQ 的内部 keyless fallback；故障不是用 T-1 替代 T，而是 fallback 返回了非空但落后的尾部，旧逻辑在 stale 检查处提前结束了重试。
- 已确认 QFQ writer 先读取历史快照、所有目标 provider 成功后才替换目标身份；非目标历史继续保留，失败时不写入。
- 已完成候选运行时、日报 Dashboard/email、Cloud 状态与 Sheets client 的针对性回归（175 passed）；全量 `python -m unittest discover -s tests -v` 为 815 passed、3 skipped，变更文件 `py_compile` 与 `git diff --check` 通过。PR #100 已 squash merge，合并前 exact-head CI（CI Test Gate、Daily Decision Chain、Paper trade lifecycle、Portfolio Risk generic operational shadow）4/4 成功。

## Production Acceptance

- 代码测试通过不等于真实生产验收。当前未访问或写入真实 Google Sheet，未做历史补抓、生产状态写入、Paper、真实 holdings、真实交易或 Final OOS。
- 尚未证明修复后的真实 US QFQ 已到 exact T、CN writer 已绕过 429 并完成正式 QFQ，亦未证明 CN/US 候选 Seed→Stage A→Stage B→Daily→HTML 的动态覆盖在下一次 schedule 稳定完成。需在合并后的自然 schedule 运行后只读核验 latest、正式收盘、验证状态、QFQ 尾日、候选漏斗、完整 HTML、日报状态和通知。
- 下一次自然 schedule 后必须分别核对 CN/US：Candidate Seed → Stage A → Stage B → Daily Decision 的实际数量、状态、过滤原因及标的身份；CN Sheets 429、正式 QFQ 更新，以及 US BABA/RKLB exact-T QFQ。
- 必须逐市场核对 HTML 实际完成分析数量与 JSON 一致，正式池和动态候选结果完整展示（包括无交易信号的股票），并核对邮件覆盖数量、数据异常、候选诊断与 HTML 一致。
- 必须区分真实无候选、候选链路失败、数据阻断和正常无交易信号；少数正式池股票分析成功不能视为全市场扫描成功。
- Cloud Daily Report 仍是独立 read-only 内存路径，不读取或回写旧 `最新行情` / `历史行情_前复权`；不得把 Cloud 成功当作 Sheet writer 恢复验收。

## Blocker

当前唯一未完成节点为 `PRODUCTION_ACCEPTANCE_PENDING`：等待合并后的自然 schedule 做只读 Sheet/QFQ/候选覆盖/日报与并发验收；本任务无实现或安全 blocker，不手动触发生产写入、不补抓历史、不运行 Paper 或真实交易。

## Next Action

下一次启动 Codex 时，在自然 schedule 已完成且已知各市场 exact T 后，分别以只读默认运行：
`python scripts/run_production_daily_decision.py --run --market CN --date <CN_EXACT_T>`
和 `python scripts/run_production_daily_decision.py --run --market US --date <US_EXACT_T>`；同时只读核对 Sheet latest/QFQ、Candidate 漏斗、HTML/JSON/email 覆盖与通知一致性。继续保持 `PRODUCTION_ACCEPTANCE_PENDING`，不得加 `--write-state` 或 `--paper-track`。

## Constraints

- 总体主线唯一事实源为 `docs/TRADING_SYSTEM_SPEC.md`：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- 禁止 look-ahead、未来 Swing/ZigZag、T-1 冒充 T、伪造目标价或机会；Candidate 只作筛选/分析输入，不自动晋级、写策略池或生成买入信号。
- latest / QFQ 必须 exact completed session、正式收盘和正确 provenance；缺失或 stale 必须 DATA_* fail closed。
- 不改生产推送时间；不读取真实 holdings；不运行真实交易、Paper、broker、Final OOS 或历史补抓；凭证只来自既定环境变量/Secrets。
- `REAL_HOLDINGS_SHADOW` 固定为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 `NOT_RUN_USER_PRIVACY`，不是本任务 blocker。

## Known Pitfalls

- US QFQ 的 Yahoo Chart 是 yfinance provider 内部 fallback，不是独立正式 QFQ source；只有 exact-T 完成后才可返回。
- Sheets 读取可有限重试 429，写入不做自动重试；历史替换必须保留非目标身份，且 provider 全部成功后才允许写。
- 日报首页和邮件应使用同一诊断事实；异常时列出标的和原因，正常无信号时列出真实 coverage/filter 统计，不把候选链路缺失或未报告误写成没有机会。
- Candidate 全链路保持 CN/US 独立；动态候选只拥有 `READ_ONLY_DISCOVERY`，不得晋级正式策略池或触发状态写入。HTML 完整结果必须以实际 `reports[].报告.results` 为准，不能以重点筛选数量代替分析覆盖。

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`
