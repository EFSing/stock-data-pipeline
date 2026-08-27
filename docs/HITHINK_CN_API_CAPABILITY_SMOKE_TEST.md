# HiThink CN API capability/provenance smoke test

**Run:** 2026-08-27 18:16:12 Asia/Shanghai (rerun in standard and elevated execution contexts)
**Source identity:** `HITHINK-FINANCIAL-API-FUYAO` / 同花顺金融数据服务（HiThink Financial API）
**Base URL:** `https://fuyao.aicubes.cn`  
**API-key environment variable:** `HITHINK_FINANCE_API_KEY` (not visible to the smoke-test execution context; key material was not read or emitted)
**Research role:** candidate CN Research Data Provider only; not connected to the production Tencent/Sina quote path.

The endpoint and field contracts were taken from the provider's public documentation: [REST contract](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api.md), [metadata endpoints](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-meta.md), [prices and corporate actions](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-prices.md), [calendar](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-calendar.md), [index constituents](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-index.md), and [market dumps](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-market-dumps.md).

## Scope and method

- Seven bounded `GET` probes were made. No write endpoint was used.
- The market-dump response was not followed; no Parquet or OHLCV was downloaded.
- No formal Phase 5K symbol manifest or validation dataset was generated.
- No SETUP_03 output, `CONFIRMED` event, return/MFE/MAE/win-rate/P&L result, or final OOS was accessed.
- Exact response bytes were written locally under `artifacts/hithink_cn_capability_smoke_2026-08-27-keyed/` and hashed with SHA-256. The artifact directory remains ignored by Git; hashes below are the durable audit record.
- A boolean-only environment check found `HITHINK_FINANCE_API_KEY` absent from the runner's Process/User/Machine scopes. No value, length, or secret content was printed, logged, or committed.

## Results

All probes returned HTTP `200` with envelope `code=2003` and `data=null`. The provider contract defines `2003` as no permission or invalid key. Since no key was configured, the result is `AUTH_REQUIRED_OR_UNAUTHORIZED` for every probe. No source data timestamp or as-of value was observable because no successful `data` payload was returned.

| Capability | Actual endpoint | HTTP / API code | Returned fields | Raw response SHA-256 |
| --- | --- | --- | --- | --- |
| A 股股票代码列表 | `/api/meta/tickers/list?exchange=SH%2CSZ&asset_type=a-share&limit=1&offset=0` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:98a3d06b533ce6c704ca0d882e3de0e731c99e8e93d2b639f20541c584cafbc3` |
| CSI300 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000300.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:3158d39fa7f64261d14927c047652730690ec7f9541f7440e00e29b9df7b59a4` |
| CSI500 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000905.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:c001cc8f1779dc3ee0151335fd9879ada90e20dcdd8335241f8492c101fce6aa` |
| CSI1000 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000852.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:817df9fd358796f1d9aba5335a268e832a5d83254ccd01faeb2a858b857245d5` |
| 全市场历史日 K / market dump 签名端点 | `/api/dump/market-dumps/daily-k/download-url` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:f195e54e9e916baf68b167ea84a63246f2d4e88d1771e14b5e7e2dd9f6776a3a` |
| 公司行动 / 复权因子 | `/api/a-share/corporate-actions/adjustment-factors?thscode=600519.SH&from=2024-01-01&to=2024-12-31` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:cbc8f518c0285f78a7e32b8d67725160e9a82c8d0b8a63510fe2657e278ae336` |
| 交易日历 | `/api/a-share/calendar/trading-days` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:9a74499d7e13ef2740a9ed402d3a4752b4bbcbeacef1370636d5e91eaea66310` |

## Capability conclusion

| Requested capability | Current result | What is still required |
| --- | --- | --- |
| A 股股票代码列表 | `UNVERIFIED_AUTH_REQUIRED` | Configure a real HiThink API Key and rerun the bounded probe; record `data.item[]` fields and `data.timestamp`. |
| CSI300 / CSI500 / CSI1000 constituents | `UNVERIFIED_AUTH_REQUIRED` | Confirm all three return current constituent lists; record each response timestamp and the provider's current-only limitation. |
| Full-market historical daily K / dump | `UNVERIFIED_AUTH_REQUIRED` | Confirm entitlement to the signing endpoint; only after explicit approval may a later phase download the Parquet file. |
| Corporate actions / adjustment factors | `UNVERIFIED_AUTH_REQUIRED` | Confirm event fields and effective-date semantics; do not treat raw event stream as a precomputed daily factor. |
| Trading calendar | `UNVERIFIED_AUTH_REQUIRED` | Confirm the returned one-year A-share calendar and timestamp semantics. |

**Provisional decision:** HiThink Financial API remains a candidate CN Research Data Provider, but it is not yet proven usable for Phase 5K. The user reports that a key is configured, but this executor did not inherit it in either standard or elevated context; a fresh process/session with the user-level environment variable visible is required. The API Key must never be pasted into chat, committed, or written to this report.

**Current blocker:** this is an environment propagation issue. Because no key reached the runner, the observed `2003` cannot distinguish invalid/missing entitlement from a key configured outside this executor. Do not proceed to Phase 5K-A1 until a rerun returns HTTP 200 and `code=0` for the required capabilities.

**Historical constituent limitation:** the public contract describes the index constituent endpoint as returning current constituents and not a historical add/remove series. A later universe snapshot may therefore be formed on the actual retrieval date, but it must not be presented as a fabricated historical constituent snapshot.
