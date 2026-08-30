"""Strict as-of structural replay for SETUP_01.

The replay layer records lifecycle snapshots and only emits first-entry
CONFIRMED/FAILED events.  It has no return, execution, Decision, or production
Sheet path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core import Quote
from trading.models import Setup01Evaluation, SetupState, validate_quote_series
from trading.setup01 import (
    SETUP01_PROTOCOL_VERSION,
    SETUP01_TYPE,
    evaluate_setup01_history,
    setup01_evaluation_to_dict,
)


SETUP01_REPLAY_STATES = (
    SetupState.NONE,
    SetupState.WATCH,
    SetupState.ARMED,
    SetupState.CONFIRMED,
    SetupState.FAILED,
)


@dataclass(frozen=True)
class Setup01ReplayDay:
    symbol: str
    trade_date: date
    setup01: Setup01Evaluation
    confirmed_event: bool = False
    failed_event: bool = False


@dataclass(frozen=True)
class Setup01ReplayEvent:
    event_identity: str
    symbol: str
    trade_date: date
    event_type: SetupState
    setup01: Setup01Evaluation


@dataclass(frozen=True)
class Setup01ReplayReport:
    symbol: str
    market: str
    days: tuple[Setup01ReplayDay, ...]
    events: tuple[Setup01ReplayEvent, ...] = ()
    state_day_counts: dict[SetupState, int] = field(default_factory=dict)
    state_dates: dict[SetupState, tuple[date, ...]] = field(default_factory=dict)
    confirmed_event_dates: tuple[date, ...] = ()
    failed_event_dates: tuple[date, ...] = ()

    @property
    def current(self) -> Setup01Evaluation:
        if not self.days:
            raise ValueError("SETUP_01 replay has no days")
        return self.days[-1].setup01

    def summary_row(self) -> dict:
        row = {
            "setup_type": SETUP01_TYPE,
            "protocol_version": SETUP01_PROTOCOL_VERSION,
            "symbol": self.symbol,
            "market": self.market,
            "replay_days": len(self.days),
            "CONFIRMED_events": len(self.confirmed_event_dates),
            "FAILED_events": len(self.failed_event_dates),
            "CONFIRMED_event_dates": _join_dates(self.confirmed_event_dates),
            "FAILED_event_dates": _join_dates(self.failed_event_dates),
            "current_state": self.current.state.value,
            "current_as_of_date": self.current.as_of_date.isoformat(),
            "current_primary_wave_scenario": self.current.primary_wave_scenario,
            "current_alternate_wave_scenario": self.current.alternate_wave_scenario,
            "current_reason": self.current.reason,
        }
        for state in SETUP01_REPLAY_STATES:
            row[f"{state.value}_days"] = self.state_day_counts.get(state, 0)
            row[f"{state.value}_dates"] = _join_dates(
                self.state_dates.get(state, ())
            )
        return row


def _join_dates(values: Iterable[date]) -> str:
    return ",".join(value.isoformat() for value in values)


def setup01_event_identity(
    symbol: str,
    trade_date: date,
    event_type: SetupState,
    lifecycle_index: int | None,
) -> str:
    """Return a stable identity that distinguishes CONFIRMED from FAILED."""
    return (
        f"{symbol}|{SETUP01_TYPE}|{trade_date.isoformat()}|"
        f"{event_type.value}|lifecycle={lifecycle_index or 0}"
    )


def replay_setup01_history(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> Setup01ReplayReport:
    """Replay SETUP_01 using only the visible historical prefix.

    Passing an explicit ``as_of_date`` makes the future-append invariant
    testable: bars after that date are not sent to the evaluator at all.
    """
    validate_quote_series(quotes)
    resolved_as_of = as_of_date or quotes[-1].trade_date
    visible = [quote for quote in quotes if quote.trade_date <= resolved_as_of]
    if not visible:
        raise ValueError("as_of_date 之前没有可用行情")

    snapshots = evaluate_setup01_history(
        visible,
        daily_swing_lookback=daily_swing_lookback,
        weekly_swing_lookback=weekly_swing_lookback,
    )
    state_dates: dict[SetupState, list[date]] = {
        state: [] for state in SETUP01_REPLAY_STATES
    }
    days: list[Setup01ReplayDay] = []
    events: list[Setup01ReplayEvent] = []
    event_ids: set[str] = set()
    confirmed_dates: list[date] = []
    failed_dates: list[date] = []

    for index, (quote, snapshot) in enumerate(zip(visible, snapshots)):
        state_dates[snapshot.state].append(quote.trade_date)
        # The evaluator owns terminal-event semantics.  A terminal state can
        # persist on later bars, so replay must consume the explicit as-of
        # event flags rather than treating every terminal snapshot as new.
        confirmed = snapshot.is_new_confirmed_event_as_of
        failed = snapshot.is_new_failed_event_as_of
        if confirmed or failed:
            event_type = SetupState.CONFIRMED if confirmed else SetupState.FAILED
            event_id = setup01_event_identity(
                quote.symbol,
                quote.trade_date,
                event_type,
                snapshot.lifecycle_index,
            )
            if event_id not in event_ids:
                event_ids.add(event_id)
                events.append(
                    Setup01ReplayEvent(
                        event_identity=event_id,
                        symbol=quote.symbol,
                        trade_date=quote.trade_date,
                        event_type=event_type,
                        setup01=snapshot,
                    )
                )
            if confirmed:
                confirmed_dates.append(quote.trade_date)
            else:
                failed_dates.append(quote.trade_date)
        days.append(
            Setup01ReplayDay(
                symbol=quote.symbol,
                trade_date=quote.trade_date,
                setup01=snapshot,
                confirmed_event=confirmed,
                failed_event=failed,
            )
        )

    state_date_tuples = {state: tuple(values) for state, values in state_dates.items()}
    return Setup01ReplayReport(
        symbol=visible[0].symbol,
        market=visible[0].market,
        days=tuple(days),
        events=tuple(events),
        state_day_counts={state: len(values) for state, values in state_date_tuples.items()},
        state_dates=state_date_tuples,
        confirmed_event_dates=tuple(confirmed_dates),
        failed_event_dates=tuple(failed_dates),
    )


def setup01_event_rows(reports: Iterable[Setup01ReplayReport]) -> list[dict]:
    rows: list[dict] = []
    for report in reports:
        for event in report.events:
            row = setup01_evaluation_to_dict(event.setup01)
            rows.append(
                {
                    "event_identity": event.event_identity,
                    "symbol": event.symbol,
                    "market": report.market,
                    "trade_date": event.trade_date.isoformat(),
                    "event_type": event.event_type.value,
                    **row,
                }
            )
    return rows


__all__ = [
    "SETUP01_REPLAY_STATES",
    "Setup01ReplayDay",
    "Setup01ReplayEvent",
    "Setup01ReplayReport",
    "replay_setup01_history",
    "setup01_event_identity",
    "setup01_event_rows",
]
