# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`DAILY_REPORT_NOTIFICATION_AND_SESSION_FINALITY_PR_READY`：从最新 `main` 创建的独立分支
`fix/daily-report-notification-session-finality-v1` 已提交并推送，PR #138 保持 Open；
不直接修改或合并 `main`。本任务 supersede PR #137 中“Ledger 失败阻断 final delivery”
的通知语义，但不改变 readiness threshold、Ledger 数据模型、交易策略、Candidate ranking、
provider 合同或 cron。

目标是让正式日报数据状态与 Opportunity Ledger 状态独立、bounded retry 静默，并在自然自动
路径的 provider work 之前以 durable final marker 对 market/session 做 terminal NOOP；显式历史
diagnostic/replay 仍不发送通知、不污染 production marker。

#136 merge closeout 已客观核对：GitHub 状态为 MERGED，main 已包含其最终提交；其 required
checks 与 generic operational shadows 均为成功。历史状态仅作为只读 evidence，不写成当前
任务的 natural acceptance。

本分支基线已包含 PR #137 的 formal exact-T coverage、Candidate broad-stale gate、
`DailySymbolInput.qfq_history` / `data_quality_status` Ledger 接线、独立 alert marker 与
corrected-final recovery contract。本任务正在把 final Email、Ledger Bark、retry finalization
和 session terminality 重新解耦；PR #137 的历史语义保留在 `docs/DECISION_LOG.md`，不静默改写。

## Current State / Completed

- Daily Report diagnostics 已将 Candidate component/stage 状态合并为单一中文摘要，真正的
  symbol-level provider/stale 错误按标的展示，正常筛选排除单独放在中性区域；不会再把
  `DATA_OK`、Candidate stage 状态或正常规则排除误报成标的故障。
- US/CN dashboard 与 email 已使用中文用户可见文案；partial Candidate 使用 warning，
  formal readiness/system failure 才使用 blocking danger；Opportunity Ledger failure
  单独显示，不改变 `FINAL_REPORT_ELIGIBLE` 的数据资格。
- US 历史 artifact 回归已确认：1024 seed、1017 data-qualified、999 included、999
  strategy-analyzed；5 个真实标的异常与 25 个正常筛选排除分离，Candidate component 只保留
  1 个摘要。CN 历史 artifact 也已回归，2 个标的异常与正常排除分离。
- Candidate Yahoo forensic 为 diagnostic-only、确定性、全局有界采样：最多 3 个 stale
  样本和 2 个 control 样本；两 host comparison 最多产生 10 个额外请求；population、
  sample、request count 与 sampled symbols 写入 Candidate runtime artifact。

- Yahoo latest-row diagnostics 已同时保留 `timestamp_last_date`、实际最后 timestamp 的
  raw/adjclose availability、`latest_complete_raw_session` 与
  `latest_complete_qfq_session`；兼容字段 `raw_latest_row_complete` /
  `adjclose_latest_available` 已与实际最后 timestamp 对齐。US exact-T stale 的
  `stale_host_comparison` 仅记录 query1/query2 的有限状态与尾部诊断，不改变 query1
  正式选源或 query2 fallback 语义。
- Daily Report human-opportunity UI（已 merged to main）：CN/US 使用同一个 `trading/daily_dashboard.py`
  renderer；展开顺序为“人工机会判断 → 确认后的交易判断 → 机会新鲜度 → 折叠结构依据 →
  折叠开发者原始数据”。WATCH/ARMED 缺少 anchor 时明确列出缺口，不从价格倒推目标。
- `CONFIRMED + SETUP_01 + ABOVE_ENTRY_ZONE` 即使正式 target-before gate 提前终止，
  也会从既有 Decision anchors 通过共享 canonical Wave3 projection 展示人工空间；正式
  T1/RR 仍为空，正式结论仍为确认有效但超过允许入场区、不追高。
- Dashboard/email renderer 已把 causal `continuation_low0/high1/low2`（及已有
  `continuation_high3`）接入 WATCH/ARMED 的共享 Wave3 geometry helper，并为
  `ABOVE_ENTRY_ZONE` 保存独立参考第一目标、来源、上涨空间与参考 R/R；正式
  gate/action/target/RR 不变。
