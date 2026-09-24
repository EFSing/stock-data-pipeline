# SETUP_01 earlier entry - stage 2 economic validation V1

> Research only. No production rule, state, Sheet or broker path is touched, no Final OOS or real holdings are read, and portfolio drawdown is not estimable.

- Protocol: `SETUP01_EARLY_ENTRY_STAGE2_ECONOMIC_VALIDATION_V1` (`sha256:19a5fe3fc45c61a075ad0f439d573cf7cce8bf9d2ea65f1293be79e9c3c7be91`)
- Status: **INSUFFICIENT_EVIDENCE**
- Selected package: `PKG_B_ATR_EXECUTION_STOP`
- Denominator: 2291 anchor contexts, 987 ARMED signals, 790 first-CONFIRMED events

## Decision

a registered floor failed, so the comparison against the full incumbent is not evaluable at the registered standard; the protocol states that a failed floor yields INSUFFICIENT_EVIDENCE and never NOT_SUPPORTED. Raw pooled point estimates are kept as reported: C-B 0.3563 and C-A -0.2952

| market | realized A / B / C | mean net R C-A | mean net R C-B | floors failed |
|---|---:|---:|---:|---|
| CN | 0 / 285 / 436 | - | 0.316 | MIN_REALIZED_TRADES_A |
| US | 3 / 366 / 503 | -0.241 | 0.393 | MIN_REALIZED_TRADES_A |

| pooled statistic (CN+US) | baseline | stress 25bp | drop leading symbol | bootstrap 95% baseline |
|---|---:|---:|---:|---|
| B_FIRST_CONFIRMED_STRUCTURAL_minus_A_FULL_INCUMBENT | -0.651 | -0.626 | -0.656 | [-2.994, 0.544] |
| C_ARMED_CONSTRAINED_PKG_B_minus_A_FULL_INCUMBENT | -0.295 | -0.287 | -0.291 | [-2.655, 0.915] |
| C_ARMED_CONSTRAINED_PKG_B_minus_B_FIRST_CONFIRMED_STRUCTURAL | 0.356 | 0.340 | 0.365 | [0.299, 0.416] |

## Funnels (conserved; all statuses retained)

| identity | eligible | admitted | not executable at research budget | skip reasons |
|---|---:|---:|---:|---|
| A full incumbent Decision | 790 | 3 | 0 | NOT_EXECUTED_BY_INCUMBENT=787 |
| B first-CONFIRMED structural comparator (not a strategy) | 790 | 789 | 0 | SKIP_NO_NEXT_SESSION_BAR=1 |
| C ARMED + constrained PKG_B (research group) | 987 | 981 | 0 | SKIP_NO_NEXT_SESSION_BAR=1, SKIP_OPEN_AT_OR_BELOW_WAVE2_LOW=2, SKIP_ZERO_VOLUME_AT_ENTRY=3 |

Production first-CONFIRMED funnel: 790 events, gate reasons {'Setup01DecisionGateReason.ABOVE_ENTRY_ZONE': 492, 'Setup01DecisionGateReason.ENTRY_ALLOWED': 8, 'Setup01DecisionGateReason.RR_BELOW_MINIMUM': 61, 'Setup01DecisionGateReason.TARGET_UPSIDE_BELOW_MINIMUM': 229}, execution outcomes {'EXECUTED': 3, 'SKIP_GAP_ABOVE_ENTRY_ZONE': 4, 'SKIP_GAP_BELOW_CONFIRMATION': 1}.

## Primary policy (T1 exit enabled)

### combined

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 3 | 0 | 0.127 | -1.026 | -0.0013 | -0.0475 | 0.044 | 0.667 | 0.667 | 10.0 |
| B_FIRST_CONFIRMED_STRUCTURAL | 651 | 138 | -0.525 | -0.941 | -0.0789 | -0.0778 | 0.023 | 0.699 | 0.433 | 19.0 |
| C_ARMED_CONSTRAINED_PKG_B | 939 | 42 | -0.169 | -0.334 | -0.0135 | -0.0239 | 0.035 | 0.614 | 0.268 | 11.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {'EXIT_STOP_TRIGGERED': 2, 'EXIT_TARGET_T1_REACHED': 1}; status {'LATER_CONFIRMED': 3}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 31, 'EXIT_STOP_TRIGGERED': 230, 'EXIT_STRUCTURAL_INVALIDATION': 142, 'EXIT_TARGET_T1_REACHED': 248}; status {'LATER_CONFIRMED': 789}; censored 138.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 16, 'EXIT_LIFECYCLE_TERMINATED': 353, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 64, 'EXIT_STOP_TRIGGERED': 210, 'EXIT_STRUCTURAL_INVALIDATION': 138, 'EXIT_TARGET_T1_REACHED': 158}; status {'FAILED': 286, 'LATER_CONFIRMED': 328, 'NEVER_CONFIRMED': 367}; censored 42.

