# Position Management + Exit v1 Protocol

Status: `POSITION_MANAGEMENT_EXIT_V1_PREMERGE_HARDENED_READY_FOR_SOL_REVIEW`

Protocol identity: `POSITION-MANAGEMENT-EXIT-2026-09-02-v1`

Machine-readable contract: `research/protocols/position_management_exit_v1.json`。

## Scope

This is a read-only `DEVELOPMENT_EXPOSED` mechanical replay downstream of the
frozen SETUP_01/SETUP_02 execution ledgers. Only rows with
`outcome == EXECUTED` become positions. Non-executed rows are ignored; no new
entry is generated and Position Management never re-screens an entry.

Each position freezes source setup and event identity, symbol/market, execution
date and actual entry, initial execution stop, initial structural invalidation,
T1/T2/T3, original Wave anchors, and initial risk/share. `PositionTarget`
copies the first three Decision target candidates in their original
price/order/source/provenance order; target prices are never recomputed after
execution. `1R` is exactly
`actual_entry - initial_execution_stop > 0` for the life of the position.

## Causal daily state

After entry, each observed bar records CurrentR, MFE_R, MAE_R and MFE Drawdown R
from only the current and prior bars. Targets are diagnostic state only:
`NOT_REACHED`, `T1_REACHED`, `T2_REACHED`, or `T3_REACHED`, using HIGH; reaching a
target never auto-sells.

The initial stop is active immediately. A structurally confirmed higher-low may
propose `higher-low - 0.5 * ATR14`, only when it is above the active stop and
below the T close. A new stop is active on the next session and stops never move
down. ATR is descriptive fixed protocol input; no replay threshold is tuned.

The MFE floor starts at the first MFE >= 2R, allows a maximum 1R giveback, and is
`entry + (MFE_R - 1R) * 1R`. It is monotonic and becomes active next session. A
close below a new floor creates `PROFIT_PROTECTION_EXIT_PENDING`, whose earliest
execution is next OPEN.

Stop execution is mechanical: next-session OPEN at or below the active stop is
`EXIT_GAP_BELOW_STOP` at OPEN; otherwise LOW at or below the active stop is
`EXIT_STOP_TRIGGERED` at the active stop. Structural invalidation/protected
higher-low close failure creates `STRUCTURAL_EXIT_PENDING`, also earliest next
OPEN. Structural pending takes precedence over MFE pending when both occur.

## Wave5 context and action priority

For still-open three-wave positions, context is only
`NO_WAVE5_CONTEXT`, `WAVE4_PULLBACK_CONTEXT`, or `WAVE5_CANDIDATE`. It requires
confirmed `HIGH3 -> LOW4`, `LOW4 > original Wave2 low`, and a strict T close
above HIGH3. The record preserves supporting evidence, counter-evidence,
invalidation, and swing provenance. It can create `NO_ADD` or advisory
`PROFIT_PROTECTION`, never a full exit and never a new entry.

Risk flags are independent advisories: Wave5 candidate, provenance-qualified
Fib target proximity/reached, provenance-qualified confirmed-swing target
proximity/reached, abnormal high volume, price stall, long upper wick, and
momentum divergence. A confirmed-swing target is never labelled Fib; a
dual-source target may emit both labels. Action priority is confirmed exit -> `EXIT`, pending
structural/MFE -> `PROFIT_PROTECTION`, Wave5 -> `NO_ADD`, raised stop/high-risk
flag -> `PROFIT_PROTECTION`, otherwise `HOLD`.

## Evidence boundary

The replay may emit positions, position-days, R diagnostics, stop raises,
pending/exit counts, Wave4/Wave5 context, target reach, action counts, causal
conservation checks, and per-symbol ledgers. It must not emit or calculate win
rate, aggregate P&L, expectancy, profit factor, Sharpe, optimized thresholds,
or Final OOS. It does not access holdings, broker/account data, production
Sheets, or production execution.

Synthetic fixtures cover frozen 1R, confirmed/provisional swing timing, next
session activation, gap/intraday stop paths, MFE trigger/floor/giveback, target
tracking without auto-sell, structural pending, Wave4/Wave5 strictness, NO_ADD,
terminal exit behavior, future-append invariance, and read-only operational
terminal exit behavior, future-append invariance, and read-only operational
controls. The one-time frozen replay cache audit compares the strict original
prefix path and cached path for every frozen bar and every Wave/SETUP snapshot
and event field; its exact canonical digests are recorded in the replay
artifact under `cache_semantic_parity`.
