# Prospective Daily Decision Chain V1

Status: `PRODUCTION_DAILY_DECISION_CHAIN_V1_HUMAN_IN_LOOP_READY_FOR_REVIEW`

Protocol identity: `PROSPECTIVE-DAILY-DECISION-CHAIN-2026-09-02-v1`

Implementation: `trading/daily_decision_chain.py`

## Scope and boundary

This phase is a production-data prospective decision-support chain. It is not
an automated trading system and has no broker/order path:

```text
Market Data → Data Quality → Weekly/Daily State → Swing → Wave Scenario
→ SETUP_01 / SETUP_02 → Individual Decision → STRATEGY_PROPOSAL
→ explicit approval of published proposal event identity
→ explicit allocation_budget → Portfolio Risk / Position Size
→ Position Management / Wave5 context → read-only JSON/Markdown report
```

SETUP_01 and SETUP_02 remain enabled through their frozen evaluators. SETUP_03
remains `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`; SETUP_04 is not implemented.
The chain does not re-calculate Entry Zone, Target, invalidation, execution
stop, minimum R/R, or T+1 rules.

## Immutable contracts

`DailySymbolInput` requires symbol, market, T date, qfq history, data-quality
status, and a `CompletedSessionIdentity`. Every supplied bar is validated as
`data <= T`; future bars are rejected. `OpenPositionState` may intentionally
contain no `PositionOrigin`. In that case the report emits
`POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT` and leaves Current R, MFE, MAE, and
stop fields empty.

`DailyDecisionEventIdentity` is an alias to the existing SETUP event identity.
`daily_decision_event_identity()` returns the existing `SETUP_01` or `SETUP_02`
first-entry CONFIRMED identity; the chain does not create a second Setup key.
Only a new CONFIRMED event as of T enters Individual Decision.

T+1 is represented separately as `PENDING_T1_EXECUTION_CHECK` and
`T1_EXECUTION_OBSERVED`, with `execution_outcome` separately set to
`EXECUTED` or `SKIPPED`. An observed EXECUTED result only records a mechanical
decision-ledger observation and creates a frozen in-memory position origin; it
never submits a broker order.

Portfolio Risk delegates to `PORTFOLIO-RISK-2026-09-02-v1`, but is downstream
of the strategy proposal boundary. An `ENTRY_ALLOWED` individual Decision
remains visible as `STRATEGY_PROPOSAL`, with no position size, reservation or
capital allocation, until two independent inputs exist together: an explicit
user approval of the published proposal's event identity
(`approved_event_identities`) and an explicit `allocation_budget`. A budget
alone is never approval: a budget with an empty approval set yields zero
reservations and zero pending. Approval is granted per event identity, never
guessed per symbol, and an approval of a missing, unpublished, already-pending
or already-settled identity fails closed with
`STRATEGY_PROPOSAL_APPROVAL_REQUIRED` without changing the proposal. UNKNOWN
risk group keeps a development candidate visible but returns
`BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION` in production. A reservation is saved as
pending only after Portfolio Risk allows it.

`allocation_budget` is the total strategy budget the user authorizes for the
account's entire strategy risk ledger. It is not broker NAV, account equity,
account total assets, deposits/withdrawals, P&L, purchasing power, or a
new-cash tranche. Existing system-managed open positions and the same-run
approved proposals share this budget as the Portfolio Risk denominator, with
the frozen fractions `BASE_RISK_FRACTION=0.005`,
`MAX_RISK_PER_GROUP_FRACTION=0.01`, and
`MAX_TOTAL_OPEN_RISK_FRACTION=0.02` unchanged.

## Production architecture audit

