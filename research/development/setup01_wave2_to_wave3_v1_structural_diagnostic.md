# SETUP_01 Wave 2 → Wave 3 v1 structural diagnostic

This is a development-only, structure-only diagnostic for
`SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`. It replays the frozen 40-symbol
development holdout through strict historical prefixes and the formal Wave
Scenario Engine v1. It is not a production signal, Decision, Risk, or OOS
result.

## Result

- 40/40 symbols evaluated; 86,305 replay days; 0 evaluator errors.
- 1,404 lifecycle events: 745 `CONFIRMED`, 659 `FAILED`.
- Event markets: CN 299/313 (`CONFIRMED`/`FAILED`), US 446/346.
- Final per-symbol states: CN 8 `CONFIRMED`, 12 `FAILED`; US 1 `ARMED`, 5
  `CONFIRMED`, 14 `FAILED`.
- The only non-terminal current candidate is `STX` (US), `ARMED`, as of
  `2026-08-26`; its Fib context is ratio `0.7180753779527214`, region
  `0.618-0.786`, and confirmation level `921.780029296875`.

## Blocking / ambiguity profile

The primary Wave families were: `WAVE_2_TO_3_CANDIDATE` 21,439,
`WAVE_3_CONTINUATION_CANDIDATE` 9,313, `UPTREND_UNKNOWN_WAVE` 28,644,
`ABC_CORRECTION_CANDIDATE` 3,644, `DOWNTREND_OR_INVALID_FOR_LONG` 21,137,
and `NO_VALID_SCENARIO` 2,128 state-days. `NONE` without an eligible primary
SETUP_01 context accounted for 2,298 state-days. ABC and weekly downtrend
contexts are explicit blocks, not silently converted into Wave 3.

## Boundary

The replay uses only `data <= as_of_date`, confirmed causal Swings, and the
existing Fibonacci implementation. It emits only structural lifecycle
snapshots and first-entry `CONFIRMED`/`FAILED` identities. No outcome metrics,
Final OOS, production Decision, `ENTRY_ALLOWED`, or Sheets write is part of
this diagnostic. See the JSON companion for hashes and machine-readable
controls.
