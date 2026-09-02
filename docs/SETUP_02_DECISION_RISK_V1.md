# SETUP_02 Decision/Risk v1 Protocol

Status: `SETUP_02_DECISION_RISK_V1_GEOMETRY_CORRECTED_READY_FOR_SOL_REVIEW`

Protocol identity: `SETUP-02-DECISION-RISK-2026-09-02-v2`

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

## Pre-merge geometry correction

The pre-merge version used the wrong continuation-Fib reference leg:
`structural_invalidation → HIGH3`. With `D = HIGH3 - structural_invalidation`,
`planned_entry > HIGH3`, and `execution_stop < structural_invalidation`, that
geometry gives `RR < r - 1` for every extension ratio `r`. The largest existing
ratio is `2.618`, so the target family is mathematically bounded below
`1.618R`, before the ATR stop buffer lowers R/R further. This was recorded as
`PREMERGE_TARGET_GEOMETRY_DEFECT`; it was an ex-ante structural correction,
not outcome-driven tuning. The minimum R/R remains `2`; the Entry Zone and stop
are unchanged.

The twelve pre-correction `INVALID_STRUCTURE` rows were audited in the causal
Decision prefix. Each has `structural_invalidation >= HIGH3` and is therefore
classified as `STALE_CONFIRMATION_GEOMETRY`. The Decision layer fails closed;
the upstream structural lifecycle is not changed. The machine-readable audit
is emitted as `setup02_invalid_structure_geometry_audit.csv`.

The deterministic audit rows are:

| symbol | T date | LOW0 | HIGH1 | LOW2 | HIGH3 | structural_invalidation | T close | exact reason |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 000963.SZ | 2018-02-14 | 20.94123232 | 23.08316879 | 21.40586448 | 25.14012930 | 26.39468546 | 27.12487635 | `STALE_CONFIRMATION_GEOMETRY` |
| 601117.SH | 2024-11-04 | 6.84641309 | 7.28271585 | 6.90192025 | 7.29223574 | 7.39695453 | 7.82534958 | `STALE_CONFIRMATION_GEOMETRY` |
| 601390.SH | 2025-11-07 | 4.83098808 | 5.38336850 | 5.15867138 | 5.39273088 | 5.41205840 | 5.47004474 | `STALE_CONFIRMATION_GEOMETRY` |
| 601658.SH | 2025-01-08 | 4.07612200 | 4.50975200 | 4.31895480 | 4.63175427 | 4.93322940 | 5.11619295 | `STALE_CONFIRMATION_GEOMETRY` |
| 603893.SH | 2025-02-14 | 51.43548100 | 60.59158670 | 54.69076670 | 68.44951200 | 95.23633250 | 167.43285256 | `STALE_CONFIRMATION_GEOMETRY` |
| AI | 2023-07-21 | 11.28999996 | 13.60000038 | 11.71000004 | 14.97000027 | 31.56999969 | 38.02999878 | `STALE_CONFIRMATION_GEOMETRY` |
| INTC | 2023-07-28 | 24.44444235 | 29.29475870 | 27.23120532 | 29.40083064 | 30.75315878 | 36.09429550 | `STALE_CONFIRMATION_GEOMETRY` |
| INTC | 2026-06-08 | 32.88999939 | 44.02000046 | 34.95000076 | 54.59999847 | 102.40000153 | 110.26999664 | `STALE_CONFIRMATION_GEOMETRY` |
| MU | 2018-04-25 | 38.09860488 | 45.63642314 | 39.75634446 | 45.81194399 | 46.08498813 | 46.41652679 | `STALE_CONFIRMATION_GEOMETRY` |
| MU | 2021-12-20 | 69.34201205 | 73.74963195 | 69.42003158 | 73.99342236 | 78.63754247 | 80.10230255 | `STALE_CONFIRMATION_GEOMETRY` |
| RKLB | 2025-09-22 | 20.23200035 | 30.78000069 | 25.52000046 | 32.70000076 | 42.38999939 | 49.81000137 | `STALE_CONFIRMATION_GEOMETRY` |
| ROP | 2024-02-06 | 472.45488091 | 494.64232314 | 480.13814595 | 498.72897877 | 511.98955017 | 535.91870117 | `STALE_CONFIRMATION_GEOMETRY` |

## Target-first construction

