# SETUP_01 earlier entry - second-stage execution-feasibility decision node V1

> Research only. This delivery registers and freezes no second-stage protocol, computes no cost, net return, win rate or expectancy, accesses no Final OOS, and changes no production rule, state, Sheet or broker path.

- Artifact: `SETUP01_EARLY_ENTRY_SECOND_STAGE_DECISION_V1`
- Status: `READY_FOR_DECISION`
- First stage: `SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1` (`FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`)
- Protocol registered: `false`
- Production authorization: `false`

## Conclusion

The second stage cannot uniquely determine a tradable definition of the experimental group from the frozen rules, so it stops at this decision node:

- `entry_admission_geometry`: the only frozen SETUP_01 admission rule is the confirmation-day Decision entry zone [H1, H1 + 0.5*ATR14(T)] with entry_zone_low = H1, and its executor classifies any OPEN below H1 as SKIP_GAP_BELOW_CONFIRMATION; the overwhelming majority of early entries opens below H1 by construction, so that frozen rule rejects almost every early trade and a new admission rule must be chosen
- `preconfirmation_execution_stop_and_risk_basis`: no stop exists for a pre-confirmation position; the 0.5% risk budget and position_size() need |entry - execution_stop|, and the stage-1 artifact records production_stop_defined=false for the experimental group
- `preconfirmation_target_and_gate_semantics`: the incumbent target set is built from confirmed swing highs known as of T and above the confirmed reference entry, plus Wave-1 projections; at an earlier date the nearest confirmed swing high above the entry is normally H1 itself, so T1, the 5% gross-upside gate and the 2R gate produce a different admission set than at confirmation, and reusing the confirmation-day target set on the earlier date would backfill geometry that only exists at confirmation
- `preconfirmation_termination_and_long_unconfirmed_handling`: about two thirds of executable early signals never reach the incumbent confirmation, and the cohort also contains screened-out and right-censored contexts; the frozen Position Management protocol only consumes positions created by an EXECUTED confirmation-day Decision, so no frozen rule says when a pre-confirmation position must be closed
- `post_confirmation_handoff`: Position Management / Exit v1 freezes 1R = actual_entry - initial_execution_stop and its stop-raise rule references the T close of the confirmation-day Decision; an early position needs an explicit mapping of the initial stop, of the target set taken at the first CONFIRMED day, and of whether the confirmation-day 5%/2R gates may eject an already open position
- `execution_cost_and_market_tradability_inputs`: no cost, spread, slippage, lot-size, price-limit or suspension rule is registered for either market, and the frozen replay input carries no quote or spread data; these must be pre-registered as explicit scenarios with sources and dates, or marked unknown

The three packages below are mutually exclusive candidate implementations. The research selects none of them and does not rank them by outcome; only after the user chooses or rejects them can a second-stage protocol be pre-registered.

## Already uniquely determined by frozen rules

| dimension | rule | source |
|---|---|---|
| `entry_trigger` | first causal primary/alternate WAVE_2_TO_3 context day with all three Swing anchors confirmed, close >= wave2_low + 0.5 * (wave1_peak - wave2_low) and close <= wave1_peak | trading/setup01.py SETUP01_RECOVERY_RATIO=0.5 ARMED predicate; stage-1 protocol single_experimental_group |
| `signal_information_set_and_execution_timing` | data <= signal date only; entry is the exact next frozen market-session OPEN; no same-bar fill; no later-bar or T+2 substitution | stage-1 protocol causal_contract; research/market_sessions.py session SSOT; docs/SETUP_01_DECISION_RISK_V1.md time contract |
| `structural_invalidation` | close <= confirmed Wave 2 low is the SETUP_01 trade-structure invalidation; close <= Wave 1 origin is the wave-scenario invalidation | trading/setup01.py _state_for_candidate and _context_failure_reason |
| `common_denominator` | every strict as-of causal Wave2 anchor context of the frozen sample, including FAILED, never-CONFIRMED, screened-out and right-censored rows; never the later-CONFIRMED subset | stage-1 protocol denominator and cohort_construction |

## Candidate packages (mutually exclusive, none selected)

| package | admission | pre-confirmation stop | pre-confirmation targets |
|---|---|---|---|
| `PKG_A_STRUCTURAL_RISK_ONLY` | UNCONDITIONAL_EXACT_NEXT_SESSION_OPEN | CONFIRMED_WAVE2_LOW_CLOSE_BASED | DEFERRED_TO_THE_FIRST_CONFIRMED_DAY |
| `PKG_B_ATR_EXECUTION_STOP` | UNCONDITIONAL_EXACT_NEXT_SESSION_OPEN | CONFIRMED_WAVE2_LOW_MINUS_HALF_ATR14_AT_SIGNAL_DATE | DEFERRED_TO_THE_FIRST_CONFIRMED_DAY |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | TRIGGER_BAND_PLUS_INCUMBENT_TARGET_UPSIDE_AND_RR_GATES | CONFIRMED_WAVE2_LOW_MINUS_HALF_ATR14_AT_SIGNAL_DATE | EVALUATED_AT_THE_SIGNAL_DATE |

