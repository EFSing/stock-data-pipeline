# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`CN_US_PRODUCTION_OBSERVATION`：Candidate snapshot as-of 修复完成，HITHINK provider
已恢复，CN/US workflow 公开 fixture + 真实 provider 验证完成。PR #128 已经用户授权
squash merge，代码已进入 main；正式 branch/PR/CI 状态以 GitHub 实时查询为准。
当前只观察合并后的自然日报，不开启新开发 Phase，不修改策略逻辑。

## Current State / Completed

- CN 生产价格/历史仍为 `HITHINK_FINANCIAL_API`，US 为 `YAHOO_CHART`；CN Candidate
  仍为官方 `000300.SH` ∪ `000905.SH`，US 为 iShares IWB Russell 1000 holdings。
- membership snapshot 与每条 seed metadata 都必须有日期且 `snapshot_date <= report_as_of_date`；
  US adapter 接收实际 report date，不再丢弃 as-of。runtime 在任何 Candidate price fetch 前
  验证 envelope 与逐行日期；selector 也拒绝未来 metadata。CN ISO timestamp 按上海日期解释。
- 已核对 HITHINK 官方接口：成分股只支持当前清单，没有历史日期 selector；已验证 IWB
  `latest-holdings.csv` 也是当前下载，不能用未证明有效的 `asOfDate` 参数声称历史取数。
  未来或未知日期一律 fail closed，诊断给出 snapshot/report date、来源、current-only
  限制和 `NO_ELIGIBLE_SNAPSHOT`，不将 timestamp 改为上一交易日。
- production Candidate 无本地/persistent snapshot cache；当前流程每次加载都验证原始日期，
  注入的/cache-backed seed loader 同样过 runtime 日期门。provider/CDN 返回较旧但合法日期时
  保留真实 source-as-of，不重标日期。legacy BaoStock 历史指数查询仍传 report date，另核对
  返回的 index/industry metadata 日期；不接回 production。
- `512400.SH` 的默认 2000 日 QFQ 请求超过 fund endpoint 的五自然年单次窗口；现在按该限制
  分段、连续请求整个原区间，保留同一 vendor 与既有 forward-adjusted provenance。
- CN/US manual 与 scheduled 日报默认使用相同 operational exit：已完成 partial report 为
  exit 0，数据质量仍 PARTIAL；只在显式 `require_complete=true` 时 strict audit exit 2。
  provider-wide failure、session/core/artifact failure 的 non-zero 语义不变。
- PR 审查确认修改范围符合上述修复目标，无未解决 merge conflict；CI、三个 generic
  shadow 与 CN/US 真实 provider workflow 均通过。合并后的自然日报验收仍待观察。

## Validation

- 完整 `python -m unittest discover -s tests -v`：962 tests，960 passed、2 skipped；
  `py_compile`、`git diff --check` 和 PR code CI/generic shadows 已通过。
- 真实 Actions 使用修复 code commit 派生的临时验证分支，保留两个日报 workflow 身份，
  运行实际 provider / Candidate runtime / report runner；仅将账户配置换为公开合成 fixture。
  未注入 Google/真实 holdings/VPS credentials，未发送通知、未写 Sheet/state/Paper/D1。
  该临时验证 harness 不进入 PR。
- CN：HS300/CSI500 均返回 `2026-10-01` 快照，对 `2026-09-30` 正确拒绝；正式数据输入
  继续获取，报告 `COMPLETED/PARTIAL/UNAVAILABLE`，默认 exit 0、strict exit 2。
  公开 ETF `512400.SH` 长窗口请求成功，返回 119 bars，尾日 `2026-09-30`，无 1003。
- US：IWB 返回 `2026-09-29` / 1023 equity seeds，可用于 `2026-09-30`，对 `2026-09-28`
  明确拒绝。真实 Candidate/Strategy 分析与 JSON/HTML 完成，公开无效标的/单个 provider
  symbol failure 保持局部 partial，默认 exit 0、strict exit 2。
- 本次是公开 provider operational 验证，不代表真实 holdings shadow 或自然 D1 evidence
  验收。D1 activation、durable storage、natural collector、reconciliation 保持独立。

## Blocker / Remaining Risks

无本修复的实现 blocker。current-only provider 无合法较早快照时 Candidate 仍 unavailable，
这是要求的未来数据保护；恢复历史日 discovery 必须有真实 dated 官方数据或已捕获的合法
快照，不可放宽 gate 或换 vendor。HITHINK 本次 ETF 仅实际返回上述 119 bars，不保证完整
多年历史；既有 history/data-quality gates 继续适用。

另发现独立的既有 formal reader 接入问题：`trading/production_prerequisites.py` 仍要求
`校验状态=已验证`，CN 单源行情通过 provider 校验后可能仍被判 `DATA_BAD`，公开 fixture 的
两只正式池标的因此未进入 Strategy 计算。此问题不由 Candidate as-of 修复引入，本 PR 不
改该 data gate；生产观察期间仅记录影响，不主动修复，不将数据阻断写成无信号。

## Next Action

只读核对 main 后续 CN/US Daily Report：自然触发与 completed session、Candidate seed /
included / deep-ready 数量、individual ENTRY_ALLOWED、DATA_BLOCKED、JSON/HTML 完整性及
RUN_STATUS / DATA_STATUS / CANDIDATE_STATUS。未出现新的自然运行时保持待验收，不以验证
fixture 或合并前运行替代。只记录问题，不扩展需求；仅遇真实生产 blocker 或需要用户
决策时停止并通知。D1 natural evidence 验收与 helper deployment identity hardening、
#110/#82/#96 保持各自独立，不混入本观察任务。

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
- 不读真实 holdings，不写 Sheet/state/Paper，不运行 broker，不改 D1 activation/window。
- CN/US D1 V2 activation 已完成；本任务没有读取/修改正式 D1 evidence，不从旧交接的
  formal count 推断实时 evidence 状态。

`HANDOFF_CURRENT_AND_CONSISTENT`
