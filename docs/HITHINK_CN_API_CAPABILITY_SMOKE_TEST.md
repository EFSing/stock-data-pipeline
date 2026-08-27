# HiThink CN API capability/provenance smoke test

**Run:** 2026-08-27 18:34:47 Asia/Shanghai (keyed rerun in network-enabled executor)
**Source identity:** `HITHINK-FINANCIAL-API-FUYAO` / 同花顺金融数据服务（HiThink Financial API）
**Base URL:** `https://fuyao.aicubes.cn`  
**Authentication:** `X-api-key` header sourced from `HITHINK_FINANCE_API_KEY`; only a boolean configured-state was recorded. Key material was not printed, logged, written, or committed.
**Research role:** candidate CN Research Data Provider only; production Tencent/Sina quote paths were not changed.

The endpoint and field contracts were taken from the provider's public documentation: [REST contract](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api.md), [metadata endpoints](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-meta.md), [prices and corporate actions](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-prices.md), [calendar](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-calendar.md), [index constituents](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/endpoints-index.md), and [market dumps](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/endpoints-market-dumps.md).

## Scope and method

- Seven bounded `GET` probes were made; all returned HTTP `200` and envelope `code=0`.
- The market-dump signing endpoint was called, but the returned signed URL was not followed; no Parquet/OHLCV was downloaded.
- No Phase 5K-A1 symbol manifest or validation dataset was generated.
- No SETUP_03 execution, signal/output artifact, final OOS, or frozen-rule modification was performed.
- Exact response bytes and SHA-256 hashes are under the ignored local directory `artifacts/hithink_cn_capability_smoke_2026-08-27-keyed-rerun-escalated/`. The signed URL itself is not reproduced here.
- The smoke-test report records only `api_key_configured=true`; it does not contain the API Key.

## Results

All seven probes returned the envelope fields `code`, `data`, `message`, and `request_id`. The source timestamps below are the provider-returned `data.timestamp` values in epoch milliseconds; the endpoint-specific meaning is not independently confirmed unless stated.

| Capability | Endpoint | HTTP / API code | Returned field summary | Data/source timestamp | As-of semantics | Raw response SHA-256 | Current permission / limitation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A 股股票代码列表 | `/api/meta/tickers/list?exchange=SH%2CSZ&asset_type=a-share&limit=1&offset=0` | 200 / 0 | `data.item[]`, `data.timestamp`; item fields: `asset_type`, `currency`, `exchange`, `name`, `thscode`, `ticker`; 1 item due bounded `limit=1` | `1787817615327` (`data.timestamp`) | Provider snapshot timestamp; endpoint-specific as-of semantics require confirmation | `sha256:dd7e0171461b5d5e4cc21751c05e8d6ea636a437f894ef7a54d28d7c48b72a00` | Authorized for this probe; full enumeration was intentionally not requested |
| CSI300 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000300.SH` | 200 / 0 | `data.item[]`, `data.timestamp`; item fields: `name`, `thscode`, `ticker`; 300 items | `1787826905040` (`data.timestamp`) | Current provider snapshot; historical membership series not observed | `sha256:22a68dcfa12546c2913f0c9d9d7579d85b7c07d41d245479de5534d459c6166f` | Real constituent list returned; current-only limitation |
| CSI500 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000905.SH` | 200 / 0 | `data.item[]`, `data.timestamp`; item fields: `name`, `thscode`, `ticker`; 500 items | `1787826905140` (`data.timestamp`) | Current provider snapshot; historical membership series not observed | `sha256:879f48b1916678880f18060d223cb3215a80c1438ffb97c6828d6d2f9014f932` | Real constituent list returned; current-only limitation |
| CSI1000 成分股 | `/api/a-share-index/constituents/ths-stock-list?thscode=000852.SH` | 200 / 0 | `data.item[]`, `data.timestamp`; item fields: `name`, `thscode`, `ticker`; 1000 items | `1787826905337` (`data.timestamp`) | Current provider snapshot; historical membership series not observed | `sha256:a80a74bf0320af362a418777d890bd592555490e5b6a53be94cf7af0bca7d8b9` | Real constituent list returned; current-only limitation |
| 全市场历史日 K / market dump 签名端点 | `/api/dump/market-dumps/daily-k/download-url` | 200 / 0 | `data.presigned_url`, `data.expires_in_seconds`, `data.presigned_url_expires_at` | No `data.timestamp`; signed URL metadata reported `expires_in_seconds=300` and an expiry field | Dataset as-of not observable from this response; only signed-URL expiry metadata was observed | `sha256:ee9dc62351d12956c3d3d3e1b92364b3209a5f20d906e399d9bbd129d761d775` | Signing/access capability authorized; download intentionally not followed |
| 公司行动 / 复权因子 | `/api/a-share/corporate-actions/adjustment-factors?thscode=600519.SH&from=2024-01-01&to=2024-12-31` | 200 / 0 | `data.item[]`, `data.thscode`, `data.ticker`; item fields: `dividend_per_share`, `ex_date_ms`, `per_share_bonus`, `ticker`; 2 items | No `data.timestamp`; observed `ex_date_ms` range corresponds to CN local dates 2024-06-19 through 2024-12-20 | Ex-date is explicit, but no precomputed adjustment-factor field or factor formula/effective-date convention was observed; provider confirmation required | `sha256:997e6a4366dc6f5af076ee8ecec236c19c42e6e8ba60afd2b06dc64c834fde6b` | Corporate-action event access authorized; adjustment-factor semantics remain unproven |
| 交易日历 | `/api/a-share/calendar/trading-days` | 200 / 0 | `data.item[]`, `data.timestamp`; item fields: `date`, `date_ms`; 243 items | `1787826906051` (`data.timestamp`); returned dates `20250827`–`20260827` | Provider snapshot timestamp; observed response is a one-year window | `sha256:458517d9053473f5a36552d4d57c21c597da057d23ff6f8ffccf09693d610fba` | Endpoint authorized, but 243 observed trading days do not cover the protocol target of about 6000 valid daily K bars per market; range/pagination remains unverified |

## Capability conclusion

- **A 股代码列表:** access proven for the bounded list probe; full list retrieval remains intentionally untested.
- **CSI300/500/1000:** all three returned real-sized current constituent lists (300/500/1000 items respectively), with current-snapshot timestamps; no historical membership series was observed.
- **全市场历史日 K dump:** signed download URL capability proven; no dataset download or Phase 5K acquisition was performed. The returned URL is short-lived (`300` seconds).
- **公司行动/复权因子:** corporate-action events and explicit `ex_date_ms` were returned, but the response did not expose a precomputed adjustment factor or an unambiguous adjustment formula/as-of convention.
- **交易日历:** access proven, but the observed one-year/243-day response is insufficient by itself for the registered CN validation coverage target of about 6000 valid daily K bars per market. A date-range/pagination contract still needs confirmation.

**Decision:** `HITHINK_CN_RESEARCH_DATA_PROVIDER_NOT_READY`

The provider passes the smoke-test transport/envelope criterion (`HTTP 200 + response code=0`) for all five capability groups, including genuine CSI300/500/1000 constituent responses and market-dump signing. It is not ready for Phase 5K because adjustment-factor semantics and validation-range calendar coverage remain unproven. Do not proceed to Phase 5K-A1 until those limitations are resolved in a separately authorized capability validation.
