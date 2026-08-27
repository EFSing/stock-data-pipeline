# HiThink CN API capability/provenance smoke test

**Run:** 2026-08-27 17:52:18 Asia/Shanghai  
**Source identity:** `HITHINK-FINANCIAL-API-FUYAO` / 同花顺金融数据服务（HiThink Financial API）  
**Base URL:** `https://fuyao.aicubes.cn`  
**API-key environment variable:** `HITHINK_FINANCE_API_KEY` (not configured in this run)  
**Research role:** candidate CN Research Data Provider only; not connected to the production Tencent/Sina quote path.

The endpoint and field contracts were taken from the provider's public documentation: [REST contract](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api.md), [metadata endpoints](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-meta.md), [prices and corporate actions](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-prices.md), [calendar](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-calendar.md), [index constituents](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-index.md), and [market dumps](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-market-dumps.md).

## Scope and method

- Seven bounded `GET` probes were made. No write endpoint was used.
- The market-dump response was not followed; no Parquet or OHLCV was downloaded.
- No formal Phase 5K symbol manifest or validation dataset was generated.
- No SETUP_03 output, `CONFIRMED` event, return/MFE/MAE/win-rate/P&L result, or final OOS was accessed.
- Exact response bytes were written locally under `artifacts/hithink_cn_capability_smoke_2026-08-27/` and hashed with SHA-256. The artifact directory remains ignored by Git; hashes below are the durable audit record.

## Results

All probes returned HTTP `200` with envelope `code=2003` and `data=null`. The provider contract defines `2003` as no permission or invalid key. Since no key was configured, the result is `AUTH_REQUIRED_OR_UNAUTHORIZED` for every probe. No source data timestamp or as-of value was observable because no successful `data` payload was returned.

| Capability | Actual endpoint | HTTP / API code | Returned fields | Raw response SHA-256 |
| --- | --- | --- | --- | --- |
| A 股股票代码列表 | `/api/meta/tickers/list?exchange=SH%2CSZ&asset_type=a-share&limit=1&offset=0` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:7686412201b08eb7bcc80f7ca43430a50b7961c51e29512c83b89870649633ad` |
| CSI300 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000300.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:25f9285da8c0fb29713b2c4d236957bafb3fdb5c1ae520a5542c1c3fc2e25d0d` |
| CSI500 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000905.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:c46accc04fb3a4ea70f0d2eaa6d9593b327a5af50d816b569b02160271179f4e` |
| CSI1000 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000852.SH` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:f25b178add8a2a228143172512af8544e5ead120cc1dee5a00e80b4f0b2f6253` |
| 全市场历史日 K / market dump 签名端点 | `/api/dump/market-dumps/daily-k/download-url` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:7facb1f5eedf357a21ef62d0a6532304b6da16e1e2e5a1520f30d080cd33b187` |
| 公司行动 / 复权因子 | `/api/a-share/corporate-actions/adjustment-factors?thscode=600519.SH&from=2024-01-01&to=2024-12-31` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:278904b1b6d66076c2e857210e48273697e89558fa59e0d2c886a9ac8784dfa6` |
| 交易日历 | `/api/a-share/calendar/trading-days` | 200 / 2003 | `code`, `data`, `message`, `request_id` | `sha256:a6b1d80925be2c913010d1c04b60aee9769b89e221a374c40b0920078c8f07a6` |

## Capability conclusion

| Requested capability | Current result | What is still required |
| --- | --- | --- |
| A 股股票代码列表 | `UNVERIFIED_AUTH_REQUIRED` | Configure a real HiThink API Key and rerun the bounded probe; record `data.item[]` fields and `data.timestamp`. |
| CSI300 / CSI500 / CSI1000 constituents | `UNVERIFIED_AUTH_REQUIRED` | Confirm all three return current constituent lists; record each response timestamp and the provider's current-only limitation. |
| Full-market historical daily K / dump | `UNVERIFIED_AUTH_REQUIRED` | Confirm entitlement to the signing endpoint; only after explicit approval may a later phase download the Parquet file. |
| Corporate actions / adjustment factors | `UNVERIFIED_AUTH_REQUIRED` | Confirm event fields and effective-date semantics; do not treat raw event stream as a precomputed daily factor. |
| Trading calendar | `UNVERIFIED_AUTH_REQUIRED` | Confirm the returned one-year A-share calendar and timestamp semantics. |

**Provisional decision:** HiThink Financial API remains a candidate CN Research Data Provider, but it is not yet proven usable for Phase 5K. A real API Key and any required entitlement/authorization are needed. The API Key must be supplied through a user-level secret/environment variable and must never be committed or written to this report.

**Historical constituent limitation:** the public contract describes the index constituent endpoint as returning current constituents and not a historical add/remove series. A later universe snapshot may therefore be formed on the actual retrieval date, but it must not be presented as a fabricated historical constituent snapshot.
