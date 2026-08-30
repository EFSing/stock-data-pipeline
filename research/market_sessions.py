"""Deterministic market-session dates derived from an already frozen dataset.

The helpers in this module intentionally do not call a calendar provider.  A
market session is a distinct local ``Quote.trade_date`` present in the frozen
input for that market.  This is sufficient for descriptive event-date drift
and keeps the qualification evidence tied to the exact replay input.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from core import Quote


DEVELOPMENT_SESSION_IDENTITY = "FROZEN_DATASET_MARKET_SESSION_SET"


def build_market_session_dates(
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> dict[str, tuple[date, ...]]:
    """Return the sorted frozen-dataset session union for each market.

    This is the development T+1 identity.  It is deliberately not an
    exchange-calendar claim: if an entire frozen market universe is absent on
    a real session, this observed union cannot identify that missing session.
    """
    dates_by_market: dict[str, set[date]] = {}
    for quotes in symbol_quotes.values():
        for quote in quotes:
            dates_by_market.setdefault(quote.market, set()).add(quote.trade_date)
    return {
        market: tuple(sorted(dates))
        for market, dates in sorted(dates_by_market.items())
    }


def trading_day_distance(
    old_date: date,
    new_date: date,
    *,
    market: str,
    market_session_dates: Mapping[str, Sequence[date]],
) -> int:
    """Return absolute ordinal distance in the supplied market sessions.

    Both dates must be present in the corresponding market session set.  This
    fail-closed check prevents a malformed event date from silently receiving
    a calendar-day interpretation.
    """
    sessions = tuple(market_session_dates.get(market, ()))
    ordinal = {session_date: index for index, session_date in enumerate(sessions)}
    missing = [event_date.isoformat() for event_date in (old_date, new_date) if event_date not in ordinal]
    if missing:
        raise ValueError(
            f"matched event date is not in {market} market session set: {', '.join(missing)}"
        )
    return abs(ordinal[new_date] - ordinal[old_date])


__all__ = [
    "DEVELOPMENT_SESSION_IDENTITY",
    "build_market_session_dates",
    "trading_day_distance",
]
