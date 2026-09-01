"""Strict as-of structural replay for SETUP_02.

Only first-entry CONFIRMED and FAILED events are emitted.  This layer has no
Decision, execution, outcome, production Sheet, or OOS path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core import Quote
from trading.models import SetupState, validate_quote_series
from trading.setup02 import (
    SETUP02_PROTOCOL_VERSION,
    SETUP02_TYPE,
    Setup02Evaluation,
    evaluate_setup02_history,
    setup02_evaluation_to_dict,
)


SETUP02_REPLAY_STATES = (
    SetupState.NONE,
    SetupState.WATCH,
    SetupState.ARMED,
    SetupState.CONFIRMED,
    SetupState.FAILED,
)


@dataclass(frozen=True)
class Setup02ReplayDay:
    symbol: str
    trade_date: date
    setup02: Setup02Evaluation
    confirmed_event: bool = False
    failed_event: bool = False


@dataclass(frozen=True)
class Setup02ReplayEvent:
    event_identity: str
    symbol: str
    trade_date: date
    event_type: SetupState
    setup02: Setup02Evaluation
    market: str = ""


@dataclass(frozen=True)
class Setup02ReplayReport:
    symbol: str
    market: str
    days: tuple[Setup02ReplayDay, ...]
    events: tuple[Setup02ReplayEvent, ...] = ()
    state_day_counts: dict[SetupState, int] = field(default_factory=dict)
    state_dates: dict[SetupState, tuple[date, ...]] = field(default_factory=dict)
    confirmed_event_dates: tuple[date, ...] = ()
    failed_event_dates: tuple[date, ...] = ()

    @property
    def current(self) -> Setup02Evaluation:
        if not self.days:
            raise ValueError("SETUP_02 replay has no days")
        return self.days[-1].setup02

    @property
    def current_candidates(self) -> tuple[Setup02ReplayDay, ...]:
        if not self.days or self.current.state not in {
            SetupState.WATCH,
            SetupState.ARMED,
        }:
            return ()
        return (self.days[-1],)

    def summary_row(self) -> dict:
        row = {
            "setup_type": SETUP02_TYPE,
            "protocol_version": SETUP02_PROTOCOL_VERSION,
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
        for state in SETUP02_REPLAY_STATES:
            row[f"{state.value}_days"] = self.state_day_counts.get(state, 0)
            row[f"{state.value}_dates"] = _join_dates(
                self.state_dates.get(state, ())
            )
        return row


def _join_dates(values: Iterable[date]) -> str:
    return ",".join(value.isoformat() for value in values)


def setup02_event_identity(
    symbol: str,
    trade_date: date,
    event_type: SetupState,
    lifecycle_index: int | None,
) -> str:
    """Return a deterministic exactly-once identity in the SETUP_02 namespace."""
    return (
        f"{symbol}|{SETUP02_TYPE}|{trade_date.isoformat()}|"
        f"{event_type.value}|lifecycle={lifecycle_index or 0}"
    )


def replay_setup02_history(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> Setup02ReplayReport:
    """Replay SETUP_02 using only the visible historical prefix."""
    validate_quote_series(quotes)
    resolved_as_of = as_of_date or quotes[-1].trade_date
    visible = [quote for quote in quotes if quote.trade_date <= resolved_as_of]
    if not visible:
        raise ValueError("as_of_date 之前没有可用行情")

    snapshots = evaluate_setup02_history(
        visible,
        daily_swing_lookback=daily_swing_lookback,
        weekly_swing_lookback=weekly_swing_lookback,
    )
    state_dates: dict[SetupState, list[date]] = {
        state: [] for state in SETUP02_REPLAY_STATES
    }
    days: list[Setup02ReplayDay] = []
    events: list[Setup02ReplayEvent] = []
    event_ids: set[str] = set()
    confirmed_dates: list[date] = []
    failed_dates: list[date] = []

    for quote, snapshot in zip(visible, snapshots):
        state_dates[snapshot.state].append(quote.trade_date)
        confirmed = snapshot.is_new_confirmed_event_as_of
        failed = snapshot.is_new_failed_event_as_of
        if confirmed or failed:
            event_type = SetupState.CONFIRMED if confirmed else SetupState.FAILED
            event_id = setup02_event_identity(
                quote.symbol,
                quote.trade_date,
                event_type,
                snapshot.lifecycle_index,
            )
            if event_id not in event_ids:
                event_ids.add(event_id)
                events.append(
                    Setup02ReplayEvent(
                        event_identity=event_id,
                        symbol=quote.symbol,
                        trade_date=quote.trade_date,
                        event_type=event_type,
                        setup02=snapshot,
                        market=quote.market,
                    )
                )
            if confirmed:
                confirmed_dates.append(quote.trade_date)
            else:
                failed_dates.append(quote.trade_date)
        days.append(
            Setup02ReplayDay(
                symbol=quote.symbol,
                trade_date=quote.trade_date,
                setup02=snapshot,
                confirmed_event=confirmed,
                failed_event=failed,
            )
        )

    state_date_tuples = {state: tuple(values) for state, values in state_dates.items()}
    return Setup02ReplayReport(
        symbol=visible[0].symbol,
        market=visible[0].market,
        days=tuple(days),
        events=tuple(events),
        state_day_counts={
            state: len(values) for state, values in state_date_tuples.items()
        },
        state_dates=state_date_tuples,
        confirmed_event_dates=tuple(confirmed_dates),
        failed_event_dates=tuple(failed_dates),
    )


def setup02_event_rows(reports: Iterable[Setup02ReplayReport]) -> list[dict]:
    rows: list[dict] = []
    for report in reports:
        for event in report.events:
            row = setup02_evaluation_to_dict(event.setup02)
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
    "SETUP02_REPLAY_STATES",
    "Setup02ReplayDay",
    "Setup02ReplayEvent",
    "Setup02ReplayReport",
    "replay_setup02_history",
    "setup02_event_identity",
    "setup02_event_rows",
]
