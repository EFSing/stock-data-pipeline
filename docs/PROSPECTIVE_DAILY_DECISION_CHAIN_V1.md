# Prospective Daily Decision Chain V1

Status: `PROSPECTIVE_DAILY_DECISION_CHAIN_V1_READY_FOR_SOL_REVIEW`

Protocol identity: `PROSPECTIVE-DAILY-DECISION-CHAIN-2026-09-02-v1`

Implementation: `trading/daily_decision_chain.py`

## Scope and boundary

This phase is a production-data prospective decision-support chain. It is not
an automated trading system and has no broker/order path:

```text
Market Data → Data Quality → Weekly/Daily State → Swing → Wave Scenario
→ SETUP_01 / SETUP_02 → Individual Decision → STRATEGY_PROPOSAL
→ user approval + allocation_budget → Portfolio Risk / Position Size
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
of the strategy proposal boundary. Without a user-supplied
`allocation_budget`, an `ENTRY_ALLOWED` individual Decision remains visible as
`STRATEGY_PROPOSAL`, with no position size, reservation or capital allocation.
After approval, the explicit budget enters Portfolio Risk. UNKNOWN risk group
keeps a development candidate visible but returns
`BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION` in production. A reservation is saved as
pending only after Portfolio Risk allows it.

## Production architecture audit

| Question | Verified repository fact | Chain decision |
|---|---|---|
| Formal strategy universe | No dedicated strategy-universe registry/provider exists. `main.py` currently iterates enabled rows in `自选清单` for the market-data pipeline; that is not formally declared as the strategy universe. | Inject `UniverseProvider`; production wiring fails closed with `PRODUCTION_STRATEGY_UNIVERSE_REQUIRED`. `自选清单` and holdings are never silently substituted. |
| Production daily/qfq data | `providers.py` provides raw snapshots through BaoStock/Tencent/Sina/yfinance fallback and qfq history through configured `自选清单.历史数据源` (`BaoStock` or `yfinance`). `latest_snapshot.py` owns completed-session/freshness/validation semantics. | Reuse these adapters at a future production wrapper boundary; current chain consumes injected qfq history only. |
| Authoritative strategy decision persistence | `SheetsClient` has `交易决策` upsert for the legacy SETUP_03 surface. It is not a versioned SETUP_01/02 daily event store. | Provide `DecisionStateStore` plus `InMemoryDecisionStateStore` for tests/shadow; do not choose a new long-term backend in this phase. |
| Published-event identity ledger | Existing SETUP_01/02 replay event identities are deterministic. The existing Sheet ledger is SETUP_03-keyed. | Reuse existing SETUP_01/02 event identity; store exact-once published identities in the injected state store. |
| Production capital | Account NAV/assets are not strategy inputs. `参数设置. decision_risk_capital` is a legacy individual-decision input, not an allocation budget. | Proposal generation is independent of NAV. After user approval, Portfolio Risk accepts only explicit `allocation_budget`; account NAV is never substituted. |
| Risk-group/sector metadata | No reliable sector/risk-group metadata source is present in the production data path. | Inject accepted metadata when Portfolio Risk allocation is requested; production UNKNOWN fails closed there. |
| Real open-position origin | Holdings lifecycle tracks enabled symbols and historical data, not complete strategy position origins. Position Management has immutable replay origins only when created from an executed frozen Decision. | Require authoritative `PositionOrigin`; never derive entry/stop/origin from holdings average cost or chart history. |
| Session/calendar | `latest_completed_market_session()` and `ordinary_calendar_freshness_guard()` use source evidence plus an ordinary weekday guard. `research.market_sessions` uses a frozen observed session union and explicitly is not an exchange calendar. | T-day prospective decisions are allowed. Production T+1 execution is disabled with `PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED` until an exact exchange-calendar source is injected. |
| Current output/publish surface | Existing scheduled workflows write `最新行情`, history, validation, logs, and legacy `交易决策` through Google Sheets. | This chain is read-only and emits machine JSON plus concise Chinese-first Markdown; no Sheet write is added. |
| Reusable vs fail-closed | Reusable: core Quote/QC, providers/latest contracts, Wave, SETUP_01/02, frozen Decision/Risk, Portfolio Risk, Position Management/Wave5. | Fail closed: missing formal universe, accepted allocation budget after approval, accepted risk group when allocating, position origin, exact calendar, or persistence backend for production enablement. |

## Persistence boundary

The `DecisionStateStore` interface records published event identity, pending T+1
decisions, settled execution identity, system-created position origins, and
daily report history. `InMemoryDecisionStateStore` is intentionally limited to
tests and synthetic shadow. No Google Sheets schema, GitHub state file, or
external database is selected as the production fact source. That choice is a
separate review decision.

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
no credentials. The real-data shadow was not run because no formal production
strategy universe is defined; holdings are not used as a substitute.

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