### CN

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 0 | 0 | - | - | - | - | - | - | - | - |
| B_FIRST_CONFIRMED_STRUCTURAL | 285 | 66 | -0.547 | -0.932 | -0.0870 | -0.0982 | 0.025 | 0.688 | 0.386 | 17.0 |
| C_ARMED_CONSTRAINED_PKG_B | 436 | 23 | -0.231 | -0.404 | -0.0212 | -0.0302 | 0.043 | 0.672 | 0.236 | 12.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {}; status {}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 6, 'EXIT_STOP_TRIGGERED': 91, 'EXIT_STRUCTURAL_INVALIDATION': 84, 'EXIT_TARGET_T1_REACHED': 104}; status {'LATER_CONFIRMED': 351}; censored 66.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 5, 'EXIT_LIFECYCLE_TERMINATED': 174, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 32, 'EXIT_STOP_TRIGGERED': 85, 'EXIT_STRUCTURAL_INVALIDATION': 80, 'EXIT_TARGET_T1_REACHED': 60}; status {'FAILED': 138, 'LATER_CONFIRMED': 152, 'NEVER_CONFIRMED': 169}; censored 23.

### US

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 3 | 0 | 0.127 | -1.026 | -0.0013 | -0.0475 | 0.044 | 0.667 | 0.667 | 10.0 |
| B_FIRST_CONFIRMED_STRUCTURAL | 366 | 72 | -0.508 | -0.943 | -0.0726 | -0.0689 | 0.020 | 0.708 | 0.470 | 21.0 |
| C_ARMED_CONSTRAINED_PKG_B | 503 | 19 | -0.115 | -0.241 | -0.0068 | -0.0159 | 0.030 | 0.565 | 0.296 | 10.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {'EXIT_STOP_TRIGGERED': 2, 'EXIT_TARGET_T1_REACHED': 1}; status {'LATER_CONFIRMED': 3}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 25, 'EXIT_STOP_TRIGGERED': 139, 'EXIT_STRUCTURAL_INVALIDATION': 58, 'EXIT_TARGET_T1_REACHED': 144}; status {'LATER_CONFIRMED': 438}; censored 72.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 11, 'EXIT_LIFECYCLE_TERMINATED': 179, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 32, 'EXIT_STOP_TRIGGERED': 125, 'EXIT_STRUCTURAL_INVALIDATION': 58, 'EXIT_TARGET_T1_REACHED': 98}; status {'FAILED': 148, 'LATER_CONFIRMED': 176, 'NEVER_CONFIRMED': 198}; censored 19.


## Secondary policy (no target exit)

### combined

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 3 | 0 | -1.036 | -1.040 | -0.0589 | -0.0516 | 0.040 | 1.000 | 1.000 | 10.0 |
| B_FIRST_CONFIRMED_STRUCTURAL | 595 | 194 | -1.026 | -1.018 | -0.1319 | -0.1143 | 0.022 | 1.000 | 0.701 | 56.0 |
| C_ARMED_CONSTRAINED_PKG_B | 902 | 79 | -0.454 | -0.790 | -0.0357 | -0.0437 | 0.035 | 0.773 | 0.379 | 13.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {'EXIT_STOP_TRIGGERED': 3}; status {'LATER_CONFIRMED': 3}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 56, 'EXIT_STOP_TRIGGERED': 333, 'EXIT_STRUCTURAL_INVALIDATION': 206}; status {'LATER_CONFIRMED': 789}; censored 194.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 34, 'EXIT_LIFECYCLE_TERMINATED': 353, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 64, 'EXIT_STOP_TRIGGERED': 275, 'EXIT_STRUCTURAL_INVALIDATION': 176}; status {'FAILED': 286, 'LATER_CONFIRMED': 328, 'NEVER_CONFIRMED': 367}; censored 79.

### CN

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 0 | 0 | - | - | - | - | - | - | - | - |
| B_FIRST_CONFIRMED_STRUCTURAL | 270 | 81 | -1.018 | -1.018 | -0.1412 | -0.1296 | 0.024 | 1.000 | 0.615 | 51.5 |
| C_ARMED_CONSTRAINED_PKG_B | 425 | 34 | -0.457 | -0.736 | -0.0413 | -0.0459 | 0.042 | 0.805 | 0.320 | 14.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {}; status {}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 11, 'EXIT_STOP_TRIGGERED': 138, 'EXIT_STRUCTURAL_INVALIDATION': 121}; status {'LATER_CONFIRMED': 351}; censored 81.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 7, 'EXIT_LIFECYCLE_TERMINATED': 174, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 32, 'EXIT_STOP_TRIGGERED': 114, 'EXIT_STRUCTURAL_INVALIDATION': 98}; status {'FAILED': 138, 'LATER_CONFIRMED': 152, 'NEVER_CONFIRMED': 169}; censored 34.

