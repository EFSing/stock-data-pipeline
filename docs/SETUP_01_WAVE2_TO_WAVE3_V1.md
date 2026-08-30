# SETUP_01 Wave 2 → Wave 3 v1

## Scope and identity

`SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1` is a structural lifecycle evaluator
for `SETUP_01`. It consumes `WAVE-SCENARIO-ENGINE-2026-08-30-v1` and stops at
structural `CONFIRMED` / `FAILED` events. It does not call
`decide_platform_breakout()`, does not emit `ENTRY_ALLOWED`, and does not
write production Sheets.

The implementation is in `trading/setup01.py` and
`trading/setup01_replay.py`. `trading/setup.py` and `trading/decision.py`
remain the unchanged SETUP_03 Platform Breakout path.

## Eligible Wave context

v1 uses the Wave Engine **primary** scenario only. A valid context requires:

1. primary family is `WAVE_2_TO_3_CANDIDATE`;
2. `setup01_context_eligible` is true;
3. weekly parent state is not `DOWNTREND`;
4. the three confirmed Swing identities are, in pivot order, Wave 1
   origin `LOW`, Wave 1 peak `HIGH`, and subsequent Wave 2 low `LOW`;
5. all three Swing points have `confirmed_index <= t`;
6. `Wave1 peak > Wave1 origin`; and
7. `Wave2 low > Wave1 origin`; and
8. `Wave2 low < Wave1 peak`, so the later LOW is an actual retracement and
   not merely a subsequent low above the peak.

Any failed requirement prevents a new valid lifecycle. The alternate Wave
scenario is retained for diagnostics and is not an eligibility override. An
explicit primary `ABC_CORRECTION_CANDIDATE` or weekly `DOWNTREND` therefore
blocks confirmation.

## Lifecycle contract

Only these states exist:

`NONE → WATCH ↔ ARMED → CONFIRMED` and `WATCH/ARMED → FAILED`.

- `NONE`: no eligible primary Wave 2 → Wave 3 context.
- `WATCH`: the confirmed Wave 1 / Wave 2 context exists, but causal recovery
  has not reached the fixed threshold.
- `ARMED`: the structure remains valid and
  `close >= Wave2 low + 0.5 × (Wave1 peak − Wave2 low)`, while
  `close <= Wave1 peak`. The threshold is fixed by protocol, uses only the
  current confirmed context and current close, and is not selected from
  returns or any outcome metric. A subsequent close below it returns to
  `WATCH` while remaining above the invalidation levels.
- `CONFIRMED`: `daily close > Wave1 peak` strictly. Equality is not enough.
- `FAILED`: before confirmation, either the current lifecycle loses its Wave
  context, the weekly parent becomes `DOWNTREND`, the primary context becomes
  an explicit ABC correction, or price reaches a structural invalidation.

No `ACTIVE` or `COMPLETED` state is implemented. A terminal lifecycle is not
backfilled or repeated. A new confirmed Wave 1 origin/peak can start a new
lifecycle; a changed pre-confirmation context updates the current context
without inventing a synthetic failure event.

## Two invalidations

- Wave-scenario invalidation: `Wave1 origin`; a close `<= origin` fails the
  current pre-confirmation lifecycle.
- SETUP_01 trade-structure invalidation: confirmed `Wave2 low`; a close
  `<= Wave2 low` fails the current pre-confirmation lifecycle.

They are separate output fields and are never collapsed into one stop. These
are structural diagnostics, not execution stops.

## Fibonacci contract

The evaluator reuses `trading.fibonacci.py` and its canonical retracement
ratios `0.382`, `0.5`, `0.618`, and `0.786`. It reports the Wave 2
retracement ratio and adjacent canonical region, including explicit outside
labels where needed. Fib is descriptive context only; no Fib level confirms
the setup and no parameter grid is introduced.

## As-of replay and event identity

`replay_setup01_history()` evaluates every visible bar from a strict prefix.
The Wave Engine receives only `quotes[:index + 1]`, and its confirmed Swing
filter remains the single source of Wave structure. For an explicit
`as_of_date`, all later bars are excluded before evaluation. Appending future
bars therefore cannot rewrite a historical snapshot or event.

Only first-entry `CONFIRMED` and `FAILED` events are emitted. The deterministic
identity is:

`symbol|SETUP_01|trade_date|event_type|lifecycle=<index>`

The event type is part of the identity, so confirmation and failure cannot be
silently conflated or duplicated.

The structural projection explicitly separates a persisted terminal lifecycle
from a new event on the current as-of date:

- `terminal_event_type` and `terminal_event_date` retain the historical
  `CONFIRMED`/`FAILED` event for the current lifecycle;
- `is_new_confirmed_event_as_of` is true only when
  `state == CONFIRMED` and `confirmed_date == as_of_date`;
- `is_new_failed_event_as_of` is true only when
  `state == FAILED` and `failed_date == as_of_date`;
- `is_live_preconfirmation_candidate` is true only for `WATCH` or `ARMED`.

Consequently, a historical terminal `CONFIRMED` snapshot remains visible on a
later date but is not a new signal and cannot be re-decided. These are
read-only projection fields; they do not change lifecycle transitions, event
identity, or event counts.

## Development-only output boundary

The structural replay uses the frozen `DEVELOPMENT_ONLY` holdout input already
present under ignored `artifacts/phase5j_v3_development_holdout/`. It reports
lifecycle state days, `CONFIRMED` / `FAILED` event counts and dates, Wave
family distributions, per-market counts, current candidates and block
reasons. It does not read or calculate returns, forward returns, MFE, MAE,
P&L, win rate, expectancy, Final OOS, or formal Phase 5K data.

The existing read-only Wave shadow now includes a nested SETUP_01 snapshot for
each fresh, data-qualified enabled holding. It outputs the weekly/daily state,
primary/alternate Wave family, SETUP_01 state, three Wave Swing fields, Fib
region, confirmation/invalidation levels, reason, freshness and error. It
continues to write only JSON/CSV artifacts and does not write Sheets,
Decision, production signals, or trading fields. Provider and freshness
failures remain fail-closed; no provider is guessed and no OHLC is filled.