| Question | Verified repository fact | Chain decision |
|---|---|---|
| Formal strategy universe | `ProductionInputAdapter` reads enabled, account-scoped rows from the formal `策略股票池`; `自选清单` remains a market-data coverage source and holdings are not a substitute. | Use the existing formal Sheet contract; fail closed with `PRODUCTION_STRATEGY_UNIVERSE_REQUIRED` when no enabled strategy row is available. No new registry/provider is added in V1. |
| Production daily/qfq data | The production adapter reads completed-session latest rows and non-empty QFQ history from the formal Sheet contracts, validates exact T coverage and rejects future/stale/duplicate data before the chain. | Reuse the existing latest/QFQ contracts and injected `DailySymbolInput` boundary; provider expansion and new adjustment semantics are out of scope for V1. |
| Authoritative strategy decision persistence | `交易决策` remains the legacy SETUP_03 surface; `策略决策状态` is the existing typed/account-scoped V1 state store for SETUP_01/02 daily identities. | Reuse `SheetsDecisionStateStore` for formal production reads and explicitly authorized state writes; use an empty `InMemoryDecisionStateStore` only as a transient read-only view for non-formal Candidate/position inputs, tests, and shadow. |
| Published-event identity ledger | Existing SETUP_01/02 replay event identities are deterministic. The existing Sheet ledger is SETUP_03-keyed. | Reuse existing SETUP_01/02 event identity; store exact-once published identities in the injected state store. |
| Production capital | Account NAV/assets are not strategy inputs. `参数设置. decision_risk_capital` is a legacy individual-decision input, not an allocation budget. | Proposal generation is independent of NAV. After user approval, Portfolio Risk accepts only explicit `allocation_budget`; account NAV is never substituted. |
| Risk-group/sector metadata | No reliable sector/risk-group metadata source is present in the production data path. | Inject accepted metadata when Portfolio Risk allocation is requested; production UNKNOWN fails closed there. |
| Real open-position origin | Holdings lifecycle tracks enabled symbols and historical data, not complete strategy position origins. Position Management has immutable replay origins only when created from an executed frozen Decision. | Require authoritative `PositionOrigin`; never derive entry/stop/origin from holdings average cost or chart history. |
| Session/calendar | `latest_completed_market_session()` and `ordinary_calendar_freshness_guard()` use source evidence plus an ordinary weekday guard. `research.market_sessions` uses a frozen observed session union and explicitly is not an exchange calendar. | T-day prospective decisions are allowed. Production T+1 execution is disabled with `PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED` until an exact exchange-calendar source is injected. |
| Current output/publish surface | Existing scheduled workflows write `最新行情`, history, validation, logs, and legacy `交易决策` through Google Sheets. | The manual runner emits machine JSON plus concise Chinese-first Markdown by default; only explicit `--write-state` may append system-owned rows to `策略决策状态`. |
| Reusable vs fail-closed | Reusable: core Quote/QC, providers/latest contracts, Wave, SETUP_01/02, frozen Decision/Risk, Portfolio Risk, Position Management/Wave5. | Fail closed: missing formal universe, accepted allocation budget after approval, accepted risk group when allocating, position origin, exact calendar, or persistence backend for production enablement. |

## Persistence boundary

The `DecisionStateStore` interface records published event identity, pending T+1
decisions, settled execution identity, system-created position origins, and
daily report history. Production formal-pool inputs use the existing
account-scoped `SheetsDecisionStateStore` backed by `策略决策状态`; its default
is read-only. The runner may use the existing `InMemoryDecisionStateStore` as
an empty transient read-only view for non-formal Candidate/position inputs; it
never receives writes and is not a production persistence backend. No new Sheet
schema, external database, broker, or automatic schedule is added by this V1
wiring.

## Production Daily Runner V1

`scripts/run_production_daily_decision.py --run` now emits the account-isolated
Daily Chain report in read-only mode by default. It reads the five formal
production contracts and the existing `策略决策状态` ledger, but does not append
published events, pending T+1 reservations, settlements, PositionOrigins, or
daily-result rows. A report can therefore expose per-symbol `DATA_BAD`, stale,
unavailable, missing-universe, missing-calendar, or other fail-closed outcomes
without turning a diagnostic run into a state mutation.

`--write-state` is the only explicit state-write opt-in and is accepted only
when preflight is `READY`; it still writes only system-owned
`策略决策状态` rows for formal `策略股票池` inputs. Dynamic Candidate-only inputs
are evaluated in a separate empty read-only state view and cannot publish events,
create/settle T+1 pending, reserve Portfolio Risk, or become production-execution
eligible. They require manual promotion into the formal pool and a new run. Human-in-the-loop inputs remain explicit:
`--approve-event EVENT_IDENTITY` matches an already-published proposal identity,
and `--allocation-budget ACCOUNT_ID=AMOUNT` supplies the account's strategy
risk-ledger budget. Neither option reads or substitutes account NAV, and neither
option submits a broker order. There is no automatic schedule or broker path in
V1.

