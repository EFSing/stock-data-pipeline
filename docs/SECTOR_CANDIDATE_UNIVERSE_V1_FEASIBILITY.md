# SECTOR_CANDIDATE_UNIVERSE_V1 — Feasibility Audit

状态：`READY_FOR_DECISION_DATA_SOURCE`

本审计基于 live `main` 的 `f65f76eb06592a17a897e4a27560e3d5db2c04f9`，以及当前
工作树的 provider、watchlist、strategy-universe、history-QC 和 frozen strategy
engine 代码。结论是：现有 production data layer 可以处理“已知标的”的行情和历史，
但不能安全地产出可持续的 CN/US Sector / Industry Candidate Universe。没有实现
selector，也没有添加 provider、数据库、缓存、Sheet 或 production 输出。

## 目标边界

```text
Sector / Industry Universe
→ Tradable Candidate Selector
→ Candidate Universe
→ existing Data Quality / Weekly / Daily / Swing / Wave / Fibonacci / Setup chain
```

Candidate layer 只决定标的是否值得进入完整策略分析；它不产生
`ENTRY_ALLOWED`、`STRATEGY_PROPOSAL`、买入信号或仓位。Wave、Swing、SETUP_01、
SETUP_02、Entry/Stop/Target/RR、T→T+1、Portfolio Risk 语义保持 frozen；
SETUP_03/04、broker/order、production state writes 仍未启动。

## 字段级审计

| 能力 | 当前可用来源 | 结论 |
|---|---|---|
| CN/US 可交易证券列表 | production 只读取人工维护的 `自选清单`；`策略股票池` 也是人工配置表。Hithink 列表/指数快照只存在 research 证据 | 缺少 production-grade、可分页、可复核的 CN/US security master |
| security type / active status | watch row 没有 security type；CN code mapping 只做交易所前缀推导；现有 provider 不返回 security master 状态 | 缺失，不能安全排除 ETF、指数、退市或不可交易证券 |
| market / exchange | watch row 有 `市场`；CN 交易所可由代码前缀辅助推导，但没有统一 exchange/MIC 字段 | 只能支持已配置身份，不能作为完整 universe metadata |
| sector / industry | production `Quote` 只有 OHLCV、成交量、成交额、换手率和币种；没有 sector/industry 字段。研究 US snapshot 只有部分 `source_sector`，CN 没有对应 production mapping | 缺失；不能做 sector-aware grouping |
| price | 已知身份可从 yfinance/BaoStock/Tencent/Sina 得到 latest/历史价格 | 可复用，但没有可批量发现候选的 universe 输入 |
| liquidity / trading cost | 已知身份可得到 volume，部分来源有 amount/turnover；没有可靠 bid/ask spread，也没有候选层滚动 liquidity snapshot | 可以使用成交额/成交量 proxy，但当前没有批量候选入口；不得伪造 spread |
| history availability | 已有 `history_coverage_report()` 可对已加载标的检查 raw/qfq、至少 180 bars 和最长 14 日 observed-session gap | 对已知标的可靠；候选阶段缺轻量、可批量、不会先写 Sheet 的 history availability probe |
| CN 最低交易单位 | 当前 `trading/risk.py` 明确把 lot-size/executable rounding 留待 market metadata；provider/watch schema 没有 lot 字段 | 缺失。不能把所有 A 股无条件写死为 100；至少要限定支持板块并绑定规则证据 |
| US affordability | 已知标的可读取 price；当前没有 candidate gate，也没有 allocation boundary 的 1,000 USD hard-cap 校验 | 只能在未来 candidate 与 allocation 两层分别实现，当前不具备候选输入 |

## 已核对的仓库事实

- `core.Quote` 的字段是价格、`volume`、可选 `amount`、可选
  `turnover_rate` 和币种；没有 security master、sector、industry 或 lot。
- `providers.py` 只注册 `BaoStock`、`Tencent`、`Sina`、`yfinance` 的已知标的
  latest/history 路径；没有 universe/metadata provider。
