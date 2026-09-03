# PRODUCTION_PREREQUISITES_V1

Status: `PRODUCTION_PREREQUISITES_V1_READY_FOR_SOL_REVIEW`

This phase adds the production-data contract and construction boundary for the
existing prospective Daily Decision Chain. It does not redesign or modify the
frozen strategy, risk, T+1, Position Management, Wave, Swing, Fibonacci,
Entry, Target, or R/R semantics.

## SSOT matrix

| Surface | Worksheet / provider | Owner | Production role |
|---|---|---|---|
| Strategy account | `策略账户` | Human | Account ID, market, currency, reference NAV and NAV date |
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
  Enabled accounts require a unique non-empty ID, a positive finite NAV and a
  valid NAV date equal to T. CN accounts use CNY and US accounts use USD.
* `策略股票池`: `启用`, `账户ID`, `市场`, `统一代码`, `名称`, `备注`.
  An enabled row must reference an enabled account with the same market. The
  same `(market, symbol)` cannot be enabled for two accounts and fails closed
  with `STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS`.
* `策略风险分组`: `市场`, `统一代码`, `风险组`, `备注`. The key is unique.
  No external sector database or name-based classification is used. Missing
  or `UNKNOWN` risk group is `BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION`.
* `策略持仓`: `启用`, `账户ID`, `市场`, `统一代码`, `数量`, `实际入场价`,
  `当前保护止损`, `入场日期`, `来源事件ID`, `更新时间`, `备注`.
  Enabled facts require a matching enabled account and strategy universe,
  positive quantity and finite actual entry/stop. The current price is always
  taken from verified T-day `最新行情`; it is never manually supplied.
* `策略决策状态`: `记录类型`, `主键`, `账户ID`, `市场`, `统一代码`, `交易日期`,
  `状态`, `PayloadJSON`, `更新时间`. Primary key is `(记录类型, 主键)`.
  The minimum record types are `PUBLISHED_EVENT`, `PENDING_T1`, `SETTLEMENT`,
  `POSITION_ORIGIN`, and `DAILY_RESULT`.

## Risk-book isolation

Each enabled account runs one separate `DailyDecisionChain` and one separate
`PortfolioRiskEngine` input set:

```text
one account = one market = one currency = one reference NAV
```

NAV, open positions, reservations, total-risk cap and risk-group cap are never
merged across accounts. The frozen constants remain `0.005`, `0.02` and
`0.01`; the frozen remaining-loss formula remains based on
`actual_entry - active_protective_stop`. V1 has no FX normalization. An
account/market/currency mismatch fails closed with
`PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH`.

## Calendar and data-quality contracts

The production calendar provider uses `exchange_calendars>=4.13,<5` with:

```text
CN → XSHG
US → XNYS
```

It returns a `CompletedSessionIdentity` for T and the exact next session. A
weekend, exchange holiday, unsupported market or missing mapping fails closed
with `PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED`.

`DATA_OK` requires all of the following: latest row exists, `正式收盘=true`,
`校验状态=已验证`, latest `交易日期 == T`, non-empty QFQ history, QFQ final
date `== T`, and calendar confirmation that T is a completed session.
Missing latest/QFQ data maps to `DATA_UNAVAILABLE`; an older final date maps to
`DATA_STALE`; unverified, malformed, future or identity-conflicting data maps
to `DATA_BAD`. Non-OK data never reaches T+1 execution or settlement.

## Persistent DecisionStateStore

`SheetsDecisionStateStore` is a persistence adapter for the existing
`DecisionStateStore` protocol. It stores canonical JSON payloads in the same
workbook and reloads them after a process boundary. Duplicate primary keys,
unknown record types, invalid JSON, unknown payload types, constructor errors
and inconsistent typed payloads fail closed. It preserves:

* published event identity and duplicate suppression;
* pending T+1 decisions;
* exactly-once settlement, with settled reservations not returned as pending;
* PositionOrigin reload through the additive `get_position_origin(identity)`;
* daily result history.

The store defaults to read-only. `--preflight` never passes write authority.
The stateful runner requires an explicit `--write-state` flag, and its only
write surface is the system-owned `策略决策状态` worksheet.

## Production construction and preflight

The minimum construction path is:

```python
from datetime import date
from trading.production_prerequisites import ProductionInputAdapter

snapshot = ProductionInputAdapter(client, as_of_date=date(2026, 9, 3)).snapshot()
```

`snapshot.account_runs` contains isolated `DailySymbolInput` tuples,
account-local `existing_positions`, and the account NAV. A PositionOrigin is
loaded only from the state store by authoritative `来源事件ID`; it is never
invented from holdings average cost, current price or charts. Actual entry,
quantity, stop and risk group remain available for Portfolio Risk accounting
even when Position Management must fail closed for a missing origin.

The CLI supports a read-only preflight:

```text
python scripts/run_production_daily_decision.py --preflight --date YYYY-MM-DD
```

It prints a Chinese-first per-account summary containing account, market,
currency, T, NAV status, strategy/position counts, data counts, missing risk
groups, missing PositionOrigins, calendar status, state-store status and
readiness. The preflight has no state write and no Sheets mutation. No cron,
workflow schedule, broker, IBKR or order path is added.

## Manual next steps

1. Create the five worksheets with the schemas above in the existing workbook.
2. Populate enabled accounts with same-day authoritative NAVs.
3. Populate the formal strategy universe, explicit risk groups and actual open
   position facts; do not use `自选清单` as a strategy-universe substitute.
4. Review a preflight report for each intended T.
5. Separately authorize any stateful production run; this PR does not execute
   it and does not mutate real Sheets.
