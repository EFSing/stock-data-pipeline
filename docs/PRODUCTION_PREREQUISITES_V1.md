# PRODUCTION_PREREQUISITES_V1

Status: `PRODUCTION_PREREQUISITES_V1_MERGED`

This phase adds the production-data contract and construction boundary for the
existing prospective Daily Decision Chain. It does not redesign or modify the
frozen strategy, risk, T+1, Position Management, Wave, Swing, Fibonacci,
Entry, Target, or R/R semantics.

## SSOT matrix

| Surface | Worksheet / provider | Owner | Production role |
|---|---|---|---|
| Strategy account | `策略账户` | Human | Account ID, market and currency; legacy reference NAV/date remain optional fields |
| Strategy universe | `策略股票池` | Human | Formal enabled strategy symbols; `自选清单` is not a substitute |
| Risk group | `策略风险分组` | Human | Explicit `(market, symbol) → risk group` join |
| Open strategy positions | `策略持仓` | Human | Actual quantity, actual entry and active protective stop |
| Decision state | `策略决策状态` | System | Published event, pending T+1, settlement, PositionOrigin and daily result |
| Latest market data | `最新行情` | Existing market-data pipeline | T-day formal-close and validation evidence |
| QFQ history | `历史行情_前复权` | Existing market-data pipeline | Causal history through T |
| Session identity | `exchange_calendars` | System provider | Exact completed T and next real session |

The adapter reuses the existing `SheetsClient.records(sheet_name)` boundary.
It does not create a second Google API client.

## Sheet schemas

The required headers are exact names; extra columns remain allowed.

* `策略账户`: `账户ID`, `启用`, `市场`, `币种`, `参考净值`, `净值日期`, `备注`.
  Enabled accounts require a unique non-empty ID, market and currency. The
  legacy `参考净值` and `净值日期` columns remain readable for compatibility,
  but missing, stale or malformed values do not block a strategy proposal.
  CN accounts use CNY and US accounts use USD.
* `策略股票池`: `启用`, `账户ID`, `市场`, `统一代码`, `名称`, `备注`.
  An enabled row must reference an enabled account with the same market. The
  same `(market, symbol)` cannot be enabled for two accounts and fails closed
  with `STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS`.
* `策略风险分组`: `市场`, `统一代码`, `风险组`, `备注`. The key is unique.
  No external sector database or name-based classification is used. Missing
  or `UNKNOWN` risk group is `BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION` when an
  approved proposal enters production Portfolio Risk allocation.
* `策略持仓`: `启用`, `账户ID`, `市场`, `统一代码`, `数量`, `实际入场价`,
  `当前保护止损`, `入场日期`, `来源事件ID`, `更新时间`, `备注`.
  Enabled facts require a matching enabled account and strategy universe,
  positive quantity and finite actual entry/stop. The current price is always
  taken from verified T-day `最新行情`; it is never manually supplied.
* `策略决策状态`: `记录类型`, `主键`, `账户ID`, `市场`, `统一代码`, `交易日期`,
  `状态`, `PayloadJSON`, `更新时间`. Persistence identity is
  `(账户ID, 记录类型, 主键)`; the frozen event identity inside `主键` is not
  changed. Every system-owned state row must have a non-empty known account ID.
  The minimum record types are `PUBLISHED_EVENT`, `PENDING_T1`, `SETTLEMENT`,
  `POSITION_ORIGIN`, and `DAILY_RESULT`.

## Risk-book isolation

Each enabled account runs one separate `DailyDecisionChain` input set. A
`PortfolioRiskEngine` input set is created only after an approved proposal has
an explicit `allocation_budget`:

```text
one account = one market = one currency
approved proposal + allocation_budget → one Portfolio Risk allocation
```

Open positions, reservations, total-risk cap and risk-group cap are never
merged across accounts. Account NAV, assets, deposits, withdrawals, P&L and
purchasing power are not strategy inputs and are never substituted for
`allocation_budget`. The frozen constants remain `0.005`, `0.02` and `0.01`;
they apply to the explicit budget. The frozen remaining-loss formula remains
based on `actual_entry - active_protective_stop`. V1 has no FX normalization.
An account/market/currency mismatch fails closed with
`PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH`.

## Calendar and data-quality contracts

The production calendar provider uses `exchange_calendars>=4.13,<5` with:

```text
CN → XSHG
US → XNYS
```

It returns a `CompletedSessionIdentity` for T and the exact next session. The
adapter passes a reliable timezone-aware current `now` (or an injected clock),
so a valid session before its exchange close is rejected with
`COMPLETED_SESSION_REQUIRED`. A weekend, exchange holiday, unsupported market
or missing mapping fails closed with
`PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED`.

`DATA_OK` requires all of the following: latest row exists, `正式收盘=true`,
`校验状态=已验证`, latest `交易日期 == T`, non-empty QFQ history, QFQ final
date `== T`, and calendar confirmation that T is a completed session.
Missing latest or QFQ data maps to `DATA_UNAVAILABLE`; empty currency,
unverified, malformed, future or identity-conflicting data maps to `DATA_BAD`;
an older final date maps to `DATA_STALE`. Market-data currency is required on
each latest/QFQ row and is never filled from account currency. Non-OK data
never reaches T+1 execution or settlement.

