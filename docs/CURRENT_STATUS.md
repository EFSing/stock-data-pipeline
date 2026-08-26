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
- 行情来源质量选择：同日主源 OHLCV 异常、校验源正常时，整根行情采用校验源，并同步替换未复权历史末根 K 线；两源均异常时继续待复核
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
- Phase 5B SETUP_03 Research Backtest & Parameter Diagnostics（PR #13 已合并）：直接消费统一 CONFIRMED 事件流水；T 日生产 Decision gate 后，仅 `ENTRY_ALLOWED` 在 T+1 Open 尝试三分支执行。真实 Core → ReplayEvent → EXECUTED 集成测试、CONFIRMED → Decision → T+1 守恒漏斗、退出 bar 保守 MFE/MAE 与实际 `observation_days` 口径均已冻结；真实 3 年只读 workflow `32747728644`（9 标的/6037 bars）：生产参数 `0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`；固定 54 组累计 `206 CONFIRMED → 4 ENTRY_ALLOWED → 3 SKIP_GAP_BELOW + 1 SKIP_GAP_ABOVE + 0 EXECUTED`，计数守恒且不排名、不优化、不改生产参数

## In Progress

- Phase 5C SETUP_03 Decision Gate Diagnostics（PR #14 待审阅）：Decision 同一次生产计算返回原 `Decision` 与只读 `DecisionDiagnostics`，ReplayEvent 原样携带 diagnostics，research 固定 54 组只投影、不重算交易条件；新增逐事件/逐参数组合 CSV，并强制 reason 守恒；全量 164/164 通过。真实 3 年只读 workflow `32821290764` 成功（9/9 标的、6032 bars、skipped=0）：生产参数仍为 `0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`；54 组为 `197 CONFIRMED → 4 ENTRY_ALLOWED → 3 SKIP_GAP_BELOW + 1 SKIP_GAP_ABOVE + 0 EXECUTED`，27 组有 CONFIRMED、3 组有 ENTRY_ALLOWED。Decision gate 为 `139 ABOVE_ENTRY_ZONE + 54 RR_BELOW_MINIMUM + 4 ENTRY_ALLOWED`，其余 reason（含 OTHER/invalid context）均为 0；不排名、不选 best、不修改生产参数或交易行为
- Phase 5D Replay Input Reproducibility（PR #15，基于待合并 PR #14 的堆叠开发）：对实际进入 replay 的完整 Quote 生成逐 symbol/全数据集 SHA-256 manifest；支持六类显式 manifest diff、确定性 frozen input、跳过 live fetch 的 frozen replay 与 artifact 间自动比较。任何 frozen 内容与嵌入 manifest 不一致时 fail fast；`artifacts/` 已加入 gitignore。全量 172/172 通过。真实 live runs `32826696259` / `32828129539` 均成功：均为 9 symbols / 6032 bars、bar count 与日期范围相同，但 aggregate hash 由 `sha256:2b8203…c54703` 变为 `sha256:8166e1…09e36`，6 symbols 为 `CONTENT_CHANGED_WITH_SAME_BAR_COUNT`，grid funnel 由 `207 CONFIRMED → 4 ENTRY_ALLOWED → 0 EXECUTED` 变为 `200 → 4 → 0`。frozen run `32829662164` 从首轮 artifact 重放成功：9/9 `IDENTICAL`，aggregate/frozen bytes/六份核心报告 hash 与 funnel 全部一致，验证 same input + same config/code 可重复
- Phase 5E Frozen Dataset Validation（PR #16，基于 PR #15 的堆叠开发）：固定 Phase 5D 首轮 run `32826696259`（9 标的/6032 bars，dataset hash `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`）及生产参数版本 `sha256:abe4d3026892`；Phase 5E 入口禁止 live history，任何 dataset/参数漂移 fail fast，并跳过 54 组参数网格。只读输出中文漏斗、Decision reason、标的/市场/年份/季度、集中度及信号后 5/10/20D forward return/MFE/MAE；全量 176/176 与 PR CI 通过。真实 frozen workflow `32853329965` 成功且 9/9 manifest `IDENTICAL`：`0 CONFIRMED → 0 ENTRY_ALLOWED → 0 EXECUTED`，6032 个状态日全部为 NONE，因此收益、MAE/MFE、集中度与初步 Edge 均不可评估；不优化参数，不启动最终样本外验证
- Phase 5F SETUP_03 Confirmation Gate Diagnostics（PR #17，基于 PR #16 的堆叠开发）：production Setup 同一次计算返回原 `Setup` 与只读 `SetupDiagnostics`，兼容 API 和交易行为不变；Replay 只携带 diagnostics，research 仅投影互斥守恒 terminal reason、逐 gate 漏斗、辅助多重失败与 near-miss 分布。全量 179/179 与 PR CI `32855313853` 通过；真实 frozen workflow `32855822844` 成功，9 标的/6032 bars 且 dataset hash 仍为 `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`。terminal reason 守恒为 `438 NO_NEW_CONFIRMED_SWING + 3474 INSUFFICIENT_HIGH_SWINGS + 837 INSUFFICIENT_LOW_SWINGS + 823 STRUCTURE_NOT_RANGE_OR_TRANSITION + 460 HIGH_SPAN_EXCEEDS_TOLERANCE = 6032`；顺序漏斗中最后 460/460 在零容差 high-span gate 全部淘汰，因此无任何平台被识别，后续 WATCH/ARMED/CONFIRMED 全为 0。不改生产参数/规则，不优化，不启动 OOS。

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
- Phase 5B 真实 54 组严格逐日前缀回放约需 14 分钟；当前仅手动 research workflow 使用，后续若扩大标的池需在不改变 as-of/事件语义前提下优化编排性能
- 三年 live replay 仍按运行日滚动，数据源也可能修订历史 OHLC；Phase 5D 可准确识别、冻结并重放输入，但不会阻止上游修订。manifest/frozen input 当前随 GitHub artifact retention 生命周期保存，长期样本外基准需另行决定保留策略
- Phase 5E 固定集已经用于 Phase 5B~5E 开发诊断，不能再作为最终样本外保留集；最终 OOS universe、时间边界与保留策略尚未定义，本阶段明确不启动
- Phase 5E workflow 仍需只读 Google Sheets 获取生产参数；真实 run 首次 attempt 曾遇到 Google API HTTP 503，原 run 重跑后成功。当前未新增 Sheets 初始化重试，外部服务瞬时不可用仍可能令手动诊断失败
