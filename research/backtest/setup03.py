"""SETUP_03 T+1 execution research and parameter diagnostics.

The input event ledger is produced by ``trading.events`` through
``trading.replay``. This module deliberately has no terminal-event detector and
does not call Setup or Decision engines for an individual outcome.

Research exit convention
------------------------
The production system does not yet define position management. For diagnostics
only, an executed trade observes at most 20 trading sessions from T+1. The first
touch of the execution stop or T1 closes the diagnostic trade. If both are
touched in one daily bar, stop is assumed first. If neither is touched after 20
sessions, the 20D close is marked to market. A shorter unresolved tail is
censored and excluded from R-based aggregate statistics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from itertools import product
from statistics import fmean
from typing import Sequence

from core import Quote
from trading.models import DecisionAction, SetupState, validate_quote_series
from trading.replay import ReplayEvent, SymbolReplayReport, replay_setup03_history


FORWARD_HORIZON = 20
SENSITIVITY_SWING_LOOKBACKS = (3, 5, 7)
SENSITIVITY_PLATFORM_WINDOWS = (30, 40, 60)
SENSITIVITY_PLATFORM_TOLERANCES = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05)


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    SKIP_SIGNAL_NOT_ENTRY_ALLOWED = "SKIP_SIGNAL_NOT_ENTRY_ALLOWED"
    SKIP_NO_T_PLUS_1_BAR = "SKIP_NO_T_PLUS_1_BAR"
    SKIP_GAP_BELOW_BREAKOUT = "SKIP_GAP_BELOW_BREAKOUT"
    SKIP_GAP_ABOVE_ENTRY_ZONE = "SKIP_GAP_ABOVE_ENTRY_ZONE"


@dataclass(frozen=True)
class Setup03TradeOutcome:
    symbol: str
    market: str
    signal_date: date
    confirmed_date: date
    t_plus_1_date: date | None
    execution_status: ExecutionStatus
    t_plus_1_open: float | None
    actual_entry: float | None
    entry_zone_high: float | None
    stop: float | None
    targets: tuple[float, ...]
    return_5d: float | None = None
    return_10d: float | None = None
    return_20d: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    first_exit_event: str | None = None
    first_exit_date: date | None = None
    final_r: float | None = None
    observation_days: int = 0
    horizon_complete: bool = False

    def to_row(self) -> dict:
        row = {
            "symbol": self.symbol,
            "market": self.market,
            "signal_date": self.signal_date,
            "confirmed_date": self.confirmed_date,
            "T+1_date": self.t_plus_1_date,
            "execution_status": self.execution_status.value,
            "T+1_open": self.t_plus_1_open,
            "actual_entry": self.actual_entry,
            "entry_zone_high": self.entry_zone_high,
            "stop": self.stop,
            "5D_return": self.return_5d,
            "10D_return": self.return_10d,
            "20D_return": self.return_20d,
            "MFE_pct": self.mfe_pct,
            "MAE_pct": self.mae_pct,
            "MFE_R": self.mfe_r,
            "MAE_R": self.mae_r,
            "first_exit_event": self.first_exit_event,
            "first_exit_date": self.first_exit_date,
            "final_R": self.final_r,
            "observation_days": self.observation_days,
            "horizon_complete": self.horizon_complete,
        }
        row.update(_target_columns(self.targets))
        return row


@dataclass(frozen=True)
class Setup03ResearchReport:
    symbol: str
    market: str
    confirmed_count: int
    outcomes: tuple[Setup03TradeOutcome, ...]

    @property
    def executed_count(self) -> int:
        return sum(
            outcome.execution_status is ExecutionStatus.EXECUTED
            for outcome in self.outcomes
        )


def research_trade_outcomes(
    replay_report: SymbolReplayReport,
    quotes: list[Quote],
) -> Setup03ResearchReport:
    """Consume the shared CONFIRMED event ledger and apply T+1 open rules."""
    validate_quote_series(quotes)
    confirmed_events = tuple(
        event
        for event in replay_report.events
        if event.event_type is SetupState.CONFIRMED
    )
    outcomes = tuple(
        _simulate_event(event, replay_report.market, quotes)
        for event in confirmed_events
    )
    return Setup03ResearchReport(
        replay_report.symbol,
        replay_report.market,
        len(confirmed_events),
        outcomes,
    )


def parameter_sensitivity_rows(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    production_setup_parameters: dict,
    decision_parameters: dict,
    swing_lookbacks: Sequence[int] = SENSITIVITY_SWING_LOOKBACKS,
    platform_windows: Sequence[int] = SENSITIVITY_PLATFORM_WINDOWS,
    platform_tolerances: Sequence[float] = SENSITIVITY_PLATFORM_TOLERANCES,
) -> list[dict]:
    """Run the declared research grid in stable order without ranking it."""
    rows: list[dict] = []
    input_bar_count = sum(len(quotes) for quotes in symbol_quotes.values())
    for swing_lookback, platform_window, tolerance in product(
        swing_lookbacks, platform_windows, platform_tolerances
    ):
        research_setup_parameters = dict(production_setup_parameters)
        research_setup_parameters.update(
            swing_lookback=swing_lookback,
            platform_window=platform_window,
            platform_tolerance_pct=tolerance,
        )
        reports: list[Setup03ResearchReport] = []
        for quotes in symbol_quotes.values():
            replay_report = replay_setup03_history(
                quotes,
                risk_capital,
                research_setup_parameters,
                decision_parameters,
            )
            reports.append(research_trade_outcomes(replay_report, quotes))

        outcomes = [outcome for report in reports for outcome in report.outcomes]
        executed = [
            outcome
            for outcome in outcomes
            if outcome.execution_status is ExecutionStatus.EXECUTED
        ]
        observed = [outcome for outcome in executed if outcome.final_r is not None]
        final_rs = [outcome.final_r for outcome in observed]
        mfe_rs = [outcome.mfe_r for outcome in observed if outcome.mfe_r is not None]
        mae_rs = [outcome.mae_r for outcome in observed if outcome.mae_r is not None]
        rows.append(
            {
                "swing_lookback": swing_lookback,
                "platform_window": platform_window,
                "platform_tolerance_pct": tolerance,
                "symbol_count": len(symbol_quotes),
                "input_bar_count": input_bar_count,
                "sample_size": len(observed),
                "confirmed_count": sum(report.confirmed_count for report in reports),
                "executed_count": len(executed),
                "censored_count": len(executed) - len(observed),
                **_performance_metrics(final_rs, mfe_rs, mae_rs),
            }
        )
    return rows


def _simulate_event(
    event: ReplayEvent,
    market: str,
    quotes: list[Quote],
) -> Setup03TradeOutcome:
    if event.signal_date is None or event.confirmed_date is None:
        raise ValueError("CONFIRMED event contract is missing signal/confirmed date")
    confirmed_index = event.setup.confirmed_index
    if confirmed_index is None or confirmed_index >= len(quotes):
        raise ValueError("CONFIRMED event contract has an invalid confirmed_index")
    if quotes[confirmed_index].trade_date != event.confirmed_date:
        raise ValueError("CONFIRMED event date does not match its as-of quote")

    decision = event.decision
    entry_plan = decision.entry_plan if decision is not None else None
    stop = decision.execution_stop if decision is not None else None
    targets = decision.targets if decision is not None else ()
    common = {
        "symbol": event.symbol,
        "market": market,
        "signal_date": event.signal_date,
        "confirmed_date": event.confirmed_date,
        "entry_zone_high": (
            entry_plan.entry_zone_high if entry_plan is not None else None
        ),
        "stop": stop,
        "targets": targets,
    }
    next_index = confirmed_index + 1
    if next_index >= len(quotes):
        return Setup03TradeOutcome(
            **common,
            t_plus_1_date=None,
            execution_status=ExecutionStatus.SKIP_NO_T_PLUS_1_BAR,
            t_plus_1_open=None,
            actual_entry=None,
        )

    next_quote = quotes[next_index]
    next_open = float(next_quote.open)
    next_common = {
        **common,
        "t_plus_1_date": next_quote.trade_date,
        "t_plus_1_open": next_open,
    }
    if (
        decision is None
        or decision.action is not DecisionAction.ENTRY_ALLOWED
        or entry_plan is None
        or stop is None
        or not targets
    ):
        return Setup03TradeOutcome(
            **next_common,
            execution_status=ExecutionStatus.SKIP_SIGNAL_NOT_ENTRY_ALLOWED,
            actual_entry=None,
        )

    breakout_price = event.setup.breakout_price
    if breakout_price is None:
        raise ValueError("CONFIRMED event contract is missing breakout_price")
    if next_open < breakout_price:
        return Setup03TradeOutcome(
            **next_common,
            execution_status=ExecutionStatus.SKIP_GAP_BELOW_BREAKOUT,
            actual_entry=None,
        )
    if next_open > entry_plan.entry_zone_high:
        return Setup03TradeOutcome(
            **next_common,
            execution_status=ExecutionStatus.SKIP_GAP_ABOVE_ENTRY_ZONE,
            actual_entry=None,
        )

    path = quotes[next_index : next_index + FORWARD_HORIZON]
    return _executed_outcome(event, market, next_quote, next_open, path)


def _executed_outcome(
    event: ReplayEvent,
    market: str,
    execution_quote: Quote,
    actual_entry: float,
    path: list[Quote],
) -> Setup03TradeOutcome:
    assert event.signal_date is not None
    assert event.confirmed_date is not None
    assert event.decision is not None
    assert event.decision.entry_plan is not None
    assert event.decision.execution_stop is not None
    stop = event.decision.execution_stop
    targets = event.decision.targets
    risk_per_share = actual_entry - stop
    if risk_per_share <= 0:
        raise ValueError("T+1 actual_entry must be above the execution stop")

    forward_returns = {
        days: _forward_return(path, days, actual_entry) for days in (5, 10, 20)
    }
    first_exit_event = None
    first_exit_date = None
    final_r = None
    exit_index = len(path) - 1
    for index, quote in enumerate(path):
        if float(quote.low) <= stop:
            first_exit_event = "STOP"
            first_exit_date = quote.trade_date
            final_r = -1.0
            exit_index = index
            break
        if float(quote.high) >= targets[0]:
            first_exit_event = "T1"
            first_exit_date = quote.trade_date
            final_r = (targets[0] - actual_entry) / risk_per_share
            exit_index = index
            break

    horizon_complete = len(path) == FORWARD_HORIZON
    if final_r is None and horizon_complete:
        first_exit_event = "MARK_TO_MARKET_20D"
        first_exit_date = path[-1].trade_date
        final_r = (float(path[-1].close) - actual_entry) / risk_per_share
    elif final_r is None:
        first_exit_event = "CENSORED_END_OF_DATA"

    observed_path = path[: exit_index + 1]
    max_high = max(float(quote.high) for quote in observed_path)
    min_low = min(float(quote.low) for quote in observed_path)
    favorable_move = max(max_high - actual_entry, 0.0)
    adverse_move = min(min_low - actual_entry, 0.0)
    return Setup03TradeOutcome(
        symbol=event.symbol,
        market=market,
        signal_date=event.signal_date,
        confirmed_date=event.confirmed_date,
        t_plus_1_date=execution_quote.trade_date,
        execution_status=ExecutionStatus.EXECUTED,
        t_plus_1_open=actual_entry,
        actual_entry=actual_entry,
        entry_zone_high=event.decision.entry_plan.entry_zone_high,
        stop=stop,
        targets=targets,
        return_5d=forward_returns[5],
        return_10d=forward_returns[10],
        return_20d=forward_returns[20],
        mfe_pct=favorable_move / actual_entry,
        mae_pct=adverse_move / actual_entry,
        mfe_r=favorable_move / risk_per_share,
        mae_r=adverse_move / risk_per_share,
        first_exit_event=first_exit_event,
        first_exit_date=first_exit_date,
        final_r=final_r,
        observation_days=len(path),
        horizon_complete=horizon_complete,
    )


def _forward_return(path: list[Quote], days: int, entry: float) -> float | None:
    if len(path) < days:
        return None
    return float(path[days - 1].close) / entry - 1.0


def _performance_metrics(
    final_rs: list[float],
    mfe_rs: list[float],
    mae_rs: list[float],
) -> dict:
    wins = [value for value in final_rs if value > 0]
    losses = [value for value in final_rs if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    average_r = fmean(final_rs) if final_rs else None
    return {
        "win_rate": len(wins) / len(final_rs) if final_rs else None,
        "avg_R": average_r,
        "expectancy": average_r,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (math.inf if gross_profit > 0 else None)
        ),
        "MFE": fmean(mfe_rs) if mfe_rs else None,
        "MAE": fmean(mae_rs) if mae_rs else None,
    }


def _target_columns(targets: Sequence[float]) -> dict:
    return {
        "T1": targets[0] if len(targets) > 0 else None,
        "T2": targets[1] if len(targets) > 1 else None,
        "T3": targets[2] if len(targets) > 2 else None,
    }