## Persistent DecisionStateStore

`SheetsDecisionStateStore` is a persistence adapter for the existing
`DecisionStateStore` protocol. It stores canonical JSON payloads in the same
workbook and reloads them after a process boundary. Duplicate primary keys,
unknown record types, invalid JSON, unknown payload types, constructor errors
unknown/blank/mismatched account ownership and inconsistent typed payloads fail
closed. A store is constructed as `SheetsDecisionStateStore(account_id=X)`;
it only exposes X, while the production adapter creates one read-only scoped
store per enabled account. It preserves:

* published event identity and duplicate suppression;
* pending T+1 decisions;
* exactly-once settlement, with settled reservations not returned as pending;
* PositionOrigin reload through the additive `get_position_origin(identity)`;
* daily result history.

Reload validates the compound lineage. A published `PORTFOLIO_ALLOWED` result
in `PENDING_T1_EXECUTION_CHECK` must have its pending or settlement record;
every settlement must have both its published event and expected pending
lineage; every system-owned `POSITION_ORIGIN` must have its corresponding
`SETTLEMENT`; and a new published event must have its daily result. An origin
persisted without settlement fails closed with
`PERSISTED_STATE_INCOMPLETE:origin_without_settlement:<identity>`. Incomplete
independent appends fail closed with `PERSISTED_STATE_INCOMPLETE`.

The store defaults to read-only. `--preflight` and the default `--run` path
never pass write authority. The stateful runner requires an explicit
`--write-state` flag, and its only write surface is the system-owned
`策略决策状态` worksheet.

## Production construction and preflight

The minimum construction path is:

```python
from datetime import date, datetime, timezone
from trading.production_prerequisites import ProductionInputAdapter

snapshot = ProductionInputAdapter(
    client,
    as_of_date=date(2026, 9, 3),
    now=datetime.now(timezone.utc),
).snapshot()
```

`snapshot.account_runs` contains isolated `DailySymbolInput` tuples and
account-local `existing_positions`; the account object may retain optional
legacy NAV/date fields for compatibility, but the strategy proposal path does
not consume them. A PositionOrigin is
loaded only from the state store by authoritative `来源事件ID`; it is never
invented from holdings average cost, current price or charts. Actual entry,
quantity, stop and risk group remain available for Portfolio Risk accounting
after a user supplies an allocation budget, even when Position Management must
fail closed for a missing origin. Therefore
missing PositionOrigin is reported in `missing_position_origins` but does not
make the account risk book `NOT_READY`; wrong identity/market, future origin
entry date or corrupt origin remains a hard failure.

Before construction, an enabled account must have at least one enabled row in
the formal strategy universe. The adapter never calls
`DailyDecisionChain.evaluate([])`. Persisted PENDING_T1 symbols must remain in
that account's enabled strategy universe, otherwise preflight fails closed
with `PENDING_T1_SYMBOL_OUTSIDE_STRATEGY_UNIVERSE`.

During a Daily Chain run, a T+1 settlement-created `OpenPortfolioPosition` is
merged into the same Portfolio Risk exposure before new candidates reserve.
Any unresolved PENDING_T1 reservation conservatively blocks new Portfolio
reservations with `PORTFOLIO_PENDING_RESERVATION_UNRESOLVED`; it is never
treated as absent.

The CLI supports a read-only preflight and a read-only full Daily Chain report:

```text
python scripts/run_production_daily_decision.py --preflight --date YYYY-MM-DD
python scripts/run_production_daily_decision.py --run --date YYYY-MM-DD
```

Preflight prints a Chinese-first per-account readiness summary. `--run` prints
the same preflight snapshot plus one account-isolated machine-JSON and Markdown
Daily Chain report, including fail-closed symbol rows when data or production
prerequisites are not ready. Both modes have no state write and no Sheets
mutation by default. Use `--approve-event EVENT_IDENTITY` only for an already
published proposal and `--allocation-budget ACCOUNT_ID=AMOUNT` for the explicit
strategy risk-ledger budget; these are not NAV substitutes. Add
`--write-state` only for an explicitly authorized stateful run after a READY
preflight. No cron, workflow schedule, broker, IBKR or order path is added.

## Manual next steps

1. Create the five worksheets with the schemas above in the existing workbook.
2. Populate the formal strategy universe and actual open position facts; do not
   use `自选清单` as a strategy-universe substitute.
3. After a strategy proposal is approved, provide its explicit
   `allocation_budget` and accepted risk-group metadata for Portfolio Risk.
4. Review a preflight report for each intended T.
5. Review the read-only `--run` report for each intended T. Separately authorize
   any stateful production run with `--write-state`; this PR does not schedule
   it, submit orders, or mutate real Sheets unless that flag is explicitly used.
