<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->
# SETUP_03 Development Strategy Decision Capsule v3

状态：`VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`。本报告执行已冻结的 qualification matrix 与 lexicographic rule；不写入 production parameter。

## Immutable bindings

- Capsule file：`C:/Users/soush/Documents/ChatGPT/交易系统开发/stock-data-pipeline/research/development/development_strategy_decision_capsule_v3.json`
- Capsule SHA-256：`sha256:3fa511fa43b146fae9d1a17799b1ae17ce44ba4915ec4813d7120e53eef5b24c`
- Universe：`sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046`
- Dataset manifest：`sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`
- Aggregate dataset：`sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356`
- Replay input：`sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18`
- Coverage：CN 20 / 40,873 bars；US 20 / 43,411 bars；ALL 40 / 84,284 bars
- Provider split：CN `BAOSTOCK_DEVELOPMENT_QFQ`；US `YFINANCE_DEVELOPMENT_HISTORICAL`
- Formal universe overlap：`[]`

## True legacy-main parity

- Baseline：`40a3e5f980bf82a85717748ae106847793d1469f`
- Cells / bars / events compared：280 / 589988 / 3120
- `LEGACY_MAIN_PARITY_MISMATCHES`：`0`
- Legacy vs shared current path mismatches：`0`
- Legacy vs precomputed current path mismatches：`0`
- Comparison includes every bar Setup/state/diagnostic, every terminal event/date, and Decision action/diagnostics/deterministic fields.

## Derived market session dates

- `market_session_dates` is the sorted union of all valid local `Quote.trade_date` values in the frozen v2 replay input; no live calendar/provider was used.
- `CN`: 2343 sessions, `2017-01-03` through `2026-08-26`.
- `US`: 2425 sessions, `2017-01-03` through `2026-08-26`.

## Frozen qualification matrix

- Protocol: `SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US` / `sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0`
- Every row below is one candidate × market × frozen threshold observation. `trading_day_drift` is the only qualification drift field; calendar-day drift is descriptive only.

| candidate | market | scope | adjacent pair | threshold | observed | operator | frozen threshold | margin | status |
|---:|---|---|---|---|---:|:---:|---:|---:|---|
| 3.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 58 | `>=` | 8 | +50.00 | `PASS` |
| 3.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 17.24% | `<=` | 25.00% | +7.76% | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 64.29% | `>=` | 60.00% | +4.29% | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 93.10% | `>=` | 80.00% | +13.10% | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 7.00 | `<=` | 5.00 | -2.00 | `FAIL` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 8.60 | `<=` | 15.00 | +6.40 | `PASS` |
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 37.93% | `<=` | 50.00% | +12.07% | `PASS` |
| 3.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 91 | `>=` | 8 | +83.00 | `PASS` |
| 3.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 13.19% | `<=` | 25.00% | +11.81% | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 67.77% | `>=` | 60.00% | +7.77% | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 90.11% | `>=` | 80.00% | +10.11% | `PASS` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 10.00 | `<=` | 5.00 | -5.00 | `FAIL` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.80 | `<=` | 15.00 | -4.80 | `FAIL` |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 23.08% | `<=` | 50.00% | +26.92% | `PASS` |
| 4.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 80 | `>=` | 8 | +72.00 | `PASS` |
| 4.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 12.50% | `<=` | 25.00% | +12.50% | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 64.29% | `>=` | 60.00% | +4.29% | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 93.10% | `>=` | 80.00% | +13.10% | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 7.00 | `<=` | 5.00 | -2.00 | `FAIL` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 8.60 | `<=` | 15.00 | +6.40 | `PASS` |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 37.93% | `<=` | 50.00% | +12.07% | `PASS` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 69.81% | `>=` | 60.00% | +9.81% | `PASS` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 92.50% | `>=` | 80.00% | +12.50% | `PASS` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 9.50 | `<=` | 5.00 | -4.50 | `FAIL` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 456.50 | `<=` | 15.00 | -441.50 | `FAIL` |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 25.00% | `<=` | 50.00% | +25.00% | `PASS` |
| 4.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 112 | `>=` | 8 | +104.00 | `PASS` |
| 4.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 11.61% | `<=` | 25.00% | +13.39% | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_jaccard` | 67.77% | `>=` | 60.00% | +7.77% | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_retention` | 90.11% | `>=` | 80.00% | +10.11% | `PASS` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 10.00 | `<=` | 5.00 | -5.00 | `FAIL` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.80 | `<=` | 15.00 | -4.80 | `FAIL` |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `adjacent_confirmed_rate_relative_increase` | 23.08% | `<=` | 50.00% | +26.92% | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 74.31% | `>=` | 60.00% | +14.31% | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 95.54% | `>=` | 80.00% | +15.54% | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 5.00 | `<=` | 5.00 | +0.00 | `PASS` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 279.60 | `<=` | 15.00 | -264.60 | `FAIL` |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 24.11% | `<=` | 50.00% | +25.89% | `PASS` |
| 5.0% | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 100 | `>=` | 8 | +92.00 | `PASS` |
| 5.0% | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 13.00% | `<=` | 25.00% | +12.00% | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 69.81% | `>=` | 60.00% | +9.81% | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 92.50% | `>=` | 80.00% | +12.50% | `PASS` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 9.50 | `<=` | 5.00 | -4.50 | `FAIL` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 456.50 | `<=` | 15.00 | -441.50 | `FAIL` |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 25.00% | `<=` | 50.00% | +25.00% | `PASS` |
| 5.0% | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 139 | `>=` | 8 | +131.00 | `PASS` |
| 5.0% | US | candidate | — | `maximum_symbol_confirmed_concentration` | 10.07% | `<=` | 25.00% | +14.93% | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_jaccard` | 74.31% | `>=` | 60.00% | +14.31% | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_retention` | 95.54% | `>=` | 80.00% | +15.54% | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 5.00 | `<=` | 5.00 | +0.00 | `PASS` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 279.60 | `<=` | 15.00 | -264.60 | `FAIL` |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `adjacent_confirmed_rate_relative_increase` | 24.11% | `<=` | 50.00% | +25.89% | `PASS` |