## Report surface

`DailyTradingDecisionReport.to_dict()` emits machine enums and protocol
versions. `to_markdown()` uses the required user-facing sections:

1. `需要关注`
2. `STRATEGY_PROPOSAL`
3. `ENTRY_ALLOWED但组合层阻塞`
4. `PORTFOLIO_ALLOWED`
5. `持仓管理`
6. `NO_TRADE`
7. `数据/生产前置条件异常`

Each symbol shows date/data status, weekly/daily state, primary/alternate
scenario, both Setup states, Decision geometry, Portfolio Risk,
Position Management/Wave5 context, final status, and blocking reasons.

## Operational validation

`scripts/run_daily_decision_chain_generic_operational_shadow.py` runs 17
synthetic cases and writes JSON/Markdown artifacts. The dedicated workflow is
pull-request and `workflow_dispatch` only; it has no cron schedule and injects
no credentials. A real-data shadow was not run in this task because no live
Sheets credentials or user-authorized account run was supplied; the formal
strategy universe is now wired through `策略股票池`, and holdings are not used
as a substitute.

## Sol review correctness hardening

The chain now applies the data-quality gate before every downstream stage.
`DATA_BAD`, stale, unavailable, or incomplete T data returns a fail-closed
result without Wave, Setup, Individual Decision, or Position Management replay.
An authoritative Position Management observation is the only result shown in
the `持仓管理` report section; missing position origin, evaluation failure,
entry-after-as-of, and no-visible-day results are classified under
`数据/生产前置条件异常`.

Portfolio Risk receives the canonical merge of global `existing_positions` and
each supplied `OpenPositionState.portfolio_position`. Equal key risk facts are
deduplicated by canonical symbol; a conflict in source event identity, actual
entry, quantity, protective stop, or risk group fails closed with
`PORTFOLIO_EXISTING_POSITION_CONFLICT`. This preserves open positions outside
the strategy universe when they are supplied through the global input.

The Wave contract emits one primary scenario, and SETUP_01/SETUP_02 each accept
only their own primary family, so two new same-symbol/T first-entry
`CONFIRMED` events are formally unreachable through the frozen upstream path.
The chain nevertheless guards the boundary with
`DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION`: it creates no Portfolio
candidate, records both identities as explicitly disposed, and does not choose
a Setup priority.

Settlement checks use only the `DecisionStateStore.get_settlement()` protocol
method. A report run rejects mixed `DailySymbolInput.as_of_date` values before
any report is generated.

For any due T+1 observation, the orchestration layer requires
`data_quality_status == DATA_OK` and exactly one qfq bar on the exact
`expected_execution_date` before calling either frozen T+1 executor or
`PortfolioRiskEngine.settle`. `DATA_BAD`, `DATA_STALE`,
`DATA_UNAVAILABLE`, and a missing/ambiguous expected bar return the single
machine-readable blocker `T1_EXECUTION_DATA_REQUIRED`; the pending reservation
remains pending, with no `EXECUTED`, strategy `SKIP` settlement, release, or
`PositionOrigin`.

An `OpenPositionState` is an authoritative claim that a symbol is already
held. If it has no `portfolio_position`, a new `ENTRY_ALLOWED` is blocked with
`PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED`. The chain never infers
quantity, actual entry, protective stop, or risk group from PositionOrigin,
current price, holdings average cost, or chart history. The existing global
and per-symbol authoritative position merge/deduplication/conflict behavior is
otherwise unchanged.

The strategy proposal boundary is intentionally outcome-blind and capital
independent: account NAV, account assets, deposits, withdrawals, P&L,
purchasing power and broker balances are not read as strategy inputs. The
frozen risk fractions remain unchanged; they are applied only to the explicit
user `allocation_budget` after approval.
