# Wave Scenario Engine v1

## Scope

`WAVE-SCENARIO-ENGINE-2026-08-30-v1` is a read-only structural context
engine for `SETUP_01` and `SETUP_02`. It is not a complete Elliott Wave
counter and it never emits `ENTRY_ALLOWED`, a Decision, a target, a stop, a
return, or an OOS result.

The finite scenario families are:

- `WAVE_2_TO_3_CANDIDATE`
- `WAVE_3_CONTINUATION_CANDIDATE`
- `ABC_CORRECTION_CANDIDATE`
- `UPTREND_UNKNOWN_WAVE`
- `DOWNTREND_OR_INVALID_FOR_LONG`
- `NO_VALID_SCENARIO`

Every evaluation has a primary and an alternate scenario. Missing structure
is represented explicitly; it is never forced into a wave count.

## Causal contract

1. The input is strictly bounded to `trade_date <= as_of_date` before any
   daily, weekly, swing, structure, or Fibonacci calculation.
2. Daily structure reuses `trading.swing.find_swings()` and
   `trading.structure.market_structure()`. Only Swing points whose existing
   `confirmed_index` is available at the as-of prefix are eligible.
3. Weekly bars use the security's actual session dates. They are grouped by
   ISO week and aggregate open/high/low/close/volume from observed sessions.
   The current ISO week is excluded from the weekly parent state so an
   incomplete current-week close cannot become a historical input.
4. Weekly state is the parent context for daily state. `DOWNTREND` weekly
   context blocks long-side SETUP_01/02 context eligibility even when daily
   prices rebound.
5. Appending future bars cannot change a result when the same explicit
   `as_of_date` is supplied.

## Minimal structural rules

`WAVE_2_TO_3_CANDIDATE` requires a confirmed `LOW -> HIGH -> LOW` sequence,
the upward leg's high to exceed its origin, the retracement low to remain
above the origin, and no explicit weekly downtrend conflict. A close that has
not exceeded the impulse peak is reported as WATCH-like context; the engine
does not claim that Wave 3 has started.

`WAVE_3_CONTINUATION_CANDIDATE` requires a confirmed higher-high /
higher-low expansion sequence, daily `UPTREND`, weekly `UPTREND`, and a
current close above the latest confirmed higher-low. EMA, RSI, or Fibonacci
alone cannot produce this family.

`ABC_CORRECTION_CANDIDATE` recognizes only the bounded five-point form
`LOW(origin) -> HIGH(peak) -> LOW(A) -> HIGH(B) -> LOW(C)`, with a lower B
high, lower C low, and C still above the impulse origin. This is deliberately
used as a counter-scenario to avoid calling every rebound Wave 3.

The remaining families are conservative fallbacks for downtrend, incomplete,
ambiguous, or invalid structure. Each scenario carries the relevant confirmed
Swing identities, legs, evidence, counter-evidence, invalidation reason, and
context eligibility flags.

## Score and Fibonacci contract

`evidence_score` is the count of satisfied, named structural predicates in the
scenario evidence tuple. It is not a subjective confidence probability and is
not selected or calibrated against returns.

Fibonacci values come from the existing `trading.fibonacci` implementation.
The engine only converts adjacent existing levels into inclusive candidate
regions; a region is context/evidence, not a signal. Structural invalidation
comes from the impulse origin or latest confirmed higher-low and is never
manufactured to improve R/R.

## Shadow output

`scripts/run_wave_shadow.py` reads enabled holdings from `自选清单`, uses the
explicit qfq history source, and evaluates each holding as of its latest
observed bar. It writes only `wave_shadow_report.json` and
`wave_shadow_report.csv` under the workflow artifact directory and publishes
a summary. It reads Google Sheets but writes no Sheet, history, Decision, or
production configuration. The report includes weekly/daily state, primary and
alternate scenarios, confirmed Swing identities, Fibonacci regions,
invalidation, context eligibility, as-of date, and explicit `returns_accessed`
/ `oos_accessed` / `sheets_written` false markers.
