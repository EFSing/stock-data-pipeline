<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->
# SETUP_03 ATR-normalized platform boundary structure-only qualification

> 本报告只验证预注册 ATR-normalized platform boundary family 的结构稳定性；不构成 formal validation、production parameter selection 或 Final OOS。

## 固定身份与边界

- protocol: `SETUP_03-ATR-BOUNDARY-STRUCTURAL-QUALIFICATION-2026-08-29-v1` / `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`
- universe: `SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1` / `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b` / CN20 + US20
- dataset: `SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1` / `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29` / `88075` bars
- normalized aggregate: `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`
- replay input aggregate/file: `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76` / `sha256:5d9ded8750efa7a78d9537c803db416d0b925276fea5823eaeedd1feb972d96b`
- base: `main@21c73977195682df576750648765b1b74d8824e2`
- family: Wilder ATR period 14, as-of `t`, symmetric high/low width divided by the same `ATR[t]`; thresholds are 1.0/1.5/2.0/2.5 ATR.
- unchanged: causal swing, strict as-of, lifecycle, breakout, confirmed/failed, Decision/execution contracts, terminal and rearm semantics.

## Candidate results

| threshold ATR | market | bars | platform detections | confirmed | terminals | event symbols | max share | HHI | zero-event pathology |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1.0 | CN | 42355 | 146 | 87 | 146 | 19 | 9.20% | 0.0635 | False |
| 1.0 | US | 45720 | 130 | 77 | 130 | 20 | 11.69% | 0.0626 | False |
| 1.5 | CN | 42355 | 246 | 135 | 246 | 19 | 10.37% | 0.0606 | False |
| 1.5 | US | 45720 | 218 | 130 | 217 | 20 | 8.46% | 0.0570 | False |
| 2.0 | CN | 42355 | 303 | 163 | 303 | 19 | 8.59% | 0.0570 | False |
| 2.0 | US | 45720 | 296 | 166 | 293 | 20 | 7.83% | 0.0548 | False |
| 2.5 | CN | 42355 | 338 | 177 | 337 | 19 | 7.91% | 0.0560 | False |
| 2.5 | US | 45720 | 350 | 194 | 347 | 20 | 7.73% | 0.0548 | False |

## Adjacent event and lifecycle stability

| pair | market | exact Jaccard | retention | added rate | disappeared rate | drift median/P90 | lifecycle divergence |
|---|---|---:|---:|---:|---:|---:|---:|
| 1.0→1.5 | CN | 45.10% | 79.31% | 48.89% | 20.69% | 4.00/14.20 | 94.31% |
| 1.0→1.5 | US | 52.21% | 92.21% | 45.38% | 7.79% | 6.50/12.00 | 88.02% |
| 1.5→2.0 | CN | 66.48% | 88.15% | 26.99% | 11.85% | 5.50/27.90 | 79.87% |
| 1.5→2.0 | US | 64.44% | 89.23% | 30.12% | 10.77% | 2.50/12.40 | 77.82% |
| 2.0→2.5 | CN | 78.95% | 92.02% | 15.25% | 7.98% | 4.00/5.40 | 62.91% |
| 2.0→2.5 | US | 73.91% | 92.17% | 21.13% | 7.83% | 4.50/11.90 | 79.25% |

## Qualification matrix

- qualified candidates: `[]`
- selected research candidate (not production): `None`
- status: `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`
- next: `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`

