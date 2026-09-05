# Portfolio Risk V1 Protocol

Status: `PR_70_SOL_REVIEW_FIX_READY`

Protocol identity: `PORTFOLIO-RISK-2026-09-02-v1`

Machine-readable contract: `research/protocols/portfolio_risk_v1.json`。

## Scope and layer boundary

Portfolio Risk is a conservative, fail-closed capacity gate downstream of the
frozen SETUP_01 / SETUP_02 Individual Decision layer:

```text
Individual Decision ENTRY_ALLOWED
→ Portfolio Risk reservation
→ T+1 OPEN individual execution gate
→ open portfolio position only when EXECUTED
```

It does not modify Entry geometry, Wave, Swing, Target, minimum R/R, Position
Management, Exit, or Wave5 rules. It does not create an entry or rescreen a
candidate. The implementation is independent in `trading/portfolio_risk.py`.

## Fixed risk unit and explicit allocation budget

The frozen system risk unit is:

```text
BASE_RISK_FRACTION = 0.005
planned_risk_capital = allocation_budget * 0.005
quantity = risk_capital / abs(entry - execution_stop)
```

The existing `trading.risk.position_size()` engine is reused and theoretical
quantity is retained. V1 does not round for A-shares, US shares, purchasing
power, margin, or FX conversion. Portfolio Risk never narrows stop distance to
fit capacity.

`DEVELOPMENT_EXPOSED` replay retains its fixed normalized `reference_nav = 1.0`
compatibility contract. This is normalized risk-unit accounting, not P&L or a
simulated account balance. In production, strategy proposal generation does
not enter this layer and does not require account NAV.

Production allocation enters this layer only when the user explicitly approves
the published proposal's event identity (`approved_event_identities`) and
supplies an explicit positive `allocation_budget`; missing input returns
`ALLOCATION_BUDGET_REQUIRED`. A budget alone never grants approval: a budget
with an empty approval set yields zero reservations and zero pending, and an
approval of a missing, unpublished, already-pending or already-settled
identity fails closed without changing the proposal. Approval is matched by
exact event identity, never guessed per symbol.

`allocation_budget` is the total strategy budget the user authorizes for the
account's entire strategy risk ledger. It is not broker NAV, account equity,
account total assets, deposits/withdrawals, P&L, purchasing power, or a
new-cash tranche. Existing system-managed open positions and the same-run
approved proposals share this budget as the Portfolio Risk denominator.
Account NAV, assets, deposits, withdrawals, P&L and purchasing power are never
used as a substitute.

## Total and concentration gates

```text
MAX_TOTAL_OPEN_RISK_FRACTION = 0.02
MAX_RISK_PER_GROUP_FRACTION = 0.01
```

For each open long position:

```text
remaining_loss_risk_per_share = max(actual_entry - active_protective_stop, 0)
remaining_loss_risk_fraction = quantity * remaining_loss_risk_per_share / allocation_budget
portfolio_open_risk = sum(remaining_loss_risk)
```

This is remaining capital-loss risk, not mark-to-stop giveback risk. Current
price does not participate in this capacity calculation. If the active
protective stop is at or above the frozen actual entry, remaining loss risk is
zero. Locked profit is never a negative offset for other positions. A new
proposal is allowed only when total current open risk plus its `0.5%` initial
risk is at most `2%`; otherwise the gate emits
`BLOCK_TOTAL_RISK_BUDGET`. Equality at the boundary is allowed.

In production this denominator is the user-supplied `allocation_budget`; the
development replay keeps its fixed normalized `reference_nav = 1.0` for
backward-compatible mechanical evidence.

Every open position must carry a finite frozen `actual_entry`. Missing entry
provenance fails closed under
`PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING`; Portfolio
Risk never falls back to current price.

The same canonical symbol can have only one open long position. A duplicate
is blocked with `BLOCK_EXISTING_POSITION_SAME_SYMBOL`; ADD is not implemented
in this phase. Position Management `NO_ADD` is also respected for a same-symbol
new-entry request.

## Risk groups and market diagnostics

`risk_group` is supplied only from reliable existing sector metadata. V1 does
not infer a group from historical price correlation and does not add an
external industry provider. Missing metadata is `UNKNOWN`:

- development allows the candidate through total risk with advisory flag
  `RISK_GROUP_UNKNOWN`;
- production fails closed with `BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION` until the
  current candidate has accepted metadata or UNKNOWN is explicitly accepted.

For a known group, current group risk plus the proposed `0.5%` must be at most
`1%`; otherwise the gate emits `BLOCK_RISK_GROUP_CONCENTRATION`. CN/US open
risk and position counts are recorded as diagnostics only. V1 adds no market
hard cap and does not derive a threshold from the 40-symbol replay.

## Deterministic competition and T+1 settlement

Candidates from the same Decision session are sorted by:

1. `HIGH_ASYMMETRY`, then `HIGH_QUALITY`, then `NORMAL`;
2. T1 planned R/R descending within the same quality;
3. canonical symbol ascending.

No future return, MFE, MAE, historical win rate, sector performance, or manual
order participates. Each candidate is checked once. An accepted reservation
is immediately released when the exact individual T+1 execution result is not
`EXECUTED`; it cannot permanently consume capacity. Only an `EXECUTED`
settlement creates one frozen-quantity open portfolio position.

## Position Management interaction

Each session reads the already-frozen Position Management active protective
stop. A stop raise can reduce future remaining capital-loss risk, but Portfolio
Risk does not change the stop, MFE floor, exit behavior, or account NAV. The corrected
before/after diagnostic is the same entry-to-stop formula, and a stop raise
must satisfy `after <= before`. When Position Management exits a position,
that position is removed from the next session's open-risk ledger and its
remaining portfolio risk becomes zero. Gap/slippage loss beyond the stop is
execution tail risk and is intentionally outside this capacity budget:
`GAP/SLIPPAGE TAIL RISK NOT MODELED IN PORTFOLIO_RISK_V1`.
Wave5 creates no new strategy; its `NO_ADD` action cannot be overridden for
the same symbol.

## Development replay and evidence boundary

`research/portfolio_risk_replay.py` composes the frozen v2 SETUP_01/SETUP_02
Decision/Execution streams with Position Management v1 output. The replay may
report proposals, reservation and release ledgers, block reasons, risk before
and after, risk-group/market exposure, deterministic ordering, final executed
positions, stop-raise/exit capacity release, and exact-once/conservation
checks. It does not calculate return, portfolio P&L, equity curve, drawdown,
Sharpe, win rate, expectancy, profit factor, optimization, or Final OOS.

The synthetic operational shadow covers all 17 frozen boundary cases in the
machine-readable protocol. It is synthetic-only and does not access brokers,
holdings, account values, Secrets, or Sheets.

## Production prerequisites

Before production Portfolio Risk allocation for an approved proposal, the
system must provide:

```text
STRATEGY_PROPOSAL_APPROVAL_REQUIRED (when the published proposal event identity is not explicitly approved)
ALLOCATION_BUDGET_REQUIRED (when the explicit user budget is absent)
PRODUCTION_RISK_GROUP_METADATA_REQUIRED_FOR_NEW_ENTRY
```

The strategy proposal may be produced without any of those allocation inputs,
and an `ENTRY_ALLOWED` stays `STRATEGY_PROPOSAL` until approval and budget are
both present. `reference_nav` remains only in lower-level/replay compatibility
signatures; production allocation uses the explicit budget. IBKR, broker
holdings, account secrets, Google Sheets account values, and production
execution wiring are intentionally outside this phase.
