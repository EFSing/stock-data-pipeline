<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->
# SETUP_03 Phase 5J-v3 第二套 independent development holdout 报告

> 本报告只提供 structure-only stability evidence；不构成 formal validation、Final OOS 或 production parameter freeze。

## 固定身份与 hashes

- protocol: `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1` / `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`
- universe: `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2` / `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`
- symbol-list: `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`
- dataset: `SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1` / `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`
- normalized aggregate: `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`
- replay input: `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`
- capsule file SHA-256: `sha256:f8038643acc009bae41b1b9e72616e6e2b2da0c653efb4e8ca055bff4d04c271`

## 排除证明与 coverage/QC

- A1 formal 120 intersection: `[]`
- development v1 40 intersection: `[]`
- valid symbols/bars: `40` / `86305`
- CN provider: `BAOSTOCK_DEVELOPMENT_QFQ` / `query_history_k_data_plus` / `frequency=d` / `adjustflag=2`
- US provider: `YFINANCE_DEVELOPMENT_HISTORICAL` / adjusted historical / `repair=False`
- missing dates are not filled; no interpolation, synthetic suspension bars, history splice, provider switching, OHLC mutation, or result-driven replacement.

## Candidate-level structure-only results

| tolerance | market | symbols | bars | platform | CONFIRMED | CONFIRMED/1000 | ENTRY_ALLOWED | max symbol share |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2.5% | CN | 20 | 41274 | 92 | 33 | 0.80 | 2 | 18.18% |
| 2.5% | US | 20 | 45031 | 107 | 59 | 1.31 | 0 | 13.56% |
| 2.5% | ALL | 40 | 86305 | 199 | 92 | 1.07 | 2 | 8.70% |
| 3.0% | CN | 20 | 41274 | 114 | 42 | 1.02 | 3 | 14.29% |
| 3.0% | US | 20 | 45031 | 129 | 70 | 1.55 | 1 | 12.86% |
| 3.0% | ALL | 40 | 86305 | 243 | 112 | 1.30 | 4 | 8.04% |
| 4.0% | CN | 20 | 41274 | 168 | 65 | 1.57 | 4 | 12.31% |
| 4.0% | US | 20 | 45031 | 179 | 107 | 2.38 | 3 | 11.21% |
| 4.0% | ALL | 40 | 86305 | 347 | 172 | 1.99 | 7 | 6.98% |
| 5.0% | CN | 20 | 41274 | 214 | 93 | 2.25 | 6 | 9.68% |
| 5.0% | US | 20 | 45031 | 227 | 129 | 2.86 | 7 | 9.30% |
| 5.0% | ALL | 40 | 86305 | 441 | 222 | 2.57 | 13 | 5.41% |
| 5.5% | CN | 20 | 41274 | 229 | 102 | 2.47 | 8 | 8.82% |
| 5.5% | US | 20 | 45031 | 253 | 147 | 3.26 | 9 | 10.20% |
| 5.5% | ALL | 40 | 86305 | 482 | 249 | 2.89 | 17 | 6.02% |
| 7.5% | CN | 20 | 41274 | 282 | 122 | 2.96 | 10 | 9.02% |
| 7.5% | US | 20 | 45031 | 317 | 182 | 4.04 | 18 | 8.79% |
| 7.5% | ALL | 40 | 86305 | 599 | 304 | 3.52 | 28 | 5.26% |
| 10.0% | CN | 20 | 41274 | 332 | 150 | 3.63 | 16 | 10.00% |
| 10.0% | US | 20 | 45031 | 377 | 207 | 4.60 | 24 | 9.18% |
| 10.0% | ALL | 40 | 86305 | 709 | 357 | 4.14 | 40 | 5.32% |

## 3%→4% / 4%→5% frozen v3 matching

| transition | market | exact retained | added | disappeared | matched | unmatched old/new | Jaccard | retention | matched drift median/P90 | buckets 0-2/3-5/6-10/11-15/>15 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 3.0%→4.0% | CN | 35 | 30 | 7 | 7 | 0/23 | 48.61% | 83.33% | 11.00/19.80 | 0/1/2/3/1 |
| 3.0%→4.0% | US | 66 | 41 | 4 | 4 | 0/37 | 59.46% | 94.29% | 4.50/12.30 | 1/1/1/1/0 |
| 3.0%→4.0% | ALL | 101 | 71 | 11 | 11 | 0/60 | 55.19% | 90.18% | 8.00/15.00 | 1/2/3/4/1 |
| 4.0%→5.0% | CN | 58 | 35 | 7 | 6 | 1/29 | 58.00% | 89.23% | 4.50/15.50 | 3/0/1/1/1 |
| 4.0%→5.0% | US | 100 | 29 | 7 | 6 | 1/23 | 73.53% | 93.46% | 5.00/12.50 | 1/2/1/2/0 |
| 4.0%→5.0% | ALL | 158 | 64 | 14 | 12 | 2/52 | 66.95% | 91.86% | 5.00/12.90 | 4/2/2/3/1 |

