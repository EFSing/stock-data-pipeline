# SINGLE_SOURCE_MARKET_DATA_V1

状态：`SINGLE_SOURCE_PRODUCTION_CUTOVER_READY`。代码、离线 fixture 与真实 provider
acceptance 已完成；D1 V2 immutable activation 与 production cutover 仍需用户最终授权。

本合同只改变 production data plane 与 failure isolation，不改变 Wave、Swing、
Fibonacci、Setup、Entry、Target、Stop、RR、Risk、Paper、broker 或 Final OOS 语义。

## Provider identity

| market | 唯一 production price vendor / implementation | raw | adjusted | 允许的重试 |
|---|---|---|---|---|
| CN | `HITHINK_FINANCIAL_API` | HITHINK metadata `asset_type=a-share` → `/api/a-share/prices/historical?adjust=none`; `fund-etf` → `/api/fund/market/historical` | 股票：仓库内 `CN_FORWARD_ADJUSTMENT_ENGINE_V1`；ETF：同一 HITHINK fund endpoint 的 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` | 同一 HITHINK provider 的 bounded retry |
| US | `YAHOO_CHART` | Yahoo Chart `/v8/finance/chart` | Yahoo Chart `adjclose` factor，`YAHOO_CHART_ADJCLOSE_ENGINE_V1` | 同一 Yahoo Chart implementation 的 bounded retry |

`yfinance`、BaoStock、Tencent、Sina 仍可被 legacy/research compatibility code 使用，
但不能从 CN/US production runtime 作为隐式 fallback、交叉校验或 qfq provider。Yahoo
的 query1/query2 只是同一个 Chart implementation 的 bounded transport retry，不是第二
vendor。CN asset type 只能来自明确的 watch metadata 或同一 HITHINK metadata directory
的 exact symbol match；不得使用代码前缀猜测 ETF。候选 universe seed（例如 CN 的 BaoStock 指数成分、US 的 IWB holdings）是
universe metadata，不是 price-data vendor。

## Minimum sufficient normalized contract

每个 normalized row 至少包含：

`symbol`、`market`、`session_date`、`open`、`high`、`low`、`close`、`volume`、
`source identity`、`acquired_at`、`adjustment provenance`。

`amount`、`turnover_rate`、`preclose`、`pct_change`、名称和 seed metadata 只能作为
辅助或展示字段；Wave / Swing / Fibonacci / Price Action 的生产输入不以成交额或
第二 provider agreement 为硬依赖。

单源合同由 `market_data_contract.validate_single_source_quotes()` 执行：

1. identity 与 market 必须匹配；
2. session date 严格递增且无重复；
3. OHLC 满足 `low <= open/close <= high`，数值有限且为正；
4. volume 非负；
5. 不接受 future bar；
6. exact-T 与 required history length 必须满足；
7. schema 不完整或 adjustment provenance 无法证明时 fail closed。

因此：`DATA_VALID = SINGLE_SOURCE_CONTRACT_VALID`，不再定义为“两家价格在容差内”。

## CN adjustment provenance

CN stock production 不使用 HITHINK 预计算 adjusted OHLC 作为 qfq SSOT。先取同一 vendor
的 raw daily OHLCV，再取同一 vendor 的 corporate-action events，由
`CN_FORWARD_ADJUSTMENT_ENGINE_V1` 生成 adjusted OHLCV。ETF/fund 是明确的另一资产合同：
HITHINK metadata 必须识别为 `fund-etf`，随后使用同一 HITHINK 的
`/api/fund/market/historical`；该 endpoint 的 provider-documented OHLC 已为
forward-adjusted，记录 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` 与
`HITHINK_PROVIDER_FORWARD_ADJUSTED`，不得把它伪装成股票 raw+action chain，也不得回退其他
vendor。每个 qfq result 记录：

- raw endpoint / source identity；
- corporate-action event source；
- event date、dividend、bonus 与 factor chain 的 SHA-256；
- adjustment engine version、asset type 与 adjustment source；
- symbol/session provenance。

若股票 corporate-action 数据未准备、字段不完整或其他资产合同无法证明，
不换 vendor、不猜公式，直接将该 symbol 标为 `DATA_ADJUSTMENT_UNVERIFIED` 并隔离。

## Symbol-level isolation

production data plane 的 symbol 状态为：

`DATA_OK`、`DATA_MISSING`、`DATA_STALE`、`DATA_INVALID`、
`DATA_ADJUSTMENT_UNVERIFIED`、`PROVIDER_SYMBOL_ERROR`。