- 用户可见普通区域已统一使用中文语义：3浪斐波那契、正式判断、参考目标、缺失原因、
  结构失效价等；开发者原始数据/审计区继续保留内部原值。共享 `html_consistency_audit()`
  提供 `USER_VISIBLE_LANGUAGE_AUDIT`，返回 raw enum、内部字段、不必要英文、半中英提示计数，
  以及完整允许保留缩写清单。
- 旧 CN/US Daily Report JSON 不含完整历史行情前缀，不能被旧 JSON 重渲染冒充当前代码完整
  重放。最终 artifact 使用 canonical provider 严格按 T 重建指定标的：CN 2026-09-30 的
  `002436.SZ`，US 2026-10-02 的 `ANET`、`QCOM`、`SANM`、`SPCX`；均为只读重放。

- `日报历史` 保存 market/session summary，复用已有日报漏斗和展示投影；同一 session
  使用行级 upsert，不清空历史表，不覆盖另一个市场。
- `机会观察账本` 对 SETUP_01/02 每个 new CONFIRMED 保存原始 birth snapshot；包括
  ENTRY_ALLOWED 和全部拒绝原因，缺字段为 null，不补交易公式。身份为
  `market|existing event identity`，原 event identity 单独保留。
- `机会观察跟踪` 身份为 `opportunity_id + as_of_date`，仅从 T+1 起，跟踪10个真实
  exchange sessions。复用已有 canonical QFQ loader 和 active-symbol seed 模式；
  Opportunity 与 Paper 身份分开，Candidate dropout 后继续加载，不额外运行策略。
- 原 T1/T2/T3/stop/invalidation 冻结；same-bar stop/target 明确 ambiguous。
  缺数据、漏运行、复权基准变化显式 coverage gap；不回填缺口收益，不虚构成交/PnL/R。
  有缺口的成熟样本不进入收益描述统计，样本不足明确提示，不形成参数建议。
- Cloud 自动 session 默认记录；手动指定当前自然session也记录；历史 --date 仅诊断，不写正式账本。2026-10-04
  release 前的 session 被排除；正式 birth 只在自然 completed session 的 close→next-open
  窗口产生。三个 tab 已用现有 Cloud Google Secrets 创建并核验写权限，无新增权限。
- 写入失败独立为 OPPORTUNITY_LEDGER_STATUS=FAILED，尽量生成 JSON/HTML，workflow
  非零退出；正式日报仍可发 Email，并只为账本异常发一次独立 Bark；部分写入不伪称零写入。
  已有 session/strategy/data/provider 合同不放宽。
- 所有交易规则、正式策略状态、Paper lifecycle、持仓、broker 和 D1 evidence 均不变；
  不处理 601059/601198 residual data；US lifecycle hygiene 只处理通用 IWB metadata/identity
  status，不新增 Phase/registry/storage abstraction。
- 生产 CN A-share qfq 使用 `CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2` /
  `CN_HITHINK_PROVIDER_FORWARD_QFQ_CONTRACT_V2`；ETF 与 US contract 不变。
