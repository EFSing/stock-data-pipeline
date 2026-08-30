# SETUP_01 Decision/Risk v1

## Scope and event identity

`SETUP-01-DECISION-RISK-2026-08-30-v1` is an independent T-day plan and
T+1-open feasibility evaluator. It consumes only `Setup01ReplayEvent` values
whose `event_type == CONFIRMED` and whose
`is_new_confirmed_event_as_of` is true. A repeated current `CONFIRMED` state is
not a new event. The event identity is the SETUP_01 replay identity, and the
stream evaluator emits at most one Decision for each identity.

It does not import or call `decide_platform_breakout()` and does not alter the
SETUP_03 path. It does not read returns, MFE, MAE, P&L, Final OOS, or any other
outcome metric.

## Time contract

- T is the daily close that is strictly above the Wave 1 peak and creates the
  first `CONFIRMED` event.
- T can create a Decision/plan only.
- The earliest execution observation is the exact next market session after T,
  resolved from the existing `research.market_sessions` session-set SSOT,
  using only that session's `OPEN`.
- If that expected session's bar is missing for the symbol, execution is
  `SKIP_NO_T1_BAR`; a later observed bar is never substituted. Weekend and
  holiday gaps are resolved by the same market-session set, not by a second
  calendar rule.
- Same-bar execution is forbidden. T+1 high/low/close are not read.

## Entry and invalidation

For a long plan:

```text
confirmation_level = Wave 1 peak
planned_entry      = T close
entry_zone_low     = Wave 1 peak
entry_zone_high    = Wave 1 peak + 0.5 * ATR14(T)
```

If `planned_entry > entry_zone_high`, the Decision is `NO_TRADE` with
`ABOVE_ENTRY_ZONE`. The evaluator never widens this zone to create more
trades.

Structural invalidations remain separate:

```text
Wave Scenario Invalidation = Wave 1 origin
SETUP_01 Structural Invalidation = confirmed Wave 2 low
Execution Stop = Wave 2 low - 0.5 * ATR14(T)
```

ATR14 is the existing causal Wilder ATR as of T. The execution stop is a risk
stop and never overwrites either structural invalidation.

At T+1 OPEN, an `ENTRY_ALLOWED` plan is classified as:

- `SKIP_BELOW_INVALIDATION` when `open <= confirmed Wave 2 low`;
- `SKIP_GAP_BELOW_CONFIRMATION` when the open is below the confirmation level
  but above invalidation;
- `SKIP_GAP_ABOVE_ENTRY_ZONE` when the open is above the entry-zone high;
- `SKIP_RR_BELOW_MINIMUM_AT_OPEN` when the open is inside the inclusive entry
  zone but the actual-open first-target R/R is below 2;
- `EXECUTED` when the open is inside the inclusive allowed entry zone, the
  structure remains valid, and actual-open first-target R/R is at least 2;
- `SKIP_NO_T1_BAR` when the exact expected next session bar is missing.

The T-day `targets` and `execution_stop` are frozen before execution. When an
in-zone T+1 OPEN is available, execution-time R/R calls the existing shared
calculator with only `actual_entry=T+1 OPEN`, those frozen targets, and that
frozen stop. It does not choose a new target, adjust the stop, widen the zone,
change the 2R threshold, or consume T+1 high/low/close.

## Target, R/R and position risk

Target is calculated before R/R. Candidates are only derived from:

1. confirmed swing highs known by T and above planned entry; and
2. Wave 1 length projections using the existing `trading.fibonacci.EXTENSION_RATIOS`:

```text
reference_range = Wave 1 peak - Wave 1 origin
projection = Wave 2 low + reference_range * existing extension ratio
```

Candidates retain source and reason, are sorted by price, de-duplicated by
price, and the first three become T1/T2/T3. If none is valid, the gate is
`NO_VALID_TARGET`.

