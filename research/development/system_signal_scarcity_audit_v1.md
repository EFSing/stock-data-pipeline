<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->
# SYSTEM_SIGNAL_SCARCITY_AUDIT_V1

> 本报告只做当前生产语义的 Development replay funnel、first-fail、overlap 与 one-gate counterfactual attribution；不改变生产策略，不产生生产授权。

## 1. 结论

- 最终分类：`STRUCTURAL_GATE_COLLISION_OBSERVED` — `STRUCTURAL_GATE_COLLISION_OBSERVED`。
- 证据摘要：595 of 999 confirmed events (59.56%) were already above the unchanged Entry Zone upper bound on the confirmation close. This recurring confirmation/Entry Zone interaction is a structural collision observation, not a recommendation to change either rule.
- 研究状态：`READY_FOR_DECISION`。
- Confirmation ablation 仅为理论 signal-loss accounting；不得把 pre-confirmation rows 当作合法 `ENTRY_ALLOWED`。

## 2. 固定输入与边界

- dataset：`SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1`；manifest `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`。
- replay aggregate：`sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`；symbols `40`；bars `86305`。
- Development holdout 是主要 attribution population；没有访问 Final OOS、provider、真实 holdings、Sheets、state 或 broker。
- symbol-session denominator 是冻结 Quote 行；candidate selector 没有被重新筛选，避免把 outcome-driven universe 混入研究。
- SETUP_03：Excluded from this SETUP_01/SETUP_02 attribution population: formal validation is stopped; its legacy manual path remains outside this audit's enabled production source scope.。
- SETUP_04：Not implemented and therefore has no production source or entry contribution.。

## 3. Symbol-session funnel

| scope | candidate/session | DATA_OK | history≥60 | weekly state | daily state | SETUP_01 wave | SETUP_02 wave |
|---|---:|---:|---:|---:|---:|---:|---:|
| ALL | 86305 | 86305 | 83945 | 75269 | 83975 | 21439 | 7255 |
| CN | 41274 | 41274 | 40094 | 35952 | 40099 | 9390 | 2509 |
| US | 45031 | 45031 | 43851 | 39317 | 43876 | 12049 | 4746 |

## 4. Production funnel by setup

| setup/scope | wave eligible sessions | lifecycles/setup events | WATCH | ARMED | CONFIRMED | Decision | ENTRY_ALLOWED | exact T+1 attempts | EXECUTED |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SETUP_01/ALL | 21439 | 1503 | 2898 | 2427 | 745 | 745 | 5 | 5 | 4 |
| SETUP_01/CN | 9390 | 670 | 1570 | 1111 | 299 | 299 | 0 | 0 | 0 |
| SETUP_01/US | 12049 | 833 | 1328 | 1316 | 446 | 446 | 5 | 5 | 4 |
| SETUP_02/ALL | 7255 | 547 | 1472 | 1449 | 254 | 254 | 3 | 3 | 0 |
| SETUP_02/CN | 2509 | 197 | 743 | 506 | 77 | 77 | 0 | 0 | 0 |
| SETUP_02/US | 4746 | 350 | 729 | 943 | 177 | 177 | 3 | 3 | 0 |
| AGGREGATE/ALL | — | 2050 | — | — | 999 | 999 | 8 | 8 | 4 |

## 5. First-fail attribution

### Confirmed → Decision

| setup | first fail | count | rate of confirmed decisions |
|---|---|---:|---:|
| SETUP_01 | ABOVE_ENTRY_ZONE | 464 | 62.28% |
| SETUP_01 | TARGET_UPSIDE_BELOW_MINIMUM | 198 | 26.58% |
| SETUP_01 | RR_BELOW_MINIMUM | 78 | 10.47% |
| SETUP_02 | ABOVE_ENTRY_ZONE | 131 | 51.57% |
| SETUP_02 | TARGET_UPSIDE_BELOW_MINIMUM | 79 | 31.10% |
| SETUP_02 | RR_BELOW_MINIMUM | 22 | 8.66% |
| SETUP_02 | STALE_CONFIRMATION_GEOMETRY | 14 | 5.51% |
| SETUP_02 | NO_VALID_TARGET | 5 | 1.97% |

### Lifecycle and exact T+1

