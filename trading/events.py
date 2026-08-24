"""Shared SETUP_03 terminal-event semantics.

This orchestration layer is the single path used by production publishing and
historical replay.  It does not implement Setup or Decision formulas; those
remain in ``trading.setup`` and ``trading.decision``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Collection

from core import Quote
from trading.decision import decide_platform_breakout
from trading.models import Decision, Setup, SetupState
from trading.setup import detect_platform_breakout


DecisionEventKey = tuple[str, str, str]


@dataclass(frozen=True)
class Setup03Evaluation:
    setup: Setup
    event_type: SetupState | None
    event_date: date | None
    confirmed_date: date | None
    decision: Decision | None
    duplicate: bool = False


def setup03_decision_key(
    symbol: str,
    trade_date: date | str,
    setup_type: str = "SETUP_03",
) -> DecisionEventKey:
    """Return the production Sheet idempotency key in its stored string form."""
    return symbol, str(trade_date), setup_type


def terminal_event_type(setup: Setup, current_index: int) -> SetupState | None:
    """Return a terminal event only on the bar that first enters that terminal."""
    if (
        setup.state is SetupState.CONFIRMED
        and setup.confirmed_index == current_index
    ):
        return SetupState.CONFIRMED
    if (
        setup.state is SetupState.FAILED
        and setup.state_entered_index == current_index
    ):
        return SetupState.FAILED
    return None


def evaluate_setup03_event(
    quotes: list[Quote],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
    published_decision_keys: Collection[DecisionEventKey] = (),
) -> Setup03Evaluation:
    """Evaluate the latest as-of snapshot using shared terminal-event semantics.

    A Decision is calculated only for a new CONFIRMED event.  FAILED remains a
    Setup terminal event without a trade Decision.  If the CONFIRMED event key
    already exists in the production event stream, Decision calculation is
    skipped so same-day reruns are idempotent beyond the Sheet upsert itself.
    """
    setup_parameters = dict(setup_parameters or {})
    decision_parameters = dict(decision_parameters or {})
    setup = detect_platform_breakout(quotes, **setup_parameters)
    current_index = len(quotes) - 1
    event_type = terminal_event_type(setup, current_index)
    event_date = quotes[current_index].trade_date if event_type is not None else None
    confirmed_date = (
        quotes[setup.confirmed_index].trade_date
        if setup.confirmed_index is not None
        else None
    )

    if event_type is not SetupState.CONFIRMED:
        return Setup03Evaluation(
            setup, event_type, event_date, confirmed_date, None
        )

    key = setup03_decision_key(
        quotes[current_index].symbol,
        quotes[current_index].trade_date,
        setup.setup_type,
    )
    if key in published_decision_keys:
        return Setup03Evaluation(
            setup, event_type, event_date, confirmed_date, None, duplicate=True
        )

    decision = decide_platform_breakout(
        quotes, setup, risk_capital, **decision_parameters
    )
    return Setup03Evaluation(
        setup, event_type, event_date, confirmed_date, decision
    )