Each T1 candidate also carries a compact descriptive provenance audit: source,
confirmed-swing pivot/confirmation dates and session ages when applicable,
Fib extension ratio when applicable, planned entry, observed T+1 OPEN, actual
entry, planned and actual-open first-target R/R, quality, >5R flags, and the
existing target provenance/geometry check. This audit adds no target lookback,
age threshold, or new target filter. A >5R or stale historical swing
observation is evidence for Sol review only; it does not create a new gate.

## Execution ledger and development session identity

The execution ledger has a strict field invariant:

```text
actual_entry != None  if and only if  outcome == EXECUTED
```

`t1_open` is the observed price at the exact T+1 OPEN and is retained for
diagnostics. `actual_entry` represents only a real executed fill. Therefore an
in-zone OPEN that fails the actual-open R/R gate is recorded as
`SKIP_RR_BELOW_MINIMUM_AT_OPEN` with `t1_open` and `actual_rr` populated but
`actual_entry=None`. All other skip outcomes also keep `actual_entry=None`.

Development T+1 session identity is formally:

```text
DEVELOPMENT_SESSION_IDENTITY = FROZEN_DATASET_MARKET_SESSION_SET
```

The existing `research.market_sessions` helper builds the sorted union of
local `Quote.trade_date` values across all symbols in the frozen dataset for
each market. Development T+1 means the next session in that observed set.
This prevents a missing symbol bar from falling forward to T+2, but cannot
prove that a real session is present when the entire frozen market universe is
missing that date. Production execution therefore requires:

```text
PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION
```

This prerequisite is not a PR #37 blocker, is not implemented here, does not
add a third-party calendar, and does not change the development funnel.

The existing `trading.risk.risk_reward()` and `position_size()` are reused:

```text
RR = (Target - Entry) / (Entry - Execution Stop)
RR < 2       -> NO_TRADE / RR_BELOW_MINIMUM
2 <= RR < 3  -> NORMAL
3 <= RR <= 5 -> HIGH_QUALITY
RR > 5       -> HIGH_ASYMMETRY + target reasonableness check
```

Risk capital is an explicit input. When it is not reliable for a holdings
shadow, no NAV or position size is guessed; the output carries
`risk_per_share` through R/R and `position_size_required_input=risk_capital`.

## Historical funnel and holdings shadow

The development funnel consumes the existing `DEVELOPMENT_EXPOSED`
SETUP_01 CONFIRMED event stream and reports conserved counts by total, market
(`CN`/`US`), and symbol:

```text
CONFIRMED
 -> Decision calculable
 -> ENTRY_ALLOWED or NO_TRADE(reason)
 -> T+1 execution attempt
 -> EXECUTED or skip(reason)
```

Decision reasons are `ATR_UNAVAILABLE`, `ABOVE_ENTRY_ZONE`,
`NO_VALID_TARGET`, `RR_BELOW_MINIMUM`, `INVALID_STRUCTURE`, and
`ENTRY_ALLOWED`. Execution reasons include
`SKIP_GAP_BELOW_CONFIRMATION`, `SKIP_GAP_ABOVE_ENTRY_ZONE`,
`SKIP_BELOW_INVALIDATION`, `SKIP_NO_T1_BAR`,
`SKIP_RR_BELOW_MINIMUM_AT_OPEN`, and `EXECUTED`.

The default operational gate is
`scripts/run_setup01_generic_operational_shadow.py`, which uses only the
controlled public `GENERIC.*` synthetic holdings fixture. It validates
Decision/Risk, event-identity exactly-once, T-to-T+1 OPEN timing, terminal
semantics, fail-closed behavior, and JSON/CSV reporting without real holdings
or account secrets.

Real holdings shadow is a separate product-governance category:

```text
classification = OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION
status         = NOT_RUN_USER_PRIVACY
```

It is not a default SETUP_01 research/development blocker. This task does not
read real holdings or emit holdings-derived information to GitHub Actions. Only
a future, explicitly named production milestone that requires real-holdings
integration may make this validation a scope-local blocker.
