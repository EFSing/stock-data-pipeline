"""Causal research-only observer for the frozen post-H1 dual-path design."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from statistics import median
from typing import Any

from core import Quote
from trading.fibonacci import EXTENSION_RATIOS, project_extension
from trading.indicators import atr
from trading.models import SwingKind, validate_quote_series
from trading.swing import find_swings


OBSERVER_VERSION = "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1"


@dataclass(frozen=True)
class BreakoutAnchor:
    event_identity: str
    breakout_date: date
    low0: float
    h1: float
    wave2_low: float


def _event(symbol: str, market: str, day: date, kind: str, **values: Any) -> dict[str, Any]:
    return {
        "event_id": f"{OBSERVER_VERSION}|{market}|{symbol}|{day.isoformat()}|{kind}",
        "observer_version": OBSERVER_VERSION,
        "symbol": symbol,
        "market": market,
        "session_date": day.isoformat(),
        "event_type": kind,
        "research_only_candidate": kind in {"PATH_A_SIGNAL", "PATH_B_SIGNAL"},
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
        **values,
    }


def _zone(prefix: list[Quote], *, breakout_index: int, day_index: int, anchor: BreakoutAnchor,
          atr_values: list[float | None]) -> dict[str, Any] | None:
    """Select the one active zone before day_index using data <= day_index-1."""
    if day_index <= breakout_index:
        return None
    atr_b = atr_values[breakout_index]
    if atr_b is None:
        return None
    previous_close = float(prefix[day_index - 1].close)
    candidates: list[dict[str, Any]] = []
    shelf = {"kind": "H1_SHELF", "lower": anchor.h1 - .25 * atr_b,
             "upper": anchor.h1 + .25 * atr_b, "priority": 1}
    candidates.append(shelf)
    running_high = max(float(row.high) for row in prefix[breakout_index:day_index])
    if running_high - anchor.h1 >= .5 * atr_b:
        candidates.append({
            "kind": "RUNNING_LEG_FIB",
            "lower": running_high - .618 * (running_high - anchor.h1),
            "upper": running_high - .382 * (running_high - anchor.h1),
            "priority": 2,
        })
    visible = prefix[:day_index]
    for swing in find_swings(visible):
        if swing.kind is not SwingKind.LOW or swing.pivot_index <= breakout_index:
            continue
        if swing.confirmed_index is None or swing.confirmed_index > day_index - 1:
            continue
        atr_at_confirmation = atr_values[swing.confirmed_index]
        if atr_at_confirmation is None:
            continue
        candidates.append({
            "kind": "CONFIRMED_SWING",
            "lower": swing.price - .25 * atr_at_confirmation,
            "upper": swing.price + .25 * atr_at_confirmation,
            "priority": 3,
            "pivot_date": swing.pivot_date.isoformat(),
            "confirmed_date": swing.confirmed_date.isoformat() if swing.confirmed_date else None,
        })
    eligible = [item for item in candidates
                if item["upper"] < previous_close and item["lower"] > anchor.wave2_low]
    if not eligible:
        return None
    selected = max(eligible, key=lambda item: (item["upper"], item["priority"]))
    return {key: value for key, value in selected.items() if key != "priority"}


def _targets(prefix: list[Quote], index: int, anchor: BreakoutAnchor, trigger: float) -> list[dict[str, Any]]:
    candidates: list[tuple[float, str]] = []
    for swing in find_swings(prefix[: index + 1]):
        if swing.kind is SwingKind.HIGH and swing.confirmed_index is not None and swing.confirmed_index <= index:
            if swing.price > trigger:
                candidates.append((float(swing.price), f"CONFIRMED_SWING_HIGH:{swing.pivot_date.isoformat()}"))
    for label, ratio in EXTENSION_RATIOS.items():
        value = project_extension(anchor.wave2_low, anchor.low0, anchor.h1, ratio)
        if value > trigger:
            candidates.append((value, f"WAVE1_EXTENSION:{label}"))
    merged: dict[float, list[str]] = {}
    for value, source in candidates:
        merged.setdefault(round(value, 10), []).append(source)
    return [{"price": value, "provenance": sorted(sources)}
            for value, sources in sorted(merged.items())][:3]


def _diagnostics(entry: float, stop: float, t1: float) -> dict[str, Any]:
    risk = entry - stop
    upside = (t1 - entry) / entry if entry > 0 else None
    rr = (t1 - entry) / risk if risk > 0 else None
    stop_distance = risk / entry if entry > 0 and risk > 0 else None
    if upside is None:
        return_band = "UNAVAILABLE"
    elif upside < .01:
        return_band = "LT_1_PCT"
    elif upside < .02:
        return_band = "1_TO_LT_2_PCT"
    elif upside < .03:
        return_band = "2_TO_LT_3_PCT"
    elif upside < .05:
        return_band = "3_TO_LT_5_PCT"
    else:
        return_band = "GE_5_PCT"
    return {
        "target_upside_pct": upside,
        "gross_t1_headroom_pct": upside,
        "planned_stop_distance_pct": stop_distance,
        "one_r_pct": stop_distance,
        "t1_rr": rr,
        "five_pct_pass": bool(upside is not None and upside >= .05),
        "two_r_pass": bool(rr is not None and rr >= 2.0),
        "gate_role": "DIAGNOSTIC_ONLY_G1_DOES_NOT_REJECT",
        "estimated_trading_cost": {
            "status": "PENDING_EVENT_DATE_QUANTITY_AND_EFFECTIVE_FEE_EVIDENCE",
            "baseline_spread_slippage_bp_per_side": 10.0,
            "stress_spread_slippage_bp_per_side": 25.0,
            "gross_is_not_net": True,
        },
        "diagnostic_dimensions": {
            "SIGNAL_VALID": "VALID",
            "RISK_VALID": "VALID" if stop_distance is not None else "INVALID",
            "TARGET_GEOMETRY": "NEAREST_CAUSAL_T1_RECORDED",
            "ECONOMIC_ATTRACTIVENESS": {
                "status": "READ_ONLY_DIAGNOSTIC_NO_HARD_THRESHOLD",
                "gross_headroom_band": return_band,
                "user_low_return_preference_recorded": True,
            },
            "RESEARCH_ADMISSION": "ADMITTED_UNDER_FROZEN_D1_PROTOCOL",
        },
    }


def observe_dual_path(quotes: list[Quote], anchor: BreakoutAnchor, *, as_of_date: date | None = None) -> list[dict[str, Any]]:
    """Replay only the observed prefix and emit immutable research facts.

    The function models daily-OHLC outcomes, never real executions. It uses one
    Path-A and one Path-B opportunity until the first modeled fill, with a
    shared 20-completed-session window beginning on breakout day B.
    """
    validate_quote_series(quotes)
    visible = [row for row in quotes if as_of_date is None or row.trade_date <= as_of_date]
    if not visible:
        return []
    symbol, market = visible[0].symbol, visible[0].market.upper()
    try:
        b = next(i for i, row in enumerate(visible) if row.trade_date == anchor.breakout_date)
    except StopIteration as exc:
        raise ValueError("breakout date is absent from the observed prefix") from exc
    if b == 0:
        raise ValueError("breakout requires a preceding session")
    atr_values = atr(visible, 14)
    atr_b = atr_values[b]
    if atr_b is None:
        raise ValueError("breakout ATR14 unavailable")
    events: list[dict[str, Any]] = [_event(
        symbol, market, visible[b].trade_date, "H1_BREAKOUT",
        lifecycle_id=f"{anchor.event_identity}|SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1",
        anchors={"LOW0": anchor.low0, "H1": anchor.h1, "wave2_low": anchor.wave2_low, "ATR_B": atr_b},
    )]
    path_used = {"A": False, "B": False}
    retest_touched = False
    pending: dict[str, Any] | None = None
    position: dict[str, Any] | None = None
    entry_day_stop_pending = False
    completed = False
    censored_emitted = False

    for i in range(b, min(len(visible), b + 20)):
        row = visible[i]
        atr_t = atr_values[i]
        if not all(math.isfinite(float(value)) and float(value) > 0 for value in (row.open, row.high, row.low, row.close)):
            events.append(_event(symbol, market, row.trade_date, "DATA_MISSING", model_outcome="INVALID_OHLC"))
            continue
        if row.volume is None or not math.isfinite(float(row.volume)) or float(row.volume) <= 0:
            events.append(_event(symbol, market, row.trade_date, "DATA_MISSING", model_outcome="SUSPENDED_OR_VOLUME_UNAVAILABLE"))
            continue

        # A plan is valid for exactly this next session and never rolls forward.
        if pending is not None and pending["execution_index"] == i and position is None:
            trigger, ceiling, stop, t1 = (pending[key] for key in ("trigger", "ceiling", "stop", "t1"))
            outcome, actual = "NOT_TRIGGERED", None
            if float(row.open) > ceiling:
                outcome = "SKIP_GAP_ABOVE_CEILING"
            elif trigger <= float(row.open) <= ceiling:
                actual, outcome = float(row.open), "MODEL_EXECUTED"
            elif float(row.open) < trigger <= float(row.high):
                actual, outcome = trigger, "MODEL_EXECUTED"
            if actual is not None and actual >= t1:
                actual, outcome = None, "SKIP_NO_REMAINING_TARGET"
            kind = "MODEL_EXECUTION" if actual is not None else "MODEL_EXECUTION_SKIPPED"
            ambiguity = bool(actual is not None and float(row.low) <= stop and float(row.high) >= t1)
            events.append(_event(symbol, market, row.trade_date, kind, path=pending["path"],
                                 model_outcome=outcome, actual_entry=actual,
                                 ambiguity="BUY_STOP_STOP_TARGET_ORDER_UNKNOWN_STOP_FIRST" if ambiguity else None))
            if actual is not None:
                position = {**pending, "entry": actual, "entry_index": i}
                if market == "CN" and float(row.low) <= stop:
                    entry_day_stop_pending = True
                    events.append(_event(symbol, market, row.trade_date, "ENTRY_DAY_STOP_BREACH_PENDING",
                                         model_outcome="CN_T_PLUS_ONE_SELL_REQUIRED"))
                elif market == "US" and float(row.low) <= stop:
                    completed = True
                    events.append(_event(symbol, market, row.trade_date, "RESEARCH_EXIT",
                                         model_outcome="STOP_FIRST", exit_price=min(float(row.open), stop)))
                elif market == "US" and float(row.high) >= t1:
                    completed = True
                    events.append(_event(symbol, market, row.trade_date, "RESEARCH_EXIT",
                                         model_outcome="X1_T1_FULL_EXIT", exit_price=t1))
            pending = None

        if position is not None and not completed and i > position["entry_index"]:
            stop, t1 = position["stop"], position["t1"]
            if entry_day_stop_pending:
                completed = True
                events.append(_event(symbol, market, row.trade_date, "RESEARCH_EXIT",
                                     model_outcome="CN_T_PLUS_ONE_PENDING_STOP", exit_price=float(row.open)))
            elif float(row.open) <= stop or float(row.low) <= stop:
                completed = True
                events.append(_event(symbol, market, row.trade_date, "RESEARCH_EXIT",
                                     model_outcome="GAP_STOP" if float(row.open) <= stop else "INTRADAY_STOP",
                                     exit_price=float(row.open) if float(row.open) <= stop else stop))
            elif float(row.high) >= t1:
                completed = True
                events.append(_event(symbol, market, row.trade_date, "RESEARCH_EXIT",
                                     model_outcome="X1_T1_FULL_EXIT", exit_price=t1))
        if position is not None or completed:
            continue
        if float(row.close) <= anchor.low0 or float(row.close) <= anchor.wave2_low:
            events.append(_event(symbol, market, row.trade_date, "STRUCTURAL_INVALIDATION",
                                 model_outcome="LOW0" if float(row.close) <= anchor.low0 else "WAVE2_LOW"))
            break

        zone = _zone(visible, breakout_index=b, day_index=i, anchor=anchor, atr_values=atr_values)
        touched = bool(zone and float(row.low) <= zone["upper"] and float(row.high) >= zone["lower"])
        if i > b and zone and not retest_touched:
            events.append(_event(symbol, market, row.trade_date, "PATH_B_CANDIDATE",
                                 levels={"support_zone": [zone["lower"], zone["upper"]], "support_kind": zone["kind"]}))
        if i > b and touched:
            retest_touched = True
            events.append(_event(symbol, market, row.trade_date, "PATH_B_TOUCH",
                                 levels={"support_zone": [zone["lower"], zone["upper"]], "support_kind": zone["kind"]}))
        bar_range = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open)) / bar_range if bar_range > 0 else 0.0
        close_location = (float(row.close) - float(row.low)) / bar_range if bar_range > 0 else 0.0
        previous = visible[i - 1]
        path: str | None = None
        if i > b and touched and not path_used["B"] and zone is not None:
            if (float(row.close) > zone["upper"] and float(row.close) > float(row.open)
                    and float(row.close) > float(previous.close) and body >= .35 and close_location >= .70):
                path = "B"
        elif not retest_touched and not path_used["A"]:
            if (float(row.close) > anchor.h1 and float(row.close) > float(previous.high)
                    and float(row.close) > float(row.open) and body >= .50 and close_location >= .75):
                path = "A"
        if path is None or atr_t is None:
            continue
        path_used[path] = True
        trigger = float(row.high)
        ceiling = trigger + .5 * atr_t
        stop = (min(float(row.low), anchor.h1) if path == "A"
                else min(float(row.low), float(zone["lower"]))) - .25 * atr_t
        targets = _targets(visible, i, anchor, trigger)
        levels = {"support_zone": None if zone is None else [zone["lower"], zone["upper"]],
                  "entry_trigger": trigger, "entry_ceiling": ceiling, "stop": stop,
                  "T1": targets[0]["price"] if targets else None,
                  "T2": targets[1]["price"] if len(targets) > 1 else None,
                  "T3": targets[2]["price"] if len(targets) > 2 else None,
                  "targets": targets}
        kind = "PATH_A_SIGNAL" if path == "A" else "PATH_B_SIGNAL"
        if not targets or stop >= trigger:
            events.append(_event(symbol, market, row.trade_date, kind, levels=levels,
                                 diagnostics={}, model_outcome="INVALID_PLAN_NO_TARGET_OR_STOP"))
            continue
        rvol = None
        if i >= 20:
            prior_volumes = [float(item.volume) for item in visible[i - 20:i]
                             if item.volume is not None and float(item.volume) > 0]
            if len(prior_volumes) == 20:
                rvol = float(row.volume) / median(prior_volumes)
        diagnostics = {**_diagnostics(ceiling, stop, targets[0]["price"]), "rvol20": rvol}
        events.append(_event(symbol, market, row.trade_date, kind, levels=levels,
                             diagnostics=diagnostics, model_outcome="RESEARCH_PLAN_CREATED"))
        if i + 1 < len(visible) and i + 1 < b + 20:
            pending = {"path": path, "trigger": trigger, "ceiling": ceiling, "stop": stop,
                       "t1": targets[0]["price"], "execution_index": i + 1}
        else:
            events.append(_event(symbol, market, row.trade_date, "RIGHT_CENSORED",
                                 model_outcome="NEXT_SESSION_NOT_OBSERVED"))
            censored_emitted = True
    if position is not None and not completed:
        events.append(_event(symbol, market, visible[min(len(visible) - 1, b + 19)].trade_date,
                             "RIGHT_CENSORED", model_outcome="OPEN_RESEARCH_POSITION"))
    elif len(visible) >= b + 20 and not completed and pending is None:
        events.append(_event(symbol, market, visible[b + 19].trade_date, "OBSERVATION_TIMEOUT",
                             model_outcome="NO_MODELED_FILL_IN_20_SESSIONS"))
    elif not censored_emitted and not completed and pending is None:
        events.append(_event(symbol, market, visible[-1].trade_date, "RIGHT_CENSORED",
                             model_outcome="OBSERVATION_PREFIX_ENDED"))
    return events


__all__ = ["BreakoutAnchor", "OBSERVER_VERSION", "observe_dual_path"]
