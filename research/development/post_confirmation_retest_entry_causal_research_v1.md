# Post-confirmation Retest Entry Causal Research V1

`DEVELOPMENT_ONLY / NOT_PRODUCTION_AUTHORIZED`

Parent audit remains `MIXED_ARCHITECTURE_SIGNAL_STARVATION`. This fixed study tests decoupling confirmed facts from immediate entry; it does not prove Entry Zone wrong.

## Finding

Absolute recovery is small: A adds 0 executable events; B forms 8 plans (7 from previously non-ENTRY_ALLOWED facts) and adds 5 executions. The 595 ABOVE_ENTRY_ZONE cohort contributes 7 B plans and 4 executions (0.672%).
SETUP_01 adds 4; SETUP_02 adds 1. CN/US add 1/4; EARLY/LATE add 5/0. This is no broad or time-stable restoration of the missing cohort, and no production authorization.

## Fixed policies / timing

A retains a frozen confirmed pending fact, checks only exact T+1 OPEN and reuses the incumbent executor. A pending plan is not incumbent ENTRY_ALLOWED; recovered plans exclude existing ENTRY_ALLOWED.
B searches only after A did not execute. First close inside the frozen zone must pass frozen T1 5%, 2R and existing target reasonableness; execute only its exact next-session OPEN. A failed first retest ends the observation, with no second attempt.
All confirmation-day targets/provenance, ATR14 zone, confirmation level, structural invalidation and stop remain frozen. Existing candidate eligibility/key and lifecycle replacement terminate waiting causally; structure invalidation is CLOSE <= frozen invalidation. Known HIGH >= frozen T1 exhausts it; the confirmation-day HIGH is already known at T close. Same-close terminators precede a retest conservatively. No waiting window or outcome/parameter optimization.

## Aggregate

| Cohort | Confirmed | Incumbent allowed | Incumbent executed | A recovered pending plans | A executable | B plan total | B recovered plans | B executable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 999 | 8 | 4 | 620 | 0 | 8 | 7 | 5 |
| ABOVE_ENTRY_ZONE | 595 | 0 | 0 | 352 | 0 | 7 | 7 | 4 |
| SETUP_01 | 745 | 5 | 4 | 465 | 0 | 7 | 7 | 4 |
| SETUP_02 | 254 | 3 | 0 | 155 | 0 | 1 | 0 | 1 |
| CN | 376 | 0 | 0 | 214 | 0 | 1 | 1 | 1 |
| US | 623 | 8 | 4 | 406 | 0 | 7 | 6 | 4 |
| EARLY | 523 | 7 | 3 | 352 | 0 | 8 | 7 | 5 |
| LATE | 476 | 1 | 1 | 268 | 0 | 0 | 0 | 0 |

## ALL terminal reasons

```json
{
  "A_terminal_reasons": {
    "INCUMBENT_EXECUTED": 4,
    "NO_VALID_FROZEN_GEOMETRY_OR_TARGET": 43,
    "OUTSIDE_FROZEN_ENTRY_ZONE": 397,
    "RETEST_RR_BELOW_MINIMUM": 71,
    "RETEST_TARGET_UPSIDE_BELOW_MINIMUM": 121,
    "SKIP_BELOW_INVALIDATION": 2,
    "SKIP_NO_T1_BAR": 1,
    "T1_EXHAUSTED_AT_CONFIRMATION": 328,
    "T1_EXHAUSTED_AT_T1_OPEN": 32
  },
  "B_terminal_reasons": {
    "CONTEXT_REPLACED_OR_LIFECYCLE_ENDED": 112,
    "DATA_OR_SESSION_CONTRACT_UNPROVEN": 1,
    "EXECUTED": 5,
    "INCUMBENT_EXECUTED": 4,
    "NEVER_RETESTED_RIGHT_CENSORED_DATASET_END": 1,
    "NO_VALID_FROZEN_GEOMETRY_OR_TARGET": 43,
    "RETEST_RR_BELOW_MINIMUM": 110,
    "RETEST_TARGET_UPSIDE_BELOW_MINIMUM": 84,
    "SKIP_GAP_ABOVE_ENTRY_ZONE": 1,
    "SKIP_GAP_BELOW_CONFIRMATION": 2,
    "STRUCTURAL_INVALIDATION": 22,
    "STRUCTURAL_INVALIDATION_AT_T1_OPEN": 2,
    "T1_EXHAUSTED_AT_CONFIRMATION": 328,
    "T1_EXHAUSTED_BEFORE_RETEST": 284
  },
  "B_retest_latency_sessions": {
    "count": 202,
    "max": 17.0,
    "mean": 2.920792,
    "median": 1.0,
    "min": 1.0,
    "p10": 1.0,
    "p90": 6.9
  },
  "B_executable_retest_latency_sessions": {
    "count": 5,
    "max": 17.0,
    "mean": 9.4,
    "median": 6.0,
    "min": 3.0,
    "p10": 3.4,
    "p90": 17.0
  }
}
```