### Information availability

- All three packages share the same entry trigger, the same exact next-session OPEN execution and the same structural invalidation definition.
- A and B use pre-confirmation targets and the 5%/2R gates only after the first CONFIRMED day; the signal date reads no geometry that exists only at confirmation.
- C evaluates the incumbent 5% and 2R gates at the signal date against signal-date confirmed swing highs and Wave-1 Fib projections; it backfills nothing from the confirmation day.

### Executability and composition (geometry only, no cost or return)

| package | market | executable | admitted | admission composition |
|---|---|---:|---:|---|
| `PKG_A_STRUCTURAL_RISK_ONLY` | CN | 461 | 461 | ADMITTED=461 |
| `PKG_A_STRUCTURAL_RISK_ONLY` | US | 525 | 523 | ADMITTED=523, SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION=2 |
| `PKG_B_ATR_EXECUTION_STOP` | CN | 461 | 461 | ADMITTED=461 |
| `PKG_B_ATR_EXECUTION_STOP` | US | 525 | 525 | ADMITTED=525 |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | CN | 461 | 0 | SKIP_OPEN_OUTSIDE_TRIGGER_BAND=38, SKIP_RR_BELOW_MINIMUM_AT_OPEN=29, SKIP_TARGET_UPSIDE_BELOW_MINIMUM=394 |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | US | 525 | 0 | SKIP_OPEN_OUTSIDE_TRIGGER_BAND=64, SKIP_RR_BELOW_MINIMUM_AT_OPEN=24, SKIP_TARGET_UPSIDE_BELOW_MINIMUM=437 |

### Admission notes

- `PKG_A_STRUCTURAL_RISK_ONLY`: admits 984/986; blocked: SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION=2
  - CN: admits every executable signal (461/461); US: admits 523/525; blocked: SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION=2
- `PKG_B_ATR_EXECUTION_STOP`: admits every executable signal (986/986)
  - CN: admits every executable signal (461/461); US: admits every executable signal (525/525)
- `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE`: admits no trade on the frozen sample: 831/986 signals are blocked first by SKIP_TARGET_UPSIDE_BELOW_MINIMUM
  - CN: admits no trade on the frozen sample: 394/461 signals are blocked first by SKIP_TARGET_UPSIDE_BELOW_MINIMUM; US: admits no trade on the frozen sample: 437/525 signals are blocked first by SKIP_TARGET_UPSIDE_BELOW_MINIMUM

A package that admits no trade on the frozen sample is not a usable second-stage candidate as written; it must be rejected or re-specified by the user before any protocol is registered.

### Compatibility with the existing system

| package | new rules required | reused | risk-profile note |
|---|---|---|---|
| `PKG_A_STRUCTURAL_RISK_ONLY` | early entry bypasses the confirmation-day entry zone; structural invalidation becomes an executable exit and the 1R basis; pre-confirmation positions are exempt from the T-day 5%/2R admission gates | ARMED milestone and Wave/Swing engine; confirmed Wave 2 low structural invalidation; exact T+1 OPEN timing and the market-session SSOT; confirmation-day target set and Position Management / Exit v1 afterwards | narrower per-trade risk distance than the ATR-buffer package, because the buffer sits 0.5*ATR below the structural low; the implied notional per 0.5% risk unit is therefore larger |
| `PKG_B_ATR_EXECUTION_STOP` | early entry bypasses the confirmation-day entry zone; a pre-confirmation execution stop equal to the incumbent ATR formula evaluated at the signal date; pre-confirmation positions are exempt from the T-day 5%/2R admission gates | ARMED milestone and Wave/Swing engine; incumbent execution-stop formula wave2_low - 0.5*ATR14; confirmation-day target set and Position Management / Exit v1 afterwards | per-trade risk distance is wider than the structural-only package on every lifecycle, because the incumbent Execution Stop formula places the stop 0.5*ATR below the structural low; it also admits the opens that gap below the structural low but not below that stop. The stop itself is not part of any registered pre-confirmation semantics |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | early entry zone [recovery level, H1 + 0.5*ATR14 at the signal date]; pre-confirmation execution stop equal to the incumbent ATR formula at the signal date; the incumbent 5% target-upside and 2R gates are evaluated at the signal date against a signal-date target set | ARMED milestone and Wave/Swing engine; incumbent target construction, 5% gate and 2R gate, unmodified, on the earlier information set; confirmation-day target set and Position Management / Exit v1 afterwards | most restrictive package because H1 necessarily becomes the nearest target candidate on the earlier date, which makes the incumbent upside and R/R gates bind far earlier than at confirmation |

