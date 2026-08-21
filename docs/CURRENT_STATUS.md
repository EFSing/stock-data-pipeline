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
- 31 个 unittest 测试通过

## In Progress

- **CI Test Gate 建设**：新增 `.github/workflows/ci.yml`，PR 与 main push 自动跑现有 31 个 unittest（不连 Google Sheets、不需要 Secrets）

## Next

- 验证 CI Test Gate 在 PR 上运行通过
- Phase 1：Swing 引擎 / Market Structure（详见 `TRADING_SYSTEM_SPEC.md` 开发优先级）
- 迁移测试框架到 pytest（可选，当前明确不做）

## Known Issues

- 本地 Windows 开发需 `tzdata`（已补入 requirements.txt，待验证）
- 日股 (JP)、瑞典股 (SE) 无校验源，只能「单源可用」
- 项目为扁平模块结构，交易决策模块增多后需渐进模块化
- CI 工作流未运行测试
- **`总览` 表无读写逻辑**：需先核实真实 Google Sheets 结构再决定是否接入，不擅自补逻辑
- **`自选清单` 为 A:O（15 列）**，代码只消费其中 12 列（启用/市场/主数据源/校验数据源/时区/收盘时间/统一代码/名称/币种/BaoStock代码/yfinance代码/AKShare代码）；未消费列含义未核实，禁止猜测。列映射详见 `ARCHITECTURE.md`