| candidate | market | scope | pair | criterion | observed | frozen | status |
|---:|---|---|---|---|---:|---|---|
| 1.0 | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 87 | `>= 8` | `PASS` |
| 1.0 | CN | candidate | — | `minimum_event_symbols_per_market_candidate` | 19 | `>= 8` | `PASS` |
| 1.0 | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.09195402298850575 | `<= 0.25` | `PASS` |
| 1.0 | CN | candidate | — | `maximum_symbol_confirmed_hhi` | 0.06354868542740125 | `<= 0.2` | `PASS` |
| 1.0 | CN | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_jaccard` | 0.45098039215686275 | `>= 0.6` | `FAIL` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_retention` | 0.7931034482758621 | `>= 0.8` | `FAIL` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `added_event_rate` | 0.4888888888888889 | `<= 0.5` | `PASS` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `disappeared_event_rate` | 0.20689655172413793 | `<= 0.5` | `PASS` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_median` | 4 | `<= 5` | `PASS` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_p90` | 14.199999999999998 | `<= 15` | `PASS` |
| 1.0 | CN | adjacent_pair | 1.0→1.5 | `lifecycle_divergence_rate` | 0.943089430894309 | `<= 0.5` | `FAIL` |
| 1.0 | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 77 | `>= 8` | `PASS` |
| 1.0 | US | candidate | — | `minimum_event_symbols_per_market_candidate` | 20 | `>= 8` | `PASS` |
| 1.0 | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.11688311688311688 | `<= 0.25` | `PASS` |
| 1.0 | US | candidate | — | `maximum_symbol_confirmed_hhi` | 0.06257378984651712 | `<= 0.2` | `PASS` |
| 1.0 | US | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_jaccard` | 0.5220588235294118 | `>= 0.6` | `FAIL` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_retention` | 0.922077922077922 | `>= 0.8` | `PASS` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `added_event_rate` | 0.45384615384615384 | `<= 0.5` | `PASS` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `disappeared_event_rate` | 0.07792207792207792 | `<= 0.5` | `PASS` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_median` | 6.5 | `<= 5` | `FAIL` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_p90` | 12.0 | `<= 15` | `PASS` |
| 1.0 | US | adjacent_pair | 1.0→1.5 | `lifecycle_divergence_rate` | 0.880184331797235 | `<= 0.5` | `FAIL` |
| 1.5 | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 135 | `>= 8` | `PASS` |
| 1.5 | CN | candidate | — | `minimum_event_symbols_per_market_candidate` | 19 | `>= 8` | `PASS` |
| 1.5 | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.1037037037037037 | `<= 0.25` | `PASS` |
| 1.5 | CN | candidate | — | `maximum_symbol_confirmed_hhi` | 0.06063100137174211 | `<= 0.2` | `PASS` |
| 1.5 | CN | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_jaccard` | 0.45098039215686275 | `>= 0.6` | `FAIL` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_retention` | 0.7931034482758621 | `>= 0.8` | `FAIL` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `added_event_rate` | 0.4888888888888889 | `<= 0.5` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `disappeared_event_rate` | 0.20689655172413793 | `<= 0.5` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_median` | 4 | `<= 5` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_p90` | 14.199999999999998 | `<= 15` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.0→1.5 | `lifecycle_divergence_rate` | 0.943089430894309 | `<= 0.5` | `FAIL` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_jaccard` | 0.664804469273743 | `>= 0.6` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_retention` | 0.8814814814814815 | `>= 0.8` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `added_event_rate` | 0.26993865030674846 | `<= 0.5` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `disappeared_event_rate` | 0.11851851851851852 | `<= 0.5` | `PASS` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_median` | 5.5 | `<= 5` | `FAIL` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_p90` | 27.900000000000002 | `<= 15` | `FAIL` |
| 1.5 | CN | adjacent_pair | 1.5→2.0 | `lifecycle_divergence_rate` | 0.7986798679867987 | `<= 0.5` | `FAIL` |
| 1.5 | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 130 | `>= 8` | `PASS` |
| 1.5 | US | candidate | — | `minimum_event_symbols_per_market_candidate` | 20 | `>= 8` | `PASS` |
| 1.5 | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.08461538461538462 | `<= 0.25` | `PASS` |
| 1.5 | US | candidate | — | `maximum_symbol_confirmed_hhi` | 0.057041420118343206 | `<= 0.2` | `PASS` |
| 1.5 | US | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_jaccard` | 0.5220588235294118 | `>= 0.6` | `FAIL` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `adjacent_confirmed_retention` | 0.922077922077922 | `>= 0.8` | `PASS` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `added_event_rate` | 0.45384615384615384 | `<= 0.5` | `PASS` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `disappeared_event_rate` | 0.07792207792207792 | `<= 0.5` | `PASS` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_median` | 6.5 | `<= 5` | `FAIL` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `matched_confirmed_event_date_drift_p90` | 12.0 | `<= 15` | `PASS` |
| 1.5 | US | adjacent_pair | 1.0→1.5 | `lifecycle_divergence_rate` | 0.880184331797235 | `<= 0.5` | `FAIL` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_jaccard` | 0.6444444444444445 | `>= 0.6` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_retention` | 0.8923076923076924 | `>= 0.8` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `added_event_rate` | 0.30120481927710846 | `<= 0.5` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `disappeared_event_rate` | 0.1076923076923077 | `<= 0.5` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_median` | 2.5 | `<= 5` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_p90` | 12.400000000000002 | `<= 15` | `PASS` |
| 1.5 | US | adjacent_pair | 1.5→2.0 | `lifecycle_divergence_rate` | 0.7781569965870307 | `<= 0.5` | `FAIL` |
| 2.0 | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 163 | `>= 8` | `PASS` |
| 2.0 | CN | candidate | — | `minimum_event_symbols_per_market_candidate` | 19 | `>= 8` | `PASS` |
| 2.0 | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.08588957055214724 | `<= 0.25` | `PASS` |
| 2.0 | CN | candidate | — | `maximum_symbol_confirmed_hhi` | 0.05702134066016787 | `<= 0.2` | `PASS` |
| 2.0 | CN | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_jaccard` | 0.664804469273743 | `>= 0.6` | `PASS` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_retention` | 0.8814814814814815 | `>= 0.8` | `PASS` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `added_event_rate` | 0.26993865030674846 | `<= 0.5` | `PASS` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `disappeared_event_rate` | 0.11851851851851852 | `<= 0.5` | `PASS` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_median` | 5.5 | `<= 5` | `FAIL` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_p90` | 27.900000000000002 | `<= 15` | `FAIL` |
| 2.0 | CN | adjacent_pair | 1.5→2.0 | `lifecycle_divergence_rate` | 0.7986798679867987 | `<= 0.5` | `FAIL` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_jaccard` | 0.7894736842105263 | `>= 0.6` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_retention` | 0.9202453987730062 | `>= 0.8` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `added_event_rate` | 0.15254237288135594 | `<= 0.5` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `disappeared_event_rate` | 0.07975460122699386 | `<= 0.5` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_median` | 4.0 | `<= 5` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_p90` | 5.399999999999999 | `<= 15` | `PASS` |
| 2.0 | CN | adjacent_pair | 2.0→2.5 | `lifecycle_divergence_rate` | 0.629080118694362 | `<= 0.5` | `FAIL` |
| 2.0 | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 166 | `>= 8` | `PASS` |
| 2.0 | US | candidate | — | `minimum_event_symbols_per_market_candidate` | 20 | `>= 8` | `PASS` |
| 2.0 | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.0783132530120482 | `<= 0.25` | `PASS` |
| 2.0 | US | candidate | — | `maximum_symbol_confirmed_hhi` | 0.05479750326607634 | `<= 0.2` | `PASS` |
| 2.0 | US | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_jaccard` | 0.6444444444444445 | `>= 0.6` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `adjacent_confirmed_retention` | 0.8923076923076924 | `>= 0.8` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `added_event_rate` | 0.30120481927710846 | `<= 0.5` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `disappeared_event_rate` | 0.1076923076923077 | `<= 0.5` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_median` | 2.5 | `<= 5` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `matched_confirmed_event_date_drift_p90` | 12.400000000000002 | `<= 15` | `PASS` |
| 2.0 | US | adjacent_pair | 1.5→2.0 | `lifecycle_divergence_rate` | 0.7781569965870307 | `<= 0.5` | `FAIL` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_jaccard` | 0.7391304347826086 | `>= 0.6` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_retention` | 0.9216867469879518 | `>= 0.8` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `added_event_rate` | 0.211340206185567 | `<= 0.5` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `disappeared_event_rate` | 0.0783132530120482 | `<= 0.5` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_p90` | 11.9 | `<= 15` | `PASS` |
| 2.0 | US | adjacent_pair | 2.0→2.5 | `lifecycle_divergence_rate` | 0.792507204610951 | `<= 0.5` | `FAIL` |
| 2.5 | CN | candidate | — | `minimum_confirmed_events_per_market_candidate` | 177 | `>= 8` | `PASS` |
| 2.5 | CN | candidate | — | `minimum_event_symbols_per_market_candidate` | 19 | `>= 8` | `PASS` |
| 2.5 | CN | candidate | — | `maximum_symbol_confirmed_concentration` | 0.07909604519774012 | `<= 0.25` | `PASS` |
| 2.5 | CN | candidate | — | `maximum_symbol_confirmed_hhi` | 0.05595454690542309 | `<= 0.2` | `PASS` |
| 2.5 | CN | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_jaccard` | 0.7894736842105263 | `>= 0.6` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_retention` | 0.9202453987730062 | `>= 0.8` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `added_event_rate` | 0.15254237288135594 | `<= 0.5` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `disappeared_event_rate` | 0.07975460122699386 | `<= 0.5` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_median` | 4.0 | `<= 5` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_p90` | 5.399999999999999 | `<= 15` | `PASS` |
| 2.5 | CN | adjacent_pair | 2.0→2.5 | `lifecycle_divergence_rate` | 0.629080118694362 | `<= 0.5` | `FAIL` |
| 2.5 | US | candidate | — | `minimum_confirmed_events_per_market_candidate` | 194 | `>= 8` | `PASS` |
| 2.5 | US | candidate | — | `minimum_event_symbols_per_market_candidate` | 20 | `>= 8` | `PASS` |
| 2.5 | US | candidate | — | `maximum_symbol_confirmed_concentration` | 0.07731958762886598 | `<= 0.25` | `PASS` |
| 2.5 | US | candidate | — | `maximum_symbol_confirmed_hhi` | 0.05478796896588373 | `<= 0.2` | `PASS` |
| 2.5 | US | candidate | — | `zero_confirmed_event_pathology` | False | `= False` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_jaccard` | 0.7391304347826086 | `>= 0.6` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `adjacent_confirmed_retention` | 0.9216867469879518 | `>= 0.8` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `added_event_rate` | 0.211340206185567 | `<= 0.5` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `disappeared_event_rate` | 0.0783132530120482 | `<= 0.5` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_median` | 4.5 | `<= 5` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `matched_confirmed_event_date_drift_p90` | 11.9 | `<= 15` | `PASS` |
| 2.5 | US | adjacent_pair | 2.0→2.5 | `lifecycle_divergence_rate` | 0.792507204610951 | `<= 0.5` | `FAIL` |

## Parity, reproducibility and boundaries

- precomputed-swing parity: `PASS`; cells `280`, bars `616525`, terminal events `3253`, setup mismatches `0`, event mismatches `0`.
- deterministic repeat: `PASS`; canonical digest is recorded in the capsule and must match the second run.
- incumbent 3%/4%/5% percentages are reference-only; no fixed-percentage search or production selection was performed.
- no returns, forward returns, MFE, MAE, P&L, winrate, expectancy, Final OOS, formal Phase 5K-B1, IBKR, Decision calculation or production write was accessed.

Artifact hashes:

- `candidate_level_matrix.csv`: `sha256:e6abcae7d116bc4f98f34b23fa9d8909ff8ec21087216865f49bd4f29e5b8370`
- `adjacent_stability_matrix.csv`: `sha256:bed45db2ab40c4bd0e3cb8a280b2dc1aabfdf8e6123cdb047052b10e12c919ef`
- `lifecycle_divergence_matrix.csv`: `sha256:0f9e9cb8b4d05dcc1f39c2a6796a056fc04cdf03f7b6d60c9c25233dc71a6694`
- `baseline_reference.csv`: `sha256:3e556485d923cf5722d30b6b5f49640b26d3b55627a650ef892ba185703e1085`
- `decision_capsule.json`: `sha256:ac182d1442fd816c4eab5d6ae3e0cf2b4b8b55909b0ab7acab29b7ddc5c44c70`

`STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`
