# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`DAILY_REPORT_CROSS_STAGE_CONSISTENCY_MERGED_WAITING_NATURAL_ACCEPTANCE`：PR #135
已 squash merge 到 `main`。Daily Report human-opportunity、SETUP_02 WATCH/ARMED causal
projection、ABOVE_ENTRY_ZONE 独立参考诊断、用户可见语言与 cross-stage consistency 已成为
main 能力；此前 PR #133/#134 的 CN provider-forward 与 US Candidate lifecycle 状态不变；
真实 D1 activation 未执行。

当前已无 PR #135 实现 blocker；merge commit、main HEAD 与 main CI 继续从 GitHub 实时核对，
不以本文件作动态证明。最终 validation artifact 是 `READ_ONLY_VALIDATION_REPLAY`，不代表
natural production acceptance；Opportunity Ledger natural acceptance 与 D1 activation 仍
保持原边界。

## Current State / Completed

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
  非零退出；部分写入不伪称零写入。已有 session/strategy/data/provider 合同不放宽。
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

- 本轮 focused tests 141 passed；全量 `python -m unittest discover -s tests -v` 为
  1007 passed、2 skipped；`compileall`/`py_compile` 与 `git diff --check` 通过。
- Dashboard 与 email fixture 的 `USER_VISIBLE_LANGUAGE_AUDIT` 均为：
  `user_visible_raw_enum_count=0`、`user_visible_internal_field_count=0`、
  `user_visible_unnecessary_english_count=0`、`user_visible_mixed_language_count=0`；
  允许清单为 `SETUP_01`、`SETUP_02`、`T1`、`T2`、`T3`、`R/R`、`ATR14`、`CN`、`US`。
- Daily Decision Chain、Paper lifecycle、Portfolio Risk 三个 `GENERIC_OPERATIONAL_SHADOW`
  均为 SUCCESS；均未读取真实持仓、凭证或 broker，也未写 Sheets。
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

- 新 D1 activation 仍需独立治理授权；本次 merge 不写真实 VPS/GCS activation，不运行新
  D1 V3 collector，不回填迁移窗口。
- 601059/601198 保持 stale/unavailable；JMKE 的 `HISTORY_INSUFFICIENT` 与 lifecycle
  exclusions 是合法 fail-closed 结果。真实 prospective 结果必须等待自然 session，不能
  通过历史回填补齐。
- `DAILY_REPORT_CROSS_STAGE_CONSISTENCY` 已 merged；剩余风险仅为自然 production
  acceptance、Opportunity Ledger natural acceptance 与独立授权的 D1 activation 边界，
  不把只读历史重放写成自然验收。
- 旧保存 JSON 的 ARMED/WATCH anchor 缺口只能由未来自然日报重生成解决；不能通过历史
  artifact 回填伪造 Wave3 projection。浏览器安全策略拒绝本地 `file:` URL 的自动绑定，
  因此保留本地静态 artifact/文件预览验收证据，不把它写成真实浏览器验收已完成。

## Next Action

等待首次 post-merge 自然 CN/US Daily Report 与 Opportunity Ledger natural acceptance；
后续 T+1/10-session acceptance，以及未来经独立授权的 D1 decision 仍按原边界处理。不要
为清零合法 unavailable/lifecycle 状态继续开发；不把 READ_ONLY_VALIDATION_REPLAY、live
probe 或历史回放写成 prospective/natural production acceptance。

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
