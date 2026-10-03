# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`DAILY_OPPORTUNITY_LEDGER_V1`：独立实现生产日报“机会→结果”反馈闭环，代码与回归完成，
准备审阅独立 stacked PR。开始任务时 #131 仍 OPEN，已从其 exact head 建立
`codex/daily-opportunity-ledger-v1`，临时 base 为 `codex/fix-formal-reader-single-source`。
未修改、扩大或合并 #131；其 formal DATA_OK reader 修复是本分支的依赖，不是本任务 diff。
branch / PR / HEAD / CI 继续从 GitHub 实时核对，不以本文件作动态证明。

## Current State / Completed

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
- Cloud 自动 session 默认记录；显式历史 --date 仅诊断，不写正式账本。2026-10-04
  release 前的 session 被排除；正式 birth 只在自然 completed session 的 close→next-open
  窗口产生。三个 tab 已用现有 Cloud Google Secrets 创建并核验写权限，无新增权限。
- 写入失败独立为 OPPORTUNITY_LEDGER_STATUS=FAILED，尽量生成 JSON/HTML，workflow
  非零退出；部分写入不伪称零写入。已有 session/strategy/data/provider 合同不放宽。
- 所有交易规则、正式策略状态、Paper lifecycle、持仓、broker 和 D1 evidence 均不变；
  不处理33条 Candidate unavailable，不新增 Phase/registry/protocol/storage abstraction。

## Validation

- focused tests、全量 unittest、git diff --check 和 Daily Decision / Paper lifecycle /
  Portfolio Risk 三个 generic shadows 已通过；PR 的 fresh CI/shadow 按 GitHub 实时核对。
- 2026-09-30 已保存的只读诊断中5个 new CONFIRMED、ENTRY_ALLOWED=0，fixture 得到5/5
  birth（3个目标空间不足、1个RR不足、1个超过入场区）。fixture不写正式 prospective rows。
- 受控 synthetic 验证同session重跑零重复，T+1产生follow-up，掉出Candidate仍续载，
  数据缺失/错误provider/未来bar/复权基准变化为gap，same-bar ambiguous，无其他Sheet副作用。
- 独立临时 Actions harness 只创建/核验三个 observation tab 表头，无生产observation、
  持仓读取、策略/Paper/broker/D1访问或通知。harness不进入PR，临时远端branch已清理。

## Blocker / Remaining Risks

无实现或Sheets权限blocker；本任务尚未merge/deploy。依赖#131的reader修复仍待用户审阅，
本任务保持stacked base。真实prospective结果必须等待自然session，不能通过历史回填补齐。

## Next Action

审阅本任务独立PR；不得merge。#131后续合并时，本chat自动核对真实远端事实，将本任务
retarget/rebase到最新main，重新验证代码、CI与generic shadows并检查真实diff；不需要用户
中途操作。不得修改或合并#131。真实自然启用、T+1和10-session成熟样本仍需未来session
实际发生；不把fixture、权限核验或只读历史报告写成prospective production/D1 evidence。

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
- #131尚未部署时不能把reader公开provider/synthetic验证写成真实正式池自然恢复。

`HANDOFF_CURRENT_AND_CONSISTENT`
