# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`DAILY_REPORT_CROSS_STAGE_CONSISTENCY_FIX_IN_PROGRESS`：继续 PR #135，PR 保持 open，branch
`feat/daily-report-human-opportunity-v1` 未合并。已发现此前 ready 结论与 branch HEAD 的
真实 SETUP_02 WATCH/ARMED 投影、ABOVE_ENTRY_ZONE 参考诊断及最终 HTML 本体不一致；当前正在
修复并重新验收，不能报告为 PR-ready。此前 PR #133/#134 的 CN provider-forward 与 US
Candidate lifecycle 状态不变；真实 D1 activation 未执行。

当前修复只允许继续现有 PR #135；不得新建 PR 或 merge。branch / PR / HEAD / CI 继续从
GitHub 实时核对，不以本文件作动态证明。修复完成前不把此前 generic fixture audit 或
旧 HTML 重渲染结果写成最终 acceptance；真实自然 production acceptance、Opportunity
Ledger natural acceptance 与 D1 activation 仍保持原边界。

## Current State / Completed

- Daily Report human-opportunity UI PR：CN/US 使用同一个 `trading/daily_dashboard.py`
  renderer；展开顺序为“人工机会判断 → 确认后的交易判断 → 机会新鲜度 → 折叠结构依据 →
  折叠开发者原始数据”。WATCH/ARMED 缺少 anchor 时明确列出缺口，不从价格倒推目标。
- `CONFIRMED + SETUP_01 + ABOVE_ENTRY_ZONE` 即使正式 target-before gate 提前终止，
  也会从既有 Decision anchors 通过共享 canonical Wave3 projection 展示人工空间；正式
  T1/RR 仍为空，正式结论仍为确认有效但超过允许入场区、不追高。
- 既有 Dashboard/email renderer 已支持 SETUP_02 target candidates 与中文化，但当前
  follow-up 正在把 causal `continuation_low0/high1/low2` 投影接入 WATCH/ARMED，并为
  `ABOVE_ENTRY_ZONE` 补独立参考第一目标诊断；正式 gate/action/target/RR 不变。
- 用户可见普通区域已统一使用中文语义：3浪斐波那契、正式判断、参考目标、缺失原因、
  结构失效价等；开发者原始数据/审计区继续保留内部原值。共享 `html_consistency_audit()`
  提供 `USER_VISIBLE_LANGUAGE_AUDIT`，返回 raw enum、内部字段、不必要英文、半中英提示计数，
  以及完整允许保留缩写清单。
- 实际保存的旧 CN/US Daily Report JSON 已生成新 HTML artifact；这些旧 JSON 尚未携带新
  ARMED/WATCH anchor fields，artifact 对相应标的保留显式 data gap，不能写成新 projection
  已在历史报告中自然存在。最终 artifact 使用 CN 2026-09-30 与 US 2026-10-02；US
  2026-10-02 来自真实成功 HTML 的原始 Daily Decision 字段重建只读输入。

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

- 既有 focused/full test 数量属于此前 HEAD 事实；本轮 consistency 修复完成前不沿用其
  ready 结论，需重新执行完整 `unittest discover`、最终 artifact audit 与 exact-head CI。
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
- 已保存的旧只读 CN/US HTML artifact 曾重新渲染，但旧 JSON 缺少本轮所需的
  SETUP_02 continuation anchors/reference diagnostics，不能作为当前修复的最终验收：
  `artifacts/daily_report_human_opportunity_v1/CN/2026-09-30-setup02-projection.html`
  与 `artifacts/daily_report_human_opportunity_v1/US/2026-10-02-setup02-projection.html`；
  CN 600901.SH 已展示 T1 + 四个 Fib，US SETUP_02 走同一 renderer。
- 本轮 exact-head CI、最终 CN/US READ_ONLY_VALIDATION_REPLAY artifact、整页 audit 与
  consistency matrix 待修复完成后重新取得；PR 保持 open，未合并。

## Blocker / Remaining Risks

- 新 D1 activation 仍需独立治理授权；两次 merge 不写真实 VPS/GCS activation，不运行新
  D1 V3 collector，不回填迁移窗口。
- 601059/601198 保持 stale/unavailable；JMKE 的 `HISTORY_INSUFFICIENT` 与 lifecycle
  exclusions 是合法 fail-closed 结果。真实 prospective 结果必须等待自然 session，不能
  通过历史回填补齐。
- 当前 blocker 是 `DAILY_REPORT_CROSS_STAGE_CONSISTENCY_FIX_IN_PROGRESS`：必须完成
  SETUP_02 causal projection、ABOVE_ENTRY_ZONE reference diagnostics、最终 HTML 本体
  audit 与治理校正后才能恢复 ready。生产自然 acceptance 仍是独立边界。
- 旧保存 JSON 的 ARMED/WATCH anchor 缺口只能由未来自然日报重生成解决；不能通过历史
  artifact 回填伪造 Wave3 projection。浏览器安全策略拒绝本地 `file:` URL 的自动绑定，
  因此保留本地静态 artifact/文件预览验收证据，不把它写成真实浏览器验收已完成。

## Next Action

完成本轮 consistency 修复、完整测试、CN/US READ_ONLY_VALIDATION_REPLAY artifact
与最终 HTML audit 后，更新治理状态并推送到 PR #135；保持 PR open、不要 merge。随后再
等待 PR review/用户决定、自然 CN/US report、Opportunity Ledger T+1/10-session acceptance
及经独立授权的 D1 decision。不要为清零合法 unavailable/lifecycle 状态继续开发；不把
live probe 写成 prospective D1 evidence。

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

`HANDOFF_CURRENT_AND_CONSISTENT`（当前修复进行中；ready 状态须待最终验收后恢复）
