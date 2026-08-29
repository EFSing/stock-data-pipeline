"""Structure-only qualification for the frozen SETUP_03 ATR boundary family.

The runner reuses the production causal swing and SETUP_03 lifecycle detector,
but never calls Decision or any outcome/forward-return code path.  It records
confirmed-event identities, terminal lifecycle identities, adjacent structural
stability and deterministic precomputed-swing parity only.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
import csv
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from core import Quote
from research.atr_boundary_dataset import (
    DATASET_MANIFEST_PATH,
    DATASET_STATUS,
    DATASET_VERSION,
    FROZEN_INPUT_PATH,
    READY_STATUS,
    REPLAY_MANIFEST_PATH,
    canonical_json,
    manifest_integrity_hash,
)
from research.atr_boundary_protocol import EXPECTED_PROTOCOL_SHA256, PROTOCOL_VERSION, load_protocol
from research.atr_boundary_universe import UNIVERSE_PATH, load_universe_manifest
from research.market_sessions import build_market_session_dates
from research.phase5j_v3_event_matching import match_event_identities
from research.replay_input import build_input_manifest, read_frozen_input
from trading.events import terminal_event_type
from trading.models import SetupState
from trading.setup import (
    ATR_NORMALIZED_BOUNDARY_MODE,
    PERCENTAGE_BOUNDARY_MODE,
    detect_platform_breakout_history_with_diagnostics,
)
from trading.swing import find_swings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "research" / "atr_boundary_qualification"
CAPSULE_PATH = OUTPUT_DIR / "decision_capsule.json"
REPORT_PATH = OUTPUT_DIR / "report.md"
CANDIDATE_MATRIX_PATH = OUTPUT_DIR / "candidate_level_matrix.csv"
ADJACENT_MATRIX_PATH = OUTPUT_DIR / "adjacent_stability_matrix.csv"
LIFECYCLE_MATRIX_PATH = OUTPUT_DIR / "lifecycle_divergence_matrix.csv"
BASELINE_PATH = OUTPUT_DIR / "baseline_reference.csv"
ARTIFACT_HASHES_PATH = OUTPUT_DIR / "artifact_hashes.json"

ATR_CANDIDATES = (1.0, 1.5, 2.0, 2.5)
BASELINE_REFERENCES = (0.03, 0.04, 0.05)
ADJACENT_PAIRS = tuple(zip(ATR_CANDIDATES, ATR_CANDIDATES[1:]))
FIXED_SETUP = {"swing_lookback": 5, "platform_window": 40, "arm_proximity_pct": 0.0}
EXPECTED_UNIVERSE_SHA256 = "sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b"
EXPECTED_UNIVERSE_VERSION = "SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1"
EXPECTED_MAIN_SHA256 = "21c73977195682df576750648765b1b74d8824e2"
QUALIFICATION_STATUS_PASS = "SETUP_03_BOUNDARY_REDESIGN_SURVIVES_INDEPENDENT_DEVELOPMENT"
QUALIFICATION_STATUS_FAIL = "STOP_SETUP_03_STRUCTURAL_DEVELOPMENT"
QUALIFICATION_NEXT_PASS = "READY_FOR_FORMAL_VALIDATION"
QUALIFICATION_NEXT_FAIL = "STOP_SETUP_03_STRUCTURAL_DEVELOPMENT"

CANDIDATE_CRITERIA = (
    ("minimum_confirmed_events_per_market_candidate", ">=", 8, "events"),
    ("minimum_event_symbols_per_market_candidate", ">=", 8, "symbols"),
    ("maximum_symbol_confirmed_concentration", "<=", 0.25, "share"),
    ("maximum_symbol_confirmed_hhi", "<=", 0.20, "HHI"),
    ("zero_confirmed_event_pathology", "=", False, "boolean"),
)
ADJACENT_CRITERIA = (
    ("adjacent_confirmed_jaccard", ">=", 0.60, "share"),
    ("adjacent_confirmed_retention", ">=", 0.80, "share"),
    ("added_event_rate", "<=", 0.50, "share"),
    ("disappeared_event_rate", "<=", 0.50, "share"),
    ("matched_confirmed_event_date_drift_median", "<=", 5, "trading sessions"),
    ("matched_confirmed_event_date_drift_p90", "<=", 15, "trading sessions"),
    ("lifecycle_divergence_rate", "<=", 0.50, "share"),
)


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _format_threshold(value: float) -> str:
    return f"{float(value):.1f}"


def _format_pair(pair: tuple[float, float]) -> str:
    return f"{pair[0]:.1f}->{pair[1]:.1f}"


def _validate_dataset_bindings() -> tuple[dict[str, Any], dict[str, Any], dict[str, list[Quote]], Any, dict[str, Any]]:
    dataset = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
    if dataset.get("dataset_version") != DATASET_VERSION or dataset.get("status") != DATASET_STATUS:
        raise ValueError("ATR clean-holdout dataset identity/status changed")
    if dataset.get("integrity", {}).get("manifest_sha256") != manifest_integrity_hash(dataset):
        raise ValueError("ATR clean-holdout dataset manifest integrity mismatch")
    if dataset.get("coverage_status") != READY_STATUS:
        raise ValueError("ATR clean-holdout dataset is not replay-ready")
    if dataset.get("protocol", {}).get("version") != PROTOCOL_VERSION or dataset.get("protocol", {}).get("sha256") != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("ATR clean-holdout dataset protocol binding changed")
    if dataset.get("universe", {}).get("manifest_sha256") != EXPECTED_UNIVERSE_SHA256:
        raise ValueError("ATR clean-holdout dataset universe binding changed")
    if dataset.get("aggregate_symbol_count") != 40:
        raise ValueError("ATR clean-holdout dataset symbol count changed")
    universe = load_universe_manifest(UNIVERSE_PATH)
    if universe.get("universe_version") != EXPECTED_UNIVERSE_VERSION or universe.get("integrity", {}).get("manifest_sha256") != EXPECTED_UNIVERSE_SHA256:
        raise ValueError("ATR clean-holdout universe identity changed")
    symbol_quotes, replay_manifest = read_frozen_input(FROZEN_INPUT_PATH)
    actual_manifest = build_input_manifest(symbol_quotes)
    if actual_manifest != replay_manifest:
        raise ValueError("ATR replay input manifest changed after serialization")
    if replay_manifest.aggregate_hash != dataset.get("replay_input_manifest_sha256"):
        raise ValueError("ATR replay input aggregate binding changed")
    wrapper = json.loads(REPLAY_MANIFEST_PATH.read_text(encoding="utf-8"))
    if wrapper.get("schema_version") != "setup03-atr-boundary-clean-holdout-replay-manifest-v1":
        raise ValueError("ATR replay wrapper schema changed")
    if wrapper.get("dataset_manifest_sha256") != dataset["integrity"]["manifest_sha256"]:
        raise ValueError("ATR replay wrapper dataset binding changed")
    if wrapper.get("replay_manifest") != replay_manifest.to_dict():
        raise ValueError("ATR replay wrapper does not match frozen replay input")
    if wrapper.get("integrity", {}).get("manifest_sha256") != manifest_integrity_hash(wrapper):
        raise ValueError("ATR replay wrapper integrity mismatch")
    return dataset, universe, symbol_quotes, replay_manifest, wrapper


def _terminal_record(quote: Quote, index: int, setup: Any, event_type: SetupState) -> dict[str, Any]:
    return {
        "market": quote.market,
        "canonical_symbol": quote.symbol,
        "terminal_index": index,
        "terminal_date": quote.trade_date.isoformat(),
        "terminal_type": event_type.value,
        "detected_index": setup.detected_index,
        "breakout_price": None if setup.breakout_price is None else float(setup.breakout_price).hex(),
        "structural_invalidation": None if setup.structural_invalidation is None else float(setup.structural_invalidation).hex(),
    }


def _assign_lifecycle_ordinals(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(record) for record in records),
        key=lambda row: (
            row["market"],
            row["canonical_symbol"],
            int(row["terminal_index"]),
            row["terminal_type"],
            -1 if row["detected_index"] is None else int(row["detected_index"]),
        ),
    )
    ordinals: Counter[tuple[str, str]] = Counter()
    for record in ordered:
        key = (record["market"], record["canonical_symbol"])
        ordinals[key] += 1
        record["ordinal"] = ordinals[key]
    return ordered


def _run_configuration(
    symbol_quotes: Mapping[str, list[Quote]],
    *,
    mode: str,
    threshold: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[tuple[str, str, date]]], dict[str, list[dict[str, Any]]], dict[str, int]]:
    by_market: dict[str, dict[str, Any]] = {
        market: {
            "symbol_count": 0,
            "bar_count": 0,
            "platform_detection_count": 0,
            "confirmed_events": [],
            "terminal_events": [],
            "reason_counts": Counter(),
        }
        for market in ("CN", "US")
    }
    event_keys: dict[str, list[tuple[str, str, date]]] = {"CN": [], "US": []}
    lifecycles: dict[str, list[dict[str, Any]]] = {"CN": [], "US": []}
    parity = {"cells": 0, "bar_comparisons": 0, "event_comparisons": 0, "setup_mismatches": 0, "event_mismatches": 0}
    for symbol in sorted(symbol_quotes):
        quotes = symbol_quotes[symbol]
        market = quotes[0].market
        by_market[market]["symbol_count"] += 1
        by_market[market]["bar_count"] += len(quotes)
        swings = find_swings(quotes, lookback=FIXED_SETUP["swing_lookback"])
        kwargs: dict[str, Any] = {
            **FIXED_SETUP,
            "platform_boundary_mode": mode,
        }
        if mode == ATR_NORMALIZED_BOUNDARY_MODE:
            kwargs["platform_atr_period"] = 14
            kwargs["platform_boundary_threshold_atr"] = threshold
        else:
            kwargs["platform_tolerance_pct"] = threshold
        history = detect_platform_breakout_history_with_diagnostics(quotes, **kwargs)
        precomputed_history = detect_platform_breakout_history_with_diagnostics(quotes, swings=swings, **kwargs)
        parity["cells"] += 1
        parity["bar_comparisons"] += len(quotes)
        for index, (shared, precomputed) in enumerate(zip(history, precomputed_history)):
            if shared != precomputed:
                parity["setup_mismatches"] += 1
            shared_event = terminal_event_type(shared.setup, index)
            precomputed_event = terminal_event_type(precomputed.setup, index)
            if shared_event is not None or precomputed_event is not None:
                parity["event_comparisons"] += 1
                if shared_event != precomputed_event:
                    parity["event_mismatches"] += 1
            diagnostic = shared.diagnostics
            by_market[market]["reason_counts"][diagnostic.reason.value] += 1
            by_market[market]["platform_detection_count"] += int(bool(diagnostic.platform_detected_this_bar))
            if shared_event is SetupState.CONFIRMED:
                quote = quotes[index]
                record = _terminal_record(quote, index, shared.setup, shared_event)
                by_market[market]["confirmed_events"].append(record)
                event_keys[market].append((market, quote.symbol, quote.trade_date))
            if shared_event is not None:
                lifecycles[market].append(_terminal_record(quotes[index], index, shared.setup, shared_event))
    for market in ("CN", "US"):
        lifecycles[market] = _assign_lifecycle_ordinals(lifecycles[market])
        for record in by_market[market]["confirmed_events"]:
            record["event_identity"] = [record["market"], record["canonical_symbol"], record["terminal_date"]]
        by_market[market]["terminal_event_count"] = len(lifecycles[market])
        by_market[market]["confirmed_event_count"] = len(by_market[market]["confirmed_events"])
        symbol_counts = Counter(record["canonical_symbol"] for record in by_market[market]["confirmed_events"])
        total = len(by_market[market]["confirmed_events"])
        shares = [count / total for count in symbol_counts.values()] if total else []
        by_market[market]["event_symbol_count"] = len(symbol_counts)
        by_market[market]["symbol_confirmed_counts"] = dict(sorted(symbol_counts.items()))
        by_market[market]["max_symbol_confirmed_share"] = max(shares, default=None)
        by_market[market]["confirmed_hhi"] = sum(share * share for share in shares)
        by_market[market]["zero_confirmed_event_pathology"] = total == 0 or len(symbol_counts) == 0
        by_market[market]["reason_counts"] = dict(sorted(by_market[market]["reason_counts"].items()))
    return by_market, event_keys, lifecycles, parity


def _event_metrics(
    previous: Iterable[tuple[str, str, date]],
    current: Iterable[tuple[str, str, date]],
    sessions: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    previous = tuple(previous)
    current = tuple(current)
    result = match_event_identities(previous, current, market_session_dates=sessions)
    old = set(previous)
    new = set(current)
    retained = len(result["retained"])
    union_count = len(old | new)
    distances = [int(pair["trading_session_distance"]) for pair in result["matched_pairs"]]
    return {
        "previous_event_count": len(old),
        "current_event_count": len(new),
        "retained_exact": retained,
        "added": len(result["added"]),
        "disappeared": len(result["disappeared"]),
        "unmatched_previous": len(result["unmatched_previous"]),
        "unmatched_current": len(result["unmatched_current"]),
        "exact_date_jaccard": retained / union_count if union_count else 1.0,
        "retention": retained / len(old) if old else (1.0 if not new else 0.0),
        "added_event_rate": len(result["added"]) / len(new) if new else 0.0,
        "disappeared_event_rate": len(result["disappeared"]) / len(old) if old else 0.0,
        "matched_count": len(distances),
        "trading_session_drift_median": median(distances) if distances else None,
        "trading_session_drift_p90": _quantile(distances, 0.90),
        "distance_buckets": {
            "0-2": sum(distance <= 2 for distance in distances),
            "3-5": sum(3 <= distance <= 5 for distance in distances),
            "6-10": sum(6 <= distance <= 10 for distance in distances),
            "11-15": sum(11 <= distance <= 15 for distance in distances),
            ">15": sum(distance > 15 for distance in distances),
        },
        "matched_pairs": result["matched_pairs"],
        "retained_exact_keys": result["retained"],
        "added_keys": result["added"],
        "disappeared_keys": result["disappeared"],
        "unmatched_previous_keys": result["unmatched_previous"],
        "unmatched_current_keys": result["unmatched_current"],
    }


def _lifecycle_metrics(previous: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    changed_fields = ("terminal_type", "terminal_date", "detected_index", "breakout_price", "structural_invalidation")
    old = {(row["canonical_symbol"], int(row["ordinal"])): row for row in previous}
    new = {(row["canonical_symbol"], int(row["ordinal"])): row for row in current}
    changed: list[list[Any]] = []
    unmatched_previous: list[list[Any]] = []
    unmatched_current: list[list[Any]] = []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            unmatched_current.append([key[0], key[1]])
        elif key not in new:
            unmatched_previous.append([key[0], key[1]])
        elif any(old[key].get(field) != new[key].get(field) for field in changed_fields):
            changed.append([key[0], key[1]])
    divergence_count = len(unmatched_previous) + len(unmatched_current) + len(changed)
    denominator = max(len(old), len(new), 1)
    return {
        "previous_lifecycle_count": len(old),
        "current_lifecycle_count": len(new),
        "retained_ordinal_count": len(set(old) & set(new)),
        "unmatched_previous_count": len(unmatched_previous),
        "unmatched_current_count": len(unmatched_current),
        "changed_retained_ordinal_count": len(changed),
        "divergence_count": divergence_count,
        "divergence_rate": divergence_count / denominator,
        "unmatched_previous": unmatched_previous,
        "unmatched_current": unmatched_current,
        "changed_retained_ordinals": changed,
    }


def _candidate_observation(summary: Mapping[str, Any], criterion_id: str) -> Any:
    return {
        "minimum_confirmed_events_per_market_candidate": summary["confirmed_event_count"],
        "minimum_event_symbols_per_market_candidate": summary["event_symbol_count"],
        "maximum_symbol_confirmed_concentration": summary["max_symbol_confirmed_share"],
        "maximum_symbol_confirmed_hhi": summary["confirmed_hhi"],
        "zero_confirmed_event_pathology": summary["zero_confirmed_event_pathology"],
    }[criterion_id]


def _adjacent_observation(event_row: Mapping[str, Any], lifecycle_row: Mapping[str, Any], criterion_id: str) -> Any:
    return {
        "adjacent_confirmed_jaccard": event_row["exact_date_jaccard"],
        "adjacent_confirmed_retention": event_row["retention"],
        "added_event_rate": event_row["added_event_rate"],
        "disappeared_event_rate": event_row["disappeared_event_rate"],
        "matched_confirmed_event_date_drift_median": event_row["trading_session_drift_median"],
        "matched_confirmed_event_date_drift_p90": event_row["trading_session_drift_p90"],
        "lifecycle_divergence_rate": lifecycle_row["divergence_rate"],
    }[criterion_id]


def _passes(observed: Any, operator: str, threshold: Any) -> bool:
    if observed is None:
        return False
    if operator == ">=":
        return observed >= threshold
    if operator == "<=":
        return observed <= threshold
    if operator == "=":
        return observed is threshold or observed == threshold
    raise ValueError(f"unsupported qualification operator: {operator}")


def _matrix_and_selection(
    candidate_runs: Mapping[float, Mapping[str, Mapping[str, Any]]],
    adjacent_runs: Mapping[tuple[float, float], Mapping[str, Mapping[str, Any]]],
    lifecycle_runs: Mapping[tuple[float, float], Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    matrix: list[dict[str, Any]] = []
    for candidate in ATR_CANDIDATES:
        incident_pairs = [pair for pair in ADJACENT_PAIRS if candidate in pair]
        for market in ("CN", "US"):
            summary = candidate_runs[candidate][market]
            for criterion_id, operator, threshold, unit in CANDIDATE_CRITERIA:
                observed = _candidate_observation(summary, criterion_id)
                passed = _passes(observed, operator, threshold)
                margin = None if observed is None or isinstance(observed, bool) else (observed - threshold if operator == ">=" else threshold - observed)
                matrix.append({
                    "candidate_threshold_atr": candidate,
                    "market": market,
                    "scope": "candidate",
                    "adjacent_pair": None,
                    "criterion_id": criterion_id,
                    "operator": operator,
                    "frozen_threshold": threshold,
                    "unit": unit,
                    "observed_value": observed,
                    "margin_to_threshold": margin,
                    "status": "PASS" if passed else "FAIL",
                })
            for pair in incident_pairs:
                event_row = adjacent_runs[pair][market]
                lifecycle_row = lifecycle_runs[pair][market]
                for criterion_id, operator, threshold, unit in ADJACENT_CRITERIA:
                    observed = _adjacent_observation(event_row, lifecycle_row, criterion_id)
                    passed = _passes(observed, operator, threshold)
                    margin = None if observed is None else (observed - threshold if operator == ">=" else threshold - observed)
                    matrix.append({
                        "candidate_threshold_atr": candidate,
                        "market": market,
                        "scope": "adjacent_pair",
                        "adjacent_pair": list(pair),
                        "criterion_id": criterion_id,
                        "operator": operator,
                        "frozen_threshold": threshold,
                        "unit": unit,
                        "observed_value": observed,
                        "margin_to_threshold": margin,
                        "status": "PASS" if passed else "FAIL",
                    })
    evaluations: list[dict[str, Any]] = []
    for candidate in ATR_CANDIDATES:
        for market in ("CN", "US"):
            rows = [row for row in matrix if row["candidate_threshold_atr"] == candidate and row["market"] == market]
            failures = [row["criterion_id"] for row in rows if row["status"] != "PASS"]
            evaluations.append({
                "candidate_threshold_atr": candidate,
                "market": market,
                "qualifies": not failures,
                "failed_criteria": failures,
            })
    qualified = [
        candidate for candidate in ATR_CANDIDATES
        if all(row["qualifies"] for row in evaluations if row["candidate_threshold_atr"] == candidate)
    ]
    def tie_key(candidate: float) -> tuple[Any, ...]:
        incident = [pair for pair in ADJACENT_PAIRS if candidate in pair]
        worst_jaccard = min(
            adjacent_runs[pair][market]["exact_date_jaccard"]
            for pair in incident for market in ("CN", "US")
        )
        worst_lifecycle = max(
            lifecycle_runs[pair][market]["divergence_rate"]
            for pair in incident for market in ("CN", "US")
        )
        return (candidate, -worst_jaccard, worst_lifecycle, candidate)
    selected = min(qualified, key=tie_key) if qualified else None
    return {
        "matrix": matrix,
        "candidate_market_evaluations": evaluations,
        "qualified_candidates": qualified,
        "selected_candidate_atr": selected,
        "status": QUALIFICATION_STATUS_PASS if selected is not None else QUALIFICATION_STATUS_FAIL,
        "next": QUALIFICATION_NEXT_PASS if selected is not None else QUALIFICATION_NEXT_FAIL,
        "failure_breakdown": [row for row in matrix if row["status"] == "FAIL"],
    }


def run_qualification() -> dict[str, Any]:
    protocol = load_protocol()
    dataset, universe, symbol_quotes, replay_manifest, wrapper = _validate_dataset_bindings()
    sessions = build_market_session_dates(symbol_quotes)
    candidate_runs: dict[float, Mapping[str, Mapping[str, Any]]] = {}
    event_keys_by_candidate: dict[float, dict[str, list[tuple[str, str, date]]]] = {}
    lifecycle_by_candidate: dict[float, dict[str, list[dict[str, Any]]]] = {}
    parity_total = {"cells": 0, "bar_comparisons": 0, "event_comparisons": 0, "setup_mismatches": 0, "event_mismatches": 0}
    for candidate in ATR_CANDIDATES:
        summary, keys, lifecycles, parity = _run_configuration(
            symbol_quotes, mode=ATR_NORMALIZED_BOUNDARY_MODE, threshold=candidate
        )
        candidate_runs[candidate] = summary
        event_keys_by_candidate[candidate] = keys
        lifecycle_by_candidate[candidate] = lifecycles
        for field in parity_total:
            parity_total[field] += parity[field]
    baseline_runs: dict[float, Mapping[str, Mapping[str, Any]]] = {}
    for reference in BASELINE_REFERENCES:
        summary, _, _, parity = _run_configuration(
            symbol_quotes, mode=PERCENTAGE_BOUNDARY_MODE, threshold=reference
        )
        baseline_runs[reference] = summary
        for field in parity_total:
            parity_total[field] += parity[field]
    adjacent_events: dict[tuple[float, float], dict[str, dict[str, Any]]] = {}
    adjacent_lifecycles: dict[tuple[float, float], dict[str, dict[str, Any]]] = {}
    for pair in ADJACENT_PAIRS:
        adjacent_events[pair] = {}
        adjacent_lifecycles[pair] = {}
        for market in ("CN", "US"):
            adjacent_events[pair][market] = _event_metrics(
                event_keys_by_candidate[pair[0]][market],
                event_keys_by_candidate[pair[1]][market],
                sessions,
            )
            adjacent_lifecycles[pair][market] = _lifecycle_metrics(
                lifecycle_by_candidate[pair[0]][market],
                lifecycle_by_candidate[pair[1]][market],
            )
    qualification = _matrix_and_selection(candidate_runs, adjacent_events, adjacent_lifecycles)
    return {
        "schema_version": "setup03-atr-boundary-qualification-report-v1",
        "report_version": "SETUP_03-ATR-BOUNDARY-QUALIFICATION-2026-08-29-v1",
        "status": qualification["status"],
        "next": qualification["next"],
        "protocol": {"version": protocol["protocol_version"], "sha256": protocol["integrity"]["protocol_sha256"]},
        "universe": {
            "version": universe["universe_version"],
            "manifest_sha256": universe["integrity"]["manifest_sha256"],
            "symbol_list_sha256": universe["symbol_list_sha256"],
            "counts": universe["counts"],
        },
        "dataset": {
            "version": dataset["dataset_version"],
            "manifest_sha256": dataset["integrity"]["manifest_sha256"],
            "aggregate_normalized_sha256": dataset["aggregate_normalized_sha256"],
            "replay_input_aggregate_sha256": dataset["replay_input_manifest_sha256"],
            "replay_input_file_sha256": _sha256_file(FROZEN_INPUT_PATH),
            "replay_wrapper_sha256": _sha256_file(REPLAY_MANIFEST_PATH),
            "aggregate_symbol_count": dataset["aggregate_symbol_count"],
            "aggregate_valid_bar_count": dataset["aggregate_valid_bar_count"],
        },
        "main_base_sha256": EXPECTED_MAIN_SHA256,
        "fixed_setup_parameters": FIXED_SETUP,
        "boundary_family": {
            "mode": ATR_NORMALIZED_BOUNDARY_MODE,
            "atr_indicator": "WILDER_ATR",
            "atr_period": 14,
            "candidate_thresholds_atr": list(ATR_CANDIDATES),
            "candidate_count": len(ATR_CANDIDATES),
            "incumbent_reference_pct": list(BASELINE_REFERENCES),
        },
        "candidate_level": {
            _format_threshold(candidate): {
                market: candidate_runs[candidate][market]
                for market in ("CN", "US")
            }
            for candidate in ATR_CANDIDATES
        },
        "adjacent_event_matching": {
            _format_pair(pair): adjacent_events[pair] for pair in ADJACENT_PAIRS
        },
        "lifecycle_divergence": {
            _format_pair(pair): adjacent_lifecycles[pair] for pair in ADJACENT_PAIRS
        },
        "baseline_reference": {
            _format_threshold(reference): {
                market: baseline_runs[reference][market]
                for market in ("CN", "US")
            }
            for reference in BASELINE_REFERENCES
        },
        "qualification": qualification,
        "parity": {
            "status": "PASS" if parity_total["setup_mismatches"] == 0 and parity_total["event_mismatches"] == 0 else "FAIL",
            **parity_total,
            "comparison": "shared causal swings versus precomputed causal swings; every input bar and every terminal event",
        },
        "reproducibility": {
            "required": True,
            "status": "PENDING_REPEAT",
            "method": "same frozen input and protocol, second full structure-only run",
        },
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "outcome_metrics_accessed": False,
            "decision_engine_called": False,
            "production_selection": False,
            "terminal_rearm_changed": False,
            "provider_accessed_after_universe_freeze": True,
        },
    }


def canonical_payload_digest(payload: Mapping[str, Any]) -> str:
    body = deepcopy(dict(payload))
    body.pop("integrity", None)
    body["reproducibility"] = dict(body.get("reproducibility", {}))
    body["reproducibility"].pop("status", None)
    return f"sha256:{hashlib.sha256(canonical_json(body).encode('utf-8')).hexdigest()}"


def _csv_rows(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    qualification = payload["qualification"]
    candidate_rows: list[dict[str, Any]] = []
    adjacent_rows: list[dict[str, Any]] = []
    lifecycle_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    for row in qualification["matrix"]:
        output = dict(row)
        output["adjacent_pair"] = None if row["adjacent_pair"] is None else _format_pair(tuple(row["adjacent_pair"]))
        if row["scope"] == "candidate":
            candidate_rows.append(output)
        else:
            adjacent_rows.append(output)
    for pair, markets in payload["lifecycle_divergence"].items():
        for market, row in markets.items():
            lifecycle_rows.append({"adjacent_pair": pair, "market": market, **row})
    for reference, markets in payload["baseline_reference"].items():
        for market, row in markets.items():
            baseline_rows.append({
                "reference_pct": float(reference),
                "market": market,
                "symbol_count": row["symbol_count"],
                "bar_count": row["bar_count"],
                "platform_detection_count": row["platform_detection_count"],
                "confirmed_event_count": row["confirmed_event_count"],
                "terminal_event_count": row["terminal_event_count"],
                "max_symbol_confirmed_share": row["max_symbol_confirmed_share"],
                "confirmed_hhi": row["confirmed_hhi"],
                "zero_confirmed_event_pathology": row["zero_confirmed_event_pathology"],
            })
    return candidate_rows, adjacent_rows, lifecycle_rows, baseline_rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _render_report(payload: Mapping[str, Any], artifact_hashes: Mapping[str, str]) -> str:
    qualification = payload["qualification"]
    lines = [
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->",
        "# SETUP_03 ATR-normalized platform boundary structure-only qualification",
        "",
        "> 本报告只验证预注册 ATR-normalized platform boundary family 的结构稳定性；不构成 formal validation、production parameter selection 或 Final OOS。",
        "",
        "## 固定身份与边界",
        "",
        f"- protocol: `{payload['protocol']['version']}` / `{payload['protocol']['sha256']}`",
        f"- universe: `{payload['universe']['version']}` / `{payload['universe']['manifest_sha256']}` / CN20 + US20",
        f"- dataset: `{payload['dataset']['version']}` / `{payload['dataset']['manifest_sha256']}` / `{payload['dataset']['aggregate_valid_bar_count']}` bars",
        f"- normalized aggregate: `{payload['dataset']['aggregate_normalized_sha256']}`",
        f"- replay input aggregate/file: `{payload['dataset']['replay_input_aggregate_sha256']}` / `{payload['dataset']['replay_input_file_sha256']}`",
        f"- base: `main@{payload['main_base_sha256']}`",
        "- family: Wilder ATR period 14, as-of `t`, symmetric high/low width divided by the same `ATR[t]`; thresholds are 1.0/1.5/2.0/2.5 ATR.",
        "- unchanged: causal swing, strict as-of, lifecycle, breakout, confirmed/failed, Decision/execution contracts, terminal and rearm semantics.",
        "",
        "## Candidate results",
        "",
        "| threshold ATR | market | bars | platform detections | confirmed | terminals | event symbols | max share | HHI | zero-event pathology |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for candidate in ATR_CANDIDATES:
        for market in ("CN", "US"):
            row = payload["candidate_level"][_format_threshold(candidate)][market]
            share = "null" if row["max_symbol_confirmed_share"] is None else f"{row['max_symbol_confirmed_share']:.2%}"
            lines.append(
                f"| {candidate:.1f} | {market} | {row['bar_count']} | {row['platform_detection_count']} | {row['confirmed_event_count']} | {row['terminal_event_count']} | {row['event_symbol_count']} | {share} | {row['confirmed_hhi']:.4f} | {row['zero_confirmed_event_pathology']} |"
            )
    lines.extend(["", "## Adjacent event and lifecycle stability", "", "| pair | market | exact Jaccard | retention | added rate | disappeared rate | drift median/P90 | lifecycle divergence |", "|---|---|---:|---:|---:|---:|---:|---:|"])
    for pair in ADJACENT_PAIRS:
        label = _format_pair(pair)
        for market in ("CN", "US"):
            event = payload["adjacent_event_matching"][label][market]
            lifecycle = payload["lifecycle_divergence"][label][market]
            drift = "null" if event["trading_session_drift_median"] is None else f"{event['trading_session_drift_median']:.2f}/{event['trading_session_drift_p90']:.2f}"
            lines.append(f"| {pair[0]:.1f}→{pair[1]:.1f} | {market} | {event['exact_date_jaccard']:.2%} | {event['retention']:.2%} | {event['added_event_rate']:.2%} | {event['disappeared_event_rate']:.2%} | {drift} | {lifecycle['divergence_rate']:.2%} |")
    lines.extend(["", "## Qualification matrix", "", f"- qualified candidates: `{qualification['qualified_candidates']}`", f"- selected research candidate (not production): `{qualification['selected_candidate_atr']}`", f"- status: `{payload['status']}`", f"- next: `{payload['next']}`", "", "| candidate | market | scope | pair | criterion | observed | frozen | status |", "|---:|---|---|---|---|---:|---|---|"])
    for row in qualification["matrix"]:
        pair = "—" if row["adjacent_pair"] is None else f"{row['adjacent_pair'][0]:.1f}→{row['adjacent_pair'][1]:.1f}"
        observed = "null" if row["observed_value"] is None else str(row["observed_value"])
        lines.append(f"| {row['candidate_threshold_atr']:.1f} | {row['market']} | {row['scope']} | {pair} | `{row['criterion_id']}` | {observed} | `{row['operator']} {row['frozen_threshold']}` | `{row['status']}` |")
    lines.extend(["", "## Parity, reproducibility and boundaries", "", f"- precomputed-swing parity: `{payload['parity']['status']}`; cells `{payload['parity']['cells']}`, bars `{payload['parity']['bar_comparisons']}`, terminal events `{payload['parity']['event_comparisons']}`, setup mismatches `{payload['parity']['setup_mismatches']}`, event mismatches `{payload['parity']['event_mismatches']}`.", f"- deterministic repeat: `{payload['reproducibility']['status']}`; canonical digest is recorded in the capsule and must match the second run.", "- incumbent 3%/4%/5% percentages are reference-only; no fixed-percentage search or production selection was performed.", "- no returns, forward returns, MFE, MAE, P&L, winrate, expectancy, Final OOS, formal Phase 5K-B1, IBKR, Decision calculation or production write was accessed.", "", "Artifact hashes:", ""])
    for name, digest in artifact_hashes.items():
        lines.append(f"- `{name}`: `{digest}`")
    lines.extend(["", f"`{payload['status']}`", ""])
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], *, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows, adjacent_rows, lifecycle_rows, baseline_rows = _csv_rows(payload)
    candidate_path = output_dir / CANDIDATE_MATRIX_PATH.name
    adjacent_path = output_dir / ADJACENT_MATRIX_PATH.name
    lifecycle_path = output_dir / LIFECYCLE_MATRIX_PATH.name
    baseline_path = output_dir / BASELINE_PATH.name
    _write_csv(candidate_path, candidate_rows)
    _write_csv(adjacent_path, adjacent_rows)
    _write_csv(lifecycle_path, lifecycle_rows)
    _write_csv(baseline_path, baseline_rows)
    payload["integrity"] = {
        "canonical_payload_sha256": canonical_payload_digest(payload),
        "hash_scope": "canonical JSON with reproducibility.status omitted and integrity omitted",
    }
    capsule_path = output_dir / CAPSULE_PATH.name
    capsule_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    artifact_hashes = {
        "candidate_level_matrix.csv": _sha256_file(candidate_path),
        "adjacent_stability_matrix.csv": _sha256_file(adjacent_path),
        "lifecycle_divergence_matrix.csv": _sha256_file(lifecycle_path),
        "baseline_reference.csv": _sha256_file(baseline_path),
        "decision_capsule.json": _sha256_file(capsule_path),
    }
    report_path = output_dir / REPORT_PATH.name
    report_path.write_text(_render_report(payload, artifact_hashes), encoding="utf-8")
    artifact_hashes["report.md"] = _sha256_file(report_path)
    hashes_path = output_dir / ARTIFACT_HASHES_PATH.name
    hashes_path.write_text(json.dumps({"schema_version": "setup03-atr-boundary-artifact-hashes-v1", "artifacts": artifact_hashes}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    artifact_hashes["artifact_hashes.json"] = _sha256_file(hashes_path)
    return {"payload": payload, "artifact_hashes": artifact_hashes, "output_dir": output_dir}


__all__ = [
    "ADJACENT_PAIRS",
    "ATR_CANDIDATES",
    "BASELINE_REFERENCES",
    "canonical_payload_digest",
    "run_qualification",
    "write_outputs",
    "_event_metrics",
    "_lifecycle_metrics",
]
