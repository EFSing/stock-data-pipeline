# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`CN_US_CANDIDATE_SOURCE_SESSION_DATE`：PR #128 已 squash merge。根据用户确认的
“10 月 1 日非交易日返回 9 月 30 日成分数据”，已修正 CN data-ready timestamp 与真实
session date 的区分，并接入 US IWB 指定日期历史持仓。修改在独立分支
`codex/fix-candidate-session-date` / draft PR #129，尚未进入 main。
2026-09-30 CN 只读回补已恢复 Candidate 并生成完整 JSON/HTML，但发现独立的 Fibonacci
核心评估 blocker，完整策略链验收未通过。当前为 `READY_FOR_DECISION`；不改策略逻辑，
不启动新开发 Phase。动态 branch/PR/CI 状态以 GitHub 实时查询为准。

## Current State / Completed

- CN 生产价格/历史仍为 `HITHINK_FINANCIAL_API`，US 为 `YAHOO_CHART`；CN Candidate
  仍为官方 `000300.SH` ∪ `000905.SH`，US 为 iShares IWB Russell 1000 holdings。
- membership snapshot 与每条 seed metadata 都必须有日期且 `snapshot_date <= report_as_of_date`；
  US adapter 接收实际 report date，不再丢弃 as-of。runtime 在任何 Candidate price fetch 前
  验证 envelope 与逐行日期；selector 也拒绝未来 metadata。
- HITHINK REST 文档、CLI schema 与实测未发现指定日期的历史成分股能力，额外 `date`
  参数不改变返回清单。其 `timestamp` 是 data-ready time，不是成分生效日：保留原值，
  非交易日用既有 XSHG exact calendar 归属前一真实 session；交易日仍用当天日期，不为
  更早报告回退。10 月 1–2 日响应可用于 9 月 30 日，不可用于 9 月 29 日；10 月 8 日
  交易日响应也不可用于 9 月 30 日。这不是新增历史端点或 approximation 模式。
- US 指定 report date 时使用 iShares 官方同一 IWB 的历史下载端点，传 `asOfDate=YYYYMMDD`，
  日期取响应 `Fund Holdings as of`，不取请求参数；实测 9 月 30 日和 8 月 31 日返回各自
  dated snapshot。URL/date-query provenance 保留，未来或未知日期继续 fail closed。
- production Candidate 无本地/persistent snapshot cache；当前流程每次加载都验证原始日期，
  注入的/cache-backed seed loader 同样过 runtime 日期门。provider/CDN 返回较旧但合法日期时
  保留其 source-as-of，不根据目标报告日期重标。legacy BaoStock 历史指数查询仍传 report date，另核对
  返回的 index/industry metadata 日期；不接回 production。
- `512400.SH` 的默认 2000 日 QFQ 请求超过 fund endpoint 的五自然年单次窗口；现在按该限制
  分段、连续请求整个原区间，保留同一 vendor 与既有 forward-adjusted provenance。
- CN/US manual 与 scheduled 日报默认使用相同 operational exit：已完成 partial report 为
  exit 0，数据质量仍 PARTIAL；只在显式 `require_complete=true` 时 strict audit exit 2。
  provider-wide failure、session/core/artifact failure 的 non-zero 语义不变。
- PR #128 的完成状态保留；当前源日期修复为独立 PR #129，不自动合并。自然日报验收与
  本次 historical diagnostic backfill 分开，不把回补当 prospective/D1 evidence。

## Validation

- 完整 `python -m unittest discover -s tests -v`：965 tests，963 passed、2 skipped；
  `py_compile`、`git diff --check`、PR code CI、Daily Chain / Portfolio Risk shadow 已通过。
- Live adapter：CN 800 seeds，US 1023 seeds，source-as-of 均为 2026-09-30；holiday、交易日
  不回退、更早报告拒绝、原始 timestamp 与 IWB response-date 保护均有回归覆盖。
