"""Build the tracked, structure-only SETUP_03 decision capsule.

The capsule is derived from the audit-only main-baseline replay reference.  It
contains no outcome metrics and does not select a tolerance or alter SETUP_03.
The raw dataset and the full ignored evidence artifacts remain outside Git.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from core import Quote
from research.legacy_main_replay import (
    legacy_main_replay_identity,
    legacy_main_replay_setup03_history_cached,
)
from research.market_sessions import build_market_session_dates, trading_day_distance
from research.replay_input import ReplayInputManifest, build_input_manifest, read_frozen_input
from research.structural_validation_protocol_v2 import load_protocol
from trading.models import DecisionAction, SetupState
from trading.replay import replay_parity_mismatches, replay_setup03_history


TOLERANCE_SEQUENCE = (0.025, 0.03, 0.04, 0.05, 0.055, 0.075, 0.10)
PRODUCTION_TOLERANCES = (0.03, 0.04, 0.05)
RISK_CAPITAL = 100_000.0
SETUP_PARAMETERS = {
    "swing_lookback": 5,
    "platform_window": 40,
    "arm_proximity_pct": 0.0,
}
DECISION_PARAMETERS = {
    "swing_lookback": 5,
    "atr_period": 14,
    "atr_buffer": 0.5,
    "max_chase_atr": 0.5,
}

EXPECTED_UNIVERSE_HASH = "sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046"
EXPECTED_DATASET_MANIFEST_HASH = "sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216"
EXPECTED_DATASET_AGGREGATE_HASH = "sha256:c9b3a4db8158da66f0030746498a692920fe95d72bdacc32499d1ab70c150356"
EXPECTED_REPLAY_INPUT_HASH = "sha256:9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18"
QUALIFICATION_TRANSITIONS = ((0.03, 0.04), (0.04, 0.05))

_METRIC_FIELDS = (
    "symbol_count",
    "bars",
    "platform_detected",
    "platform_per_1000_bars",
    "NONE",
    "WATCH",
    "ARMED",
    "CONFIRMED_STATE_DAYS",
    "FAILED",
    "CONFIRMED_EVENTS",
    "CONFIRMED_per_1000_bars",
    "ENTRY_ALLOWED",
    "ENTRY_ALLOWED_per_1000_bars",
    "symbols_with_zero_confirmed",
    "symbols_with_1_to_2_confirmed",
    "max_symbol_event_share",
    "top_3_symbol_event_share",
    "high_span_median",
    "high_span_P90",
    "low_span_median",
    "low_span_P90",
    "platform_width_median",
    "platform_width_P90",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _quantile(values: list[float], q: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _event_key(event: Any) -> tuple[str, date]:
    return event.symbol, event.confirmed_date or event.trade_date


def _compact_report(report: Any) -> dict[str, Any]:
    """Keep only structure/decision diagnostics needed by the capsule."""
    state_counts = Counter(day.setup_state.value for day in report.days)
    terminal_reasons = Counter(
        day.setup_diagnostics.reason.value
        for day in report.days
        if day.setup_diagnostics is not None
    )
    platform_spans: list[dict[str, float]] = []
    platform_detected = 0
    for day in report.days:
        diagnostics = day.setup_diagnostics
        if diagnostics is None or not diagnostics.platform_detected_this_bar:
            continue
        platform_detected += 1
        if (
            diagnostics.high_span is not None
            and diagnostics.low_span is not None
            and diagnostics.breakout_price is not None
            and diagnostics.structural_invalidation is not None
            and diagnostics.close
            and diagnostics.close > 0
        ):
            platform_spans.append(
                {
                    "high_span": diagnostics.high_span,
                    "low_span": diagnostics.low_span,
                    "platform_width": (
                        diagnostics.breakout_price
                        - diagnostics.structural_invalidation
                    )
                    / diagnostics.close,
                }
            )
    confirmed_events = [
        event for event in report.events if event.event_type is SetupState.CONFIRMED
    ]
    decision_reasons = Counter()
    for event in confirmed_events:
        if event.decision_diagnostics is not None:
            decision_reasons[event.decision_diagnostics.reason.value] += 1
        elif event.decision is not None and event.decision.action is DecisionAction.ENTRY_ALLOWED:
            decision_reasons["ENTRY_ALLOWED"] += 1
        else:
            decision_reasons["OTHER_NO_TRADE"] += 1
    return {
        "symbol": report.symbol,
        "market": report.market,
        "bars": len(report.days),
        "state_counts": dict(sorted(state_counts.items())),
        "terminal_reasons": dict(sorted(terminal_reasons.items())),
        "platform_detected": platform_detected,
        "confirmed_events": len(confirmed_events),
        "entry_allowed": sum(
            event.decision is not None
            and event.decision.action is DecisionAction.ENTRY_ALLOWED
            for event in confirmed_events
        ),
        "decision_reasons": dict(sorted(decision_reasons.items())),
        "event_keys": [
            [symbol, event_date.isoformat()]
            for symbol, event_date in (_event_key(event) for event in confirmed_events)
        ],
        "platform_spans": platform_spans,
    }


def _parity_symbol_task(
    task: tuple[str, list[Quote], dict[str, Any], dict[str, Any], float]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    symbol, quotes, setup_parameters, decision_parameters, risk_capital = task
    parity_rows: list[dict[str, Any]] = []
    parity_mismatches: list[dict[str, Any]] = []
    compact_reports: list[dict[str, Any]] = []
    for tolerance in TOLERANCE_SEQUENCE:
        parameters = dict(setup_parameters)
        parameters["platform_tolerance_pct"] = tolerance
        legacy = legacy_main_replay_setup03_history_cached(
            quotes, risk_capital, parameters, decision_parameters
        )
        shared = replay_setup03_history(
            quotes, risk_capital, parameters, decision_parameters
        )
        precomputed = replay_setup03_history(
            quotes,
            risk_capital,
            parameters,
            decision_parameters,
            precompute_swings=True,
        )
        legacy_shared = replay_parity_mismatches(legacy, shared)
        legacy_precomputed = replay_parity_mismatches(legacy, precomputed)
        parity_rows.append(
            {
                "platform_tolerance_pct": tolerance,
                "market": quotes[0].market,
                "symbol": symbol,
                "bar_count": len(quotes),
                "legacy_event_count": len(legacy.events),
                "shared_event_count": len(shared.events),
                "precomputed_event_count": len(precomputed.events),
                "legacy_shared_mismatch_count": len(legacy_shared),
                "legacy_precomputed_mismatch_count": len(legacy_precomputed),
                "status": (
                    "IDENTICAL"
                    if not legacy_shared and not legacy_precomputed
                    else "MISMATCH"
                ),
            }
        )
        for path_name, differences in (
            ("legacy_vs_shared", legacy_shared),
            ("legacy_vs_precomputed", legacy_precomputed),
        ):
            for difference in differences[:50]:
                parity_mismatches.append(
                    {
                        "path": path_name,
                        "platform_tolerance_pct": tolerance,
                        "symbol": symbol,
                        **difference,
                    }
                )
        compact_reports.append(
            {
                "platform_tolerance_pct": tolerance,
                "report": _compact_report(legacy),
            }
        )
    return parity_rows, parity_mismatches, compact_reports


def run_legacy_main_parity(
    symbol_quotes: Mapping[str, list[Quote]],
    *,
    setup_parameters: Mapping[str, Any] = SETUP_PARAMETERS,
    decision_parameters: Mapping[str, Any] = DECISION_PARAMETERS,
    risk_capital: float = RISK_CAPITAL,
) -> dict[str, Any]:
    """Run the raw main-baseline audit and both current replay paths."""
    tasks = [
        (
            symbol,
            quotes,
            dict(setup_parameters),
            dict(decision_parameters),
            risk_capital,
        )
        for symbol, quotes in sorted(symbol_quotes.items())
    ]
    max_workers = min(8, max(1, os.cpu_count() or 1), len(tasks))
    if max_workers == 1:
        results = [_parity_symbol_task(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_parity_symbol_task, tasks))
    parity_rows = [row for rows, _, _ in results for row in rows]
    mismatches = [item for _, items, _ in results for item in items]
    compact_reports = [item for _, _, items in results for item in items]
    parity_rows.sort(key=lambda row: (row["platform_tolerance_pct"], row["symbol"]))
    compact_reports.sort(
        key=lambda item: (item["platform_tolerance_pct"], item["report"]["symbol"])
    )
    bar_comparisons = sum(row["bar_count"] for row in parity_rows)
    event_comparisons = sum(row["legacy_event_count"] for row in parity_rows)
    shared_mismatches = sum(row["legacy_shared_mismatch_count"] for row in parity_rows)
    precomputed_mismatches = sum(
        row["legacy_precomputed_mismatch_count"] for row in parity_rows
    )
    total_mismatches = shared_mismatches + precomputed_mismatches
    return {
        "schema_version": "setup03-legacy-main-parity-v1",
        "baseline_commit": "40a3e5f980bf82a85717748ae106847793d1469f",
        "scope": {
            "symbol_count": len(symbol_quotes),
            "tolerance_count": len(TOLERANCE_SEQUENCE),
            "tolerance_sequence": list(TOLERANCE_SEQUENCE),
            "cells": len(parity_rows),
            "bar_comparisons": bar_comparisons,
            "event_comparisons": event_comparisons,
            "every_bar": True,
            "every_event": True,
            "setup_fields": [
                "state",
                "breakout_price",
                "structural_invalidation",
                "detected_index",
                "state_entered_index",
                "confirmed_index",
            ],
            "setup_diagnostic_fields": [
                "reason",
                "high_count",
                "low_count",
                "trend",
                "high_span",
                "low_span",
                "arm_threshold",
                "platform_detected_this_bar",
                "auxiliary_failed_conditions",
            ],
            "event_fields": [
                "event_type",
                "trade_date",
                "signal_date",
                "confirmed_date",
            ],
            "decision_fields": ["action", "diagnostics", "deterministic_operands"],
        },
        "status": "PASS" if total_mismatches == 0 else "MISMATCH_BASELINE_REQUIRED",
        "LEGACY_MAIN_PARITY_MISMATCHES": total_mismatches,
        "legacy_vs_shared_mismatches": shared_mismatches,
        "legacy_vs_precomputed_mismatches": precomputed_mismatches,
        "rows": parity_rows,
        "mismatches": mismatches,
        "compact_reports": compact_reports,
    }


def _summary_for_market(
    compact_reports: list[dict[str, Any]], market: str
) -> dict[str, Any]:
    selected = [
        item["report"]
        for item in compact_reports
        if market == "ALL" or item["report"]["market"] == market
    ]
    bars = sum(item["bars"] for item in selected)
    symbol_event_counts = Counter()
    for item in selected:
        symbol_event_counts[item["symbol"]] += item["confirmed_events"]
    event_count = sum(symbol_event_counts.values())
    entry_allowed = sum(item["entry_allowed"] for item in selected)
    spans = [span for item in selected for span in item["platform_spans"]]
    zero = sum(value == 0 for value in symbol_event_counts.values())
    sparse = sum(1 <= value <= 2 for value in symbol_event_counts.values())
    ordered_shares = sorted(
        (value / event_count for value in symbol_event_counts.values()),
        reverse=True,
    ) if event_count else []
    row = {
        "symbol_count": len(selected),
        "bars": bars,
        "platform_detected": sum(item["platform_detected"] for item in selected),
        "NONE": sum(item["state_counts"].get(SetupState.NONE.value, 0) for item in selected),
        "WATCH": sum(item["state_counts"].get(SetupState.WATCH.value, 0) for item in selected),
        "ARMED": sum(item["state_counts"].get(SetupState.ARMED.value, 0) for item in selected),
        "CONFIRMED_STATE_DAYS": sum(
            item["state_counts"].get(SetupState.CONFIRMED.value, 0)
            for item in selected
        ),
        "FAILED": sum(item["state_counts"].get(SetupState.FAILED.value, 0) for item in selected),
        "CONFIRMED_EVENTS": event_count,
        "ENTRY_ALLOWED": entry_allowed,
        "symbols_with_zero_confirmed": zero,
        "symbols_with_1_to_2_confirmed": sparse,
        "max_symbol_event_share": ordered_shares[0] if ordered_shares else None,
        "top_3_symbol_event_share": sum(ordered_shares[:3]) if ordered_shares else None,
        "high_span_median": median([span["high_span"] for span in spans]) if spans else None,
        "high_span_P90": _quantile([span["high_span"] for span in spans], 0.9),
        "low_span_median": median([span["low_span"] for span in spans]) if spans else None,
        "low_span_P90": _quantile([span["low_span"] for span in spans], 0.9),
        "platform_width_median": median([span["platform_width"] for span in spans]) if spans else None,
        "platform_width_P90": _quantile(
            [span["platform_width"] for span in spans], 0.9
        ),
    }
    row["platform_per_1000_bars"] = (
        1000 * row["platform_detected"] / bars if bars else 0.0
    )
    row["CONFIRMED_per_1000_bars"] = 1000 * event_count / bars if bars else 0.0
    row["ENTRY_ALLOWED_per_1000_bars"] = (
        1000 * entry_allowed / bars if bars else 0.0
    )
    return {field: row.get(field) for field in _METRIC_FIELDS}


def _event_keys_for_market(
    compact_reports: list[dict[str, Any]], market: str
) -> set[tuple[str, date]]:
    keys: set[tuple[str, date]] = set()
    for item in compact_reports:
        report = item["report"]
        if market != "ALL" and report["market"] != market:
            continue
        keys.update((str(symbol), date.fromisoformat(event_date)) for symbol, event_date in report["event_keys"])
    return keys


def _symbol_market_lookup(
    compact_reports: list[dict[str, Any]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in compact_reports:
        report = item["report"]
        symbol = str(report["symbol"])
        market = str(report["market"])
        previous = lookup.setdefault(symbol, market)
        if previous != market:
            raise ValueError(f"symbol has inconsistent markets: {symbol}")
    return lookup


def _fallback_market_session_dates(
    compact_reports: list[dict[str, Any]],
) -> dict[str, tuple[date, ...]]:
    """Build a test/backward-compatible session set from observed event dates."""
    dates_by_market: dict[str, set[date]] = {}
    for item in compact_reports:
        report = item["report"]
        dates_by_market.setdefault(str(report["market"]), set()).update(
            date.fromisoformat(event_date)
            for _, event_date in report["event_keys"]
        )
    return {
        market: tuple(sorted(dates))
        for market, dates in sorted(dates_by_market.items())
    }


def _nearest_matches(
    disappeared: set[tuple[str, date]], added: set[tuple[str, date]]
) -> list[tuple[str, date, date]]:
    candidates = sorted(
        (abs((new_date - old_date).days), symbol, old_date, new_date)
        for symbol, old_date in disappeared
        for new_symbol, new_date in added
        if symbol == new_symbol
    )
    used_old: set[tuple[str, date]] = set()
    used_new: set[tuple[str, date]] = set()
    matches: list[tuple[str, date, date]] = []
    for _, symbol, old_date, new_date in candidates:
        old_key = (symbol, old_date)
        new_key = (symbol, new_date)
        if old_key in used_old or new_key in used_new:
            continue
        used_old.add(old_key)
        used_new.add(new_key)
        matches.append((symbol, old_date, new_date))
    return matches


def _adjacent_summary(
    previous: float,
    current: float,
    reports_by_tolerance: Mapping[float, list[dict[str, Any]]],
    market: str,
    market_session_dates: Mapping[str, tuple[date, ...]] | None = None,
) -> dict[str, Any]:
    old = _event_keys_for_market(reports_by_tolerance[previous], market)
    new = _event_keys_for_market(reports_by_tolerance[current], market)
    retained = old & new
    added = new - old
    disappeared = old - new
    matches = _nearest_matches(disappeared, added)
    all_reports = reports_by_tolerance[previous] + reports_by_tolerance[current]
    symbol_markets = _symbol_market_lookup(all_reports)
    sessions = market_session_dates or _fallback_market_session_dates(all_reports)
    matched_pairs: list[dict[str, Any]] = []
    for symbol, old_date, new_date in matches:
        matched_market = market if market != "ALL" else symbol_markets[symbol]
        matched_pairs.append(
            {
                "symbol": symbol,
                "market": matched_market,
                "old_date": old_date.isoformat(),
                "new_date": new_date.isoformat(),
                "calendar_day_drift": abs((new_date - old_date).days),
                "trading_day_drift": trading_day_distance(
                    old_date,
                    new_date,
                    market=matched_market,
                    market_session_dates=sessions,
                ),
            }
        )
    calendar_day_drifts = [pair["calendar_day_drift"] for pair in matched_pairs]
    trading_day_drifts = [pair["trading_day_drift"] for pair in matched_pairs]
    bucket_ranges = (
        ("0-2", 0, 2),
        ("3-5", 3, 5),
        ("6-10", 6, 10),
        ("11-15", 11, 15),
    )
    trading_day_drift_buckets = {
        label: sum(lower <= drift <= upper for drift in trading_day_drifts)
        for label, lower, upper in bucket_ranges
    }
    trading_day_drift_buckets[">15"] = sum(
        drift > 15 for drift in trading_day_drifts
    )
    extreme_drift_pairs = sorted(
        matched_pairs,
        key=lambda pair: (
            -pair["trading_day_drift"],
            pair["symbol"],
            pair["old_date"],
            pair["new_date"],
        ),
    )[:20]
    return {
        "previous_event_count": len(old),
        "current_event_count": len(new),
        "retained": len(retained),
        "added": len(added),
        "disappeared": len(disappeared),
        "exact_date_jaccard": len(retained) / len(old | new) if old | new else 1.0,
        "nearest_date_matched_count": len(matches),
        "retention": len(retained) / len(old) if old else (1.0 if not new else 0.0),
        # Historical descriptive fields retain calendar-day semantics.
        "date_drift_median": median(calendar_day_drifts) if calendar_day_drifts else None,
        "date_drift_P90": _quantile([float(value) for value in calendar_day_drifts], 0.9),
        "calendar_day_drift_median": median(calendar_day_drifts) if calendar_day_drifts else None,
        "calendar_day_drift_P90": _quantile([float(value) for value in calendar_day_drifts], 0.9),
        # These are the only drift fields eligible for frozen qualification.
        "trading_day_drift_median": median(trading_day_drifts) if trading_day_drifts else None,
        "trading_day_drift_P90": _quantile([float(value) for value in trading_day_drifts], 0.9),
        "matched_pairs": matched_pairs,
        "trading_day_drift_buckets": trading_day_drift_buckets,
        "extreme_drift_pairs": extreme_drift_pairs,
    }


def _flag_definitions() -> dict[str, dict[str, Any]]:
    return {
        "SPARSE_AT_3": {
            "rule": "At 3%, each CN and US market has at least 30% of symbols with 0, 1, or 2 confirmed events.",
            "thresholds": {"minimum_market_symbol_fraction": 0.30},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "STRUCTURAL_EXPANSION_4_TO_5": {
            "rule": "ALL confirmed events grow by at least 20%, platform density by at least 10%, and high-span median by at least 10% from 4% to 5%.",
            "thresholds": {"event_growth": 0.20, "platform_density_growth": 0.10, "high_span_growth": 0.10},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "CROSS_MARKET_DIVERGENCE": {
            "rule": "At 3%, 4%, or 5%, CN/US event-density or platform-density ratio is outside [0.80, 1.25], or zero-event-symbol difference is at least 2, or max-share difference is at least 5 percentage points.",
            "thresholds": {"ratio_lower": 0.80, "ratio_upper": 1.25, "zero_event_difference": 2, "concentration_difference": 0.05},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "CONCENTRATION_HIGH": {
            "rule": "At any production tolerance and market aggregate, max single-symbol share is at least 10% or top-3 share is at least 30%.",
            "thresholds": {"max_symbol_share": 0.10, "top_3_symbol_share": 0.30},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "ADJACENT_STABILITY_HIGH": {
            "rule": "An adjacent pair is HIGH when exact-date Jaccard is at least 75% and retained/previous is at least 90%.",
            "thresholds": {"exact_date_jaccard": 0.75, "retention": 0.90},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "ADJACENT_STABILITY_LOW": {
            "rule": "An adjacent pair is LOW when either exact-date Jaccard is below 75% or retained/previous is below 90%.",
            "thresholds": {"exact_date_jaccard": 0.75, "retention": 0.90},
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
        "NO_CLEAR_STRUCTURAL_PLATEAU": {
            "rule": "Neither production transition 3%→4% nor 4%→5% is HIGH in the ALL aggregate.",
            "scope": "descriptive evidence only; does not affect SETUP_03",
        },
    }


def _build_flags(
    summaries: Mapping[float, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    at_3 = summaries[0.03]
    sparse_observations = {
        market: {
            "symbols": at_3[market]["symbol_count"],
            "zero": at_3[market]["symbols_with_zero_confirmed"],
            "one_to_two": at_3[market]["symbols_with_1_to_2_confirmed"],
            "zero_or_one_to_two": (
                at_3[market]["symbols_with_zero_confirmed"]
                + at_3[market]["symbols_with_1_to_2_confirmed"]
            ),
            "fraction": (
                at_3[market]["symbols_with_zero_confirmed"]
                + at_3[market]["symbols_with_1_to_2_confirmed"]
            )
            / at_3[market]["symbol_count"],
        }
        for market in ("CN", "US")
    }
    sparse = all(item["fraction"] >= 0.30 for item in sparse_observations.values())

    previous = summaries[0.04]["ALL"]
    current = summaries[0.05]["ALL"]
    expansion_observation = {
        "event_growth": current["CONFIRMED_EVENTS"] / previous["CONFIRMED_EVENTS"] - 1,
        "platform_density_growth": current["platform_per_1000_bars"] / previous["platform_per_1000_bars"] - 1,
        "high_span_median_growth": current["high_span_median"] / previous["high_span_median"] - 1,
    }
    expansion = (
        expansion_observation["event_growth"] >= 0.20
        and expansion_observation["platform_density_growth"] >= 0.10
        and expansion_observation["high_span_median_growth"] >= 0.10
    )

    cross_observations: dict[str, Any] = {}
    divergence = False
    for tolerance in PRODUCTION_TOLERANCES:
        cn = summaries[tolerance]["CN"]
        us = summaries[tolerance]["US"]
        event_ratio = cn["CONFIRMED_per_1000_bars"] / us["CONFIRMED_per_1000_bars"] if us["CONFIRMED_per_1000_bars"] else None
        platform_ratio = cn["platform_per_1000_bars"] / us["platform_per_1000_bars"] if us["platform_per_1000_bars"] else None
        zero_difference = cn["symbols_with_zero_confirmed"] - us["symbols_with_zero_confirmed"]
        concentration_difference = (
            (cn["max_symbol_event_share"] or 0.0)
            - (us["max_symbol_event_share"] or 0.0)
        )
        observed = {
            "event_density_ratio_CN_to_US": event_ratio,
            "platform_density_ratio_CN_to_US": platform_ratio,
            "zero_event_symbol_difference_CN_minus_US": zero_difference,
            "max_symbol_event_share_difference_CN_minus_US": concentration_difference,
        }
        cross_observations[f"{tolerance:.1%}"] = observed
        divergence = divergence or (
            event_ratio is not None and not 0.80 <= event_ratio <= 1.25
        ) or (
            platform_ratio is not None and not 0.80 <= platform_ratio <= 1.25
        ) or abs(zero_difference) >= 2 or abs(concentration_difference) >= 0.05

    concentration_observations = {
        f"{tolerance:.1%}": {
            market: {
                "max_symbol_event_share": summaries[tolerance][market]["max_symbol_event_share"],
                "top_3_symbol_event_share": summaries[tolerance][market]["top_3_symbol_event_share"],
            }
            for market in ("CN", "US", "ALL")
        }
        for tolerance in PRODUCTION_TOLERANCES
    }
    concentration_high = any(
        values["max_symbol_event_share"] is not None
        and (
            values["max_symbol_event_share"] >= 0.10
            or (values["top_3_symbol_event_share"] or 0.0) >= 0.30
        )
        for tolerance_values in concentration_observations.values()
        for values in tolerance_values.values()
    )

    stability: dict[str, Any] = {}
    high_any = False
    low_production_all = False
    for transition, market_rows in adjacent.items():
        stability[transition] = {}
        for market, row in market_rows.items():
            previous_count = row["previous_event_count"]
            retention = row["retained"] / previous_count if previous_count else (1.0 if row["current_event_count"] == 0 else 0.0)
            high = row["exact_date_jaccard"] >= 0.75 and retention >= 0.90
            stability[transition][market] = {
                "classification": "HIGH" if high else "LOW",
                "retention": retention,
                "exact_date_jaccard": row["exact_date_jaccard"],
            }
            high_any = high_any or high
            if transition in ("3.0%→4.0%", "4.0%→5.0%") and market == "ALL":
                low_production_all = low_production_all or not high

    return {
        "definitions": _flag_definitions(),
        "values": {
            "SPARSE_AT_3": sparse,
            "STRUCTURAL_EXPANSION_4_TO_5": expansion,
            "CROSS_MARKET_DIVERGENCE": divergence,
            "CONCENTRATION_HIGH": concentration_high,
            "ADJACENT_STABILITY_HIGH": high_any,
            "ADJACENT_STABILITY_LOW": low_production_all,
            "NO_CLEAR_STRUCTURAL_PLATEAU": low_production_all,
        },
        "observations": {
            "SPARSE_AT_3": sparse_observations,
            "STRUCTURAL_EXPANSION_4_TO_5": expansion_observation,
            "CROSS_MARKET_DIVERGENCE": cross_observations,
            "CONCENTRATION_HIGH": concentration_observations,
            "ADJACENT_STABILITY": stability,
        },
    }


def _threshold_observation(
    threshold_id: str,
    *,
    candidate: float,
    market: str,
    pair: tuple[float, float] | None,
    by_tolerance: Mapping[str, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> float | None:
    if threshold_id == "minimum_confirmed_events_per_market_candidate":
        return float(by_tolerance[f"{candidate:.1%}"][market]["CONFIRMED_EVENTS"])
    if threshold_id == "maximum_symbol_confirmed_concentration":
        return by_tolerance[f"{candidate:.1%}"][market]["max_symbol_event_share"]
    if pair is None:
        raise ValueError(f"adjacent threshold without pair: {threshold_id}")
    transition = f"{pair[0]:.1%}→{pair[1]:.1%}"
    row = adjacent[transition][market]
    if threshold_id == "adjacent_confirmed_jaccard":
        return row["exact_date_jaccard"]
    if threshold_id == "adjacent_confirmed_retention":
        return row["retention"]
    if threshold_id == "matched_confirmed_event_date_drift_median":
        return row["trading_day_drift_median"]
    if threshold_id == "matched_confirmed_event_date_drift_p90":
        return row["trading_day_drift_P90"]
    if threshold_id == "adjacent_confirmed_rate_relative_increase":
        previous = by_tolerance[f"{pair[0]:.1%}"][market]["CONFIRMED_per_1000_bars"]
        current = by_tolerance[f"{pair[1]:.1%}"][market]["CONFIRMED_per_1000_bars"]
        return current / previous - 1 if previous else None
    raise ValueError(f"unsupported frozen qualification threshold: {threshold_id}")


def _threshold_unit(threshold_id: str) -> str:
    if threshold_id == "minimum_confirmed_events_per_market_candidate":
        return "events"
    if threshold_id in {
        "matched_confirmed_event_date_drift_median",
        "matched_confirmed_event_date_drift_p90",
    }:
        return "trading_days"
    return "ratio"


def _qualification_row(
    *,
    candidate: float,
    market: str,
    threshold_id: str,
    frozen_threshold: Mapping[str, Any],
    pair: tuple[float, float] | None,
    by_tolerance: Mapping[str, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    observed = _threshold_observation(
        threshold_id,
        candidate=candidate,
        market=market,
        pair=pair,
        by_tolerance=by_tolerance,
        adjacent=adjacent,
    )
    operator = str(frozen_threshold["operator"])
    threshold = float(frozen_threshold["threshold"])
    passed = (
        observed is not None
        and (observed >= threshold if operator == ">=" else observed <= threshold)
    )
    margin = None
    if observed is not None:
        margin = observed - threshold if operator == ">=" else threshold - observed
    return {
        "candidate_pct": candidate,
        "market": market,
        "scope": "candidate" if pair is None else "adjacent_pair",
        "adjacent_pair": list(pair) if pair is not None else None,
        "threshold_id": threshold_id,
        "observed_value": observed,
        "operator": operator,
        "frozen_threshold": threshold,
        "unit": str(frozen_threshold.get("unit", _threshold_unit(threshold_id))),
        "margin_to_threshold": margin,
        "status": "PASS" if passed else "FAIL",
    }


def _build_qualification(
    *,
    by_tolerance: Mapping[str, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Execute the already-frozen Phase 5J-v2 qualification matrix."""
    protocol = load_protocol()
    thresholds = {
        row["id"]: row for row in protocol["structural_validation_thresholds"]
    }
    selection_rule = protocol["parameter_selection_rule"]
    matrix_definition = selection_rule["candidate_qualification_matrix"]
    matrix_rows: list[dict[str, Any]] = []
    for candidate_definition in matrix_definition:
        candidate = float(candidate_definition["candidate_pct"])
        candidate_threshold_ids = candidate_definition["candidate_level_threshold_ids"]
        adjacent_threshold_ids = candidate_definition["adjacent_pair_threshold_ids"]
        for market in ("CN", "US"):
            for threshold_id in candidate_threshold_ids:
                matrix_rows.append(
                    _qualification_row(
                        candidate=candidate,
                        market=market,
                        threshold_id=threshold_id,
                        frozen_threshold=thresholds[threshold_id],
                        pair=None,
                        by_tolerance=by_tolerance,
                        adjacent=adjacent,
                    )
                )
            for pair_values in candidate_definition["adjacent_pairs"]:
                pair = (float(pair_values[0]), float(pair_values[1]))
                for threshold_id in adjacent_threshold_ids:
                    matrix_rows.append(
                        _qualification_row(
                            candidate=candidate,
                            market=market,
                            threshold_id=threshold_id,
                            frozen_threshold=thresholds[threshold_id],
                            pair=pair,
                            by_tolerance=by_tolerance,
                            adjacent=adjacent,
                        )
                    )

    evaluations: list[dict[str, Any]] = []
    for candidate_definition in matrix_definition:
        candidate = float(candidate_definition["candidate_pct"])
        for market in ("CN", "US"):
            rows = [
                row
                for row in matrix_rows
                if row["candidate_pct"] == candidate and row["market"] == market
            ]
            failures = [row["threshold_id"] for row in rows if row["status"] != "PASS"]
            evaluations.append(
                {
                    "candidate_pct": candidate,
                    "market": market,
                    "qualifies": not failures,
                    "passed_threshold_ids": [
                        row["threshold_id"] for row in rows if row["status"] == "PASS"
                    ],
                    "failed_threshold_ids": failures,
                }
            )

    qualified_candidates = [
        candidate
        for candidate in (float(value) for value in selection_rule["ordered_candidates_pct"])
        if all(
            row["qualifies"]
            for row in evaluations
            if row["candidate_pct"] == candidate
        )
    ]
    lexicographic_candidate = qualified_candidates[0] if qualified_candidates else None
    status = (
        "READY_FOR_SOL_FORMAL_FREEZE_DECISION"
        if lexicographic_candidate is not None
        else "VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE"
    )

    drift_diagnostics: dict[str, dict[str, Any]] = {}
    for previous, current in QUALIFICATION_TRANSITIONS:
        transition = f"{previous:.1%}→{current:.1%}"
        drift_diagnostics[transition] = {}
        for market in ("CN", "US"):
            row = adjacent[transition][market]
            drift_diagnostics[transition][market] = {
                "matched_pair_count": row["nearest_date_matched_count"],
                "trading_day_drift_buckets": dict(row["trading_day_drift_buckets"]),
                "extreme_drift_pairs_top20": list(row["extreme_drift_pairs"]),
            }

    failure_breakdown = [
        dict(row) for row in matrix_rows if row["status"] == "FAIL"
    ] if not qualified_candidates else []
    return {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["integrity"]["protocol_sha256"],
        "selection_rule": {
            "type": selection_rule["type"],
            "ordered_candidates_pct": list(selection_rule["ordered_candidates_pct"]),
        },
        "matrix": matrix_rows,
        "candidate_market_evaluations": evaluations,
        "qualified_candidates": qualified_candidates,
        "lexicographic_candidate": lexicographic_candidate,
        "status": status,
        "failure_breakdown": failure_breakdown,
        "drift_diagnostics": drift_diagnostics,
    }