## Candidate qualification and frozen lexicographic result

| candidate | market | qualifies | failed threshold IDs |
|---:|---|---|---|
| 3.0% | CN | `False` | `matched_confirmed_event_date_drift_median` |
| 3.0% | US | `False` | `matched_confirmed_event_date_drift_median`, `matched_confirmed_event_date_drift_p90` |
| 4.0% | CN | `False` | `matched_confirmed_event_date_drift_median`, `matched_confirmed_event_date_drift_median`, `matched_confirmed_event_date_drift_p90` |
| 4.0% | US | `False` | `matched_confirmed_event_date_drift_median`, `matched_confirmed_event_date_drift_p90`, `matched_confirmed_event_date_drift_p90` |
| 5.0% | CN | `False` | `matched_confirmed_event_date_drift_median`, `matched_confirmed_event_date_drift_p90` |
| 5.0% | US | `False` | `matched_confirmed_event_date_drift_p90` |

- `qualified_candidates`: `[]`
- `lexicographic_candidate`: `null`
- `lexicographic_status`: `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`

## 3%→4% and 4%→5% drift evidence

| transition | market | matched pairs | calendar median/P90 | trading-day median/P90 | buckets 0–2/3–5/6–10/11–15/>15 |
|---|---|---:|---:|---:|---|
| 3.0%→4.0% | CN | 3 | 9.00 / 18.60 | 7.00 / 8.60 | 0/1/2/0/0 |
| 3.0%→4.0% | US | 9 | 15.00 / 32.00 | 10.00 / 19.80 | 0/2/3/3/1 |
| 4.0%→5.0% | CN | 6 | 13.00 / 686.50 | 9.50 / 456.50 | 0/2/1/1/2 |
| 4.0%→5.0% | US | 5 | 7.00 / 407.00 | 5.00 / 279.60 | 1/2/0/0/2 |

## Qualification failure breakdown

| candidate | market | scope | adjacent pair | frozen threshold | observed | operator | margin to threshold |
|---:|---|---|---|---|---:|:---:|---:|
| 3.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 7.00 | `<= 5.00` | -2.00 |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 10.00 | `<= 5.00` | -5.00 |
| 3.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.80 | `<= 15.00` | -4.80 |
| 4.0% | CN | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 7.00 | `<= 5.00` | -2.00 |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 9.50 | `<= 5.00` | -4.50 |
| 4.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 456.50 | `<= 15.00` | -441.50 |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_median` | 10.00 | `<= 5.00` | -5.00 |
| 4.0% | US | adjacent_pair | 3.0%→4.0% | `matched_confirmed_event_date_drift_p90` | 19.80 | `<= 15.00` | -4.80 |
| 4.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 279.60 | `<= 15.00` | -264.60 |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_median` | 9.50 | `<= 5.00` | -4.50 |
| 5.0% | CN | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 456.50 | `<= 15.00` | -441.50 |
| 5.0% | US | adjacent_pair | 4.0%→5.0% | `matched_confirmed_event_date_drift_p90` | 279.60 | `<= 15.00` | -264.60 |

