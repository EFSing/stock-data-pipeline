# SINGLE_SOURCE_MARKET_DATA_V1

状态：代码与离线 fixture 已完成，生产切换仍需真实 credential / natural-run 验收。

本合同只改变 production data plane 与 failure isolation，不改变 Wave、Swing、
Fibonacci、Setup、Entry、Target、Stop、RR、Risk、Paper、broker 或 Final OOS 语义。

## Provider identity

| market | 唯一 production price vendor / implementation | raw | adjusted | 允许的重试 |
|---|---|---|---|---|
| CN | `HITHINK_FINANCIAL_API` | HITHINK historical daily `adjust=none` | 仓库内 `CN_FORWARD_ADJUSTMENT_ENGINE_V1` | 同一 HITHINK provider 的 bounded retry |
| US | `YAHOO_CHART` | Yahoo Chart `/v8/finance/chart` | Yahoo Chart `adjclose` factor，`YAHOO_CHART_ADJCLOSE_ENGINE_V1` | 同一 Yahoo Chart implementation 的 bounded retry |

`yfinance`、BaoStock、Tencent、Sina 仍可被 legacy/research compatibility code 使用，
但不能从 CN/US production runtime 作为隐式 fallback、交叉校验或 qfq provider。Yahoo
的 query1/query2 只是同一个 Chart implementation 的 bounded transport retry，不是第二
vendor。候选 universe seed（例如 CN 的 BaoStock 指数成分、US 的 IWB holdings）是
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

CN production 不使用 HITHINK 预计算 adjusted OHLC 作为 qfq SSOT。先取同一 vendor 的
raw daily OHLCV，再取同一 vendor 的 corporate-action events，由
`CN_FORWARD_ADJUSTMENT_ENGINE_V1` 生成 adjusted OHLCV。每个 qfq result 记录：

- raw endpoint / source identity；
- corporate-action event source；
- event date、dividend、bonus 与 factor chain 的 SHA-256；
- adjustment engine version；
- symbol/session provenance。

若 ETF、基金或其他资产无法由 raw + corporate actions 可靠证明 adjustment chain，
不换 vendor，直接将该 symbol 标为 `DATA_ADJUSTMENT_UNVERIFIED` 并隔离。

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

旧 V1 activation 不被覆盖。migration gate 在每次 natural collector 前检查 durable
store verification 和 CN/US formal session count：formal evidence 非零时直接返回
`D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE`；V1 activation 返回
`D1_SOURCE_MIGRATION_PENDING`。新的 V2 immutable activation epoch 必须在真实 VPS
session count 核对、source contract 验证和用户最终批准后创建，首个 eligible session
之前不 backfill migration window。

## Production acceptance boundary

本分支已覆盖离线 HITHINK raw + corporate action、Yahoo Chart contract、exact-T、stale、
missing、invalid、ETF adjustment isolation、partial symbol counts、provider-global
failure、Daily Report status 与 D1 V2 snapshot fixtures。真实 HITHINK credential、VPS
formal session count 和 V2 activation 尚未在本地可核对；因此本合同不宣称
`PRODUCTION_CUTOVER_READY`。
