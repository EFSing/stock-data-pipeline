# SETUP_02 Decision/Risk v1 Protocol

Status: `SETUP_02_DECISION_RISK_V1_READY_FOR_SOL_REVIEW`

Protocol identity: `SETUP-02-DECISION-RISK-2026-09-01-v1`

This protocol is the independent Decision/Risk layer after the frozen
SETUP_02 structural lifecycle. It consumes only first-entry structural
`CONFIRMED` events and stops at a T-day plan plus a read-only exact T+1 OPEN
classification. It does not implement production execution, position
management, exit, or any outcome/performance metric.

## Governance boundary

- Structural input is `Setup02ReplayEvent` with `event_type == CONFIRMED`,
  `is_new_confirmed_event_as_of == true`, `confirmed_date == trade_date`, and
  `as_of_date == trade_date`.
- Each event identity is consumed exactly once. Persisted historical
  `CONFIRMED` snapshots, repeated terminal identities, `FAILED`, and
  pre-confirmation events are ignored by the Decision stream.
- T is the first daily close strictly above frozen continuation `HIGH3`.
  The T-day close forms a plan; same-bar execution is forbidden.
- Development T+1 identity uses
  `research.market_sessions.build_market_session_dates` and the
  `FROZEN_DATASET_MARKET_SESSION_SET` identity. Production remains gated by
  `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION`.

## T-day plan

The Decision layer copies the structural event's
`structural_invalidation`. It does not recompute it, move it, or alter it for
R/R. The frozen fields are:

- `confirmation_level = HIGH3`
- `planned_entry = T close`
- `entry_zone = [HIGH3, HIGH3 + 0.5 * ATR14(T)]`
- `execution_stop = structural_invalidation - 0.5 * ATR14(T)`
- `structural_invalidation` remains a separate field from `execution_stop`

ATR14 is the existing causal Wilder ATR implementation. Missing or invalid
ATR is `NO_TRADE / ATR_UNAVAILABLE`. If `planned_entry` is above the inclusive
zone's upper bound, the gate is `NO_TRADE / ABOVE_ENTRY_ZONE`; the zone is not
expanded.

## Target-first construction

Targets are built before R/R is calculated. A valid candidate must be strictly
above `planned_entry`, and candidates are merged by exact price, sorted
ascending, and truncated to the three nearest legal prices as `T1`, `T2`, and
`T3`.

1. T-known confirmed swing highs: only `HIGH` swings with pivot and
   confirmation provenance available as of T are accepted.
2. Continuation Fib extensions: the only reference leg is
   `structural_invalidation → HIGH3`. For positive
   `reference_range = HIGH3 - structural_invalidation`, the existing canonical
   `EXTENSION_RATIOS` are reused without additions or tuning:

   `target = structural_invalidation + reference_range * extension_ratio`

   These candidates use source `CONTINUATION_FIB_EXTENSION` and retain the
   extension ratio plus both frozen reference prices. The structural
   descriptive `fib_retracement_ratio` is never a Decision gate or target
   anchor.

No legal candidate produces `NO_TRADE / NO_VALID_TARGET`.

## R/R and position sizing

The shared `trading.risk.risk_reward()` calculator is applied only after T1–T3
exist. T1 is the gate:

- `RR < 2`: `NO_TRADE / RR_BELOW_MINIMUM`
- `2 <= RR < 3`: `NORMAL`
- `3 <= RR <= 5`: `HIGH_QUALITY`
- `RR > 5`: `HIGH_ASYMMETRY`

For `RR > 5`, the implementation records a provenance/geometry audit. It
checks `structural_invalidation < HIGH3`, `execution_stop < planned_entry`,
all targets above entry, legal target provenance, and the frozen continuation
Fib reference leg. It introduces no historical performance parameter. A
failed audit is an invalid structure/provenance failure; a valid high-asymmetry
plan is not rejected merely because it is above 5R.

`position_size()` is reused only with explicitly supplied `risk_capital`. When
that input is absent, the output records `position_size_required_input =
risk_capital`; NAV, holdings-derived capital, broker, and account data are not
read.

## Exact T+1 OPEN classification

Only a T-day `ENTRY_ALLOWED` plan attempts execution. The executor selects the
exact next market session from the existing session set and reads only that
bar's `OPEN`; it never reads T+1 high, low, or close. A missing exact bar does
not fall forward to T+2.

- no exact bar: `SKIP_NO_T1_BAR`
- `open <= structural_invalidation`:
  `SKIP_BELOW_INVALIDATION`
- `structural_invalidation < open < HIGH3`:
  `SKIP_GAP_BELOW_CONFIRMATION`
- `open > entry_zone_high`: `SKIP_GAP_ABOVE_ENTRY_ZONE`
- inclusive allowed zone: reuse frozen T1–T3 and execution stop, set
  `actual_entry = T+1 OPEN` only if actual-open T1 R/R is at least 2;
  otherwise `SKIP_RR_BELOW_MINIMUM_AT_OPEN`
- passing allowed-zone/open-RR checks: `EXECUTED`

`actual_entry != None` if and only if `outcome == EXECUTED`. Observed
`t1_open` is retained on all exact-session outcomes where an OPEN was read.

## Development funnel and operational gate

`research/setup02_decision_funnel.py` and
`scripts/run_setup02_decision_funnel.py` consume the frozen
`DEVELOPMENT_EXPOSED` v2 dataset and report total conservation, CN/US,
per-symbol counts, decision reasons, target source and extension-ratio
provenance, R/R quality, >5R audits, missing T+1 bars, exact-once identity,
and the execution ledger invariant.

`scripts/run_setup02_generic_operational_shadow.py` is synthetic-only. It
covers exactly-once consumption, terminal filtering, T→T+1 OPEN behavior,
gap branches, open-time R/R, fail-closed handling, reporting, and the ledger
invariant. It does not read holdings, account secrets, Sheets, or broker data.

The funnel and shadow explicitly mark returns, forward returns, MFE, MAE,
P&L, expectancy, profit factor, and Final OOS as not accessed. No Decision/Risk
result can change the frozen structural lifecycle, ATR, Entry Zone, R/R rules,
target ratios, Swing, Wave, or SETUP_02 lifecycle.