## ABOVE_ENTRY_ZONE terminal reasons

```json
{
  "A_terminal_reasons": {
    "NO_VALID_FROZEN_GEOMETRY_OR_TARGET": 24,
    "OUTSIDE_FROZEN_ENTRY_ZONE": 306,
    "RETEST_RR_BELOW_MINIMUM": 7,
    "RETEST_TARGET_UPSIDE_BELOW_MINIMUM": 14,
    "SKIP_BELOW_INVALIDATION": 2,
    "SKIP_NO_T1_BAR": 1,
    "T1_EXHAUSTED_AT_CONFIRMATION": 219,
    "T1_EXHAUSTED_AT_T1_OPEN": 22
  },
  "B_terminal_reasons": {
    "CONTEXT_REPLACED_OR_LIFECYCLE_ENDED": 72,
    "DATA_OR_SESSION_CONTRACT_UNPROVEN": 1,
    "EXECUTED": 4,
    "NEVER_RETESTED_RIGHT_CENSORED_DATASET_END": 1,
    "NO_VALID_FROZEN_GEOMETRY_OR_TARGET": 24,
    "RETEST_RR_BELOW_MINIMUM": 49,
    "RETEST_TARGET_UPSIDE_BELOW_MINIMUM": 22,
    "SKIP_GAP_ABOVE_ENTRY_ZONE": 1,
    "SKIP_GAP_BELOW_CONFIRMATION": 2,
    "STRUCTURAL_INVALIDATION": 5,
    "STRUCTURAL_INVALIDATION_AT_T1_OPEN": 2,
    "T1_EXHAUSTED_AT_CONFIRMATION": 219,
    "T1_EXHAUSTED_BEFORE_RETEST": 193
  },
  "B_retest_latency_sessions": {
    "count": 78,
    "max": 17.0,
    "mean": 3.987179,
    "median": 2.0,
    "min": 1.0,
    "p10": 1.0,
    "p90": 11.0
  },
  "B_executable_retest_latency_sessions": {
    "count": 4,
    "max": 17.0,
    "mean": 10.25,
    "median": 10.5,
    "min": 3.0,
    "p10": 3.3,
    "p90": 17.0
  }
}
```

## Concentration / conservation

Incremental symbol counts: `601598.SH`=1, `BLDR`=1, `LIN`=1, `QTWO`=1, `TSLA`=1.
Top incremental symbol (lexicographic tie-break): `601598.SH`; excluding it retains 4 incremental executable events.
```json
{
  "A_B_overlap": 0,
  "A_terminal_count": 999,
  "B_terminal_count": 999,
  "added_A": 0,
  "added_B": 5,
  "candidate_lifecycles": 2050,
  "executed_union": 9,
  "incumbent_executed": 4,
  "incumbent_increment_overlap": 0,
  "nonconfirmed_lifecycles": 1051,
  "not_executed": 990,
  "source_events_unchanged": true,
  "unique_confirmed_events": 999,
  "unique_confirmed_lifecycles": 999
}
```

Full setup/market/time-half/symbol and ABOVE_ENTRY_ZONE strata are retained in JSON. NEVER_RETESTED at dataset end is right-censored, not proof of permanent failure. Executable counts are descriptive opportunities, not broker fills, returns or evidence of profitability.

## Decision boundary

Whether recovery is large or small, stop here. User must decide whether confirmed → wait-for-retest architecture should enter a separate production design / fresh-validation task. No production change, extra policy, waiting-window search, ATR sweep, confirmation relaxation, target replacement or Final OOS access is authorized.

`READY_FOR_DECISION_POST_CONFIRMATION_RETEST_ARCHITECTURE`