## Extreme trading-day drift pairs (descriptive)

The following pairs are retained as evidence; none is deleted or re-matched.

### 3.0%→4.0% / CN

- matched pair count: `3`
- buckets (0–2 / 3–5 / 6–10 / 11–15 / >15): `0 / 1 / 2 / 0 / 0`

| symbol | old date | new date | trading-day distance | calendar-day distance |
|---|---|---|---:|---:|
| 000027.SZ | 2024-02-29 | 2024-02-08 | 9 | 21 |
| 601658.SH | 2025-07-02 | 2025-06-23 | 7 | 9 |
| 601658.SH | 2024-05-10 | 2024-05-17 | 5 | 7 |

### 3.0%→4.0% / US

- matched pair count: `9`
- buckets (0–2 / 3–5 / 6–10 / 11–15 / >15): `0 / 2 / 3 / 3 / 1`

| symbol | old date | new date | trading-day distance | calendar-day distance |
|---|---|---|---:|---:|
| ADP | 2019-11-12 | 2020-01-15 | 43 | 64 |
| ADP | 2023-07-10 | 2023-06-16 | 14 | 24 |
| WTW | 2019-11-25 | 2019-12-13 | 13 | 18 |
| KMI | 2026-01-21 | 2026-01-05 | 11 | 16 |
| SPSC | 2022-11-30 | 2022-11-15 | 10 | 15 |
| AMD | 2019-06-13 | 2019-06-04 | 7 | 9 |
| SPSC | 2019-11-05 | 2019-10-25 | 7 | 11 |
| INTU | 2023-07-13 | 2023-07-10 | 3 | 3 |
| TTWO | 2024-08-22 | 2024-08-27 | 3 | 5 |

### 4.0%→5.0% / CN

- matched pair count: `6`
- buckets (0–2 / 3–5 / 6–10 / 11–15 / >15): `0 / 2 / 1 / 1 / 2`

| symbol | old date | new date | trading-day distance | calendar-day distance |
|---|---|---|---:|---:|
| 000833.SZ | 2021-05-10 | 2024-10-15 | 832 | 1254 |
| 002204.SZ | 2021-08-11 | 2021-04-14 | 81 | 119 |
| 000963.SZ | 2022-01-14 | 2021-12-27 | 13 | 18 |
| 000021.SZ | 2020-07-15 | 2020-07-07 | 6 | 8 |
| 000027.SZ | 2018-08-31 | 2018-08-28 | 3 | 3 |
| 000415.SZ | 2025-12-22 | 2025-12-17 | 3 | 5 |

### 4.0%→5.0% / US

- matched pair count: `5`
- buckets (0–2 / 3–5 / 6–10 / 11–15 / >15): `1 / 2 / 0 / 0 / 2`

| symbol | old date | new date | trading-day distance | calendar-day distance |
|---|---|---|---:|---:|
| TTWO | 2024-08-27 | 2023-02-03 | 392 | 571 |
| NVDA | 2026-02-25 | 2026-08-05 | 111 | 161 |
| ADP | 2018-04-27 | 2018-05-04 | 5 | 7 |
| SPSC | 2020-08-17 | 2020-08-10 | 5 | 7 |
| ROP | 2024-11-06 | 2024-11-07 | 1 | 1 |

## CN / US / ALL core numbers

