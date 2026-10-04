# SINGLE_SOURCE_MARKET_DATA_V1

状态：`CN_QFQ_PROVIDER_FORWARD_MIGRATION_MERGED_TO_MAIN`。CN A-share provider-forward
route、as-of purity、33 个 residual symbol、control 与回归验证已完成；PR #133 已 squash
merge。真实 D1 provider-forward activation 与 merge 后首个 natural CN production
acceptance 仍未执行。

本合同只改变 production data plane 与 failure isolation，不改变 Wave、Swing、
Fibonacci、Setup、Entry、Target、Stop、RR、Risk、Paper、broker 或 Final OOS 语义。

## Provider identity

| market | 唯一 production price vendor / implementation | raw | adjusted | 允许的重试 |
|---|---|---|---|---|
| CN | `HITHINK_FINANCIAL_API` | HITHINK metadata `asset_type=a-share` → `/api/a-share/prices/historical?adjust=none`; `fund-etf` → `/api/fund/market/historical` | A-share 股票：`/api/a-share/prices/historical?adjust=forward`，`CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2` / `CN_HITHINK_PROVIDER_FORWARD_QFQ_CONTRACT_V2`；旧 `CN_FORWARD_ADJUSTMENT_ENGINE_V1` 保留为 immutable legacy/D1 V2 basis；ETF：同一 HITHINK fund endpoint 的 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` | 同一 HITHINK provider 的 bounded retry |
| US | `YAHOO_CHART` | Yahoo Chart `/v8/finance/chart` | Yahoo Chart `adjclose` factor，`YAHOO_CHART_ADJCLOSE_ENGINE_V1` | 同一 Yahoo Chart implementation 的 bounded retry |

`yfinance`、BaoStock、Tencent、Sina 仍可被 legacy/research compatibility code 使用，
但不能从 CN/US production runtime 作为隐式 fallback、交叉校验或 qfq provider。Yahoo
的 query1/query2 只是同一个 Chart implementation 的 bounded transport retry，不是第二
vendor。CN asset type 只能来自明确的 watch metadata 或同一 HITHINK metadata directory
的 exact symbol match；不得使用代码前缀猜测 ETF。CN production Candidate universe 只能使用
HITHINK 官方指数成分 endpoint
`/api/a-share-index/constituents/ths-stock-list` 的 HS300 `000300.SH` 与 CSI500
`000905.SH` 当前快照，US 使用官方 IWB holdings。Candidate membership、snapshot timestamp
和 endpoint/index provenance 必须随 seed 保存；这属于 universe metadata，不改变 price-data
vendor 合同。BaoStock Candidate adapter 仅保留 legacy/research compatibility，不进入
production runtime。

CN 两个指数先按 canonical symbol 做确定性 union/dedupe，再按既有 affordability、流动性和
历史质量规则排序；production 不依赖 sector metadata，也不使用 `TOP_N_PER_SECTOR` 限额。
HITHINK 指数接口的当前快照不是 point-in-time 历史 membership：snapshot timestamp 晚于
requested `as_of` 时 fail closed，不能把后来的 membership 追溯到更早日期。

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

当前 CN A-share production qfq 使用 HITHINK 同一 provider 的
`/api/a-share/prices/historical?adjust=forward`。该 provider-forward basis 的
adjustment/version 为 `CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2`，source contract 为
`CN_HITHINK_PROVIDER_FORWARD_QFQ_CONTRACT_V2`；它不是、也不声称等价于旧的
`CN_FORWARD_ADJUSTMENT_ENGINE_V1`。旧 raw + corporate-actions engine 仍保留为
`CN_RAW_CORPORATE_ACTIONS_QFQ_CONTRACT_V1`，供历史 fixtures、旧证据和 D1 V2 使用，
不得被新的 production route 静默改写。

provider-forward qfq provenance 至少记录：

- provider identity 与 endpoint `/api/a-share/prices/historical`；
- requested adjustment=`forward` 与 response `data.adjust=forward`；
- request start/end、acquired_at、asset_type、exact session date 与 session identity；
- `CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2` 与
  `CN_HITHINK_PROVIDER_FORWARD_QFQ_CONTRACT_V2`；
- `corporate_action_source=null` 与 `adjustment_chain_sha256=null`，不得伪造旧 chain。

ETF/fund 是明确的另一资产合同：
HITHINK metadata 必须识别为 `fund-etf`，随后使用同一 HITHINK 的
`/api/fund/market/historical`；该 endpoint 的 provider-documented OHLC 已为
forward-adjusted，记录 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` 与
`HITHINK_PROVIDER_FORWARD_ADJUSTED`，不得把它伪装成股票 raw+action chain，也不得回退其他
vendor。ETF contract 与本次股票迁移无关，保持不变。

若 active provider-forward response 的 `data.adjust`、OHLCV、requested range 或
adjustment provenance 无法证明，仍不换 vendor、不猜公式，直接将该 symbol 标为
`DATA_ADJUSTMENT_UNVERIFIED` 并隔离。旧 raw+corporate-actions basis 的
`HITHINK_CORPORATE_ACTIONS_NOT_READY` 只适用于显式 legacy/D1 V2 contract，不改变当前
production provider-forward route。

## Symbol-level isolation

production data plane 的 symbol 状态为：

