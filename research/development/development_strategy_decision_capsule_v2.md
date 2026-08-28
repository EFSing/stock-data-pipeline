<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->
# SETUP_03 Development Strategy Decision Capsule v2

状态：`READY_FOR_SOL_STRATEGY_DECISION`。本报告只描述结构证据，不替研究设计者选择 tolerance。

## Immutable bindings

- Capsule file：`C:/Users/soush/Documents/ChatGPT/交易系统开发/stock-data-pipeline/research/development/development_strategy_decision_capsule_v2.json`
- Capsule SHA-256：`sha256:5a0726dccc0bbe273e32b05a71434bec8dde85859483cc9e3f1745d630b17458`
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
| 2.5%→3.0% | CN | 46 | 58 | 45 | 13 | 1 | 76.27% | 1 | 7.0 / 7.0 days |
| 2.5%→3.0% | US | 72 | 91 | 64 | 27 | 8 | 64.65% | 7 | 11.0 / 29.6 days |
| 2.5%→3.0% | ALL | 118 | 149 | 109 | 40 | 9 | 68.99% | 8 | 10.5 / 27.2 days |
| 3.0%→4.0% | CN | 58 | 80 | 54 | 26 | 4 | 64.29% | 3 | 9.0 / 18.6 days |
| 3.0%→4.0% | US | 91 | 112 | 82 | 30 | 9 | 67.77% | 9 | 15.0 / 32.0 days |
| 3.0%→4.0% | ALL | 149 | 192 | 136 | 56 | 13 | 66.34% | 12 | 13.0 / 23.7 days |
| 4.0%→5.0% | CN | 80 | 100 | 74 | 26 | 6 | 69.81% | 6 | 13.0 / 686.5 days |
| 4.0%→5.0% | US | 112 | 139 | 107 | 32 | 5 | 74.31% | 5 | 7.0 / 407.0 days |
| 4.0%→5.0% | ALL | 192 | 239 | 181 | 58 | 11 | 72.40% | 11 | 8.0 / 571.0 days |
| 5.0%→5.5% | CN | 100 | 110 | 96 | 14 | 4 | 84.21% | 4 | 8.5 / 15.2 days |
| 5.0%→5.5% | US | 139 | 148 | 134 | 14 | 5 | 87.58% | 3 | 13.0 / 30.6 days |
| 5.0%→5.5% | ALL | 239 | 258 | 230 | 28 | 9 | 86.14% | 7 | 11.0 / 24.2 days |
| 5.5%→7.5% | CN | 110 | 136 | 99 | 37 | 11 | 67.35% | 11 | 9.0 / 2050.0 days |
| 5.5%→7.5% | US | 148 | 160 | 134 | 26 | 14 | 77.01% | 12 | 13.0 / 1210.1 days |
| 5.5%→7.5% | ALL | 258 | 296 | 233 | 63 | 25 | 72.59% | 23 | 13.0 / 1573.0 days |
| 7.5%→10.0% | CN | 136 | 164 | 124 | 40 | 12 | 70.45% | 10 | 12.5 / 80.3 days |
| 7.5%→10.0% | US | 160 | 194 | 152 | 42 | 8 | 75.25% | 8 | 21.0 / 256.6 days |
| 7.5%→10.0% | ALL | 296 | 358 | 276 | 82 | 20 | 73.02% | 18 | 12.5 / 236.6 days |

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

`READY_FOR_SOL_STRATEGY_DECISION`