## Qualification matrix

- `qualified_candidates`: `[]`
- `lexicographic_candidate`: `None`
- status: `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`

| candidate | market | scope | pair | threshold | observed | frozen | margin | status |
|---:|---|---|---|---|---:|---:|---:|---|
| 3.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 42 | `>= 8.0` | 34 | `PASS` |
| 3.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.1429 | `<= 0.25` | 0.1071 | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 0.4861 | `>= 0.6` | -0.1139 | `FAIL` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 0.8333 | `>= 0.8` | 0.03333 | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 11 | `<= 5.0` | -6 | `FAIL` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.8 | `<= 15.0` | -4.8 | `FAIL` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 0.5476 | `<= 0.5` | -0.04762 | `FAIL` |
| 3.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 70 | `>= 8.0` | 62 | `PASS` |
| 3.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.1286 | `<= 0.25` | 0.1214 | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 0.5946 | `>= 0.6` | -0.005405 | `FAIL` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 0.9429 | `>= 0.8` | 0.1429 | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5.0` | 0.5 | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 12.3 | `<= 15.0` | 2.7 | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 0.5286 | `<= 0.5` | -0.02857 | `FAIL` |
| 4.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 65 | `>= 8.0` | 57 | `PASS` |
| 4.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.1231 | `<= 0.25` | 0.1269 | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 0.4861 | `>= 0.6` | -0.1139 | `FAIL` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 0.8333 | `>= 0.8` | 0.03333 | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 11 | `<= 5.0` | -6 | `FAIL` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.8 | `<= 15.0` | -4.8 | `FAIL` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 0.5476 | `<= 0.5` | -0.04762 | `FAIL` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 0.58 | `>= 0.6` | -0.02 | `FAIL` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 0.8923 | `>= 0.8` | 0.09231 | `PASS` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5.0` | 0.5 | `PASS` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 15.5 | `<= 15.0` | -0.5 | `FAIL` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 0.4308 | `<= 0.5` | 0.06923 | `PASS` |
| 4.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 107 | `>= 8.0` | 99 | `PASS` |
| 4.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.1121 | `<= 0.25` | 0.1379 | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 0.5946 | `>= 0.6` | -0.005405 | `FAIL` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 0.9429 | `>= 0.8` | 0.1429 | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5.0` | 0.5 | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 12.3 | `<= 15.0` | 2.7 | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 0.5286 | `<= 0.5` | -0.02857 | `FAIL` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 0.7353 | `>= 0.6` | 0.1353 | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 0.9346 | `>= 0.8` | 0.1346 | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 5 | `<= 5.0` | 0 | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 12.5 | `<= 15.0` | 2.5 | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 0.2056 | `<= 0.5` | 0.2944 | `PASS` |
| 5.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 93 | `>= 8.0` | 85 | `PASS` |
| 5.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.09677 | `<= 0.25` | 0.1532 | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 0.58 | `>= 0.6` | -0.02 | `FAIL` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 0.8923 | `>= 0.8` | 0.09231 | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5.0` | 0.5 | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 15.5 | `<= 15.0` | -0.5 | `FAIL` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 0.4308 | `<= 0.5` | 0.06923 | `PASS` |
| 5.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 129 | `>= 8.0` | 121 | `PASS` |
| 5.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.09302 | `<= 0.25` | 0.157 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 0.7353 | `>= 0.6` | 0.1353 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 0.9346 | `>= 0.8` | 0.1346 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 5 | `<= 5.0` | 0 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 12.5 | `<= 15.0` | 2.5 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 0.2056 | `<= 0.5` | 0.2944 | `PASS` |

## Parity and governance

- parity: `PASS`, cells `280`, bar comparisons `604135`, event comparisons `3008`, mismatches `0`
- protocol matching is maximum-cardinality, minimum-total-trading-session-distance, deterministic lexicographic tie-break, one-to-one and non-crossing; `>40` sessions remain unmatched.
- drift median/P90 use matched pairs only; exact retained, added, disappeared and unmatched identities remain fully reported.
- prohibited metrics accessed: returns=False, MFE=False, MAE=False, P&L=False, winrate=False, profit_factor=False, expectancy=False; Final OOS=False; formal Phase 5K-B1=False; IBKR=False.

`SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION`
