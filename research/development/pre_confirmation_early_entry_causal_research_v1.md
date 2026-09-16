# PRE-CONFIRMATION Early Entry Causal Research V1

> Development research only. No production entry rule, confirmation, target, stop, RR, state, Sheets, or broker behavior is changed.

- Protocol: `PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1`
- Status: `READY_FOR_DECISION`
- Frozen input: `artifacts/phase5j_v3_development_holdout/development_holdout_replay_input.jsonl.gz`
- Final OOS access: `false`

## Cohort construction

The cohort is rebuilt from every causal primary/alternate WAVE_2_TO_3 anchor context in strict as-of Wave replay, not from the existing CONFIRMED-only sample. Contexts hidden by current primary-scenario selection remain included.

| item | count |
|---|---:|
| frozen symbols | 40 |
| frozen bars | 86305 |
| causal Wave2 anchor contexts | 2254 |
| valid Wave2 geometry contexts | 2242 |
| invalid Wave2 geometry contexts retained/screened | 12 |
| PRIMARY-only / PRIMARY+ALTERNATE / ALTERNATE-only visibility | 910 / 601 / 743 |
| later CONFIRMED | 745 |
| FAILED | 947 |
| never CONFIRMED | 562 |
| screened out by current system | 551 |
| timeout/unresolved at data end | 11 |
| candidates with a causal pre-confirmation observation | 1462 |
| retained candidates without an observed pre-confirmation window | 792 |

## Fixed research policies

All definitions below were fixed in the protocol before outcome analysis; each policy emits at most one first signal per lifecycle.

| policy | signal milestone |
|---|---|
| INCUMBENT_CONFIRMED_CLOSE | first causal `close > H1` CONFIRMED day; next frozen-session OPEN |
| FIRST_BULLISH_RECOVERY | first causal primary/alternate WAVE_2_TO_3 context day after confirmed anchors with `close > previous close`, `close > LOW2`, `close <= H1` |
| ARMED_HALF_RECOVERY | first causal context day after confirmed anchors with `close >= LOW2 + 0.5 × (H1 − LOW2)`, `close <= H1` |
| H1_INTRADAY_RECLAIM | first causal context day after confirmed anchors with `high >= H1`, `close <= H1` |
| ARMED_HALF_RECOVERY_DAILY_UPTREND | fixed ARMED_HALF_RECOVERY milestone plus existing as-of daily UPTREND and weekly not DOWNTREND |

Every entry is the exact next frozen market-session OPEN. Missing symbol bars are not substituted by a later bar.

## Funnel and composition

| policy | cohort | signaled | executable next OPEN | later confirmed | never confirmed | failed | structural invalidation-first | Fib1.272 remaining headroom/R median | Fib1.618 remaining headroom/R median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| INCUMBENT_CONFIRMED_CLOSE | 2254 | 745 | 744 | 745 | 0 | 0 | 0 (0.0%) | 0.374 | 0.720 |
| FIRST_BULLISH_RECOVERY | 2254 | 1236 | 1236 | 292 | 376 | 568 | 441 (35.7%) | 0.984 | 1.330 |
| ARMED_HALF_RECOVERY | 2254 | 1005 | 1004 | 326 | 359 | 320 | 233 (23.2%) | 0.835 | 1.181 |
| H1_INTRADAY_RECLAIM | 2254 | 563 | 563 | 189 | 228 | 146 | 113 (20.1%) | 0.757 | 1.103 |
| ARMED_HALF_RECOVERY_DAILY_UPTREND | 2254 | 477 | 477 | 191 | 147 | 139 | 102 (21.4%) | 0.868 | 1.214 |

The policy counts above are signal-set counts; the cohort denominator remains the full 2254-context cohort for every policy.

## Headroom improvement versus incumbent

Positive values mean the early entry retained more normalized space than the paired incumbent next-session OPEN on the same later-CONFIRMED lifecycle. The paired adverse delta uses a common post-entry structural-invalidation/data-end horizon; positive means the early entry experienced more adverse excursion because it was held from an earlier point.

| early policy | paired executable later-CONFIRMED | H1 median gain/R | Fib1.272 median gain/R | Fib1.618 median gain/R | confirmation latency saved median sessions | paired adverse delta median/R |
|---|---:|---:|---:|---:|---:|---:|
| FIRST_BULLISH_RECOVERY | 292 | 0.337 | 0.337 | 0.337 | 4.0 | -0.309 |
| ARMED_HALF_RECOVERY | 326 | 0.264 | 0.264 | 0.264 | 4.0 | -0.243 |
| H1_INTRADAY_RECLAIM | 189 | 0.170 | 0.170 | 0.170 | 2.0 | -0.152 |
| ARMED_HALF_RECOVERY_DAILY_UPTREND | 191 | 0.256 | 0.256 | 0.256 | 4.0 | -0.224 |

## Failure and adverse-excursion tradeoff

Adverse excursion is the minimum low from executable entry through confirmation, failure, screened-out replacement, or dataset end, normalized by Wave1 `R = H1 − LOW0`. Fixed hurdles continue after confirmation until structural invalidation or dataset end for later-confirmed paths; never-confirmed paths remain censored. No production Stop is defined by this study.

