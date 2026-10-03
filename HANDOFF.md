# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`FORMAL_READER_SINGLE_SOURCE_VALIDATION_LABEL`：PR #129 已 squash merge；PR #130 已 retarget
到 main 并去除已合并的 Candidate diff，fresh exact-head CI / 三个 shadow 全通过后 squash
merge。Candidate 源日期、Wave zero-span 与日报可读性修复均已进入 main，本地 main 已同步。
用户授权的 formal reader 接入修复已在独立分支 `codex/fix-formal-reader-single-source` 完成，
尚未进入 main，准备审阅。只接入现有单源 `DATA_OK`，复用合同复核 latest/QFQ，兼容
direct Yahoo Chart 已有 `YahooChart` 行 source 名称，不接受 yfinance/未知来源。
不再扩大 #130，33 条 Candidate unavailable 暂不处理。2026-09-30 只读回补已运行成功、核心异常为 0，
数据质量仍 PARTIAL；自然生产验收继续独立。无新 Phase，公式和门槛不变；动态事实以 GitHub 为准。

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
- PR #128/#129/#130 均已合并；#130 最终 diff 仅 Wave 边界、日报展示及对应测试/治理文档。
  本次合并未加入 formal reader 或 Candidate unavailable 修复。自然日报验收与
  本次 historical diagnostic backfill 分开，不把回补当 prospective/D1 evidence。
- Wave 已判断为无效的非正向/零摆幅 impulse 不再调用描述性 Fibonacci 区域计算；该
  scenario 的原有失效与 Setup eligibility 不变。canonical Fibonacci 仍严格拒绝非正摆幅，
  未改任何公式、ratio、5%/2R 或策略阈值。
- 日报默认先显示今日重点，确认与等待确认排在异常前；全部结果仍可从“全部/诊断”访问，
  无 JavaScript 时也保留完整行。原始质量/覆盖/前瞻审计默认折叠；“报告覆盖标的”与
  “成功分析”分开，评估异常不再显示为正常 NO_TRADE。partial/failure 文案不抹掉已有结果。

## Validation

- 当前 reader 修复完整 `python -m unittest discover -s tests -v`：970 tests，968 passed、
  2 skipped；producer 行投影 round-trip、canonical source、坏 OHLCV、未收盘、旧/未来日期与
  QFQ 门均有回归覆盖，`py_compile`、`git diff --check` 通过。#129/#130 合并前 fresh
  exact-head CI 和三个 generic shadow 全通过；reader 新 PR CI 状态按 GitHub 实时核对。
- reader 真实 provider + 公开合成配置验证：CN `600000.SH` 的 1330 QFQ rows、US `AAPL` 的
  1376 rows 均经既有投影产生 DATA_OK，正式 reader preflight/input 均 DATA_OK。没有读取
  真实持仓、没有 Sheet/state 写入，未运行 Candidate runtime，也未检查/修复 33 个 unavailable。
- Live adapter：CN 800 seeds，US 1023 seeds，source-as-of 均为 2026-09-30；holiday、交易日
  不回退、更早报告拒绝、原始 timestamp 与 IWB response-date 保护均有回归覆盖。
- `601818.SH` exact-T 1000 bars 的 Wave / SETUP_01 replay / SETUP_02 replay 均完成，无原异常。
- 新的真实只读 CN 回补：800 seed → 798 data-qualified → 735 included → 701 deep-ready / 成功
  策略分析；报告共 737 行，核心评估异常 0。另 33 条 Candidate DATA_UNAVAILABLE 与 3 条
  正式输入 DATA_BAD 保留，不降低 gate。新 CONFIRMED=5、ARMED=35、WATCH=40，individual
  ENTRY_ALLOWED=0（3 个 T1 空间不足、1 个 R/R 不足、1 个超过入场区）。workflow success、
  RUN_STATUS=COMPLETED，DATA_STATUS/CANDIDATE_STATUS=PARTIAL；HTML/JSON 完整。
- 已用实际浏览器核对原报告与新版：原始诊断不再占满首屏，重点/全部结果/新确认筛选可用；
  成功分析与异常计数分开。产物保存在 git-ignored 的
  `artifacts/readonly_reports/CN/2026-09-30/wave-readability/`；不是研究/frozen artifact。
- 临时 Actions harness 仅修改日报 workflow，不进入 PR；使用 `--no-notify`，不注入通知/VPS
  marker 凭证，未调用或修改 notification marker，未发送通知、未写 Sheet/state/Paper/D1。
  回补是 diagnostic，不是 natural production / prospective evidence；D1 activation、durable
  storage、collector 与 reconciliation 保持独立。

## Blocker / Remaining Risks

零摆幅核心 blocker 已由明确的 invalid-context 边界处理解除，真实回补未再出现核心异常。
当前无本次修复实现 blocker；数据质量仍 partial，33 个 Candidate 不可评估。CN 仍无任意
历史 session 的成分股查询；非交易日归属不把 current-only 变成历史数据库。两项修复已
进入 main，自然运行验收仍待后续真实运行。

main 仍有 formal reader 旧标签接入缺口：自然日报已确认 CN 3 条、US 2 条 provider-valid
正式输入被判 DATA_BAD。独立 reader 分支已修复并通过公开 provider / 合成配置验证，尚未
部署；不能将该验证写成真实正式池或自然运行已恢复。旧 `已验证` 行兼容性保持，新
DATA_OK latest/QFQ 必须通过对应 canonical provider 与既有单源合同；公式/数据门不降低。

## Next Action

审阅独立 formal reader 修复 PR，核对其 CI/shadow 与不变的数据/策略边界；获合并授权后
再验证真实 CN/US 正式池自然分析恢复。坏/过期/未知 source 继续 fail closed，不改策略逻辑，
不处理 33 条 Candidate unavailable。main 自然观察、D1 evidence、helper deployment identity
hardening 与 #110/#82/#96 保持独立，不把回补当自然生产或 prospective evidence。

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
