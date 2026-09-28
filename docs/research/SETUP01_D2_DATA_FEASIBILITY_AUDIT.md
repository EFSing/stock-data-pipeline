# SETUP_01 D2 历史独立样本数据可行性审计

Status: `READY_FOR_DECISION_D2_POINT_IN_TIME_DATA_SOURCE`

Audit date: 2026-09-24

本审计发生在 D2 roster、历史行情、信号与收益均未创建或访问之后、经济回放之前。
它只审计现有数据合同，不授权下载 D2 数据、采购付费数据或访问 Final OOS。

## 1. 冻结标准

D2 的 CN/US 各至少 60 symbols、2017-01-01..2026-08-26 历史窗口只有在以下证据全部
可冻结时才可启动：

1. point-in-time universe：名单生成不依赖窗口末端仍存续/仍在指数或 ETF 的事实；
2. delisting/security lifecycle：退市、换码、并购与 share-class 身份可追溯；
3. corporate actions：拆并股、分红与复权口径、有效日及原始事件可重建；
4. exact sessions 与 suspension：缺失 bar 不会被误当成无信号；
5. CN 每日 board/ST/涨跌停/lot 规则：能在执行日判断 model-executable；
6. 来源、许可、retrieval time、raw/normalized snapshot 与 hash 可提交并复现。

任一市场不满足即不得以当前成分股向后回看。CN/US 分母独立，另一市场通过不能补足。

## 2. 现有来源审计

| 市场/来源 | 已有能力 | 缺口 | 判定 |
|---|---|---|---|
| CN BaoStock candidate adapter | `query_hs300_stocks(date=...)` / `query_zz500_stocks(date=...)` 可按日期请求指数名单；`query_stock_basic()` 暴露 IPO/outDate/status | 当前 adapter 的 basic/industry 是无 as-of 的现时全表；历史 bar 合同未摄取 `isST` / `tradestatus`；没有逐日 board、lot、涨跌停规则或完整退市/换码 master 的冻结合同 | `NOT_READY` |
| CN HiThink 已做 smoke | 当前 CSI300/500/1000 名单、OHLCV、公司行动 endpoint 可访问 | 仓库 smoke 明确“未观察到历史成分序列”；公司行动没有已证明的 adjustment-factor 公式/生效约定，calendar 覆盖也未完成验证 | `NOT_READY` |
| US iShares IWB adapter | 官方发行人当前 holdings CSV，含 source-as-of 与约 1000 个当前持仓 | 代码固定 `latest-holdings.csv`；没有 2017..2026 历史 membership archive、退市/并购 security master。官方页面也声明 holdings 会变化，因此当前快照不能证明历史母体 | `BLOCKED` |
| US yfinance history | 对已知 ticker 可取得 OHLCV；现有研究 acquisition 使用 auto-adjusted prices | 它不是 point-in-time universe/delisting source；现有 manifests 多为 `actions=false`，无法把调整后价格与冻结的 corporate-action event provenance 交叉绑定；已知 ticker 抓取不能纠正名单幸存者偏差 | `BLOCKED` |
| 既有 Phase 5K / Development manifests | 提供已暴露的当前 universe snapshots 与 frozen bars，可用于来源合同审计 | 已用于既往开发/研究，且 current constituent/proxy 身份明确；不得重命名为 D2 fresh independent sample | `INELIGIBLE` |

本地证据包括 `trading/candidate_universe_sources.py`、`providers.py`、
`docs/HITHINK_CN_API_CAPABILITY_SMOKE_TEST.md`、`research/development_dataset.py` 及既有
dataset/universe manifests。外部交叉核对显示，iShares IWB 页面提供的是随时变化的 holdings
下载；Yahoo 也把其 Finance 数据限定为 informational use。两者都没有补齐本协议要求的
历史 point-in-time universe 与退市主数据合同。

外部证据：

- iShares IWB 官方页面：<https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/?dataType=fund&fileName=IWB_holdings&fileType=csv>
- Yahoo Finance 数据来源与使用说明：<https://help.yahoo.com/kb/SLN2310.html>

## 3. 结论

现有免费数据栈不能满足 D2 冻结标准，整体结论为：

`BLOCKED_EXISTING_FREE_STACK_NO_COMPLIANT_POINT_IN_TIME_SOURCE`

- US 是确定性 hard blocker：当前 IWB 快照 + known-ticker yfinance history 会形成
  survivorship-biased historical roster。
- CN 的日期化指数查询是可复用基础，但现有合同仍不足以冻结逐日 ST/board/price-limit、
  delisting/security lifecycle 与可审计公司行动。
- 因此未建立 D2 roster、未抓取任何 D2 bars、未生成信号或收益，也未选择/购买付费源。
- 成本来源仍需冻结，但在 universe/metadata hard blocker 解除前不构成启动许可。

## 4. 下一决策节点

只有两类互斥方向可继续，且都需要用户新授权：

1. `D2_LICENSED_OR_USER_SUPPLIED_PIT_SOURCE`：用户指定或提供有权使用的数据源，至少覆盖
   历史 membership、退市/身份、公司行动；CN 还需逐日 board/ST/涨跌停/停牌/lot。随后只做
   capability sample 与合同冻结，仍不得直接跑收益。
2. `REOPEN_DATA_DESIGN`：放弃当前 D2，重新选择此前已定义的 D1 prospective
   time-isolated 方案；这会改变已经冻结的数据选择，必须留下新决策记录，不能自动切换。

不得选择“当前成分股 + 历史行情”作为第三条捷径；不得自动采购付费数据。

## 5. 保持不变的边界

- architecture freeze 与 B 日/T1 两项修正保持不变；
- #110 独立且仍为 `INSUFFICIENT_EVIDENCE`，不复用其结果；
- production SETUP/Risk/Decision/Paper/Sheet/broker 均不变；
- Final OOS 未建立、未访问；本审计没有经济结果。