| unit | reason | count | rate |
|---|---|---:|---:|
| SETUP_01 lifecycle | STRUCTURAL_INVALIDATION | 526 | 35.00% |
| SETUP_01 lifecycle | NO_VALID_WAVE | 106 | 7.05% |
| SETUP_01 lifecycle | CONTEXT_REPLACED_BEFORE_CONFIRMATION | 98 | 6.52% |
| SETUP_01 lifecycle | WEEKLY_STATE | 27 | 1.80% |
| SETUP_01 lifecycle | NOT_CONFIRMED | 1 | 0.07% |
| SETUP_02 lifecycle | NO_VALID_WAVE | 129 | 23.58% |
| SETUP_02 lifecycle | DAILY_STATE | 105 | 19.20% |
| SETUP_02 lifecycle | CONTEXT_REPLACED_BEFORE_CONFIRMATION | 21 | 3.84% |
| SETUP_02 lifecycle | SETUP_NOT_ELIGIBLE | 19 | 3.47% |
| SETUP_02 lifecycle | WEEKLY_STATE | 17 | 3.11% |
| SETUP_02 lifecycle | NOT_CONFIRMED | 2 | 0.37% |
| SETUP_01 T+1 | T+1 BELOW CONFIRMATION | 1 | 20.00% |
| SETUP_02 T+1 | T+1 BELOW CONFIRMATION | 1 | 33.33% |
| SETUP_02 T+1 | T+1 GAP ABOVE ENTRY ZONE | 1 | 33.33% |
| SETUP_02 T+1 | T+1 RR | 1 | 33.33% |

## 6. Gate overlap

| gate | first-fail | raw applicable | unique-only | overlap |
|---|---:|---:|---:|---:|
| ABOVE_ENTRY_ZONE | 595 | 595 | 6 | 589 |
| NO_VALID_TARGET | 5 | 29 | 5 | 24 |
| TARGET_UPSIDE_BELOW_MINIMUM | 277 | 745 | 0 | 745 |
| RR_BELOW_MINIMUM | 100 | 942 | 77 | 865 |
| FORMAL_T1_CONFIRMED_SWING_HIGH | 0 | 505 | 0 | 505 |
| TARGET_PROVENANCE_GEOMETRY | 0 | 0 | 0 | 0 |

Top pairwise overlaps:

| gates | intersection | Jaccard | conditional rates |
|---|---:|---:|---|
| RR_BELOW_MINIMUM ∩ TARGET_UPSIDE_BELOW_MINIMUM | 745 | 0.791 | RR_BELOW_MINIMUM 79.09%, TARGET_UPSIDE_BELOW_MINIMUM 100.00% |
| ABOVE_ENTRY_ZONE ∩ RR_BELOW_MINIMUM | 565 | 0.581 | ABOVE_ENTRY_ZONE 94.96%, RR_BELOW_MINIMUM 59.98% |
| FORMAL_T1_CONFIRMED_SWING_HIGH ∩ RR_BELOW_MINIMUM | 505 | 0.536 | FORMAL_T1_CONFIRMED_SWING_HIGH 100.00%, RR_BELOW_MINIMUM 53.61% |
| ABOVE_ENTRY_ZONE ∩ TARGET_UPSIDE_BELOW_MINIMUM | 468 | 0.537 | ABOVE_ENTRY_ZONE 78.66%, TARGET_UPSIDE_BELOW_MINIMUM 62.82% |
| FORMAL_T1_CONFIRMED_SWING_HIGH ∩ TARGET_UPSIDE_BELOW_MINIMUM | 463 | 0.588 | FORMAL_T1_CONFIRMED_SWING_HIGH 91.68%, TARGET_UPSIDE_BELOW_MINIMUM 62.15% |
| ABOVE_ENTRY_ZONE ∩ FORMAL_T1_CONFIRMED_SWING_HIGH | 272 | 0.329 | ABOVE_ENTRY_ZONE 45.71%, FORMAL_T1_CONFIRMED_SWING_HIGH 53.86% |
| ABOVE_ENTRY_ZONE ∩ NO_VALID_TARGET | 24 | 0.040 | ABOVE_ENTRY_ZONE 4.03%, NO_VALID_TARGET 82.76% |

## 7. Single-gate ablation

| gate | raw applicable | unique-only | incremental ENTRY_ALLOWED | incremental T+1 executable | +/100 confirmed | +/1000 symbol-sessions |
|---|---:|---:|---:|---:|---:|---:|
| TARGET_UPSIDE_BELOW_MINIMUM | 745 | 0 | 0 | 0 | 0.00% | 0.000 |
| RR_BELOW_MINIMUM | 942 | 77 | 100 | 62 | 10.01% | 1.159 |
| FORMAL_T1_CONFIRMED_SWING_HIGH | 505 | 0 | 14 | 9 | 1.40% | 0.162 |
| ENTRY_ZONE | 595 | 6 | 6 | 5 | 0.60% | 0.070 |
| CONFIRMATION_CLOSE_ABOVE_H1 | 1509 | — | — | — | — | — |
| Note | Confirmation has no production increment; it is reference-only theoretical accounting. |  |  |  |  |  |

