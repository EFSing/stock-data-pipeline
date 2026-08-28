"""Audit-only replay reference for the ``main@40a3e5f`` semantics.

This module deliberately keeps the historical replay loop as it existed at the
main baseline: every bar is evaluated by passing a fresh ``quotes[:i + 1]``
prefix through the existing Setup/Event/Decision path.  It is not imported by
production code and contains no Setup, Event, or Decision formulas.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from core import Quote
from trading.events import evaluate_setup03_event
from trading.models import DecisionAction, SetupState, validate_quote_series
from trading.replay import ReplayDay, ReplayEvent, REPLAY_SETUP_STATES, SymbolReplayReport
from trading.setup import detect_platform_breakout_history_with_diagnostics


LEGACY_MAIN_COMMIT = "40a3e5f980bf82a85717748ae106847793d1469f"
LEGACY_MAIN_REPLAY_SEMANTICS = (
    "for each bar index i, evaluate_setup03_event(quotes[:i+1], "
    "risk_capital, setup_parameters, decision_parameters)"
)


def legacy_main_replay_identity() -> dict[str, str]:
    """Return the immutable identity recorded in the decision capsule."""
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "baseline_commit": LEGACY_MAIN_COMMIT,
        "baseline_module": "trading/replay.py",
        "baseline_function": "replay_setup03_history",
        "semantics": LEGACY_MAIN_REPLAY_SEMANTICS,
        "reference_module": "research/legacy_main_replay.py",
        "reference_source_sha256": f"sha256:{source_hash}",
    }


def legacy_main_replay_setup03_history(
    quotes: list[Quote],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
    *,
    _setup_history=None,
) -> SymbolReplayReport:
    """Reproduce the main baseline replay loop for audit/test use only."""
    validate_quote_series(quotes)
    setup_parameters = dict(setup_parameters or {})
    decision_parameters = dict(decision_parameters or {})
    state_dates: dict[SetupState, list[date]] = {
        state: [] for state in REPLAY_SETUP_STATES
    }
    confirmed_event_dates: list[date] = []
    failed_event_dates: list[date] = []
    decision_dates: dict[DecisionAction, list[date]] = {}
    days: list[ReplayDay] = []
    events: list[ReplayEvent] = []

    for index, quote in enumerate(quotes):
        # This positional call is intentional: it is the exact main-baseline
        # replay seam and must not grow optimization-only arguments.
        as_of_quotes = quotes[: index + 1]
        if _setup_history is None:
            evaluation = evaluate_setup03_event(
                as_of_quotes,
                risk_capital,
                setup_parameters,
                decision_parameters,
            )
        else:
            evaluation = evaluate_setup03_event(
                as_of_quotes,
                risk_capital,
                setup_parameters,
                decision_parameters,
                setup_calculation=_setup_history[index],
            )
        setup = evaluation.setup
        state_dates[setup.state].append(quote.trade_date)

        confirmed_event = evaluation.event_type is SetupState.CONFIRMED
        failed_event = evaluation.event_type is SetupState.FAILED
        decision_action = (
            evaluation.decision.action if evaluation.decision is not None else None
        )
        if confirmed_event:
            confirmed_event_dates.append(quote.trade_date)
            assert evaluation.decision is not None
            decision_dates.setdefault(evaluation.decision.action, []).append(
                quote.trade_date
            )
        if failed_event:
            failed_event_dates.append(quote.trade_date)
        if evaluation.event_type is not None:
            events.append(
                ReplayEvent(
                    symbol=quotes[0].symbol,
                    trade_date=quote.trade_date,
                    event_type=evaluation.event_type,
                    setup=setup,
                    decision=evaluation.decision,
                    signal_date=evaluation.signal_date,
                    confirmed_date=evaluation.confirmed_date,
                    signal_close=evaluation.signal_close,
                    signal_atr=evaluation.signal_atr,
                    decision_diagnostics=evaluation.decision_diagnostics,
                )
            )

        days.append(
            ReplayDay(
                quotes[0].symbol,
                quote.trade_date,
                setup.state,
                confirmed_event,
                failed_event,
                decision_action,
                evaluation.setup_diagnostics,
                # ``setup`` is an additive audit field on the current report;
                # the baseline calculation itself remains unchanged.
                setup,
            )
        )

    state_date_tuples = {
        state: tuple(dates) for state, dates in state_dates.items()
    }
    decision_date_tuples = {
        action: tuple(dates) for action, dates in decision_dates.items()
    }
    return SymbolReplayReport(
        symbol=quotes[0].symbol,
        market=quotes[0].market,
        days=tuple(days),
        events=tuple(events),
        state_day_counts={
            state: len(dates) for state, dates in state_date_tuples.items()
        },
        state_dates=state_date_tuples,
        confirmed_event_dates=tuple(confirmed_event_dates),
        failed_event_dates=tuple(failed_event_dates),
        decision_counts={
            action: len(dates) for action, dates in decision_date_tuples.items()
        },
        decision_dates=decision_date_tuples,
    )


def legacy_main_replay_setup03_history_cached(
    quotes: list[Quote],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
) -> SymbolReplayReport:
    """Run the reference with an exact audit-only Setup snapshot cache.

    The cache is the same causal snapshot sequence already exercised by the
    current Setup engine.  Event/Decision still receive every fresh prefix;
    the raw reference remains available above for direct baseline checks.
    """
    setup_history = detect_platform_breakout_history_with_diagnostics(
        quotes,
        **dict(setup_parameters or {}),
    )
    return legacy_main_replay_setup03_history(
        quotes,
        risk_capital,
        setup_parameters,
        decision_parameters,
        _setup_history=setup_history,
    )


__all__ = [
    "LEGACY_MAIN_COMMIT",
    "LEGACY_MAIN_REPLAY_SEMANTICS",
    "legacy_main_replay_identity",
    "legacy_main_replay_setup03_history",
    "legacy_main_replay_setup03_history_cached",
]