def _build_statistics(
    compact_reports: list[dict[str, Any]],
    market_session_dates: Mapping[str, tuple[date, ...]] | None = None,
) -> dict[str, Any]:
    by_tolerance: dict[float, list[dict[str, Any]]] = {
        tolerance: [
            item for item in compact_reports
            if item["platform_tolerance_pct"] == tolerance
        ]
        for tolerance in TOLERANCE_SEQUENCE
    }
    summaries = {
        tolerance: {
            market: _summary_for_market(by_tolerance[tolerance], market)
            for market in ("CN", "US", "ALL")
        }
        for tolerance in TOLERANCE_SEQUENCE
    }
    sessions = market_session_dates or _fallback_market_session_dates(compact_reports)
    adjacent = {
        f"{previous:.1%}→{current:.1%}": {
            market: _adjacent_summary(
                previous,
                current,
                by_tolerance,
                market,
                sessions,
            )
            for market in ("CN", "US", "ALL")
        }
        for previous, current in zip(TOLERANCE_SEQUENCE, TOLERANCE_SEQUENCE[1:])
    }
    cross_market = {}
    for tolerance in PRODUCTION_TOLERANCES:
        cn = summaries[tolerance]["CN"]
        us = summaries[tolerance]["US"]
        cross_market[f"{tolerance:.1%}"] = {
            "CN_vs_US_event_density_ratio": cn["CONFIRMED_per_1000_bars"] / us["CONFIRMED_per_1000_bars"] if us["CONFIRMED_per_1000_bars"] else None,
            "CN_vs_US_platform_detection_density_ratio": cn["platform_per_1000_bars"] / us["platform_per_1000_bars"] if us["platform_per_1000_bars"] else None,
            "CN_vs_US_zero_event_symbol_difference": cn["symbols_with_zero_confirmed"] - us["symbols_with_zero_confirmed"],
            "CN_vs_US_concentration_difference": (cn["max_symbol_event_share"] or 0.0) - (us["max_symbol_event_share"] or 0.0),
            "adjacent_stability": {
                transition: {
                    market: adjacent[transition][market]
                    for market in ("CN", "US")
                }
                for transition in ("2.5%→3.0%", "3.0%→4.0%", "4.0%→5.0%", "5.0%→5.5%", "5.5%→7.5%", "7.5%→10.0%")
            },
        }
    return {
        "by_tolerance": {
            f"{tolerance:.1%}": {
                market: summaries[tolerance][market]
                for market in ("CN", "US", "ALL")
            }
            for tolerance in TOLERANCE_SEQUENCE
        },
        "adjacent_tolerance_stability": adjacent,
        "market_session_dates": {
            market: [session_date.isoformat() for session_date in dates]
            for market, dates in sorted(sessions.items())
        },
        "cross_market_comparison": cross_market,
        "mechanical_flags": _build_flags(summaries, adjacent),
        "qualification": _build_qualification(
            by_tolerance={
                f"{tolerance:.1%}": {
                    market: summaries[tolerance][market]
                    for market in ("CN", "US", "ALL")
                }
                for tolerance in TOLERANCE_SEQUENCE
            },
            adjacent=adjacent,
        ),
    }