## 8. Signal frequency

| scope | confirmed/1000 symbol-session | ENTRY_ALLOWED/1000 | executed/1000 | confirmed/100 lifecycle | ENTRY_ALLOWED/100 confirmed | executed/100 ENTRY_ALLOWED |
|---|---:|---:|---:|---:|---:|---:|
| CN | 9.110 | 0.000 | 0.000 | 43.368 | 0.000 | — |
| US | 13.835 | 0.178 | 0.089 | 52.663 | 1.284 | 50.000 |
| SETUP_01 | 8.632 | 0.058 | 0.046 | 49.568 | 0.671 | 80.000 |
| SETUP_02 | 2.943 | 0.035 | 0.000 | 46.435 | 1.181 | 0.000 |
| EARLY | 13.039 | 0.175 | 0.075 | 51.074 | 1.338 | 42.857 |
| LATE | 10.304 | 0.022 | 0.022 | 46.394 | 0.210 | 100.000 |

Symbol concentration is retained in JSON under `frequency`; it is descriptive, not a ranking rule.

## 9. Architecture classification

- `SAFETY_VALIDITY_HARD_GATE`: DATA_QUALITY, HISTORY_INSUFFICIENT, WEEKLY_STATE, DAILY_STATE, NO_VALID_WAVE, SETUP_NOT_ELIGIBLE, STRUCTURAL_INVALIDATION, STRUCTURAL_ISSUE, NO_VALID_TARGET, TARGET_PROVENANCE_GEOMETRY, STALE_CONFIRMATION_GEOMETRY, CONFIRMATION_CLOSE_ABOVE_H1, T+1 NO EXACT OPEN, T+1 BELOW INVALIDATION, T+1 BELOW CONFIRMATION.
- `ECONOMIC_HARD_GATE`: ABOVE_ENTRY_ZONE, TARGET_UPSIDE_BELOW_MINIMUM, RR_BELOW_MINIMUM, T+1 GAP ABOVE ENTRY ZONE, T+1 TARGET UPSIDE, T+1 RR.
- `QUALITY_RANKING_CANDIDATE`: trend strength, depth, overhead resistance proximity, target upside band, confirmation strength, wave quality.
- `REDUNDANT_DERIVED_CANDIDATES`: FORMAL_T1_CONFIRMED_SWING_HIGH, target/RR/entry-zone geometry overlap identified by the matrix.

## 10. Recent daily-report context

- status: `INSUFFICIENT_RECENT_LIVE_SAMPLE`; files considered: `0`.
- interpretation: No production daily-report.json artifact was present under reports; no Sheets, holdings, secrets, or provider access was attempted.

## 11. Controls and validation

- `development_only`: `True`
- `formal_validation`: `False`
- `final_oos_accessed`: `False`
- `parameter_search`: `False`
- `threshold_sweep`: `False`
- `multi_gate_combination_search`: `False`
- `production_rule_change`: `False`
- `production_code_modified`: `False`
- `state_writes`: `0`
- `sheets_writes`: `0`
- `broker_orders`: `0`
- `real_holdings_accessed`: `False`
- `provider_accessed`: `False`
- `raw_market_bars_persisted`: `False`
- `raw_event_dump_persisted`: `False`
- `outcome_metrics_computed`: `False`
- `preconfirmation_reference_used_as_constraint_only`: `True`
- `pr82_mixed_in`: `False`
- validation `current_production_funnel_parity`: `True`
- validation `first_fail_conservation`: `True`
- validation `all_fail_overlap_consistency`: `True`
- validation `single_gate_ablation_one_at_a_time`: `True`
- validation `single_gate_ablation_has_no_combined_gate`: `True`
- validation `source_event_snapshot_unchanged`: `True`
- validation `cn_us_symbol_session_conservation`: `True`
- validation `causal_as_of_replay`: `True`
- validation `exact_t_plus_1_open_only`: `True`
- validation `final_oos_accessed`: `False`
- validation `parameter_search`: `False`
- validation `threshold_sweep`: `False`
- validation `production_writes`: `False`
- validation `state_writes`: `0`
- validation `sheets_writes`: `0`
- validation `broker_orders`: `0`
- validation `real_holdings_accessed`: `False`
- validation `raw_market_bars_persisted`: `False`
- validation `raw_event_dump_persisted`: `False`
- validation `recent_live_reports_replace_development`: `False`