- `策略股票池` contract 只有启用、账户、市场、统一代码、名称、备注，不能承载
  candidate provenance、affordability tier、exclusion reason 或 sector/industry。
- 现有 risk implementation 输出 theoretical quantity；executable rounding 和
  lot size 明确等待市场 metadata。
- Hithink smoke test 观察到的代码表字段为 `asset_type`、`currency`、`exchange`、
  `name`、`thscode`、`ticker`；完整分页未在本项目验证，行业/lot 字段也未在该
  probe 证明。CSI300/500/1000 是当前成分快照，不是 production security master。

## 最小替代方案

| 方案 | 组成 | 稳定性 / 成本 / 限制 | 复杂度 |
|---|---|---|---|
| A. 有界 index-proxy V1 | 复用已保存的 CN CSI300/500/1000、US index/ETF holdings snapshot；行情继续复用现有 provider | 成本低、实现低；只覆盖有限 cohort，sector/industry 和 lot 仍不完整，不满足可扩展 full CN/US universe | 低；只适合 research/fixture，不推荐作为正式 candidate source |
| B. 最小公共源组合 | CN 评估 BaoStock `query_all_stock` / `query_stock_basic` / `query_stock_industry`；US 使用 SEC submissions/SIC + Nasdaq symbol directory；价格/成交量/历史继续用现有 yfinance；CN 仅在明确支持的 SSE/SZSE main-board common A 范围内按规则计算 | 公共源成本低；SEC/Nasdaq 有批量/公平访问约束，yfinance 无 SLA 且需控制调用；CN/US taxonomy 需要显式映射，仍需补充 source freshness 与 lot evidence | 中；是最低成本的可行工程路线，但需要用户批准 provider contract 和支持范围 |
| C. 统一 reference-data provider | 选择有 CN/US 覆盖、active/security type/exchange/sector/industry/latest/history 及明确 lot semantics 的商业 API；现有 provider 只保留为历史 fallback 或不再承担 candidate discovery | 稳定性和批量性通常最好，但有订阅/entitlement、调用限制、凭证和供应商变更风险；CN 覆盖与交易单位必须逐项验收，不能仅凭宣传页 | 中高；长期最适合正式 universe，但必须先选供应商和预算 |

### 推荐

若 V1 必须保持低成本，选择 B，但先把正式范围限制为：CN SSE/SZSE main-board
common A（其他板块 fail closed），US 只保留 security type、exchange、sector/industry
和价格证据完整的普通股；成交额/成交量只作为明确标注的 liquidity proxy；最终
`<= 1,000 USD` notional cap 仍必须在 allocation/position sizing 边界再次验证。

若希望 Candidate Universe 真正可扩展并长期减少多源拼接，选择 C，并先完成一个
只读 capability proof：字段完整性、as-of/freshness、CN lot rule、US coverage、
批量限制、历史可用性和失败重试语义。未完成该选择前，不应实现 candidate selector
或把任何候选写入生产 `策略股票池`。

## 当前停止条件

`READY_FOR_DECISION_DATA_SOURCE`。待用户决定方案 B 或 C（以及方案 C 的具体供应商）
后，下一轮才能设计最小 Candidate input contract；在此之前不新增 provider、不写
真实 workbook、不进入完整 Strategy Chain、不启动 SETUP_03/04。

外部能力参考：

- Hithink Financial API metadata/index contract：<https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api.md>
- Hithink metadata paging contract：<https://github.com/HiThink-Tech/Financial-API/blob/main/docs/mcp/hithink-finance-meta.md>
- SSE A-share odd-lot / 100-share rule reference：<https://www.sse.com.cn/lawandrules/guide/stock/jyglywznylc/tz/c/c_20230209_5716007.shtml>
- SZSE trading rule reference：<https://www.szse.cn/English/rules/siteRule/P020181124401737559498.pdf>
- SEC EDGAR API overview：<https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- Nasdaq symbol directory：<https://nasdaqtrader.com/trader.aspx?id=symbollookup>