Targets are built before R/R is calculated. A valid candidate must be strictly
above `planned_entry`, and candidates are merged by exact price, sorted
ascending, and truncated to the three nearest legal prices as `T1`, `T2`, and
`T3`.

1. T-known confirmed swing highs: only `HIGH` swings with pivot and
   confirmation provenance available as of T are accepted.
2. Wave 3 continuation Fib extensions: SETUP_02 is already inside a started
   Wave 3, so the projection reuses the original Wave 3 geometry shared with
   SETUP_01. The only reference leg is `LOW0 → HIGH1`, with `LOW2` as the
   projection base. For `wave1_length = HIGH1 - LOW0 > 0`, the existing
   canonical `EXTENSION_RATIOS` are reused without additions or tuning:

   `target = LOW2 + (HIGH1 - LOW0) * extension_ratio`

   These candidates use source `WAVE3_FIB_EXTENSION`. Their provenance retains
   LOW0, HIGH1, LOW2, the extension ratio, and formula identity
   `LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO`. The structural
   `structural_invalidation` remains only the structural invalidation and
   execution-stop anchor; it is not a Wave 3 target anchor. The descriptive
   `fib_retracement_ratio` is never a Decision gate or target anchor.

After all canonical Wave 3 and T-known confirmed swing-high candidates are
generated, only candidates strictly above `planned_entry` remain. They are
merged by price, sorted ascending, and the nearest three are T1/T2/T3. A
nearest remaining target is never skipped because its R/R is below 2 in order
to manufacture a more distant passing target; Target first, then R/R.

## Old → corrected deterministic delta

On the same 213 first-entry events and frozen v2 input, the pre-merge draft
versus corrected Decision-only counts are:

| field | pre-merge draft | corrected protocol |
|---|---:|---:|
| `ABOVE_ENTRY_ZONE` | 97 | 97 |
| stale/invalid geometry | `INVALID_STRUCTURE=12` | `STALE_CONFIRMATION_GEOMETRY=12` |
| `NO_VALID_TARGET` | 0 | 1 |
| `RR_BELOW_MINIMUM` | 104 | 102 |
| `ENTRY_ALLOWED` | 0 | 1 |
| T+1 attempts | 0 | 1 |
| T+1 classification | none | `SKIP_GAP_BELOW_CONFIRMATION=1` |

Confirmed swing-high candidates remain 771 plus one merged dual-source price.
The old continuation-Fib candidate family had 414 candidates under its old
source label; the corrected `WAVE3_FIB_EXTENSION` family has 321 standalone
candidates plus that same merged price. Corrected all-provenance extension
ratio counts are `1.272=61`, `1.618=75`, `2.0=84`, and `2.618=102`; corrected
T1 sources are confirmed swing high `44` and Wave3 Fib `59`. These are only
formula, gate, target, and T+1 classifications; no forward-performance field
is part of the delta.

If every canonical projection and T-known swing high is at or below the T-day
planned entry, the layer returns `NO_TRADE / NO_VALID_TARGET`; it does not
look ahead or select a farther target to manufacture R/R.

## R/R and position sizing

The shared `trading.risk.risk_reward()` calculator is applied only after T1–T3
exist. T1 is the gate:

- `RR < 2`: `NO_TRADE / RR_BELOW_MINIMUM`
- `2 <= RR < 3`: `NORMAL`
- `3 <= RR <= 5`: `HIGH_QUALITY`
- `RR > 5`: `HIGH_ASYMMETRY`

For `RR > 5`, the implementation records a provenance/geometry audit. It
checks `structural_invalidation < HIGH3`, `execution_stop < planned_entry`,
all targets above entry, legal target provenance, and the corrected Wave3
reference identity `LOW2 + (HIGH1-LOW0) * existing extension ratio`. It
introduces no historical performance parameter. A
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
the execution ledger invariant, and the causal stale-geometry audit.

`scripts/run_setup02_generic_operational_shadow.py` is synthetic-only. It
covers exactly-once consumption, terminal filtering, T→T+1 OPEN behavior,
gap branches, open-time R/R, fail-closed handling, reporting, and the ledger
invariant. It does not read holdings, account secrets, Sheets, or broker data.

The funnel and shadow explicitly mark returns, forward returns, MFE, MAE,
P&L, expectancy, profit factor, and Final OOS as not accessed. No Decision/Risk
result can change the frozen structural lifecycle, ATR, Entry Zone, R/R rules,
target ratios, Swing, Wave, or SETUP_02 lifecycle.
