# SECTOR_CANDIDATE_UNIVERSE_V1 — Feasibility Audit and Runtime Decision

状态：`PR_FULLY_READY_FOR_SOL_REVIEW`

本审计已由原来的“等待方案 B/C provider 决策”更新为 Sol 已批准的 bounded V1
contract。V1 不是全市场 universe，也不是 security master；它只形成一个按 sector /
industry 分散、低交易摩擦且资金可负担的候选池，随后交给现有 Strategy Engine。

## 正式数据源决定

### CN seed

- `HS300 ∪ CSI500`。
- BaoStock endpoints：`query_hs300_stocks`、`query_zz500_stocks`、
  `query_stock_basic`、`query_stock_industry`。
- 不构建全 A 股 security master，不引入 CN commercial provider。
- 实际 BaoStock 0.9.3 contract 已验证：
  - `query_hs300_stocks(date='')` / `query_zz500_stocks(date='')` 返回
    `updateDate, code, code_name`；
  - `query_stock_basic(code='', code_name='')` 返回
    `code, code_name, ipoDate, outDate, type, status`，不接受 `fields=`；
  - `query_stock_industry(code='', date='')` 返回
    `updateDate, code, code_name, industry, industryClassification`。
- 真实 adapter smoke 在 2026-09-06 使用 `as_of=2026-09-04` 完成：union=`800`
  securities，`metadata_ok=800`，`sector_present=800`。四个 endpoint 的单次
  全量查询是 bounded read-only 操作，运行时间受 BaoStock 服务端响应影响；本次
  全量 adapter smoke 约 90 秒内完成，未写任何 production state。

### US seed

- iShares Russell 1000 ETF (`IWB`) 官方公开 holdings 下载：
  `https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv`。
- 使用官方 CSV 的 ticker、name、sector、asset class、price、exchange、currency。
- 实际 CSV contract：9 行 metadata/preamble；`Fund Holdings as of`；随后字段表
  包含 `Ticker, Name, Sector, Asset Class, Price, Exchange, Currency`。
- 当前官方 adapter smoke：`source_date=2026-09-03`、`1018` Equity rows、
  所有 rows 有 sector，currency=`USD`。旧的 `.ajax?fileType=csv` URL 在机器读取时
  返回 HTML 外壳，因此没有被当作 CSV contract；没有换 provider。
- 不在 V1 构建 SEC/Nasdaq 全量 security master，不引入 Finnhub 或其他 commercial
  provider。

## Selector contract

```text
weekly seed refresh
→ security / sector normalization
→ affordability gate
→ liquidity ranking
→ history / data-quality eligibility
→ sector-aware candidate universe
```

- CN：documented board rule 计算 minimum executable quantity；`<=10,000 CNY`
  preferred，`10,000<notional<=20,000 CNY` retained/lower priority，`>20,000 CNY`
  excluded；unsupported/ambiguous board rule fail closed。SSE STAR 使用 200 股，
  不把所有 A 股写死为 100 股；main board 与 ChiNext 使用其各自官方证据。
- US：candidate stage 一股 notional `>1,000 USD` excluded；allocation stage 的
  single new strategy position hard cap=`1,000 USD` 另行验证。
- History：至少 60 根可见日线，禁止 future bar，最近 bar 超过 7 个日历日则 stale
  excluded；成交额优先，缺失时用 `close × volume`。输出 20D/60D average traded
  notional 作为明确 proxy，不新增跨市场绝对 liquidity threshold。
- Ranking：sector 内按 affordability priority、20D notional、60D notional、symbol
  做 deterministic ranking；`TOP_N_PER_SECTOR=20` 是集中可调常量，不进入 Strategy
  Engine protocol。该层没有 alpha、RSI/MACD/factor score、setup、decision 或
  `ENTRY_ALLOWED` 字段。
- Output：`included`、sector、rank、affordability tier、minimum quantity/notional、
  20D/60D liquidity metrics、history freshness、inclusion reason、exclusion reason。
  只返回 internal rows/fixture/artifact，不写真实 Google Sheets。

## 已完成实现边界

- `trading/candidate_universe.py`：frozen dataclass domain model、board rule、
  affordability、history/data-quality gate、20D/60D proxy、sector Top-N selector。
- `trading/candidate_universe_sources.py`：BaoStock CN bounded adapter、官方 IWB
  CSV parser/adapter。
- `tests/test_candidate_universe.py`：10 个 focused tests，覆盖 affordability tiers、
  board-specific quantity、US price gate、sector concentration、history gate、
  no-`ENTRY_ALLOWED` invariant、两个 source parser contracts。
- 未修改 `providers.py` 的生产回退链，未添加数据库、缓存、registry、commercial
  provider、broker/order、production state write、SETUP_03/04 或新回测 phase。

## 审计结论

原“需要方案 B/C provider 决策”的 feasibility blocker 已正式关闭。当前实现继续
保持 bounded、read-only、fail-closed；focused/full verification 与本地 integrity checks
已通过，implementation PR #71 保持 open，最终 PR tip/exact-head CI 以 GitHub 实时核验
为准，剩余工作仅为 Sol review。若后续真实 endpoint contract 改变，必须停在
`READY_FOR_DECISION_DATA_SOURCE_RUNTIME_BLOCKER`，不能自行扩展为全市场 source。

官方 board evidence：

- SSE main-board order-size reference：<https://english.sse.com.cn/news/newsrelease/c/5725303.shtml>
- SSE STAR trading reference：<https://big5.sse.com.cn/site/cht/www.sse.com.cn/star/en/gettingstarted/features/trading/>
- SZSE main-board rules：<https://www.szse.cn/English/rules/siteRule/P020181124401737559498.pdf>
- SZSE ChiNext special trading rules：<https://www.szse.cn/English/rules/siteRule/P020200811392728112984.pdf>
