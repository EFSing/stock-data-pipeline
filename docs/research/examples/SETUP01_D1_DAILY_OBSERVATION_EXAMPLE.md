# SETUP_01 D1 只读研究观察 — US 2026-09-25

> `FROZEN_SYNTHETIC_FIXTURE` 示例；不是正式 D1 数据，不是交易建议。

状态：COMPLETE；前瞻合格：fixture 中为是，正式事件计数为否。

研究候选与正式 `ENTRY_ALLOWED` 严格分离；本报告不写策略池、Paper 或 broker。

- 当日新增 H1 突破：1
- 路径 A 延续信号 K：1
- 路径 B 回踩候选/触及/反转 K：0/0/0
- next-session 模型执行/跳过：1/0
- 数据缺失/迟到：0/0

## 研究事件

- TEST｜PATH_A_SIGNAL｜支撑 H1 shelf｜触发 104.00｜上限 106.31｜止损 96.85｜
  T1 115.44｜5%/2R 诊断 true/false｜模型结果 RESEARCH_PLAN_CREATED
- TEST｜MODEL_EXECUTION｜模型入场 104.00｜`real_fill_evidence=false`｜
  正式 `ENTRY_ALLOWED=false`

## 完整性

实际运行会显示 D1 event ID、协议版本、五个 component hash 与 whole-event SHA-256。
fixture 不进入正式 store，不占用 CN/US 窗口或样本计数。
