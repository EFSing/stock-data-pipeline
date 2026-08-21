# DECISION_LOG.md — 重要决策记录

只记录重要架构／交易规则决策，不记录普通 Bug 修复。

## 2026-08-21

**Decision:** 确立 GitHub 仓库为项目唯一可信事实来源，`AGENTS.md` + `docs/` 作为跨 AI 工具共享上下文。

**Reason:** 项目将在多设备、多 AI 工具间接力开发，聊天记录不可作为长期记忆。

---

**Decision:** 项目版本基线定为 `V0.2`。

**Reason:** 行情抓取、双源校验、Google Sheets 写入已完成；交易决策引擎（Swing/Market Structure/Setup/Risk）尚未开始。仓库此前无版本号文件。

---

**Decision:** 保持现有扁平模块结构，不强行迁移到 `src/` 包布局。

**Reason:** 现有 4 个模块职责清晰且稳定；交易决策模块增多前的大规模重构风险大于收益。渐进重构优先。

---

**Decision:** 波浪分析采用「主情景 + 备选情景」，不武断输出唯一浪型；证据不足输出 `UPTREND_UNKNOWN_WAVE`。

**Reason:** 降低 Elliott Wave 主观性，防止行情波动时频繁改浪。

---

**Decision:** R/R 是交易准入条件，不是固定止盈；先算合理 Target 再算 R/R，禁止倒推目标价。

**Reason:** 防止为满足 R/R 阈值人为制造目标价格。

---

**Decision:** Swing 区分 `CONFIRMED` 与 `PROVISIONAL`。

**Reason:** 防止 Look-ahead Bias，回测时禁止拿未来确认的 Swing 回填过去信号。

---

**Decision:** 在 `requirements.txt` 增加 `tzdata` 依赖。

**Reason:** Windows 本地开发缺少系统时区数据库，`ZoneInfo("Asia/Shanghai")` 会报错；GitHub Actions 的 Ubuntu 环境自带但本地需要显式安装。

---

## 2026-08-22

**Decision:** Phase 1 Trading Core 采用克制目录结构 `trading/`（models/indicators/swing/structure/fibonacci/risk），单一权威实现，输入复用 `core.Quote`，不新建 Bar 类型。

**Reason:** 全仓库搜索确认无任何交易概念既有实现；避免重复实现与过度拆文件。

---

**Decision:** `SwingPoint` 记录 `pivot_index/pivot_date`（Swing 发生时间）与 `confirmed_index/confirmed_date`（信息实际可用时间）；任何历史决策只能用 `confirmed_index <= t` 的 Swing。

**Reason:** 明确「as-of t」语义，防止未来数据回填修改历史决策。

---

**Decision:** `MarketStructure.trend` 增加 `TRANSITION` 与 `UNKNOWN`；Swing 数量不足或结构不明确时禁止强制分类为趋势/区间。

**Reason:** 避免在证据不足时武断判定市场状态。

---

**Decision:** `fibonacci.py` 不依赖 `structure.py`，Fibonacci 只消费 `SwingPoint`。

**Reason:** 降低模块耦合，Fibonacci 是纯几何计算，不应绑定趋势判定。

---

**Decision:** `risk_reward()` 使用 `execution_stop` 计算真实 R/R；Structural Invalidation 与 Execution Stop 是两个独立概念，不在 R/R 计算中混用。

**Reason:** 结构失效与执行止损语义不同，混用会导致风险被高估或低估。

---

**Decision:** 指标定义固定：Wilder ATR、Wilder RSI、EMA 标准 `2/(N+1)`；warm-up 区间返回 `None`；指标序列长度与输入 Quotes 对齐。

**Reason:** 保证指标可复现、与输入逐位对齐，warm-up 不含未来信息。

---

**Decision:** Swing V1 以 causal pivot 为基础，可选 ATR / percentage minimum excursion filter 降噪；禁止使用事后重绘 ZigZag。

**Reason:** ZigZag 事后重标历史节点天然引入 look-ahead bias；causal pivot + excursion filter 保证因果性。

---

**Decision:** Trading Core 输入强制校验：日期严格升序、无重复、同一 symbol/market；异常 fail fast（抛异常），不静默排序或修正。

**Reason:** 输入脏数据静默修正会掩盖上游问题；显式失败更安全。

---

**Decision:** Phase 1 `PositionSize` 只输出 theoretical quantity / risk capital / max loss；A股手数、港股 lot size 等 executable rounding 待市场元数据接入后再做，不在本 PR 硬编码。

**Reason:** 避免过早绑定市场规则，保持 Phase 1 计算层纯净。
