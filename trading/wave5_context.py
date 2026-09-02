"""Causal Wave 4 / Wave 5 context for already-open long positions.

This module is deliberately downstream of the frozen SETUP_01/SETUP_02
entry layers.  It never creates an entry signal.  A Wave 5 candidate is only
an explanatory context and may produce ``NO_ADD`` in Position Management.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from core import Quote
from trading.models import SwingKind, SwingPoint
from trading.swing import find_swings


WAVE5_CONTEXT_PROTOCOL_VERSION = "WAVE-5-CONTEXT-2026-09-02-v1"


class Wave5ContextState(str, Enum):
    NO_WAVE5_CONTEXT = "NO_WAVE5_CONTEXT"
    WAVE4_PULLBACK_CONTEXT = "WAVE4_PULLBACK_CONTEXT"
    WAVE5_CANDIDATE = "WAVE5_CANDIDATE"


@dataclass(frozen=True)
class Wave5Context:
    protocol_version: str
    as_of_date: date
    state: Wave5ContextState
    supporting_evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: float | None
    high3: SwingPoint | None
    low4: SwingPoint | None


def _confirmed_swings_as_of(
    quotes: Sequence[Quote],
    as_of_index: int,
    *,
    swing_lookback: int,
    all_swings: Sequence[SwingPoint] | None = None,
) -> tuple[SwingPoint, ...]:
    """Return only swings whose confirmation is available in the prefix."""
    swings = (
        tuple(all_swings)
        if all_swings is not None
        else find_swings(list(quotes[: as_of_index + 1]), lookback=swing_lookback)
    )
    return tuple(
        swing
        for swing in swings
        if swing.confirmed_index is not None
        and swing.confirmed_index <= as_of_index
        and swing.pivot_index <= as_of_index
        and swing.confirmed_date is not None
        and swing.confirmed_date <= quotes[as_of_index].trade_date
    )


def _anchor(anchors: Sequence[object], name: str) -> object | None:
    for value in anchors:
        if getattr(value, "name", None) == name:
            return value
    return None


def evaluate_wave5_context(
    *,
    quotes: Sequence[Quote],
    as_of_index: int,
    wave_anchors: Sequence[object],
    structural_invalidation: float | None,
    swing_lookback: int = 5,
    confirmed_swings: Sequence[SwingPoint] | None = None,
) -> Wave5Context:
    """Evaluate a causal Wave4/Wave5 context for one still-open position.

    The source position supplies its original Wave3 thesis high and Wave2 low
    through immutable named anchors.  A new HIGH3 must be a confirmed higher
    high after that thesis high, followed by a confirmed LOW4 that remains
    above the original Wave2 low.  The current close must strictly exceed the
    new HIGH3 before the state becomes ``WAVE5_CANDIDATE``.
    """
    if not quotes:
        raise ValueError("quotes 不能为空")
    if as_of_index < 0 or as_of_index >= len(quotes):
        raise IndexError("as_of_index 超出 quotes 范围")
    if swing_lookback < 1:
        raise ValueError("swing_lookback 必须 >= 1")

    thesis_high = _anchor(wave_anchors, "HIGH3") or _anchor(wave_anchors, "HIGH1")
    wave2_low = _anchor(wave_anchors, "LOW2")
    if thesis_high is None or wave2_low is None:
        return Wave5Context(
            protocol_version=WAVE5_CONTEXT_PROTOCOL_VERSION,
            as_of_date=quotes[as_of_index].trade_date,
            state=Wave5ContextState.NO_WAVE5_CONTEXT,
            supporting_evidence=(),
            counter_evidence=("MISSING_WAVE3_THESIS_ANCHORS",),
            invalidation=structural_invalidation,
            high3=None,
            low4=None,
        )

    confirmed = _confirmed_swings_as_of(
        quotes,
        as_of_index,
        swing_lookback=swing_lookback,
        all_swings=confirmed_swings,
    )
    higher_highs = [
        swing
        for swing in confirmed
        if swing.kind is SwingKind.HIGH
        and swing.pivot_index > getattr(thesis_high, "pivot_index", -1)
        and swing.price > float(getattr(thesis_high, "price"))
    ]
    candidates: list[tuple[SwingPoint, SwingPoint]] = []
    for high3 in higher_highs:
        lows = [
            swing
            for swing in confirmed
            if swing.kind is SwingKind.LOW
            and swing.pivot_index > high3.pivot_index
            and swing.price > float(getattr(wave2_low, "price"))
        ]
        if lows:
            candidates.append((high3, max(lows, key=lambda item: item.pivot_index)))

    if not candidates:
        return Wave5Context(
            protocol_version=WAVE5_CONTEXT_PROTOCOL_VERSION,
            as_of_date=quotes[as_of_index].trade_date,
            state=Wave5ContextState.NO_WAVE5_CONTEXT,
            supporting_evidence=(),
            counter_evidence=("NO_CONFIRMED_HIGH3_LOW4_SEQUENCE",),
            invalidation=structural_invalidation,
            high3=None,
            low4=None,
        )

    high3, low4 = max(candidates, key=lambda item: item[1].pivot_index)
    current_close = float(quotes[as_of_index].close)
    state = (
        Wave5ContextState.WAVE5_CANDIDATE
        if current_close > high3.price
        else Wave5ContextState.WAVE4_PULLBACK_CONTEXT
    )
    supporting = (
        "CONFIRMED_HIGH3_AFTER_THESIS_HIGH",
        "CONFIRMED_LOW4_AFTER_HIGH3",
        "LOW4_ABOVE_ORIGINAL_WAVE2_LOW",
    )
    counter = (
        ()
        if state is Wave5ContextState.WAVE5_CANDIDATE
        else ("T_CLOSE_NOT_ABOVE_HIGH3",)
    )
    return Wave5Context(
        protocol_version=WAVE5_CONTEXT_PROTOCOL_VERSION,
        as_of_date=quotes[as_of_index].trade_date,
        state=state,
        supporting_evidence=supporting,
        counter_evidence=counter,
        invalidation=structural_invalidation,
        high3=high3,
        low4=low4,
    )


__all__ = [
    "WAVE5_CONTEXT_PROTOCOL_VERSION",
    "Wave5Context",
    "Wave5ContextState",
    "evaluate_wave5_context",
]