- CN 用户授权的真实只读回补：800 seed → 781 data-qualified → 720 included → 687 deep-ready；
  687 条 DATA_OK 中 686 正常策略评估，1 条 `UPSTREAM_EVALUATION_FAILED`；另 32 条 Candidate
  DATA_UNAVAILABLE 与 3 条正式输入 DATA_BAD 保留，不降低 gate。新 CONFIRMED=5，
  individual ENTRY_ALLOWED=0。JSON/HTML 完整，但核心异常使 workflow / RUN_STATUS=FAILED，
  DATA_STATUS=PARTIAL、CANDIDATE_STATUS=PARTIAL；不能宣称完整策略链通过。
- 临时 Actions harness 仅修改日报 workflow，不进入 PR；使用 `--no-notify`，不注入通知/VPS
  marker 凭证，未调用或修改 notification marker，未发送通知、未写 Sheet/state/Paper/D1。
  回补是 diagnostic，不是 natural production / prospective evidence；D1 activation、durable
  storage、collector 与 reconciliation 保持独立。

## Blocker / Remaining Risks

Candidate 日期与 US 历史取数修复已完成，但真实回补发现核心 blocker：`601818.SH` 的
Fibonacci 输入 `swing_high == swing_low == 2.5168255086545406`，触发“摆幅必须为正”并使
整次运行 FAILED。该错误不是 Candidate as-of 拒绝，也不是 partial 分类误报；按用户
“不修改策略逻辑”的约束，本次未改 Wave/Fibonacci。需用户决定是否授权独立排查修复。
CN 仍无任意历史 session 的成分股查询；非交易日归属不把 current-only 变成历史数据库。

另发现独立的既有 formal reader 接入问题：`trading/production_prerequisites.py` 仍要求
`校验状态=已验证`，本次回补 3 条正式输入仍 DATA_BAD。此问题不由 Candidate as-of 修复引入，本 PR 不
改该 data gate；生产观察期间仅记录影响，不主动修复，不将数据阻断写成无信号。

## Next Action

审阅 draft PR #129 的 Candidate 修复与回补产物；用户决定是否授权独立修复上述 Fibonacci
核心异常。当前停止扩大实现范围，不擅自忽略异常、降低数据门或放宽 as-of，不自动合并。
main 自然生产观察、D1 natural evidence 验收、helper deployment identity hardening 和
#110/#82/#96 保持各自独立。

## Constraints / Pitfalls

- 总体主线与四类 Setup 身份以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一事实源。
  主线为 Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup →
  Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- `SETUP_01` = Wave 2 → Wave 3，`SETUP_02` = Wave 3 Continuation，
  `SETUP_03` = Platform Breakout，`SETUP_04` = Extreme Fear Reversal；SETUP_03 只是
  四类 Setup 之一的子策略，Wave Scenario Engine、SETUP_01/02 的总体核心路线不变。
- Wave/Swing/Fibonacci/Setup/Decision/Risk/Target/Stop/5%/2R/T→T+1 不变；无 OOS 或参数研究。
- Candidate-only 仍 `READ_ONLY_DISCOVERY`，不 promotion、不 state/pending/Portfolio allocation。
- Candidate unavailable 与 formal data status 分离，不渲染为 `NO_SIGNAL`；无法形成 universe
  snapshot 时 D1 V2 仍不得 formal commit。
- CN/US 独立；Yahoo Chart 仅供 US 价格，不用 Yahoo 最新成分股替代 IWB membership。
- 除用户明确授权的只读生产日报输入外，不额外读取真实 holdings；不写 Sheet/state/Paper，
  不运行 broker，不改 D1 activation/window。本次回补不发送通知、不修改 production marker。
- CN/US D1 V2 activation 已完成；本任务没有读取/修改正式 D1 evidence，不从旧交接的
  formal count 推断实时 evidence 状态。

`HANDOFF_CURRENT_AND_CONSISTENT`