`DATA_OK`、`DATA_MISSING`、`DATA_STALE`、`DATA_INVALID`、
`DATA_ADJUSTMENT_UNVERIFIED`、`PROVIDER_SYMBOL_ERROR`。

这些状态都只产生 `DATA_UNAVAILABLE_FOR_DECISION:<status>`（或等价的
`DECISION_BLOCKED_DATA_UNAVAILABLE`），不产生 `NO_SIGNAL`，也不阻断其他 symbol。
formal strategy pool、active/position symbols 和 dynamic Candidate 分别记录状态；
Candidate deep-history 或 discovery 局部失败只撤销对应 Candidate 的当日资格，不能
让已有正式池停止。Candidate component failure is reported independently as
`CANDIDATE_STATUS=UNAVAILABLE`; when formal rows remain usable, the scheduled report is
`RUN_STATUS=COMPLETED`, `DATA_STATUS=PARTIAL`, not `NO_SIGNAL`. Provider-global HITHINK
auth/schema/outage remains `PROVIDER_GLOBAL_FAILURE`.

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

## D1 V2/V3 boundary

`SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 保存 attempted universe、usable/missing/invalid
symbols、per-symbol source status、provider identity、adjustment engine version、exact
session identity 与 per-symbol provenance。CN Candidate seed 的 index membership 与
current-only snapshot timestamp 也进入 universe snapshot。局部 symbol failure 可以在
session identity、provider contract、raw prefix 和 snapshot integrity 有效时提交 formal
research session；缺失 symbol 永远写作 `DATA_MISSING` / `DATA_INVALID`，不得写成
`NO_SIGNAL`。若整个 attempted universe snapshot 无法形成，则 V2 不得 formal commit；
若 attempted universe 已知而仅部分 symbol 失败，则保留 symbol-level partial evidence。

旧 V1 activation 不被覆盖。当前受控 VPS 核对结果为 CN/US formal session count `0/0`，
未发现 formal D1 evidence，已记录 `D1_SINGLE_SOURCE_MIGRATION_PRE_OUTCOME_CONFIRMED`。
migration gate 在每次 natural collector 前检查 durable
store verification 和 CN/US formal session count：formal evidence 非零时直接返回
`D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE`；V1 activation 返回
`D1_SOURCE_MIGRATION_PENDING`。新的 V2 immutable activation epoch 必须在真实 VPS
session count 核对、source contract 验证和用户最终批准后创建，首个 eligible session
之前不 backfill migration window。V1 继续固定在
`system/activation/{CN,US}.json`；V2 只能写入
`system/activation_epochs/{CN,US}/SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2.json`，提交时
按 snapshot source contract 精确绑定版本，不读取 `current`/`latest` fallback。

`SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 的 raw/QFQ basis 保持 immutable：CN 使用
`CN_RAW_CORPORATE_ACTIONS_QFQ_CONTRACT_V1`。本 PR 仅使
`SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1` code-ready；其 activation epoch
路径为 `system/activation_epochs/CN/SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1.json`，
但本 PR 不创建真实 activation、不运行 natural collector、不回填 migration window。

## Production acceptance boundary

本分支已完成离线和真实 acceptance：

- CN 最新已完成 session `2026-09-28`：`600519.SH`（沪 A）、`000001.SZ`（深 A）、
  `300750.SZ`（创业板）、`688008.SH`（科创板）、`512400.SH` 与 `159866.SZ`（ETF）均以
  HITHINK 返回 exact-T、严格递增 OHLCV；ETF 命中既有 HITHINK fund endpoint。股票
  provider-forward route 已对原 33 个 `HITHINK_CORPORATE_ACTIONS_NOT_READY` 标的实现
  33/33 usable，并对 8 个 controls 完成 exact-T/session/volume/OHLCV 验收。
  `600519.SH`（2026-06-26 ex-date）与 `000001.SZ`（2026-09-24 ex-date）的 end=T 与
  跨 ex-date end 请求在 T 及以前 bars 完全一致，未观察 future-action leakage。
- 旧 action dataset 返回 `3002` 的 fail-closed 语义与旧 engine 仍保留，但不再是当前
  production CN A-share qfq route；旧 D1 V2/历史 evidence 不被 provider-forward 数据覆盖。
- US `YAHOO_CHART` 使用 exact XNYS session `2026-09-28`；raw OHLCV 与 qfq `adjclose`
  provenance 均到 T，单个无效 symbol 只产生 symbol error，transport/schema/outage 保持
  provider-global 边界。未引入第二 US provider。
- 1、50、300 个 symbol-level failures、all-symbol unavailable、HITHINK auth/schema
  global failure、Yahoo global failure 与 scheduled `RUN_STATUS=COMPLETED` +
  `DATA_STATUS=PARTIAL` exit=0 均有语义测试；`DATA_MISSING` 与
  `DATA_ADJUSTMENT_UNVERIFIED` 不映射为 `NO_SIGNAL`。

因此当前合同状态为 `CN_QFQ_PROVIDER_FORWARD_MIGRATION_MERGED_TO_MAIN`。这不表示真实
D1 activation 已创建或 natural production 已验收：新 activation 仍只 code-ready，不创建
immutable record；merge 后首个自然 CN session 必须单独完成 acceptance，历史手动运行不计入
自然 acceptance。
