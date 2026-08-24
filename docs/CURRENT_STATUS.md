# CURRENT_STATUS.md — 项目当前进展

> 保持简短，用于告诉下一个 AI：项目现在到底开发到了哪里。每次开发结束都更新。

```text
Version:
V0.2
```

## Completed

- 多市场行情抓取（A股/港股/美股/日股/瑞典股）
- 数据源回退链（yfinance → YahooChart / BaoStock → Tencent/Sina 快照）
- 双源校验（日期、收盘价、成交量容差）
- Google Sheets 写入（最新行情 / 历史行情_未复权 / 历史行情_前复权 / 校验记录 / 运行日志）
- GitHub Actions 定时任务（亚洲 / 欧美两个工作流）
- CI Test Gate：`.github/workflows/ci.yml`，PR 与 main push 自动跑 unittest
- Trading Core Phase 1（`trading/` 包，已合并到 main）：models（数据模型 + 输入校验）/ indicators（Wilder ATR·RSI·EMA）/ swing（causal pivot 状态机 + PROVISIONAL·CONFIRMED）/ structure（Market Structure）/ fibonacci / risk（R&R + Position Size）
- Phase 1 hardening + repaint 修复（已合并）：补测试缺口 + swing 状态机修复 confirmed repaint，全量 83/83 通过
- Phase 2 SETUP_03 Platform Breakout（已合并到 main）：`setup.py` 状态机（NONE/WATCH⇄ARMED/CONFIRMED/FAILED）+ `Setup` 数据模型，平台边界一致性 + terminal lock + 直接突破；全量 93/93 通过
- Phase 3 Decision Engine（SETUP_03 最小闭环，PR #9 已合并到 main）：Entry → Structural Invalidation → Execution Stop → Target → R/R → Position Size → Decision Action；future Setup 防泄漏 + 真实 ENTRY_ALLOWED 回归案例；全量 104/104 通过
- Phase 4 第一批：SETUP_03 Decision 只读投影到 `交易决策` 表；正式收盘 + qfq 日期双门控、显式历史源、参数透传与单标的异常隔离；全量 116/116 通过
- Phase 5A：SETUP_03 Historical Replay & Diagnostics（只读）：`trading/replay.py` 按历史交易日前缀 `quotes[:i+1]` 严格 as-of 回放，复用现有 Setup / Decision Engine，明确区分状态日与 CONFIRMED/FAILED 事件，仅在 CONFIRMED 事件日运行 Decision；新增 workflow_dispatch-only 真实前复权回放 workflow（只读 artifact，不写生产 Sheet）；全量 122/122 通过
- SETUP_03 审计整改：生产与回放共用 `trading/events.py` 终态事件语义；`交易决策` 改为仅发布新 CONFIRMED 事件并以已有事件键阻止同日重算；补齐真实多生命周期回放、数据质量门控、calculable/enabled 覆盖率失败条件、只读事件明细 artifact 及 replay/生产一致性测试；全量 136/136 通过
- SETUP_03 审计整改 PR #12 已合并；带真实 Secrets 的 3 年只读 replay 在生产参数 `platform_tolerance_pct=0` 下客观为 `events=0`

## In Progress

- Phase 5B SETUP_03 Research Backtest & Parameter Diagnostics：直接消费 PR #12 统一 CONFIRMED 事件流水，只在 T+1 Open 模拟执行；新增 trade outcomes 与固定 54 组 research-only 敏感性诊断，不排名、不优化、不改生产参数

## Next

- SETUP_01/02：暂待 Wave Engine（Phase 5 后续）
- SETUP_04：暂待 Extreme Fear 输入与确认规则
- 迁移测试框架到 pytest（可选，当前明确不做）

## Known Issues

- 本地 Windows 开发需 `tzdata`（已补入 requirements.txt，本地已验证通过）
- 日股 (JP)、瑞典股 (SE) 无校验源，只能「单源可用」
- 项目为扁平模块结构，交易决策模块增多后需渐进模块化
- **`总览` 表无读写逻辑**：需先核实真实 Google Sheets 结构再决定是否接入，不擅自补逻辑
- **`自选清单` 现有 A:O 未消费列含义仍未核实**；Phase 4 使用新增的明确表头 `历史数据源`，不得复用或猜测旧列。列映射详见 `ARCHITECTURE.md`
- `交易决策` 历史上由 PR #10 写入的状态快照行不会由本整改自动删除；新版本只追加/幂等更新 CONFIRMED 事件，旧行清理需单独审阅后执行
- Replay 最新日期使用现有保守收盘日判断，异常缺口使用可配置日历日阈值；尚未接入各交易所节假日/停牌日历，真实 workflow 的 skipped 明细仍需人工复核