| tolerance | market | symbols | bars | platform | platform/1000 | NONE | WATCH | ARMED | CONFIRMED state days | FAILED | CONFIRMED events | CONFIRMED/1000 | ENTRY_ALLOWED | ENTRY_ALLOWED/1000 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2.5% | CN | 20 | 40873 | 101 | 2.47 | 10052 | 708 | 1 | 12856 | 17256 | 46 | 1.13 | 1 | 0.02 |
| 2.5% | US | 20 | 43411 | 119 | 2.74 | 7346 | 843 | 0 | 21477 | 13745 | 72 | 1.66 | 2 | 0.05 |
| 2.5% | ALL | 40 | 84284 | 220 | 2.61 | 17398 | 1551 | 1 | 34333 | 31001 | 118 | 1.40 | 3 | 0.04 |
| 3.0% | CN | 20 | 40873 | 128 | 3.13 | 8843 | 840 | 1 | 14080 | 17109 | 58 | 1.42 | 2 | 0.05 |
| 3.0% | US | 20 | 43411 | 154 | 3.55 | 5616 | 1176 | 0 | 21392 | 15227 | 91 | 2.10 | 2 | 0.05 |
| 3.0% | ALL | 40 | 84284 | 282 | 3.35 | 14459 | 2016 | 1 | 35472 | 32336 | 149 | 1.77 | 4 | 0.05 |
| 4.0% | CN | 20 | 40873 | 173 | 4.23 | 6264 | 1433 | 0 | 16521 | 16655 | 80 | 1.96 | 5 | 0.12 |
| 4.0% | US | 20 | 43411 | 202 | 4.65 | 4934 | 1852 | 0 | 19364 | 17261 | 112 | 2.58 | 7 | 0.16 |
| 4.0% | ALL | 40 | 84284 | 375 | 4.45 | 11198 | 3285 | 0 | 35885 | 33916 | 192 | 2.28 | 12 | 0.14 |
| 5.0% | CN | 20 | 40873 | 217 | 5.31 | 4306 | 1968 | 1 | 16499 | 18099 | 100 | 2.45 | 5 | 0.12 |
| 5.0% | US | 20 | 43411 | 245 | 5.64 | 4511 | 2359 | 0 | 19966 | 16575 | 139 | 3.20 | 11 | 0.25 |
| 5.0% | ALL | 40 | 84284 | 462 | 5.48 | 8817 | 4327 | 1 | 36465 | 34674 | 239 | 2.84 | 16 | 0.19 |
| 5.5% | CN | 20 | 40873 | 240 | 5.87 | 3742 | 2432 | 3 | 16732 | 17964 | 110 | 2.69 | 7 | 0.17 |
| 5.5% | US | 20 | 43411 | 261 | 6.01 | 4507 | 2657 | 0 | 20166 | 16081 | 148 | 3.41 | 14 | 0.32 |
| 5.5% | ALL | 40 | 84284 | 501 | 5.94 | 8249 | 5089 | 3 | 36898 | 34045 | 258 | 3.06 | 21 | 0.25 |
| 7.5% | CN | 20 | 40873 | 296 | 7.24 | 3062 | 3601 | 3 | 16505 | 17702 | 136 | 3.33 | 15 | 0.37 |
| 7.5% | US | 20 | 43411 | 303 | 6.98 | 4109 | 3493 | 1 | 19021 | 16787 | 160 | 3.69 | 17 | 0.39 |
| 7.5% | ALL | 40 | 84284 | 599 | 7.11 | 7171 | 7094 | 4 | 35526 | 34489 | 296 | 3.51 | 32 | 0.38 |
| 10.0% | CN | 20 | 40873 | 351 | 8.59 | 2104 | 4884 | 4 | 15576 | 18305 | 164 | 4.01 | 19 | 0.46 |
| 10.0% | US | 20 | 43411 | 355 | 8.18 | 2955 | 4525 | 1 | 20735 | 15195 | 194 | 4.47 | 21 | 0.48 |
| 10.0% | ALL | 40 | 84284 | 706 | 8.38 | 5059 | 9409 | 5 | 36311 | 33500 | 358 | 4.25 | 40 | 0.47 |

## Adjacent tolerance stability

| transition | market | previous | current | retained | added | disappeared | Jaccard | nearest matched | drift median/P90 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2.5%→3.0% | CN | 46 | 58 | 45 | 13 | 1 | 76.27% | 1 | 5.0 / 5.0 trading days |
| 2.5%→3.0% | US | 72 | 91 | 64 | 27 | 8 | 64.65% | 7 | 8.0 / 19.4 trading days |
| 2.5%→3.0% | ALL | 118 | 149 | 109 | 40 | 9 | 68.99% | 8 | 7.0 / 17.8 trading days |
| 3.0%→4.0% | CN | 58 | 80 | 54 | 26 | 4 | 64.29% | 3 | 7.0 / 8.6 trading days |
| 3.0%→4.0% | US | 91 | 112 | 82 | 30 | 9 | 67.77% | 9 | 10.0 / 19.8 trading days |
| 3.0%→4.0% | ALL | 149 | 192 | 136 | 56 | 13 | 66.34% | 12 | 8.0 / 13.9 trading days |
| 4.0%→5.0% | CN | 80 | 100 | 74 | 26 | 6 | 69.81% | 6 | 9.5 / 456.5 trading days |
| 4.0%→5.0% | US | 112 | 139 | 107 | 32 | 5 | 74.31% | 5 | 5.0 / 279.6 trading days |
| 4.0%→5.0% | ALL | 192 | 239 | 181 | 58 | 11 | 72.40% | 11 | 6.0 / 392.0 trading days |
| 5.0%→5.5% | CN | 100 | 110 | 96 | 14 | 4 | 84.21% | 4 | 5.0 / 10.9 trading days |
| 5.0%→5.5% | US | 139 | 148 | 134 | 14 | 5 | 87.58% | 3 | 9.0 / 21.8 trading days |
| 5.0%→5.5% | ALL | 239 | 258 | 230 | 28 | 9 | 86.14% | 7 | 6.0 / 17.8 trading days |
| 5.5%→7.5% | CN | 110 | 136 | 99 | 37 | 11 | 67.35% | 11 | 7.0 / 1363.0 trading days |
| 5.5%→7.5% | US | 148 | 160 | 134 | 26 | 14 | 77.01% | 12 | 8.5 / 833.3 trading days |
| 5.5%→7.5% | ALL | 258 | 296 | 233 | 63 | 25 | 72.59% | 23 | 8.0 / 1076.0 trading days |
| 7.5%→10.0% | CN | 136 | 164 | 124 | 40 | 12 | 70.45% | 10 | 8.5 / 55.2 trading days |
| 7.5%→10.0% | US | 160 | 194 | 152 | 42 | 8 | 75.25% | 8 | 15.5 / 177.3 trading days |
| 7.5%→10.0% | ALL | 296 | 358 | 276 | 82 | 20 | 73.02% | 18 | 9.0 / 158.7 trading days |