- `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 明确锁定旧 raw+corporate-actions basis；新
  `SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1` 只 code-ready，不创建 activation。
- merge 后首个 CN 自然日报必须单独审计原 33 个阻断标的、formal rows、
  `DATA_STATUS`/`CANDIDATE_STATUS` 与 Opportunity Ledger 三表；历史手动运行不计入自然
  acceptance。
- data-quality backlog 分类：HOLX unlisted/no-market 与 VYLR-WI lifecycle 已解决；JMKE
  `HISTORY_INSUFFICIENT`、601059/601198 stale/unavailable 属于合法数据/历史不可用状态；
  CN/US 自然日报、Opportunity Ledger natural acceptance 与 D1 V3 activation 边界仍待
  自然 production/独立授权，不以清零状态为目标。

## Validation

- 本轮 notification/marker/Cloud Report focused suite（60 passed）、Opportunity Ledger、
  CN/US workflow contract 与 generic operational shadow suite（19 passed）、完整
  `python -m unittest discover -s tests -v`（1058 passed、4 skipped）、compileall、目标
  文件 `py_compile` 与 `git diff --check` 均已通过；PR #138 的 CI Test Gate 与四个
  generic operational shadow 已按 exact head 通过，动态 run 事实以 GitHub 为准。
- 本轮真实历史 US/CN artifact 的 dashboard/email `USER_VISIBLE_LANGUAGE_AUDIT` 均为
  raw enum、内部字段、不必要英文、半中英提示计数全为 0；US presentation duplicate
  count 为 0，Candidate component placeholder count 为 0，partial 页面未使用 danger
  panel。
- 官方 IWB 只读验证已采用 `source_as_of=2026-10-02`、`seed_count=1026`，provenance
  保留 fallback 请求与 `requested_as_of=2026-10-05`；BABA/RKLB direct Yahoo raw/qfq
  均已验证 exact `2026-10-05`。完整 1026-symbol 本地 Candidate runtime probe 因批量
  Yahoo 请求超出有界本地验证时间而终止，未写成 production acceptance。
- #136 的 GitHub merge closeout 已核对：PR 状态为 MERGED，main 已包含其结果；其
  required CI 与 generic operational checks 均为 SUCCESS。该证据不等于本 PR 的 CI。
- independent/manual shadows（不称为 exact-head GitHub checks）：SETUP_01、SETUP_02 与
  Position Management generic operational shadow 均 SUCCESS；均未访问 broker/真实持仓或
  Sheets。
- 真实 main run artifact 重新套用本分支 contract：US 早期为 formal `0/2`、Candidate
  stale `306/717`，判 `UPSTREAM_NOT_READY`；恢复 run 的 BABA/RKLB 为 exact-T、formal
  `2/2`、Candidate stale `0`，判 `FINAL_REPORT_ELIGIBLE`；CN 为 formal `3/3`、800 seed /
  735 included，少数 Candidate error 仍判 final。均为历史只读证据，不写成 natural acceptance。
- GitHub 最近 10 次 `us-close` scheduled run 的实时审计已完成：当前 nominal `00:30 UTC`
  后，2026-09-25 至 2026-10-07 的 created/start delay 约 282–371 分钟；concurrency
  仅为 `holdings-market-data-us`，未发现其他 workflow 共用该组。调度延迟与 Yahoo stale
  已分开记录，本 PR 不先改 cron。
- Dashboard 与 email fixture 的 `USER_VISIBLE_LANGUAGE_AUDIT` 均为：
  `user_visible_raw_enum_count=0`、`user_visible_internal_field_count=0`、
  `user_visible_unnecessary_english_count=0`、`user_visible_mixed_language_count=0`；
  允许清单为 `SETUP_01`、`SETUP_02`、`T1`、`T2`、`T3`、`R/R`、`ATR14`、`CN`、`US`。
- local/full-suite generic operational evidence 也覆盖 Daily Decision Chain、Paper lifecycle、
  Portfolio Risk；均未读取真实持仓、凭证或 broker，也未写 Sheets。
- 2026-09-30 已保存的只读诊断中5个 new CONFIRMED、ENTRY_ALLOWED=0，fixture 得到5/5
  birth（3个目标空间不足、1个RR不足、1个超过入场区）。fixture不写正式 prospective rows。
- 受控 synthetic 验证同session重跑零重复，T+1产生follow-up，掉出Candidate仍续载，
  数据缺失/错误provider/未来bar/复权基准变化为gap，same-bar ambiguous，无其他Sheet副作用。
- 独立临时 Actions harness 只创建/核验三个 observation tab 表头，无生产observation、
  持仓读取、策略/Paper/broker/D1访问或通知。harness不进入PR，临时远端branch已清理。
- provider-forward live acceptance：原 33 个 residual symbols `33/33` usable，8 controls
  exact-T/chronology/OHLCV/volume contract valid；600519.SH 与 000001.SZ ex-date cutoff
  对比未发现 future-action leakage；ETF provenance 保持 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1`。
- post-merge US lifecycle sanity：HOLX → `LIFECYCLE_UNLISTED_OR_NO_MARKET`；VYLR-WI 保持
  identity 并 → `LIFECYCLE_WHEN_ISSUED`；JMKE → `HISTORY_INSUFFICIENT`；blank Exchange
  保持 ACTIVE/non-lifecycle；provider、strategy 与 affordability/history thresholds 未变。