### Potential loss (per-trade 1R distance) and capital occupation (0.5% risk)

| package | market | risk/share %entry | risk/share / Wave1 R | notional / allocation_budget | sessions to resolution |
|---|---|---:|---:|---:|---|
| `PKG_A_STRUCTURAL_RISK_ONLY` | CN | 0.061 [0.030-0.127], n=461 | 0.431 [0.261-0.719], n=461 | 0.082 [0.039-0.165], n=461 | 7.000 [1.000-18.000], n=461 |
| `PKG_A_STRUCTURAL_RISK_ONLY` | US | 0.053 [0.028-0.121], n=523 | 0.427 [0.214-0.710], n=523 | 0.094 [0.041-0.181], n=523 | 6.000 [1.000-18.000], n=523 |
| `PKG_B_ATR_EXECUTION_STOP` | CN | 0.077 [0.041-0.151], n=461 | 0.543 [0.338-0.890], n=461 | 0.065 [0.033-0.121], n=461 | 7.000 [1.000-18.000], n=461 |
| `PKG_B_ATR_EXECUTION_STOP` | US | 0.066 [0.035-0.143], n=525 | 0.526 [0.271-0.855], n=525 | 0.075 [0.035-0.141], n=525 | 6.000 [1.000-18.000], n=525 |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | CN | - | - | - | - |
| `PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE` | US | - | - | - | - |

### Shared geometry facts

| market | executable | incumbent entry-zone class | entry->H1 /R | entry->Wave2 low %entry | entry->ATR stop %entry |
|---|---:|---|---:|---:|---:|
| CN | 461 | ENTRY_OPEN_AT_OR_ABOVE_CONFIRMATION_LEVEL=24, ENTRY_OPEN_BELOW_CONFIRMATION_LEVEL=437 | 0.192 [0.036-0.377], n=461 | 0.061 [0.030-0.127], n=461 | 0.077 [0.041-0.151], n=461 |
| US | 525 | ENTRY_OPEN_AT_OR_ABOVE_CONFIRMATION_LEVEL=43, ENTRY_OPEN_BELOW_CONFIRMATION_LEVEL=482 | 0.164 [0.009-0.380], n=525 | 0.053 [0.028-0.121], n=525 | 0.066 [0.035-0.143], n=525 |

- Frozen common denominator: 987 ARMED signals, 986 with an executable exact next-session OPEN (1 not executable); eventual status {'FAILED': 290, 'LATER_CONFIRMED': 329, 'NEVER_CONFIRMED': 368}.
- Resolution composition: {'SCREENED_OUT_BY_CURRENT_SYSTEM': 363, 'STRUCTURAL_INVALIDATION_BEFORE_CONFIRMATION': 82, 'TERMINAL_CONFIRMED': 329, 'TERMINAL_FAILED': 208, 'TIMEOUT_UNRESOLVED_AT_DATA_END': 5}; dataset-end rows {'AT_DATASET_END': 5, 'RESOLVED': 981}.

## Residual parameters that still need an explicit user decision

| decision | question | required before |
|---|---|---|
| `PRE_CONFIRMATION_WAITING_BOUND` | may a pre-confirmation position stay open until the producing lifecycle fails, its execution stop triggers or the data ends, or must a maximum waiting window be pre-registered? | stage-2 protocol registration |
| `COST_AND_TRADABILITY_SCENARIOS` | which commission, minimum fee, sell-side tax, spread, slippage and tradability scenarios are pre-registered, and which cost items stay unknown for each market? | any net metric is computed |
| `POST_CONFIRMATION_HANDOFF_CONFIRMATION` | confirm that the confirmation-day target set is the post-confirmation management geometry, that the initial stop stays the frozen 1R basis and that admission gates never eject an already open position | stage-2 protocol registration |

## Stage-2 protocol items already ready to freeze

- frozen sample identity, provider contract, hashes and roster (unchanged)
- common denominator of the first stage, per market, with FAILED, never-CONFIRMED, screened-out and right-censored rows retained
- signal information set, exact T+1 OPEN execution, no same-bar fill, no T+2 fallback
- structural invalidation semantics
- conservative same-bar tie-breaking for stop and target conditions
- separate reporting of net R, net return, notional, holding period, capital occupation and opportunity cost
- per-market clustering, time aggregation and cross-market uncertainty reporting
- no Final OOS, no sample replacement, no parameter search

## Boundaries

- This artifact rebuilds only the already frozen first-stage cohort and the same ARMED signals; it adds no sample, replaces no symbol, extends no window and searches no milestone or threshold.
- It computes no P&L, net R, net return, cost, win rate, expectancy or portfolio drawdown, and touches no Final OOS, real holdings, production state, Sheets or broker path.
- All three packages are candidate implementations only; the choice must be made by the user before any cost or net-return result is read.

Status: `READY_FOR_DECISION`