## 12. Remaining boundary

- No production gate, threshold, Entry Zone, confirmation, Fib, Swing, Wave, depth band, state path, Sheets path, or broker path was changed.
- If a follow-up is approved, it must be a new protocol. Depending on the evidence, the safe next study is presentation-only ARMED context, hard-gate-vs-ranking architecture research, or fresh-validation Early Entry; no same-dataset unbounded filter search is authorized.

`READY_FOR_DECISION`


## 13. Complete diagnostic funnel

### Top three bottlenecks

| node | count | denominator | rate | unit |
|---|---:|---:|---:|---|
| CANDIDATE_LIFECYCLE_NOT_CONFIRMED | 1051 | 2050 | 51.27% | candidate lifecycle |
| CONFIRMED_TO_ABOVE_ENTRY_ZONE | 595 | 999 | 59.56% | confirmed event |
| CONFIRMED_TO_TARGET_UPSIDE_BELOW_MINIMUM | 277 | 999 | 27.73% | confirmed event |

### Funnel by provenance

| setup/scope | candidate lifecycles | WATCH | ARMED | CONFIRMED | Decision calculable | NO_TRADE | ENTRY_ALLOWED | T+1 attempts | EXECUTED |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SETUP_01/FORMAL_STRATEGY_POOL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SETUP_01/DYNAMIC_CANDIDATE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SETUP_01/DEVELOPMENT_HOLDOUT_CANDIDATE | 1503 | 680 | 566 | 745 | 745 | 740 | 5 | 5 | 4 |
| SETUP_02/FORMAL_STRATEGY_POOL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SETUP_02/DYNAMIC_CANDIDATE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SETUP_02/DEVELOPMENT_HOLDOUT_CANDIDATE | 547 | 324 | 296 | 254 | 254 | 251 | 3 | 3 | 0 |

### ARMED → CONFIRMED

| setup/scope | ARMED lifecycles | confirmed with ARMED | ARMED without CONFIRMED | transition rate | latency median/p90 | close move % median/p90 | move ATR median/p90 | 1.272 headroom % median/p90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SETUP_01 | 566 | 299 | 267 | 52.83% | 3.000/10.000 | 0.037/0.086 | 1.262/2.507 | 0.066/0.201 |
| SETUP_02 | 296 | 143 | 153 | 48.31% | 4.000/10.000 | 0.052/0.125 | 1.617/3.039 | 0.002/0.119 |
| aggregate | 862 | 442 | 420 | 51.28% | 3.000/10.000 | 0.040/0.097 | 1.370/2.794 | 0.056/0.185 |
- The ARMED transition table is a lifecycle diagnostic. Direct CONFIRMED events without an observed ARMED row are reported separately and are not silently forced into the transition denominator.

### CONFIRMED → Entry Zone and RR

| setup/scope | confirmed | valid Entry Zone geometry | above upper | above-upper rate | overshoot % median/p90 | overshoot ATR median/p90 | RR failures | stop-too-large | target-too-close | both | insufficient evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SETUP_01 | 745 | 745 | 464 | 62.28% | 0.007/0.124 | 0.272/2.960 | 718 | 7 | 22 | 11 | 678 |
| SETUP_02 | 254 | 240 | 131 | 51.57% | 0.002/0.043 | 0.075/1.205 | 224 | 0 | 4 | 3 | 217 |
| aggregate | 999 | 985 | 595 | 59.56% | 0.006/0.101 | 0.219/2.684 | 942 | 7 | 26 | 14 | 895 |

### 5% target-upside contribution

- New 5% gate first-fail events: `277` / `999` (27.73%).
- One-gate removal with all other rules fixed: `+0` `ENTRY_ALLOWED`, `+0` executable T+1 events.
- This is marginal accounting only; it does not select a replacement threshold.

### Dashboard ARMED contract

- The underlying structural evaluator has trigger and invalidation, but DailyDecisionResult does not carry the current ARMED snapshot/close/ATR projection. Therefore the missing ARMED values are a result-contract gap plus presentation gap, not evidence that the structural evaluator lacks causal inputs.
- Minimum follow-up location: `daily_decision_chain read-only result projection, reusing a shared causal pre-confirmation/Entry Zone projection helper from the existing setup Decision layer`.
- Required fields: setup_type, current_close, confirmation_trigger_price, distance_to_trigger, distance_to_trigger_pct, expected_entry_zone_low, expected_entry_zone_high, structural_invalidation, atr14_as_of_current_close.