| policy | adverse magnitude median/R | adverse magnitude P90/R | censored paths | HURDLE_0272 success | HURDLE_0618 success |
|---|---:|---:|---:|---:|---:|
| INCUMBENT_CONFIRMED_CLOSE | 0.990 | 2.102 | 171 | 661 (88.8%) | 572 (76.9%) |
| FIRST_BULLISH_RECOVERY | 0.190 | 0.598 | 376 | 388 (31.4%) | 283 (22.9%) |
| ARMED_HALF_RECOVERY | 0.227 | 0.703 | 358 | 439 (43.7%) | 317 (31.6%) |
| H1_INTRADAY_RECLAIM | 0.222 | 0.757 | 228 | 281 (49.9%) | 197 (35.0%) |
| ARMED_HALF_RECOVERY_DAILY_UPTREND | 0.196 | 0.627 | 147 | 220 (46.1%) | 166 (34.8%) |

## Robustness

### FIRST_BULLISH_RECOVERY

| slice | cohort | signaled | executable | later confirmed | never confirmed | failed |
|---|---:|---:|---:|---:|---:|---:|
| CN | 1008 | 570 | 570 | 113 | 194 | 263 |
| US | 1246 | 666 | 666 | 179 | 182 | 305 |
| depth:NORMAL_OR_SHALLOW | 1008 | 506 | 506 | 130 | 140 | 236 |
| depth:DEEP | 570 | 303 | 303 | 63 | 94 | 146 |
| depth:VERY_DEEP | 664 | 427 | 427 | 99 | 142 | 186 |
| without count-leading symbol `ADI` | 2184 | 1192 | 1192 | 278 | 367 | 547 |

### ARMED_HALF_RECOVERY

| slice | cohort | signaled | executable | later confirmed | never confirmed | failed |
|---|---:|---:|---:|---:|---:|---:|
| CN | 1008 | 438 | 438 | 124 | 180 | 134 |
| US | 1246 | 567 | 566 | 202 | 179 | 186 |
| depth:NORMAL_OR_SHALLOW | 1008 | 436 | 436 | 143 | 143 | 150 |
| depth:DEEP | 570 | 238 | 237 | 73 | 91 | 74 |
| depth:VERY_DEEP | 664 | 331 | 331 | 110 | 125 | 96 |
| without count-leading symbol `LIN` | 2180 | 968 | 967 | 312 | 348 | 308 |

### H1_INTRADAY_RECLAIM

| slice | cohort | signaled | executable | later confirmed | never confirmed | failed |
|---|---:|---:|---:|---:|---:|---:|
| CN | 1008 | 255 | 255 | 74 | 114 | 67 |
| US | 1246 | 308 | 308 | 115 | 114 | 79 |
| depth:NORMAL_OR_SHALLOW | 1008 | 264 | 264 | 87 | 104 | 73 |
| depth:DEEP | 570 | 119 | 119 | 36 | 55 | 28 |
| depth:VERY_DEEP | 664 | 180 | 180 | 66 | 69 | 45 |
| without count-leading symbol `BLDR` | 2182 | 536 | 536 | 182 | 217 | 137 |

### ARMED_HALF_RECOVERY_DAILY_UPTREND

| slice | cohort | signaled | executable | later confirmed | never confirmed | failed |
|---|---:|---:|---:|---:|---:|---:|
| CN | 1008 | 171 | 171 | 62 | 59 | 50 |
| US | 1246 | 306 | 306 | 129 | 88 | 89 |
| depth:NORMAL_OR_SHALLOW | 1008 | 244 | 244 | 98 | 69 | 77 |
| depth:DEEP | 570 | 106 | 106 | 37 | 38 | 31 |
| depth:VERY_DEEP | 664 | 127 | 127 | 56 | 40 | 31 |
| without count-leading symbol `LIN` | 2180 | 448 | 448 | 181 | 136 | 131 |

Time halves use the frozen market-session ordinal midpoint of candidate ready date. The complete JSON includes time halves, resolution strata, and later-CONFIRMED versus never-CONFIRMED/FAILED strata for every policy.

## Bias checks and controls

- `cohort_unique_lifecycle_count`: `2254`
- `cohort_eventual_status_conserved`: `true`
- `cohort_resolution_conserved`: `true`
- `all_anchor_confirmed_as_of_observation`: `true`
- `preconfirmation_window_rows_retained_even_when_not_observed`: `true`
- `early_policy_signals_strictly_before_confirmation`: `true`
- `policy_ids_match_registered_protocol`: `true`
- `signal_definition_uses_outcomes`: `false`
- `future_data_used_only_after_signal_for_evaluation`: `true`
- `exact_next_session_open_only`: `true`
- Final OOS access = `false`.
- No parameter search or threshold sweep.
- No P&L, return, win-rate, expectancy, or broker outcome was used as the first-layer selection criterion.
- Production unchanged: no confirmation, Entry, Stop, Target, RR, Wave, Swing, 5% gate, or 2R change; no state/Sheets writes; no broker orders.

## Decision node

**READY_FOR_DECISION** — The full causal cohort is reconstructable and every fixed early policy adds normalized entry headroom on its matched later-CONFIRMED subset, but all early policies also admit a substantial FAILED/never-CONFIRMED population. The first-layer question is therefore not cleared: this artifact supports a user decision about further research only, does not yet support moving to execution/cost research, and authorizes no production policy.

- Supports a separate follow-up research decision: `true`.
- Supports execution/cost research now: `false`.
- No policy is production-authorized by this artifact.

Status: `READY_FOR_DECISION`.
