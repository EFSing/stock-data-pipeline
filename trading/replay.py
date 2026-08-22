"""SETUP_03 historical replay diagnostics.

This module is intentionally read-only. It replays each historical trading day
as an as-of snapshot by passing only ``quotes[:i + 1]`` into the existing
Setup / Decision engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core import Quote
from trading.decision import decide_platform_breakout
from trading.models import DecisionAction, SetupState, validate_quote_series
from trading.setup import detect_platform_breakout


REPLAY_SETUP_STATES = (
    SetupState.NONE,
    SetupState.WATCH,
    SetupState.ARMED,
    SetupState.CONFIRMED,
    SetupState.FAILED,
)


@dataclass(frozen=True)
class ReplayDay:
    symbol: str
    trade_date: date
    setup_state: SetupState
    decision_action: DecisionAction | None = None


@dataclass(frozen=True)
class SymbolReplayReport:
    symbol: str
    market: str
    days: tuple[ReplayDay, ...]
    setup_counts: dict[SetupState, int] = field(default_factory=dict)
    setup_dates: dict[SetupState, tuple[date, ...]] = field(default_factory=dict)
    decision_counts: dict[DecisionAction, int] = field(default_factory=dict)
    decision_dates: dict[DecisionAction, tuple[date, ...]] = field(default_factory=dict)

    def summary_row(self) -> dict:
        """Return a compact diagnostics row; no production Sheet schema implied."""
        row = {
            "统一代码": self.symbol,
            "市场": self.market,
            "回放交易日数": len(self.days),
        }
        for state in REPLAY_SETUP_STATES:
            row[f"{state.value}次数"] = self.setup_counts.get(state, 0)
            row[f"{state.value}日期"] = _join_dates(self.setup_dates.get(state, ()))
        for action in (DecisionAction.ENTRY_ALLOWED, DecisionAction.NO_TRADE):
            row[f"{action.value}次数"] = self.decision_counts.get(action, 0)
            row[f"{action.value}日期"] = _join_dates(
                self.decision_dates.get(action, ())
            )
        other_actions = [
            action
            for action in self.decision_counts
            if action not in (DecisionAction.ENTRY_ALLOWED, DecisionAction.NO_TRADE)
        ]
        row["Decision其他动作次数"] = sum(
            self.decision_counts[action] for action in other_actions
        )
        other_action_set = set(other_actions)
        row["Decision其他动作日期"] = _join_dates(
            day.trade_date
            for day in self.days
            if day.decision_action in other_action_set
        )
        return row


def replay_setup03_history(
    quotes: list[Quote],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
) -> SymbolReplayReport:
    """Replay SETUP_03 state and confirmed-day decisions for one symbol.

    Each replay step calls the existing Trading Core with a prefix ending at the
    replay date. This is the as-of guardrail for Phase 5A.
    """
    validate_quote_series(quotes)
    setup_parameters = dict(setup_parameters or {})
    decision_parameters = dict(decision_parameters or {})
    setup_dates: dict[SetupState, list[date]] = {
        state: [] for state in REPLAY_SETUP_STATES
    }
    decision_dates: dict[DecisionAction, list[date]] = {}
    days: list[ReplayDay] = []

    for index, quote in enumerate(quotes):
        as_of_quotes = quotes[: index + 1]
        setup = detect_platform_breakout(as_of_quotes, **setup_parameters)
        setup_dates[setup.state].append(quote.trade_date)

        decision_action = None
        if setup.state is SetupState.CONFIRMED:
            decision = decide_platform_breakout(
                as_of_quotes, setup, risk_capital, **decision_parameters
            )
            decision_action = decision.action
            decision_dates.setdefault(decision.action, []).append(quote.trade_date)

        days.append(
            ReplayDay(quotes[0].symbol, quote.trade_date, setup.state, decision_action)
        )

    setup_date_tuples = {
        state: tuple(dates) for state, dates in setup_dates.items()
    }
    decision_date_tuples = {
        action: tuple(dates) for action, dates in decision_dates.items()
    }
    return SymbolReplayReport(
        symbol=quotes[0].symbol,
        market=quotes[0].market,
        days=tuple(days),
        setup_counts={
            state: len(dates) for state, dates in setup_date_tuples.items()
        },
        setup_dates=setup_date_tuples,
        decision_counts={
            action: len(dates) for action, dates in decision_date_tuples.items()
        },
        decision_dates=decision_date_tuples,
    )


def replay_setup03_symbols(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
) -> dict[str, SymbolReplayReport]:
    return {
        symbol: replay_setup03_history(
            quotes, risk_capital, setup_parameters, decision_parameters
        )
        for symbol, quotes in symbol_quotes.items()
    }


def replay_summary_rows(
    reports: Iterable[SymbolReplayReport],
) -> list[dict]:
    return [report.summary_row() for report in reports]


def _join_dates(dates: Iterable[date]) -> str:
    return ",".join(day.isoformat() for day in dates)