def _assert_frozen_pins(
    dataset_manifest: Mapping[str, Any],
    universe_manifest: Mapping[str, Any],
    replay_manifest: ReplayInputManifest,
) -> None:
    if dataset_manifest["integrity"]["manifest_sha256"] != EXPECTED_DATASET_MANIFEST_HASH:
        raise ValueError("v2 dataset manifest pin changed")
    if dataset_manifest["aggregate_dataset_sha256"] != EXPECTED_DATASET_AGGREGATE_HASH:
        raise ValueError("v2 aggregate dataset pin changed")
    if universe_manifest["integrity"]["manifest_sha256"] != EXPECTED_UNIVERSE_HASH:
        raise ValueError("development universe pin changed")
    if universe_manifest.get("a1_exclusion_proof", {}).get("intersection") != []:
        raise ValueError("formal universe overlap is not empty")
    if replay_manifest.aggregate_hash != EXPECTED_REPLAY_INPUT_HASH:
        raise ValueError("frozen replay input pin changed")
    if replay_manifest.total_symbol_count != 40 or replay_manifest.total_bar_count != 84284:
        raise ValueError("frozen replay input coverage changed")


def build_capsule_payload(
    *,
    dataset_manifest: Mapping[str, Any],
    universe_manifest: Mapping[str, Any],
    replay_manifest: ReplayInputManifest,
    parity: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic JSON payload before file-integrity wrapping."""
    _assert_frozen_pins(dataset_manifest, universe_manifest, replay_manifest)
    if parity.get("LEGACY_MAIN_PARITY_MISMATCHES") != 0:
        raise ValueError("cannot create decision capsule from replay mismatch")
    diagnostic = dataset_manifest["historical_yfinance_ohlc_diagnostic"]["summary"]
    qualification = statistics["qualification"]
    return {
        "schema_version": "setup03-development-strategy-decision-capsule-v3",
        "status": qualification["status"],
        "scope": {
            "development_only": True,
            "formal_validation": False,
            "structure_only": True,
            "outcome_metrics_included": False,
            "tolerance_selection": False,
            "frozen_qualification_matrix_executed": True,
            "lexicographic_candidate_is_production_config": False,
            "strategy_modification": False,
        },
        "frozen_inputs": {
            "universe_sha256": EXPECTED_UNIVERSE_HASH,
            "dataset_manifest_sha256": EXPECTED_DATASET_MANIFEST_HASH,
            "aggregate_dataset_sha256": EXPECTED_DATASET_AGGREGATE_HASH,
            "replay_input_aggregate_sha256": EXPECTED_REPLAY_INPUT_HASH,
            "symbol_count": 40,
            "bar_count": 84284,
            "market_coverage": {
                "CN": {"symbol_count": 20, "bars": 40873},
                "US": {"symbol_count": 20, "bars": 43411},
            },
            "provider_split": dataset_manifest["provider_split"],
            "a1_formal_universe_overlap": [],
        },
        "replay": {
            "identity": legacy_main_replay_identity(),
            "setup_parameters": {**SETUP_PARAMETERS, "tolerance_sequence": list(TOLERANCE_SEQUENCE)},
            "decision_parameters": dict(DECISION_PARAMETERS),
            "risk_capital": RISK_CAPITAL,
            "legacy_main_parity": {
                key: value
                for key, value in parity.items()
                if key not in {"compact_reports", "rows", "mismatches"}
            },
        },
        "data_quality": {
            "historical_yfinance_ohlc_audit": {
                "failed_symbols": diagnostic["failed_symbol_count"],
                "violating_bars": diagnostic["violating_bar_count"],
                "violation_records": diagnostic["violation_record_count"],
                "numeric_rounding_only_bars": diagnostic["numeric_ordering_tolerance_hit_count"],
                "material_provider_or_raw_ohlc_bars": diagnostic["classification_counts"]["MATERIAL_PROVIDER_OR_RAW_OHLC"],
            },
            "provider_qc_exceptions": list(dataset_manifest.get("provider_qc_exceptions", [])),
        },
        "structure_only_statistics": copy.deepcopy(statistics),
    }


def write_capsule(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    """Write deterministic capsule JSON and return content/file hashes."""
    body = copy.deepcopy(dict(payload))
    body["integrity"] = {
        "canonical_payload_sha256": None,
        "hash_scope": "canonical JSON with integrity.canonical_payload_sha256=null",
    }
    canonical_hash = f"sha256:{hashlib.sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"
    body["integrity"]["canonical_payload_sha256"] = canonical_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "canonical_payload_sha256": canonical_hash,
        "file_sha256": _sha256_file(path),
    }


def render_capsule_report(
    payload: Mapping[str, Any],
    *,
    capsule_path: Path,
    capsule_file_sha256: str,
) -> str:
    frozen = payload["frozen_inputs"]
    parity = payload["replay"]["legacy_main_parity"]
    statistics = payload["structure_only_statistics"]
    by_tolerance = statistics["by_tolerance"]
    adjacent = statistics["adjacent_tolerance_stability"]
    flags = statistics["mechanical_flags"]
    qualification = statistics["qualification"]

    def pct(value: Any) -> str:
        return "—" if value is None else f"{float(value):.2%}"

    def scalar(value: Any, unit: str) -> str:
        if value is None:
            return "null"
        if unit == "ratio":
            return f"{float(value):.2%}"
        if unit == "trading_days":
            return f"{float(value):.2f}"
        return f"{float(value):.0f}"

    def margin(value: Any, unit: str) -> str:
        if value is None:
            return "null"
        if unit == "ratio":
            return f"{float(value):+.2%}"
        return f"{float(value):+.2f}"

    lines = [
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->",
        "# SETUP_03 Development Strategy Decision Capsule v3",
        "",
        f"状态：`{payload['status']}`。本报告执行已冻结的 qualification matrix 与 lexicographic rule；不写入 production parameter。",
        "",
        "## Immutable bindings",
        "",
        f"- Capsule file：`{capsule_path.as_posix()}`",
        f"- Capsule SHA-256：`{capsule_file_sha256}`",
        f"- Universe：`{frozen['universe_sha256']}`",
        f"- Dataset manifest：`{frozen['dataset_manifest_sha256']}`",
        f"- Aggregate dataset：`{frozen['aggregate_dataset_sha256']}`",
        f"- Replay input：`{frozen['replay_input_aggregate_sha256']}`",
        f"- Coverage：CN 20 / 40,873 bars；US 20 / 43,411 bars；ALL 40 / 84,284 bars",
        f"- Provider split：CN `{frozen['provider_split']['CN']}`；US `{frozen['provider_split']['US']}`",
        f"- Formal universe overlap：`{frozen['a1_formal_universe_overlap']}`",
        "",
        "## True legacy-main parity",
        "",
        f"- Baseline：`{parity['baseline_commit']}`",
        f"- Cells / bars / events compared：{parity['scope']['cells']} / {parity['scope']['bar_comparisons']} / {parity['scope']['event_comparisons']}",
        f"- `LEGACY_MAIN_PARITY_MISMATCHES`：`{parity['LEGACY_MAIN_PARITY_MISMATCHES']}`",
        f"- Legacy vs shared current path mismatches：`{parity['legacy_vs_shared_mismatches']}`",
        f"- Legacy vs precomputed current path mismatches：`{parity['legacy_vs_precomputed_mismatches']}`",
        "- Comparison includes every bar Setup/state/diagnostic, every terminal event/date, and Decision action/diagnostics/deterministic fields.",
        "",
        "## Derived market session dates",
        "",
        "- `market_session_dates` is the sorted union of all valid local `Quote.trade_date` values in the frozen v2 replay input; no live calendar/provider was used.",
    ]
    for market, session_dates in statistics["market_session_dates"].items():
        lines.append(
            f"- `{market}`: {len(session_dates)} sessions, `{session_dates[0]}` through `{session_dates[-1]}`."
        )
    lines.extend([
        "",
        "## Frozen qualification matrix",
        "",
        f"- Protocol: `{qualification['protocol_version']}` / `{qualification['protocol_sha256']}`",
        "- Every row below is one candidate × market × frozen threshold observation. `trading_day_drift` is the only qualification drift field; calendar-day drift is descriptive only.",
        "",
        "| candidate | market | scope | adjacent pair | threshold | observed | operator | frozen threshold | margin | status |",
        "|---:|---|---|---|---|---:|:---:|---:|---:|---|",
    ])
    for row in qualification["matrix"]:
        pair = "—" if row["adjacent_pair"] is None else f"{row['adjacent_pair'][0]:.1%}→{row['adjacent_pair'][1]:.1%}"
        lines.append(
            f"| {row['candidate_pct']:.1%} | {row['market']} | {row['scope']} | {pair} | `{row['threshold_id']}` | "
            f"{scalar(row['observed_value'], row['unit'])} | `{row['operator']}` | {scalar(row['frozen_threshold'], row['unit'])} | "
            f"{margin(row['margin_to_threshold'], row['unit'])} | `{row['status']}` |"
        )
    lines.extend([
        "",
        "## Candidate qualification and frozen lexicographic result",
        "",
        "| candidate | market | qualifies | failed threshold IDs |",
        "|---:|---|---|---|",
    ])
    for row in qualification["candidate_market_evaluations"]:
        lines.append(
            f"| {row['candidate_pct']:.1%} | {row['market']} | `{row['qualifies']}` | "
            f"{', '.join(f'`{item}`' for item in row['failed_threshold_ids']) or '—'} |"
        )
    selected = qualification["lexicographic_candidate"]
    lines.extend([
        "",
        f"- `qualified_candidates`: `{json.dumps(qualification['qualified_candidates'], ensure_ascii=False)}`",
        f"- `lexicographic_candidate`: `{selected if selected is not None else 'null'}`",
        f"- `lexicographic_status`: `{qualification['status']}`",
        "",
        "## 3%→4% and 4%→5% drift evidence",
        "",
        "| transition | market | matched pairs | calendar median/P90 | trading-day median/P90 | buckets 0–2/3–5/6–10/11–15/>15 |",
        "|---|---|---:|---:|---:|---|",
    ])
    for transition in ("3.0%→4.0%", "4.0%→5.0%"):
        for market in ("CN", "US"):
            row = adjacent[transition][market]
            buckets = row["trading_day_drift_buckets"]
            calendar_pair = f"{scalar(row['calendar_day_drift_median'], 'trading_days')} / {scalar(row['calendar_day_drift_P90'], 'trading_days')}"
            trading_pair = f"{scalar(row['trading_day_drift_median'], 'trading_days')} / {scalar(row['trading_day_drift_P90'], 'trading_days')}"
            bucket_text = "/".join(str(buckets[key]) for key in ("0-2", "3-5", "6-10", "11-15", ">15"))
            lines.append(
                f"| {transition} | {market} | {row['nearest_date_matched_count']} | {calendar_pair} | {trading_pair} | {bucket_text} |"
            )

    if qualification["status"] == "VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE":
        lines.extend([
            "",
            "## Qualification failure breakdown",
            "",
            "| candidate | market | scope | adjacent pair | frozen threshold | observed | operator | margin to threshold |",
            "|---:|---|---|---|---|---:|:---:|---:|",
        ])
        for row in qualification["failure_breakdown"]:
            pair = "—" if row["adjacent_pair"] is None else f"{row['adjacent_pair'][0]:.1%}→{row['adjacent_pair'][1]:.1%}"
            lines.append(
                f"| {row['candidate_pct']:.1%} | {row['market']} | {row['scope']} | {pair} | `{row['threshold_id']}` | "
                f"{scalar(row['observed_value'], row['unit'])} | `{row['operator']} {scalar(row['frozen_threshold'], row['unit'])}` | "
                f"{margin(row['margin_to_threshold'], row['unit'])} |"
            )
        lines.extend([
            "",
            "## Extreme trading-day drift pairs (descriptive)",
            "",
            "The following pairs are retained as evidence; none is deleted or re-matched.",
        ])
        for transition in ("3.0%→4.0%", "4.0%→5.0%"):
            for market in ("CN", "US"):
                diag = qualification["drift_diagnostics"][transition][market]
                lines.extend([
                    "",
                    f"### {transition} / {market}",
                    "",
                    f"- matched pair count: `{diag['matched_pair_count']}`",
                    f"- buckets (0–2 / 3–5 / 6–10 / 11–15 / >15): `{diag['trading_day_drift_buckets']['0-2']} / {diag['trading_day_drift_buckets']['3-5']} / {diag['trading_day_drift_buckets']['6-10']} / {diag['trading_day_drift_buckets']['11-15']} / {diag['trading_day_drift_buckets']['>15']}`",
                    "",
                    "| symbol | old date | new date | trading-day distance | calendar-day distance |",
                    "|---|---|---|---:|---:|",
                ])
                for pair in diag["extreme_drift_pairs_top20"]:
                    lines.append(
                        f"| {pair['symbol']} | {pair['old_date']} | {pair['new_date']} | {pair['trading_day_drift']} | {pair['calendar_day_drift']} |"
                    )

    lines.extend([
        "",
        "## CN / US / ALL core numbers",
        "",
        "| tolerance | market | symbols | bars | platform | platform/1000 | NONE | WATCH | ARMED | CONFIRMED state days | FAILED | CONFIRMED events | CONFIRMED/1000 | ENTRY_ALLOWED | ENTRY_ALLOWED/1000 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for tolerance in TOLERANCE_SEQUENCE:
        for market in ("CN", "US", "ALL"):
            row = by_tolerance[f"{tolerance:.1%}"][market]
            lines.append(
                f"| {tolerance:.1%} | {market} | {row['symbol_count']} | {row['bars']} | {row['platform_detected']} | {row['platform_per_1000_bars']:.2f} | {row['NONE']} | {row['WATCH']} | {row['ARMED']} | {row['CONFIRMED_STATE_DAYS']} | {row['FAILED']} | {row['CONFIRMED_EVENTS']} | {row['CONFIRMED_per_1000_bars']:.2f} | {row['ENTRY_ALLOWED']} | {row['ENTRY_ALLOWED_per_1000_bars']:.2f} |"
            )
    lines.extend([
        "",
        "## Adjacent tolerance stability",
        "",
        "| transition | market | previous | current | retained | added | disappeared | Jaccard | nearest matched | drift median/P90 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for transition, market_rows in adjacent.items():
        for market in ("CN", "US", "ALL"):
            row = market_rows[market]
            drift = (
                "—"
                if row["trading_day_drift_median"] is None
                else f"{float(row['trading_day_drift_median']):.1f} / {float(row['trading_day_drift_P90']):.1f} trading days"
            )
            lines.append(
                f"| {transition} | {market} | {row['previous_event_count']} | {row['current_event_count']} | {row['retained']} | {row['added']} | {row['disappeared']} | {row['exact_date_jaccard']:.2%} | {row['nearest_date_matched_count']} | {drift} |"
            )
    lines.extend(["", "## Production-candidate boundary / concentration facts", ""])
    for tolerance in PRODUCTION_TOLERANCES:
        row = by_tolerance[f"{tolerance:.1%}"]["ALL"]
        lines.append(
            f"- `{tolerance:.1%}` ALL: high span median/P90 `{pct(row['high_span_median'])}` / `{pct(row['high_span_P90'])}`; low span `{pct(row['low_span_median'])}` / `{pct(row['low_span_P90'])}`; platform width `{pct(row['platform_width_median'])}` / `{pct(row['platform_width_P90'])}`; zero-event symbols `{row['symbols_with_zero_confirmed']}`; 1–2-event symbols `{row['symbols_with_1_to_2_confirmed']}`; max symbol share `{pct(row['max_symbol_event_share'])}`; top-3 share `{pct(row['top_3_symbol_event_share'])}`."
        )
    lines.append("")
    lines.append("压力边界 ALL（仅描述扩张）：")
    for tolerance in (0.025, 0.055, 0.075, 0.10):
        row = by_tolerance[f"{tolerance:.1%}"]["ALL"]
        lines.append(
            f"- `{tolerance:.1%}`：platform `{row['platform_detected']}`（`{row['platform_per_1000_bars']:.2f}/1000`），CONFIRMED `{row['CONFIRMED_EVENTS']}`（`{row['CONFIRMED_per_1000_bars']:.2f}/1000`），high span median/P90 `{pct(row['high_span_median'])}`/`{pct(row['high_span_P90'])}`，low span `{pct(row['low_span_median'])}`/`{pct(row['low_span_P90'])}`，width `{pct(row['platform_width_median'])}`/`{pct(row['platform_width_P90'])}`。"
        )
    lines.extend(["", "## Cross-market comparison", ""])
    for tolerance in PRODUCTION_TOLERANCES:
        row = statistics["cross_market_comparison"][f"{tolerance:.1%}"]
        lines.append(
            f"- `{tolerance:.1%}` CN/US: event-density ratio `{row['CN_vs_US_event_density_ratio']:.3f}`; platform-density ratio `{row['CN_vs_US_platform_detection_density_ratio']:.3f}`; zero-event-symbol difference `{row['CN_vs_US_zero_event_symbol_difference']}`; max-share difference `{row['CN_vs_US_concentration_difference']:.2%}`."
        )
    lines.extend(["", "## Mechanical flags", "", "```json", json.dumps(flags["values"], ensure_ascii=False, sort_keys=True, indent=2), "```", ""])
    lines.append("Definitions and raw observations are in the tracked JSON capsule.")
    lines.extend([
        "",
        "## Data quality and boundaries",
        "",
        "- Frozen v2 provider split: BaoStock qfq for CN and yfinance historical for US.",
        "- Immutable OHLC audit: 4 numeric-adjustment-rounding-only bars; 26 material provider/raw-OHLC bars.",
        "- This capsule contains no returns, MFE, MAE, P&L, winrate, or final OOS metrics.",
        "- No dataset/universe change, re-fetch, provider/symbol substitution, formal validation, strategy change, PR creation, or merge was performed.",
        "",
        f"`{payload['status']}`",
        "",
    ])
    return "\n".join(lines)


def load_frozen_capsule_inputs(
    *,
    dataset_manifest_path: Path,
    universe_manifest_path: Path,
    replay_input_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[Quote]], ReplayInputManifest]:
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    universe_manifest = json.loads(universe_manifest_path.read_text(encoding="utf-8"))
    symbol_quotes, replay_manifest = read_frozen_input(replay_input_path)
    _assert_frozen_pins(dataset_manifest, universe_manifest, replay_manifest)
    actual = build_input_manifest(symbol_quotes)
    if actual != replay_manifest:
        raise ValueError("loaded frozen replay input manifest changed")
    return dataset_manifest, universe_manifest, symbol_quotes, replay_manifest


__all__ = [
    "DECISION_PARAMETERS",
    "EXPECTED_DATASET_AGGREGATE_HASH",
    "EXPECTED_DATASET_MANIFEST_HASH",
    "EXPECTED_REPLAY_INPUT_HASH",
    "EXPECTED_UNIVERSE_HASH",
    "PRODUCTION_TOLERANCES",
    "SETUP_PARAMETERS",
    "TOLERANCE_SEQUENCE",
    "build_capsule_payload",
    "load_frozen_capsule_inputs",
    "render_capsule_report",
    "run_legacy_main_parity",
    "write_capsule",
]