- 最终 `READ_ONLY_VALIDATION_REPLAY` artifact 为：
  `artifacts/validation_replay/CN/2026-09-30/daily-report.html` 与
  `artifacts/validation_replay/US/2026-10-02/daily-report.html`；两份最终 HTML 本体的
  `USER_VISIBLE_LANGUAGE_AUDIT` 与 `DAILY_REPORT_CONSISTENCY_MATRIX_V1` 均通过，formal
  T1/RR 未被参考值污染。
- PR #135 exact-head required CI 全绿；merge 后 main CI 也已成功。PR #135 已 merged/closed，
  main 已包含本轮能力。

## Blocker / Remaining Risks

- PR #138 已创建、推送并通过 exact-head CI；当前无 code blocker，必须保持 PR Open，
  不 merge，不触发真实重复 Email/Bark。真实生产 end-to-end notification 仍未触发。
- PR #137 的历史 US artifact `Opportunity Ledger FAILED` 来自旧 main 的
  `DailySymbolInput.quotes` 接线问题；本分支只做 `.quotes` regression，不重新设计 Ledger。
- 完整 1026-symbol production Candidate runtime 的本地批量 probe 曾因 Yahoo 请求超出
  有界验证时间终止；PR 只读证据不把该 probe 写成 production acceptance，完整自然
  Candidate included/deep-ready/strategy 数量仍以未来正常运行 artifact 为准。
- 真实 Cloud recovered final 的 end-to-end notification delivery 未在本次修复中触发；当前
  证据为官方 IWB/exact-T provider probe、真实历史 artifact readiness replay 与 marker
  state-machine 回归，不能写成 natural acceptance。
- 2026-10-06 09:21 的历史 artifact 未保存足够 Yahoo raw JSON，故
  `YAHOO_EXACT_T_FORENSIC_PENDING_NATURAL_EVIDENCE`：当前可确认 readiness/ledger 顺序
  与 stale 分布，不能把 CDN、host、incomplete row 等假设写成已确认根因；新 adapter
  已增加下一自然 session 所需的实际尾行字段与有限 query1/query2 comparison，但尚无
  natural evidence。
- 新 D1 activation、natural CN/US acceptance 与 Opportunity Ledger natural acceptance
  仍保持原治理边界，不是当前 code blocker。
- 新 D1 activation 仍需独立治理授权；本次修复不写真实 VPS/GCS activation，不运行新
  D1 V3 collector，不回填迁移窗口。
- 601059/601198、JMKE 等既有合法 fail-closed 数据状态不因本任务改变；真实 prospective
  / natural acceptance 不以历史回放替代。

## Next Action

保持 `DAILY_REPORT_NOTIFICATION_AND_SESSION_FINALITY_PR_READY` 状态，等待 PR #138 review；
除 review correction 外不扩大范围，不 merge、不发送真实重复 Email/Bark。

## Constraints / Pitfalls

- 总体主线与四类Setup以docs/TRADING_SYSTEM_SPEC.md为唯一事实源：
  Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup →
  Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
  SETUP_01=Wave 2→Wave 3，SETUP_02=Wave 3 Continuation，SETUP_03=Platform Breakout，
  SETUP_04=Extreme Fear Reversal；SETUP_03只是四类Setup之一的子策略，Wave Scenario Engine
  与SETUP_01/SETUP_02的总体核心路线不变。本任务不改变Wave/Swing/Fibonacci/Entry Zone/
  5%T1/2R/Stop/Target/Portfolio Risk/Paper/broker。
- CN与US独立；只接受exact-T canonical provider，US QFQ latest-session门保持不变。
- 当前三表schema见trading/opportunity_ledger.py常量及docs/ARCHITECTURE.md；
  null保留在payload_json，不从空单元格猜数值。既有per-market workflow concurrency
  序列化schedule/manual/fallback；不要另起绕过该并发组的生产ledger writer。
- Candle顺序不明不标win/loss；覆盖不全时首次触及仅表示已观察到的首次触及。
- Cloud不写最新行情/历史行情表、策略状态、Paper或持仓；只新增独立observational持久化。
- formal reader 已合并到 main；公开 provider / synthetic 验证仍不能写成真实正式池自然
  恢复或自然生产验收。

`HANDOFF_CURRENT_AND_CONSISTENT`
