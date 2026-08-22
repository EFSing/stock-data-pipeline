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

## In Progress

- 无

## Next

- Phase 4：Google Sheets Decision Tables
- SETUP_01/02：暂待 Wave Engine（Phase 5）
- SETUP_04：暂待 Extreme Fear 输入与确认规则
- 迁移测试框架到 pytest（可选，当前明确不做）

## Known Issues

- 本地 Windows 开发需 `tzdata`（已补入 requirements.txt，本地已验证通过）
- 日股 (JP)、瑞典股 (SE) 无校验源，只能「单源可用」
- 项目为扁平模块结构，交易决策模块增多后需渐进模块化
- **`总览` 表无读写逻辑**：需先核实真实 Google Sheets 结构再决定是否接入，不擅自补逻辑
- **`自选清单` 为 A:O（15 列）**，代码只消费其中 12 列（启用/市场/主数据源/校验数据源/时区/收盘时间/统一代码/名称/币种/BaoStock代码/yfinance代码/AKShare代码）；未消费列含义未核实，禁止猜测。列映射详见 `ARCHITECTURE.md`
