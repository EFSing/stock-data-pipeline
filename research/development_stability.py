"""Descriptive SETUP_03 stability evidence for the development-only dataset.

The only signal calculation in this module is the existing strict as-of
``trading.replay.replay_setup03_history`` path.  This module aggregates state,
terminal-reason, event, tolerance-boundary, and concentration evidence.  It
does not consume forward returns, MFE/MAE, P&L, final OOS, or choose a
production tolerance.
"""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from core import Quote
from research.confirmation_diagnostics import confirmation_gate_artifacts, render_confirmation_report
from research.development_dataset import (
    DEVELOPMENT_DATASET_STATUS,
    DEVELOPMENT_DATASET_VERSION,
    DEVELOPMENT_LABELS,
)
from research.market_sessions import build_market_session_dates, trading_day_distance
from research.replay_input import ReplayInputManifest, build_input_manifest
from trading.models import DecisionAction, SetupState
from trading.replay import (
    SymbolReplayReport,
    replay_parity_mismatches,
    replay_setup03_history,
)
from trading.setup import SetupGateReason


TOLERANCE_SEQUENCE = (0.025, 0.03, 0.04, 0.05, 0.055, 0.075, 0.10)
PRODUCTION_TOLERANCES = (0.03, 0.04, 0.05)
STRESS_TOLERANCES = (0.025, 0.055, 0.075, 0.10)
SETUP_SWING_LOOKBACK = 5
PLATFORM_WINDOW = 40
ARM_PROXIMITY_PCT = 0.0
RISK_CAPITAL = 100_000.0
DECISION_PARAMETERS = {
    "swing_lookback": 5,
    "atr_period": 14,
    "atr_buffer": 0.5,
    "max_chase_atr": 0.5,
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _quantile(values: list[float], q: float) -> float | None:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _event_key(event) -> tuple[str, date]:
    return event.symbol, event.confirmed_date or event.trade_date


def _events(reports: Mapping[str, SymbolReplayReport]) -> list[Any]:
    return [
        event
        for report in reports.values()
        for event in report.events
        if event.event_type is SetupState.CONFIRMED
    ]


def _event_map(reports: Mapping[str, SymbolReplayReport], market: str) -> dict[tuple[str, date], Any]:
    return {
        _event_key(event): event
        for report in reports.values()
        if market == "ALL" or report.market == market
        for event in report.events
        if event.event_type is SetupState.CONFIRMED
    }


def _nearest_date_matches(
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
    matches = []
    for _, symbol, old_date, new_date in candidates:
        old_key = (symbol, old_date)
        new_key = (symbol, new_date)
        if old_key not in used_old and new_key not in used_new:
            used_old.add(old_key)
            used_new.add(new_key)
            matches.append((symbol, old_date, new_date))
    return matches


def _reason(event) -> str:
    if event.decision_diagnostics is not None:
        return event.decision_diagnostics.reason.value
    if event.decision is not None and event.decision.action is DecisionAction.ENTRY_ALLOWED:
        return "ENTRY_ALLOWED"
    return "OTHER_NO_TRADE"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _state_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for symbol, report in sorted(reports.items()):
        counts = Counter(day.setup_state.value for day in report.days)
        events = _events({symbol: report})
        rows.append({
            "platform_tolerance_pct": tolerance,
            "market": report.market,
            "symbol": symbol,
            "bars": len(report.days),
            "NONE": counts[SetupState.NONE.value],
            "WATCH": counts[SetupState.WATCH.value],
            "ARMED": counts[SetupState.ARMED.value],
            "CONFIRMED_STATE_DAYS": counts[SetupState.CONFIRMED.value],
            "FAILED": counts[SetupState.FAILED.value],
            "platform_detected": sum(
                bool(day.setup_diagnostics and day.setup_diagnostics.platform_detected_this_bar)
                for day in report.days
            ),
            "CONFIRMED_EVENTS": len(events),
            "ENTRY_ALLOWED": sum(
                event.decision is not None
                and event.decision.action is DecisionAction.ENTRY_ALLOWED
                for event in events
            ),
            "event_density_per_1000_bars": 1000 * len(events) / len(report.days) if report.days else 0.0,
        })
    return rows


def _market_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for market in ("CN", "US", "ALL"):
        selected = [report for report in reports.values() if market == "ALL" or report.market == market]
        days = [day for report in selected for day in report.days]
        events = _events({report.symbol: report for report in selected})
        detected = [
            day for day in days
            if day.setup_diagnostics and day.setup_diagnostics.platform_detected_this_bar
        ]
        symbol_counts = Counter(event.symbol for event in events)
        rows.append({
            "platform_tolerance_pct": tolerance,
            "market": market,
            "symbol_count": len(selected),
            "bars": len(days),
            "platform_detected": len(detected),
            "platform_per_1000_bars": 1000 * len(detected) / len(days) if days else 0.0,
            "NONE": sum(day.setup_state is SetupState.NONE for day in days),
            "WATCH": sum(day.setup_state is SetupState.WATCH for day in days),
            "ARMED": sum(day.setup_state is SetupState.ARMED for day in days),
            "CONFIRMED_STATE_DAYS": sum(day.setup_state is SetupState.CONFIRMED for day in days),
            "FAILED": sum(day.setup_state is SetupState.FAILED for day in days),
            "CONFIRMED_EVENTS": len(events),
            "ENTRY_ALLOWED": sum(
                event.decision is not None
                and event.decision.action is DecisionAction.ENTRY_ALLOWED
                for event in events
            ),
            "event_per_1000_bars": 1000 * len(events) / len(days) if days else 0.0,
            "max_symbol_event_share": max(symbol_counts.values(), default=0) / len(events) if events else None,
        })
    return rows


def _terminal_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for market in ("CN", "US", "ALL"):
        selected = [report for report in reports.values() if market == "ALL" or report.market == market]
        diagnostics = [day.setup_diagnostics for report in selected for day in report.days]
        counts = Counter(diag.reason.value for diag in diagnostics if diag is not None)
        total = sum(counts.values())
        for reason in SetupGateReason:
            rows.append({
                "platform_tolerance_pct": tolerance,
                "market": market,
                "terminal_reason": reason.value,
                "count": counts[reason.value],
                "share_of_bars": counts[reason.value] / total if total else 0.0,
                "terminal_reason_conserved": sum(counts.values()) == total,
                "total_bars": total,
            })
    return rows


def _confirmation_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for report in reports.values():
        for event in report.events:
            if event.event_type is not SetupState.CONFIRMED:
                continue
            rows.append({
                "platform_tolerance_pct": tolerance,
                "market": report.market,
                "symbol": event.symbol,
                "signal_date": event.signal_date.isoformat() if event.signal_date else "",
                "confirmed_date": event.confirmed_date.isoformat() if event.confirmed_date else "",
                "decision_action": event.decision.action.value if event.decision else "",
                "decision_gate_reason": _reason(event),
                "breakout_price": event.setup.breakout_price,
                "structural_invalidation": event.setup.structural_invalidation,
                "signal_close": event.signal_close,
                "confirmed_index": event.setup.confirmed_index,
            })
    return rows


def _boundary_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for market in ("CN", "US", "ALL"):
        selected = [report for report in reports.values() if market == "ALL" or report.market == market]
        detected = [
            day.setup_diagnostics for report in selected for day in report.days
            if day.setup_diagnostics and day.setup_diagnostics.platform_detected_this_bar
        ]
        high = [diag.high_span for diag in detected if diag.high_span is not None]
        low = [diag.low_span for diag in detected if diag.low_span is not None]
        widths = [
            (diag.breakout_price - diag.structural_invalidation) / diag.close
            for diag in detected
            if diag.breakout_price is not None
            and diag.structural_invalidation is not None
            and diag.close
            and diag.close > 0
        ]
        rows.append({
            "platform_tolerance_pct": tolerance,
            "market": market,
            "platform_count": len(detected),
            "high_span_median": median(high) if high else None,
            "high_span_P90": _quantile(high, 0.9),
            "low_span_median": median(low) if low else None,
            "low_span_P90": _quantile(low, 0.9),
            "platform_width_pct_median": median(widths) if widths else None,
            "platform_width_pct_P90": _quantile(widths, 0.9),
        })
    return rows


def _adjacent_rows(
    previous: float,
    current: float,
    reports_by_tolerance: Mapping[float, Mapping[str, SymbolReplayReport]],
    market_session_dates: Mapping[str, tuple[date, ...]] | None = None,
) -> list[dict[str, Any]]:
    if market_session_dates is None:
        derived_dates: dict[str, set[date]] = {}
        for report in reports_by_tolerance[previous].values():
            derived_dates.setdefault(report.market, set()).update(
                day.trade_date for day in report.days
            )
        market_session_dates = {
            market: tuple(sorted(dates))
            for market, dates in derived_dates.items()
        }
    rows = []
    for market in ("CN", "US", "ALL"):
        old = _event_map(reports_by_tolerance[previous], market)
        new = _event_map(reports_by_tolerance[current], market)
        old_keys, new_keys = set(old), set(new)
        retained = old_keys & new_keys
        added = new_keys - old_keys
        disappeared = old_keys - new_keys
        matches = _nearest_date_matches(disappeared, added)
        calendar_drifts = [
            abs((new_date - old_date).days)
            for _, old_date, new_date in matches
        ]
        market_by_symbol = {
            report.symbol: report.market
            for report in reports_by_tolerance[previous].values()
        }
        trading_drifts = [
            trading_day_distance(
                old_date,
                new_date,
                market=market_by_symbol[symbol],
                market_session_dates=market_session_dates,
            )
            for symbol, old_date, new_date in matches
        ]
        rows.append({
            "previous_tolerance_pct": previous,
            "current_tolerance_pct": current,
            "market": market,
            "previous_confirmed": len(old_keys),
            "current_confirmed": len(new_keys),
            "retained_exact": len(retained),
            "jaccard": len(retained) / len(old_keys | new_keys) if old_keys | new_keys else 1.0,
            "retention": len(retained) / len(old_keys) if old_keys else (1.0 if not new_keys else 0.0),
            "added_events": len(added),
            "disappeared_events": len(disappeared),
            "matched_date_events": len(matches),
            # Historical descriptive calendar-day fields.
            "date_drift_median_days": median(calendar_drifts) if calendar_drifts else None,
            "date_drift_P90_days": _quantile([float(value) for value in calendar_drifts], 0.9),
            "calendar_day_drift_median_days": median(calendar_drifts) if calendar_drifts else None,
            "calendar_day_drift_P90_days": _quantile([float(value) for value in calendar_drifts], 0.9),
            # Formal qualification uses these trading-session fields.
            "trading_day_drift_median_days": median(trading_drifts) if trading_drifts else None,
            "trading_day_drift_P90_days": _quantile([float(value) for value in trading_drifts], 0.9),
            "diagnostic_only": True,
        })
    return rows


def _concentration_rows(
    tolerance: float, reports: Mapping[str, SymbolReplayReport]
) -> list[dict[str, Any]]:
    rows = []
    for market in ("CN", "US", "ALL"):
        selected = [report for report in reports.values() if market == "ALL" or report.market == market]
        events = [
            (report.market, event.symbol, (event.confirmed_date or event.trade_date).year)
            for report in selected
            for event in report.events
            if event.event_type is SetupState.CONFIRMED
        ]
        dimensions = (("symbol", 1), ("year", 2))
        for dimension, index in dimensions:
            counts = Counter(event[index] for event in events)
            total = len(events)
            shares = [count / total for count in counts.values()] if total else []
            rows.append({
                "platform_tolerance_pct": tolerance,
                "market": market,
                "dimension": dimension,
                "confirmed": total,
                "group_count": len(counts),
                "max_group": str(max(counts, key=counts.get)) if counts else "",
                "max_share": max(shares, default=None),
                "HHI": sum(share * share for share in shares) if shares else None,
                "diagnostic_only": True,
            })
    return rows


def _sparse_rows(
    state_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "platform_tolerance_pct": row["platform_tolerance_pct"],
            "market": row["market"],
            "symbol": row["symbol"],
            "confirmed_events": row["CONFIRMED_EVENTS"],
            "platform_detected": row["platform_detected"],
            "classification": (
                "ZERO_EVENT" if row["CONFIRMED_EVENTS"] == 0
                else "SPARSE_EVENT_1_TO_2" if row["CONFIRMED_EVENTS"] <= 2
                else "NONZERO_EVENT"
            ),
        }
        for row in state_rows
    ]


def _validate_setup_parameters(setup_parameters: Mapping[str, Any]) -> None:
    expected = {
        "swing_lookback": SETUP_SWING_LOOKBACK,
        "platform_window": PLATFORM_WINDOW,
        "arm_proximity_pct": ARM_PROXIMITY_PCT,
    }
    for key, value in expected.items():
        if setup_parameters.get(key) != value:
            raise ValueError(f"development evidence requires fixed {key}={value}")


def run_precompute_replay_parity(
    symbol_quotes: Mapping[str, list[Quote]],
    *,
    output_dir: Path,
    setup_parameters: Mapping[str, Any],
    decision_parameters: Mapping[str, Any],
    risk_capital: float = RISK_CAPITAL,
) -> dict[str, Any]:
    """Run full baseline/precomputed parity across every bar and tolerance."""
    tasks = [
        (symbol, quotes, dict(setup_parameters), dict(decision_parameters), risk_capital)
        for symbol, quotes in sorted(symbol_quotes.items())
    ]
    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    max_workers = min(8, max(1, os.cpu_count() or 1), len(tasks))
    if max_workers == 1:
        results = [_precompute_parity_symbol_task(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_precompute_parity_symbol_task, tasks))
    for symbol_rows, symbol_mismatches in results:
        rows.extend(symbol_rows)
        mismatches.extend(symbol_mismatches)
    rows.sort(key=lambda row: (row["platform_tolerance_pct"], row["symbol"]))
    total_mismatches = sum(row["mismatch_count"] for row in rows)
    result = {
        "schema_version": "setup03-replay-precompute-parity-v1",
        "parity_version": "SETUP_03-REPLAY-PRECOMPUTE-PARITY-2026-08-28-v1",
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "scope": {
            "symbol_count": len(symbol_quotes),
            "tolerance_count": len(TOLERANCE_SEQUENCE),
            "tolerance_sequence": list(TOLERANCE_SEQUENCE),
            "bar_comparison": True,
            "setup_state_and_operands": True,
            "decision_and_reason": True,
        },
        "status": "PASS" if total_mismatches == 0 else "MISMATCH_BASELINE_REQUIRED",
        "optimization_enabled": total_mismatches == 0,
        "total_mismatch_count": total_mismatches,
        "rows": rows,
        "mismatches": mismatches,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "precompute_replay_parity.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_path = output_dir / "precompute_replay_parity.csv"
    _write_csv(csv_path, rows)
    result["json_path"] = str(json_path.relative_to(output_dir)).replace("\\", "/")
    result["json_sha256"] = _sha256_file(json_path)
    result["csv_path"] = str(csv_path.relative_to(output_dir)).replace("\\", "/")
    result["csv_sha256"] = _sha256_file(csv_path)
    return result


def _precompute_parity_symbol_task(
    task: tuple[str, list[Quote], dict[str, Any], dict[str, Any], float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbol, quotes, setup_parameters, decision_parameters, risk_capital = task
    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for tolerance in TOLERANCE_SEQUENCE:
        parameters = dict(setup_parameters)
        parameters["platform_tolerance_pct"] = tolerance
        baseline = replay_setup03_history(
            quotes, risk_capital, parameters, decision_parameters,
            precompute_swings=False,
        )
        optimized = replay_setup03_history(
            quotes, risk_capital, parameters, decision_parameters,
            precompute_swings=True,
        )
        differences = replay_parity_mismatches(baseline, optimized)
        rows.append({
            "platform_tolerance_pct": tolerance,
            "market": quotes[0].market,
            "symbol": symbol,
            "bar_count": len(quotes),
            "baseline_event_count": len(baseline.events),
            "precomputed_event_count": len(optimized.events),
            "mismatch_count": len(differences),
            "status": "IDENTICAL" if not differences else "MISMATCH",
        })
        for difference in differences[:50]:
            mismatches.append({
                "platform_tolerance_pct": tolerance,
                "symbol": symbol,
                **difference,
            })
    return rows, mismatches


def run_development_stability(
    symbol_quotes: dict[str, list[Quote]],
    *,
    output_dir: Path,
    dataset_manifest: Mapping[str, Any],
    setup_parameters: Mapping[str, Any] | None = None,
    decision_parameters: Mapping[str, Any] | None = None,
    risk_capital: float = RISK_CAPITAL,
    precompute_swings: bool = True,
    precompute_parity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the complete structural evidence pack without outcome metrics."""
    setup = dict(setup_parameters or {
        "swing_lookback": SETUP_SWING_LOOKBACK,
        "platform_window": PLATFORM_WINDOW,
        "platform_tolerance_pct": 0.03,
        "arm_proximity_pct": ARM_PROXIMITY_PCT,
    })
    decision = dict(decision_parameters or DECISION_PARAMETERS)
    _validate_setup_parameters(setup)
    if decision != DECISION_PARAMETERS:
        raise ValueError("development evidence decision parameters are frozen")
    if tuple(TOLERANCE_SEQUENCE) != (0.025, 0.03, 0.04, 0.05, 0.055, 0.075, 0.10):
        raise ValueError("development tolerance sequence changed")
    if not symbol_quotes:
        raise ValueError("development evidence requires valid symbol history")
    replay_manifest: ReplayInputManifest = build_input_manifest(symbol_quotes)
    market_session_dates = build_market_session_dates(symbol_quotes)
    reports_by_tolerance: dict[float, dict[str, SymbolReplayReport]] = {}
    state_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    terminal_rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    confirmation_rows: list[dict[str, Any]] = []
    concentration_rows: list[dict[str, Any]] = []
    adjacent_rows: list[dict[str, Any]] = []
    for tolerance in TOLERANCE_SEQUENCE:
        parameters = dict(setup)
        parameters["platform_tolerance_pct"] = tolerance
        reports = {
            symbol: replay_setup03_history(
                quotes,
                risk_capital,
                parameters,
                decision,
                precompute_swings=precompute_swings,
            )
            for symbol, quotes in sorted(symbol_quotes.items())
        }
        reports_by_tolerance[tolerance] = reports
        state_rows.extend(_state_rows(tolerance, reports))
        market_rows.extend(_market_rows(tolerance, reports))
        terminal_rows.extend(_terminal_rows(tolerance, reports))
        boundary_rows.extend(_boundary_rows(tolerance, reports))
        confirmation_rows.extend(_confirmation_rows(tolerance, reports))
        concentration_rows.extend(_concentration_rows(tolerance, reports))
    for previous, current in zip(TOLERANCE_SEQUENCE, TOLERANCE_SEQUENCE[1:]):
        adjacent_rows.extend(
            _adjacent_rows(
                previous,
                current,
                reports_by_tolerance,
                market_session_dates,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    table_rows = {
        "state_distribution.csv": state_rows,
        "market_summary.csv": market_rows,
        "terminal_reasons.csv": terminal_rows,
        "confirmation_events.csv": confirmation_rows,
        "structural_boundary.csv": boundary_rows,
        "adjacent_tolerance_stability.csv": adjacent_rows,
        "concentration.csv": concentration_rows,
        "zero_sparse_symbols.csv": _sparse_rows(state_rows),
    }
    for filename, rows in table_rows.items():
        path = output_dir / filename
        _write_csv(path, rows)
        files.append({"path": filename, "sha256": _sha256_file(path), "row_count": len(rows)})

    production_reports = reports_by_tolerance[0.03]
    confirmation_artifacts = confirmation_gate_artifacts(production_reports)
    confirmation_report_path = output_dir / "confirmation_gate_3pct.md"
    confirmation_report_path.write_text(
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->\n\n"
        + render_confirmation_report(confirmation_artifacts, dataset_manifest["aggregate_dataset_sha256"]),
        encoding="utf-8",
    )
    files.append({"path": confirmation_report_path.name, "sha256": _sha256_file(confirmation_report_path), "row_count": None})
    for filename, rows in {
        "confirmation_detail_3pct.csv": list(confirmation_artifacts.detail_rows),
        "confirmation_reason_3pct.csv": list(confirmation_artifacts.reason_rows),
        "confirmation_gate_3pct.csv": list(confirmation_artifacts.gate_rows),
        "confirmation_near_miss_3pct.csv": list(confirmation_artifacts.near_miss_rows),
        "confirmation_auxiliary_3pct.csv": list(confirmation_artifacts.auxiliary_rows),
    }.items():
        path = output_dir / filename
        _write_csv(path, rows)
        files.append({"path": filename, "sha256": _sha256_file(path), "row_count": len(rows)})

    tolerance_table = [
        row for row in market_rows
        if row["market"] in ("CN", "US")
    ]
    dataset_exclusions = list(dataset_manifest.get("provider_qc_exceptions", []))
    final_status = (
        "READY_FOR_STRATEGY_RESEARCH_DECISION"
        if dataset_manifest.get("coverage_status") == "DEVELOPMENT_DATASET_READY_FOR_STABILITY_DIAGNOSTICS"
        else "BLOCKER_DEVELOPMENT_YFINANCE_COVERAGE_SHORTFALL"
    )
    summary_path = output_dir / "development_strategy_stability_evidence.md"
    summary_path.write_text(
        _render_summary(
            dataset_manifest,
            replay_manifest,
            tolerance_table,
            terminal_rows,
            adjacent_rows,
            concentration_rows,
            dataset_exclusions,
            final_status,
        ),
        encoding="utf-8",
    )
    files.append({"path": summary_path.name, "sha256": _sha256_file(summary_path), "row_count": None})

    evidence_manifest = {
        "schema_version": "setup03-development-stability-evidence-manifest-v1",
        "evidence_version": "SETUP_03-DEVELOPMENT-STRATEGY-STABILITY-EVIDENCE-2026-08-28-v1",
        "status": final_status,
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "dataset": {
            "dataset_version": dataset_manifest["dataset_version"],
            "dataset_manifest_sha256": dataset_manifest["integrity"]["manifest_sha256"],
            "aggregate_dataset_sha256": dataset_manifest["aggregate_dataset_sha256"],
            "replay_input_aggregate_sha256": replay_manifest.aggregate_hash,
        },
        "fixed_setup_parameters": {
            "setup_swing_lookback": SETUP_SWING_LOOKBACK,
            "platform_window": PLATFORM_WINDOW,
            "arm_proximity_pct": ARM_PROXIMITY_PCT,
            "production_tolerance_candidates": list(PRODUCTION_TOLERANCES),
            "stress_only_tolerances": list(STRESS_TOLERANCES),
        },
        "research_boundaries": {
            "production_tolerance_selected": False,
            "new_strategy_algorithm": False,
            "forward_returns_read": False,
            "mfe_mae_read": False,
            "final_oos_accessed": False,
            "formal_phase5k_validation": False,
            "ibkr_used": False,
        },
        "precompute_replay_parity": dict(precompute_parity) if precompute_parity else None,
        "files": files,
    }
    evidence_manifest["integrity"] = {
        "manifest_sha256": f"sha256:{hashlib.sha256(_json(evidence_manifest).encode('utf-8')).hexdigest()}"
    }
    evidence_manifest_path = output_dir / "development_evidence_manifest.json"
    evidence_manifest_path.write_text(json.dumps(evidence_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "evidence_manifest": evidence_manifest,
        "evidence_manifest_path": evidence_manifest_path,
        "replay_manifest": replay_manifest,
        "reports_by_tolerance": reports_by_tolerance,
    }


def _render_summary(
    dataset_manifest: Mapping[str, Any],
    replay_manifest: ReplayInputManifest,
    market_rows: list[dict[str, Any]],
    terminal_rows: list[dict[str, Any]],
    adjacent_rows: list[dict[str, Any]],
    concentration_rows: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    final_status: str,
) -> str:
    lines = [
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->",
        "# SETUP_03 Development Strategy Stability Evidence Pack",
        "",
        "> 本包只用于 development strategy research；不构成 Phase 5K formal validation，也不构成 final OOS。",
        "",
        "## 冻结输入",
        "",
        f"- Development dataset：`{dataset_manifest['dataset_version']}`",
        f"- Dataset status：`{DEVELOPMENT_DATASET_STATUS}`",
        f"- Aggregate dataset SHA-256：`{dataset_manifest['aggregate_dataset_sha256']}`",
        f"- Replay input SHA-256：`{replay_manifest.aggregate_hash}`",
        f"- Valid symbols/bars：{dataset_manifest['aggregate_symbol_count']} / {dataset_manifest['aggregate_valid_bar_count']}",
        f"- A1 formal overlap：`{dataset_manifest['universe']['manifest_sha256']}` exclusion proof is recorded in the universe manifest; computed intersection is empty.",
        "- All provider/QC failures remain explicit exclusions; no symbol was replaced after reading SETUP_03 output.",
        "",
        "## 固定研究口径",
        "",
        f"- Production candidates: `{', '.join(f'{value:.0%}' for value in PRODUCTION_TOLERANCES)}`",
        f"- Stress-only: `{', '.join(f'{value:.1%}' for value in STRESS_TOLERANCES)}`",
        f"- Fixed: `setup_swing_lookback={SETUP_SWING_LOOKBACK}`, `platform_window={PLATFORM_WINDOW}`, `arm_proximity_pct={ARM_PROXIMITY_PCT:g}`",
        "- Each cell uses the existing strict as-of replay → Setup/Decision path; no new signal formula or market/regime/volatility rule is introduced.",
        "",
        "## CN / US coverage and tolerance sensitivity",
        "",
        "| tolerance | market | symbols | bars | platform/1000 bars | WATCH | ARMED | CONFIRMED state days | FAILED | CONFIRMED events | ENTRY_ALLOWED | event/1000 bars |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in market_rows:
        lines.append(
            f"| {row['platform_tolerance_pct']:.1%} | {row['market']} | {row['symbol_count']} | {row['bars']} | "
            f"{row['platform_per_1000_bars']:.2f} | {row['WATCH']} | {row['ARMED']} | {row['CONFIRMED_STATE_DAYS']} | "
            f"{row['FAILED']} | {row['CONFIRMED_EVENTS']} | {row['ENTRY_ALLOWED']} | {row['event_per_1000_bars']:.2f} |"
        )
    lines.extend(["", "## Terminal reason 守恒", ""])
    for tolerance in TOLERANCE_SEQUENCE:
        rows = [row for row in terminal_rows if row["platform_tolerance_pct"] == tolerance and row["market"] in ("CN", "US")]
        total = sum(row["count"] for row in rows)
        top = max(rows, key=lambda row: row["count"], default=None)
        lines.append(
            f"- `{tolerance:.1%}`：CN/US each conserve all diagnostic bars；最大 terminal reason "
            f"为 `{top['terminal_reason'] if top else 'N/A'}`（{top['count'] if top else 0}/{total if total else 0} across displayed markets）。"
        )
    lines.extend(["", "## 相邻 tolerance stability（描述性）", "", "| previous→current | market | Jaccard | retention | added | disappeared | calendar-day drift median/P90 | trading-day drift median/P90 |", "|---|---|---:|---:|---:|---:|---|---|"])
    for row in adjacent_rows:
        def fmt(value: Any) -> str:
            return "—" if value is None else f"{float(value):.1f}d"
        lines.append(
            f"| {row['previous_tolerance_pct']:.1%}→{row['current_tolerance_pct']:.1%} | {row['market']} | "
            f"{row['jaccard']:.2%} | {row['retention']:.2%} | {row['added_events']} | {row['disappeared_events']} | "
            f"{fmt(row['calendar_day_drift_median_days'])}/{fmt(row['calendar_day_drift_P90_days'])} | "
            f"{fmt(row['trading_day_drift_median_days'])}/{fmt(row['trading_day_drift_P90_days'])} |"
        )
    lines.extend(["", "## Concentration / sparse-event risk", ""])
    for row in concentration_rows:
        if row["market"] in ("CN", "US") and row["dimension"] == "symbol":
            lines.append(
                f"- `{row['platform_tolerance_pct']:.1%}` {row['market']} symbol concentration: "
                f"{row['max_group'] or 'N/A'} max share="
                f"{'不可评估' if row['max_share'] is None else f'{row['max_share']:.2%}'}; HHI="
                f"{'不可评估' if row['HHI'] is None else f'{row['HHI']:.4f}'}。"
            )
    lines.extend(["", "## Data-quality exclusions", ""])
    if exclusions:
        for row in exclusions:
            lines.append(f"- `{row['market']}/{row['canonical_symbol']}` `{row['status']}`：{row['reason']}")
    else:
        lines.append("- 无 provider/QC exclusion；各选定 symbol 均保留在 frozen dataset。")
    lines.extend([
        "",
        "## 研究边界与决策状态",
        "",
        "- 本轮只提供结构稳定性 evidence，不自动决定修改策略、不自动选择 production tolerance。",
        "- 未读取 forward return、MFE、MAE、P&L 或 final OOS；未接入 IBKR；未执行 formal Phase 5K validation。",
        "- 需要研究设计者基于本包判断：是否修改核心策略逻辑，或另行注册新的研究设计。",
        "",
        f"`{final_status}`",
        "",
    ])
    return "\n".join(lines)