## Production-candidate boundary / concentration facts

- `3.0%` ALL: high span median/P90 `1.51%` / `2.63%`; low span `1.27%` / `2.66%`; platform width `8.52%` / `14.36%`; zero-event symbols `5`; 1–2-event symbols `9`; max symbol share `8.05%`; top-3 share `21.48%`.
- `4.0%` ALL: high span median/P90 `1.82%` / `3.38%`; low span `1.69%` / `3.51%`; platform width `9.78%` / `15.13%`; zero-event symbols `3`; 1–2-event symbols `8`; max symbol share `6.77%`; top-3 share `17.71%`.
- `5.0%` ALL: high span median/P90 `2.15%` / `4.42%`; low span `2.07%` / `4.25%`; platform width `10.55%` / `16.22%`; zero-event symbols `3`; 1–2-event symbols `5`; max symbol share `5.86%`; top-3 share `16.74%`.

压力边界 ALL（仅描述扩张）：
- `2.5%`：platform `220`（`2.61/1000`），CONFIRMED `118`（`1.40/1000`），high span median/P90 `1.24%`/`2.19%`，low span `1.00%`/`2.19%`，width `7.95%`/`14.38%`。
- `5.5%`：platform `501`（`5.94/1000`），CONFIRMED `258`（`3.06/1000`），high span median/P90 `2.39%`/`4.83%`，low span `2.16%`/`4.66%`，width `11.22%`/`17.18%`。
- `7.5%`：platform `599`（`7.11/1000`），CONFIRMED `296`（`3.51/1000`），high span median/P90 `2.72%`/`6.10%`，low span `2.71%`/`5.96%`，width `12.63%`/`19.40%`。
- `10.0%`：platform `706`（`8.38/1000`），CONFIRMED `358`（`4.25/1000`），high span median/P90 `3.07%`/`7.70%`，low span `3.21%`/`8.09%`，width `14.05%`/`22.58%`。

## Cross-market comparison

- `3.0%` CN/US: event-density ratio `0.677`; platform-density ratio `0.883`; zero-event-symbol difference `1`; max-share difference `4.05%`.
- `4.0%` CN/US: event-density ratio `0.759`; platform-density ratio `0.910`; zero-event-symbol difference `-1`; max-share difference `0.89%`.
- `5.0%` CN/US: event-density ratio `0.764`; platform-density ratio `0.941`; zero-event-symbol difference `-1`; max-share difference `2.93%`.

## Mechanical flags

```json
{
  "ADJACENT_STABILITY_HIGH": true,
  "ADJACENT_STABILITY_LOW": true,
  "CONCENTRATION_HIGH": true,
  "CROSS_MARKET_DIVERGENCE": true,
  "NO_CLEAR_STRUCTURAL_PLATEAU": true,
  "SPARSE_AT_3": true,
  "STRUCTURAL_EXPANSION_4_TO_5": true
}
```

Definitions and raw observations are in the tracked JSON capsule.

## Data quality and boundaries

- Frozen v2 provider split: BaoStock qfq for CN and yfinance historical for US.
- Immutable OHLC audit: 4 numeric-adjustment-rounding-only bars; 26 material provider/raw-OHLC bars.
- This capsule contains no returns, MFE, MAE, P&L, winrate, or final OOS metrics.
- No dataset/universe change, re-fetch, provider/symbol substitution, formal validation, strategy change, PR creation, or merge was performed.

`VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`