这些状态都只产生 `DATA_UNAVAILABLE_FOR_DECISION:<status>`（或等价的
`DECISION_BLOCKED_DATA_UNAVAILABLE`），不产生 `NO_SIGNAL`，也不阻断其他 symbol。
formal strategy pool、active/position symbols 和 dynamic Candidate 分别记录状态；
Candidate deep-history 或 discovery 局部失败只撤销对应 Candidate 的当日资格，不能
让已有正式池停止。

provider authentication、全局 schema 变化、全局 outage、exact exchange session 无法
建立、配置/协议 hash 损坏或 orchestrator 无法形成 artifact 才可产生
`PROVIDER_GLOBAL_FAILURE` / system-level non-zero exit。即使所有 symbol 都因逐标的
业务原因不可用，也优先形成 `COMPLETED_NO_USABLE_SYMBOLS` 及完整 artifact。

## Daily Report semantics

日报同时发布：

- `RUN_STATUS`：`COMPLETED`、`COMPLETED_NO_USABLE_SYMBOLS`、
  `PROVIDER_GLOBAL_FAILURE` 或真正的 `FAILED`；
- `DATA_STATUS`：`OK`、`PARTIAL` 或 `NO_USABLE_SYMBOLS`。

scheduled CN/US Daily Report 不使用 `--require-complete`，symbol-level partial data
保持 Actions success；manual `workflow_dispatch` 可传该 flag 做 strict audit。最终 JSON、
HTML、email 顶部显示 attempted、`DATA_OK`、failed、coverage、failed-by-reason、
strategy analyzed 和 blocked counts；email 只展示最多 20 个异常 symbol，完整列表留在
artifact。provider-wide failure 仍先生成 artifact/notification，再返回非零。

## D1 V2 boundary

`SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 保存 attempted universe、usable/missing/invalid
symbols、per-symbol source status、provider identity、adjustment engine version、exact
session identity 与 per-symbol provenance。局部 symbol failure 可以在 session identity、
provider contract、raw prefix 和 snapshot integrity 有效时提交 formal research session；
缺失 symbol 永远写作 `DATA_MISSING` / `DATA_INVALID`，不得写成 `NO_SIGNAL`。

旧 V1 activation 不被覆盖。当前受控 VPS 核对结果为 CN/US formal session count `0/0`，
未发现 formal D1 evidence，已记录 `D1_SINGLE_SOURCE_MIGRATION_PRE_OUTCOME_CONFIRMED`。
migration gate 在每次 natural collector 前检查 durable
store verification 和 CN/US formal session count：formal evidence 非零时直接返回
`D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE`；V1 activation 返回
`D1_SOURCE_MIGRATION_PENDING`。新的 V2 immutable activation epoch 必须在真实 VPS
session count 核对、source contract 验证和用户最终批准后创建，首个 eligible session
之前不 backfill migration window。

## Production acceptance boundary

本分支已完成离线和真实 acceptance：

- CN 最新已完成 session `2026-09-28`：`600519.SH`（沪 A）、`000001.SZ`（深 A）、
  `300750.SZ`（创业板）、`688008.SH`（科创板）、`512400.SH` 与 `159866.SZ`（ETF）均以
  HITHINK 返回 exact-T、严格递增 OHLCV；股票 qfq 使用 HITHINK raw + corporate actions
  与冻结公式，ETF 分别命中 HITHINK fund endpoint。现金分红、送转样本、same-provider
  retry、stale detection、provenance、latency 与 reproducibility 已验收；bounded halt/no-
  trade probe 未找到可用样本，不改变合同。
- CN adjustment 还验证了一个 action dataset 返回 `3002` 的 fail-closed 路径，结果为
  `DATA_ADJUSTMENT_UNVERIFIED`，未把未知事件当作无事件。
- US `YAHOO_CHART` 使用 exact XNYS session `2026-09-28`；raw OHLCV 与 qfq `adjclose`
  provenance 均到 T，单个无效 symbol 只产生 symbol error，transport/schema/outage 保持
  provider-global 边界。未引入第二 US provider。
- 1、50、300 个 symbol-level failures、all-symbol unavailable、HITHINK auth/schema
  global failure、Yahoo global failure 与 scheduled `RUN_STATUS=COMPLETED` +
  `DATA_STATUS=PARTIAL` exit=0 均有语义测试；`DATA_MISSING` 与
  `DATA_ADJUSTMENT_UNVERIFIED` 不映射为 `NO_SIGNAL`。

因此当前合同状态为 `SINGLE_SOURCE_PRODUCTION_CUTOVER_READY`。这不表示已切换生产：V2
activation 只生成 preview/hash，不创建 immutable record；PR #124 也不在本轮 merge。