### US

| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 3 | 0 | -1.036 | -1.040 | -0.0589 | -0.0516 | 0.040 | 1.000 | 1.000 | 10.0 |
| B_FIRST_CONFIRMED_STRUCTURAL | 325 | 113 | -1.032 | -1.019 | -0.1241 | -0.0982 | 0.020 | 1.000 | 0.772 | 59.0 |
| C_ARMED_CONSTRAINED_PKG_B | 477 | 45 | -0.450 | -0.839 | -0.0306 | -0.0421 | 0.030 | 0.744 | 0.432 | 12.0 |

Exit reasons and status composition

- `A_FULL_INCUMBENT`: exits {'EXIT_STOP_TRIGGERED': 3}; status {'LATER_CONFIRMED': 3}; censored 0.
- `B_FIRST_CONFIRMED_STRUCTURAL`: exits {'EXIT_GAP_BELOW_STOP': 45, 'EXIT_STOP_TRIGGERED': 195, 'EXIT_STRUCTURAL_INVALIDATION': 85}; status {'LATER_CONFIRMED': 438}; censored 113.
- `C_ARMED_CONSTRAINED_PKG_B`: exits {'EXIT_GAP_BELOW_STOP': 27, 'EXIT_LIFECYCLE_TERMINATED': 179, 'EXIT_PRE_CONFIRMATION_TIMEOUT': 32, 'EXIT_STOP_TRIGGERED': 161, 'EXIT_STRUCTURAL_INVALIDATION': 78}; status {'FAILED': 148, 'LATER_CONFIRMED': 176, 'NEVER_CONFIRMED': 198}; censored 45.


## Cost scenario sensitivity (pooled)

| identity | mean net R baseline | mean net R stress | cost /R median baseline | cost /R median stress |
|---|---:|---:|---:|---:|
| A_FULL_INCUMBENT | 0.127 | 0.071 | 0.044 | 0.108 |
| B_FIRST_CONFIRMED_STRUCTURAL | -0.525 | -0.555 | 0.023 | 0.050 |
| C_ARMED_CONSTRAINED_PKG_B | -0.169 | -0.216 | 0.035 | 0.077 |

## Paired subset on shared confirmed lifecycles (descriptive)

| pair | paired lifecycles | mean net R difference | left mean net R | right mean net R |
|---|---:|---:|---:|---:|
| C_ARMED_CONSTRAINED_PKG_B_minus_B_FIRST_CONFIRMED_STRUCTURAL | 288 | 0.291 | -0.013 | -0.304 |
| C_ARMED_CONSTRAINED_PKG_B_minus_A_FULL_INCUMBENT | 2 | 0.723 | 1.434 | 0.712 |

## Censored-inclusive sensitivity (final-close valuation, not realized)

| identity | realized mean net R | censored-inclusive mean net R | n |
|---|---:|---:|---:|
| A_FULL_INCUMBENT | 0.127 | 0.127 | 3 |
| B_FIRST_CONFIRMED_STRUCTURAL | -0.525 | 1.897 | 789 |
| C_ARMED_CONSTRAINED_PKG_B | -0.169 | 0.585 | 981 |

## Registered assumptions and boundaries

- the registered primary statistic excludes right-censored rows, and censoring is asymmetric: C resolves almost every entry through its 20-session pre-confirmation waiting bound while A and B have no such bound. The final-close valuation sensitivity is therefore reported for all identities; where it reorders the comparison the economic conclusion is treated as not robust to censoring. It never replaces the realized statistic and is never mixed into it
- event-level results are not a portfolio: no concurrency, budget path or holdings state is modelled
- portfolio drawdown is NOT_ESTIMABLE
- CN limit, suspension and lot checks are model-level checks without order-book, queue or real volume evidence
- US spread and slippage are scenario assumptions because the frozen payload carries no quotes
- the sample window overlaps Development and this sample was already used for the first-stage decision, so it is not a fresh untouched out-of-sample set
- CN commission (2.5bp per side, minimum 5 CNY) and the US commission of 0 are research assumptions, not verified account rates; the CN sell stamp duty is applied as 10bp before 2023-08-28 and 5bp from 2023-08-28; the CN transfer fee is left UNKNOWN_NOT_MODELED.
- Fill model: an exit is executed at the next valid session OPEN when it is scheduled by the exit policy, at the stop price when the stop is touched intraday, and at T1 when the target is reached; the execution stop always takes precedence over a target touch on the same bar.
- The T1 exit is a research-only assumption; frozen Position Management treats targets as diagnostic and never auto-sells. The secondary policy removes it.

Status: `INSUFFICIENT_EVIDENCE`
