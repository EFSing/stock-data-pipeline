"""Run structure-only Phase 5J-v3 evidence on the independent holdout.

The module consumes a frozen holdout replay input and reuses the existing
main-baseline parity audit.  It never calculates or imports outcome metrics,
never changes SETUP_03, and never chooses a production parameter.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from core import Quote
from research.development_decision_capsule import (
    DECISION_PARAMETERS,
    SETUP_PARAMETERS,
    _summary_for_market,
    run_legacy_main_parity,
)
from research.development_holdout_dataset import (
    READY_STATUS,
)
from research.market_sessions import build_market_session_dates
from research.phase5j_v3_event_matching import load_protocol, match_event_identities


TOLERANCE_SEQUENCE = (0.025, 0.03, 0.04, 0.05, 0.055, 0.075, 0.10)
PRODUCTION_TOLERANCES = (0.03, 0.04, 0.05)
QUALIFICATION_TRANSITIONS = ((0.03, 0.04), (0.04, 0.05))
OUTPUT_SCHEMA_VERSION = "setup03-phase5j-v3-development-holdout-evidence-v1"
OUTPUT_VERSION = "SETUP_03-PHASE5J-V3-DEVELOPMENT-HOLDOUT-EVIDENCE-2026-08-29-v1"
SOL_READY_STATUS = "READY_FOR_SOL_FORMAL_FREEZE_DECISION"
SOL_FAILURE_STATUS = "SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION"
PARITY_BLOCKER_STATUS = "BLOCKER_REPLAY_SEMANTIC_DRIFT"
PROTOCOL_VERSION = "SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1"
PROTOCOL_SHA256 = "sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816"
HOLDOUT_UNIVERSE_SHA256 = "sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _quantile(values: Sequence[float], q: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _event_keys(compact_reports: Sequence[Mapping[str, Any]], market: str) -> set[tuple[str, str, date]]:
    keys: set[tuple[str, str, date]] = set()
    for item in compact_reports:
        report = item["report"]
        report_market = str(report["market"])
        if market != "ALL" and report_market != market:
            continue
        keys.update(
            (report_market, str(symbol), date.fromisoformat(str(event_date)))
            for symbol, event_date in report["event_keys"]
        )
    return keys


def _adjacent_summary(
    previous: float,
    current: float,
    compact_by_tolerance: Mapping[float, Sequence[Mapping[str, Any]]],
    market: str,
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    old = _event_keys(compact_by_tolerance[previous], market)
    new = _event_keys(compact_by_tolerance[current], market)
    result = match_event_identities(old, new, market_session_dates=market_session_dates)
    retained = len(result["retained"])
    previous_count = len(old)
    current_count = len(new)
    pairs = list(result["matched_pairs"])
    calendar_distances = [
        abs((date.fromisoformat(pair["new_date"]) - date.fromisoformat(pair["old_date"])).days)
        for pair in pairs
    ]
    trading_distances = [int(pair["trading_session_distance"]) for pair in pairs]
    buckets = {
        "0-2": sum(distance <= 2 for distance in trading_distances),
        "3-5": sum(3 <= distance <= 5 for distance in trading_distances),
        "6-10": sum(6 <= distance <= 10 for distance in trading_distances),
        "11-15": sum(11 <= distance <= 15 for distance in trading_distances),
        ">15": sum(distance > 15 for distance in trading_distances),
    }
    return {
        "previous_event_count": previous_count,
        "current_event_count": current_count,
        "retained_exact": retained,
        "added": len(result["added"]),
        "disappeared": len(result["disappeared"]),
        "matched": len(pairs),
        "unmatched_previous": len(result["unmatched_previous"]),
        "unmatched_current": len(result["unmatched_current"]),
        "exact_date_jaccard": retained / len(old | new) if old | new else 1.0,
        "retention": retained / previous_count if previous_count else (1.0 if current_count == 0 else 0.0),
        "calendar_day_drift_median": median(calendar_distances) if calendar_distances else None,
        "calendar_day_drift_P90": _quantile([float(value) for value in calendar_distances], 0.9),
        "trading_day_drift_median": median(trading_distances) if trading_distances else None,
        "trading_day_drift_P90": _quantile([float(value) for value in trading_distances], 0.9),
        "distance_buckets": buckets,
        "retained_exact_keys": list(result["retained"]),
        "added_keys": list(result["added"]),
        "disappeared_keys": list(result["disappeared"]),
        "matched_pairs": pairs,
        "unmatched_previous_keys": list(result["unmatched_previous"]),
        "unmatched_current_keys": list(result["unmatched_current"]),
        "matching_protocol": {
            "max_distance_sessions": 40,
            "objective": "maximum_cardinality_then_minimum_total_trading_session_distance_then_lexicographically_smallest_pair_sequence",
            "order_preserving": True,
            "non_crossing": True,
        },
    }


def _qualification_observation(
    threshold_id: str,
    *,
    candidate: float,
    market: str,
    pair: tuple[float, float] | None,
    summaries: Mapping[float, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> float | None:
    if threshold_id == "minimum_confirmed_events_per_market_candidate":
        return float(summaries[candidate][market]["CONFIRMED_EVENTS"])
    if threshold_id == "maximum_symbol_confirmed_concentration":
        return summaries[candidate][market]["max_symbol_event_share"]
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
        previous_count = summaries[pair[0]][market]["CONFIRMED_per_1000_bars"]
        current_count = summaries[pair[1]][market]["CONFIRMED_per_1000_bars"]
        return current_count / previous_count - 1 if previous_count else None
    raise ValueError(f"unsupported Phase 5J-v3 threshold: {threshold_id}")


def _qualification_unit(threshold_id: str) -> str:
    if threshold_id == "minimum_confirmed_events_per_market_candidate":
        return "events"
    if threshold_id in {"matched_confirmed_event_date_drift_median", "matched_confirmed_event_date_drift_p90"}:
        return "trading_days"
    return "ratio"


def _build_qualification(
    summaries: Mapping[float, Mapping[str, Mapping[str, Any]]],
    adjacent: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    protocol = load_protocol()
    bindings = protocol["frozen_qualification_bindings"]
    threshold_definitions = {
        threshold_id: {
            "operator": definition["operator"],
            "threshold": float(definition["value"]),
            "unit": definition["unit"],
        }
        for threshold_id, definition in bindings["thresholds"].items()
    }
    matrix_definition = bindings["qualification_matrix"]
    candidate_thresholds = (
        "minimum_confirmed_events_per_market_candidate",
        "maximum_symbol_confirmed_concentration",
    )
    adjacent_thresholds = (
        "adjacent_confirmed_jaccard",
        "adjacent_confirmed_retention",
        "matched_confirmed_event_date_drift_median",
        "matched_confirmed_event_date_drift_p90",
        "adjacent_confirmed_rate_relative_increase",
    )
    matrix_rows: list[dict[str, Any]] = []
    for candidate in PRODUCTION_TOLERANCES:
        candidate_label = f"{candidate:.1%}"
        pairs = [
            tuple(float(value.rstrip("%")) / 100 for value in transition.split("→"))
            for transition in matrix_definition[candidate_label]["adjacent_pairs"]
        ]
        for market in ("CN", "US"):
            for threshold_id in candidate_thresholds:
                definition = threshold_definitions[threshold_id]
                observed = _qualification_observation(
                    threshold_id, candidate=candidate, market=market, pair=None,
                    summaries=summaries, adjacent=adjacent,
                )
                passed = observed is not None and (
                    observed >= definition["threshold"] if definition["operator"] == ">=" else observed <= definition["threshold"]
                )
                matrix_rows.append({
                    "candidate_pct": candidate,
                    "market": market,
                    "scope": "candidate",
                    "adjacent_pair": None,
                    "threshold_id": threshold_id,
                    "observed_value": observed,
                    "operator": definition["operator"],
                    "frozen_threshold": definition["threshold"],
                    "unit": definition["unit"],
                    "margin_to_threshold": None if observed is None else observed - definition["threshold"] if definition["operator"] == ">=" else definition["threshold"] - observed,
                    "status": "PASS" if passed else "FAIL",
                })
            for pair in pairs:
                for threshold_id in adjacent_thresholds:
                    definition = threshold_definitions[threshold_id]
                    observed = _qualification_observation(
                        threshold_id, candidate=candidate, market=market, pair=pair,
                        summaries=summaries, adjacent=adjacent,
                    )
                    passed = observed is not None and (
                        observed >= definition["threshold"] if definition["operator"] == ">=" else observed <= definition["threshold"]
                    )
                    matrix_rows.append({
                        "candidate_pct": candidate,
                        "market": market,
                        "scope": "adjacent_pair",
                        "adjacent_pair": list(pair),
                        "threshold_id": threshold_id,
                        "observed_value": observed,
                        "operator": definition["operator"],
                        "frozen_threshold": definition["threshold"],
                        "unit": definition["unit"],
                        "margin_to_threshold": None if observed is None else observed - definition["threshold"] if definition["operator"] == ">=" else definition["threshold"] - observed,
                        "status": "PASS" if passed else "FAIL",
                    })

    evaluations = []
    for candidate in PRODUCTION_TOLERANCES:
        for market in ("CN", "US"):
            rows = [row for row in matrix_rows if row["candidate_pct"] == candidate and row["market"] == market]
            failures = [row["threshold_id"] for row in rows if row["status"] != "PASS"]
            evaluations.append({
                "candidate_pct": candidate,
                "market": market,
                "qualifies": not failures,
                "failed_threshold_ids": failures,
                "passed_threshold_ids": [row["threshold_id"] for row in rows if row["status"] == "PASS"],
            })
    qualified_candidates = [
        candidate for candidate in PRODUCTION_TOLERANCES
        if all(row["qualifies"] for row in evaluations if row["candidate_pct"] == candidate)
    ]
    selected = qualified_candidates[0] if qualified_candidates else None
    return {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["integrity"]["protocol_sha256"],
        "selection": "LEXICOGRAPHIC_CONSERVATIVE",
        "selection_order_pct": list(PRODUCTION_TOLERANCES),
        "matrix": matrix_rows,
        "candidate_market_evaluations": evaluations,
        "qualified_candidates": qualified_candidates,
        "lexicographic_candidate": selected,
        "status": SOL_READY_STATUS if selected is not None else SOL_FAILURE_STATUS,
        "failure_breakdown": [row for row in matrix_rows if row["status"] == "FAIL"],
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _write_capsule(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    body = deepcopy(dict(payload))
    body["integrity"] = {
        "canonical_payload_sha256": None,
        "hash_scope": "canonical JSON with integrity.canonical_payload_sha256=null",
    }
    canonical_hash = f"sha256:{hashlib.sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"
    body["integrity"]["canonical_payload_sha256"] = canonical_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"canonical_payload_sha256": canonical_hash, "file_sha256": _sha256_file(path)}


def _render_report(payload: Mapping[str, Any], capsule_file_sha256: str) -> str:
    dataset = payload["dataset"]
    qualification = payload["qualification"]
    lines = [
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->",
        "# SETUP_03 Phase 5J-v3 第二套 independent development holdout 报告",
        "",
        "> 本报告只提供 structure-only stability evidence；不构成 formal validation、Final OOS 或 production parameter freeze。",
        "",
        "## 固定身份与 hashes",
        "",
        f"- protocol: `{payload['protocol']['version']}` / `{payload['protocol']['sha256']}`",
        f"- universe: `{payload['universe']['version']}` / `{payload['universe']['manifest_sha256']}`",
        f"- symbol-list: `{payload['universe']['symbol_list_sha256']}`",
        f"- dataset: `{dataset['version']}` / `{dataset['manifest_sha256']}`",
        f"- normalized aggregate: `{dataset['aggregate_dataset_sha256']}`",
        f"- replay input: `{dataset['replay_input_manifest_sha256']}`",
        f"- capsule file SHA-256: `{capsule_file_sha256}`",
        "",
        "## 排除证明与 coverage/QC",
        "",
        f"- A1 formal 120 intersection: `{payload['universe']['exclusion_proofs']['a1_formal_120']['intersection']}`",
        f"- development v1 40 intersection: `{payload['universe']['exclusion_proofs']['development_v1_40']['intersection']}`",
        f"- valid symbols/bars: `{dataset['aggregate_symbol_count']}` / `{dataset['aggregate_valid_bar_count']}`",
        "- CN provider: `BAOSTOCK_DEVELOPMENT_QFQ` / `query_history_k_data_plus` / `frequency=d` / `adjustflag=2`",
        "- US provider: `YFINANCE_DEVELOPMENT_HISTORICAL` / adjusted historical / `repair=False`",
        "- missing dates are not filled; no interpolation, synthetic suspension bars, history splice, provider switching, OHLC mutation, or result-driven replacement.",
        "",
        "## Candidate-level structure-only results",
        "",
        "| tolerance | market | symbols | bars | platform | CONFIRMED | CONFIRMED/1000 | ENTRY_ALLOWED | max symbol share |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tolerance in TOLERANCE_SEQUENCE:
        for market in ("CN", "US", "ALL"):
            row = payload["candidate_level_results"][f"{tolerance:.1%}"][market]
            share = "null" if row["max_symbol_event_share"] is None else f"{row['max_symbol_event_share']:.2%}"
            lines.append(
                f"| {tolerance:.1%} | {market} | {row['symbol_count']} | {row['bars']} | {row['platform_detected']} | {row['CONFIRMED_EVENTS']} | {row['CONFIRMED_per_1000_bars']:.2f} | {row['ENTRY_ALLOWED']} | {share} |"
            )
    lines.extend([
        "",
        "## 3%→4% / 4%→5% frozen v3 matching",
        "",
        "| transition | market | exact retained | added | disappeared | matched | unmatched old/new | Jaccard | retention | matched drift median/P90 | buckets 0-2/3-5/6-10/11-15/>15 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for transition in ("3.0%→4.0%", "4.0%→5.0%"):
        for market in ("CN", "US", "ALL"):
            row = payload["adjacent_event_matching"][transition][market]
            drift = "null" if row["trading_day_drift_median"] is None else f"{row['trading_day_drift_median']:.2f}/{row['trading_day_drift_P90']:.2f}"
            buckets = "/".join(str(row["distance_buckets"][key]) for key in ("0-2", "3-5", "6-10", "11-15", ">15"))
            lines.append(
                f"| {transition} | {market} | {row['retained_exact']} | {row['added']} | {row['disappeared']} | {row['matched']} | {row['unmatched_previous']}/{row['unmatched_current']} | {row['exact_date_jaccard']:.2%} | {row['retention']:.2%} | {drift} | {buckets} |"
            )
    lines.extend([
        "",
        "## Qualification matrix",
        "",
        f"- `qualified_candidates`: `{qualification['qualified_candidates']}`",
        f"- `lexicographic_candidate`: `{qualification['lexicographic_candidate']}`",
        f"- status: `{qualification['status']}`",
        "",
        "| candidate | market | scope | pair | threshold | observed | frozen | margin | status |",
        "|---:|---|---|---|---|---:|---:|---:|---|",
    ])
    for row in qualification["matrix"]:
        pair = "—" if row["adjacent_pair"] is None else f"{row['adjacent_pair'][0]:.1%}→{row['adjacent_pair'][1]:.1%}"
        observed = "null" if row["observed_value"] is None else f"{row['observed_value']:.4g}"
        margin = "null" if row["margin_to_threshold"] is None else f"{row['margin_to_threshold']:.4g}"
        lines.append(
            f"| {row['candidate_pct']:.1%} | {row['market']} | {row['scope']} | {pair} | `{row['threshold_id']}` | {observed} | `{row['operator']} {row['frozen_threshold']}` | {margin} | `{row['status']}` |"
        )
    lines.extend([
        "",
        "## Parity and governance",
        "",
        f"- parity: `{payload['parity']['status']}`, cells `{payload['parity']['scope']['cells']}`, bar comparisons `{payload['parity']['scope']['bar_comparisons']}`, event comparisons `{payload['parity']['scope']['event_comparisons']}`, mismatches `{payload['parity']['LEGACY_MAIN_PARITY_MISMATCHES']}`",
        "- protocol matching is maximum-cardinality, minimum-total-trading-session-distance, deterministic lexicographic tie-break, one-to-one and non-crossing; `>40` sessions remain unmatched.",
        "- drift median/P90 use matched pairs only; exact retained, added, disappeared and unmatched identities remain fully reported.",
        "- prohibited metrics accessed: returns=False, MFE=False, MAE=False, P&L=False, winrate=False, profit_factor=False, expectancy=False; Final OOS=False; formal Phase 5K-B1=False; IBKR=False.",
        "",
        f"`{payload['status']}`",
        "",
    ])
    return "\n".join(lines)


def run_holdout_evidence(
    symbol_quotes: Mapping[str, list[Quote]],
    *,
    dataset_manifest: Mapping[str, Any],
    universe_manifest: Mapping[str, Any],
    replay_manifest: Any,
    output_dir: Path,
) -> dict[str, Any]:
    protocol = load_protocol()
    if protocol["protocol_version"] != PROTOCOL_VERSION or protocol["integrity"]["protocol_sha256"] != PROTOCOL_SHA256:
        raise ValueError("Phase 5J-v3 protocol pin changed")
    if dataset_manifest.get("coverage_status") != READY_STATUS:
        raise ValueError("holdout dataset is not ready for evidence")
    if universe_manifest.get("integrity", {}).get("manifest_sha256") != HOLDOUT_UNIVERSE_SHA256:
        raise ValueError("holdout universe pin changed")
    if len(symbol_quotes) != 40:
        raise ValueError("holdout evidence requires exactly 40 replay symbols")

    parity = run_legacy_main_parity(
        symbol_quotes,
        setup_parameters=SETUP_PARAMETERS,
        decision_parameters=DECISION_PARAMETERS,
    )
    parity_status = parity["status"]
    compact_reports = parity.pop("compact_reports")
    compact_by_tolerance = {
        tolerance: [item for item in compact_reports if item["platform_tolerance_pct"] == tolerance]
        for tolerance in TOLERANCE_SEQUENCE
    }
    sessions = build_market_session_dates(symbol_quotes)
    summaries = {
        tolerance: {
            market: _summary_for_market(compact_by_tolerance[tolerance], market)
            for market in ("CN", "US", "ALL")
        }
        for tolerance in TOLERANCE_SEQUENCE
    }
    adjacent = {
        f"{previous:.1%}→{current:.1%}": {
            market: _adjacent_summary(previous, current, compact_by_tolerance, market, sessions)
            for market in ("CN", "US", "ALL")
        }
        for previous, current in QUALIFICATION_TRANSITIONS
    }
    qualification = _build_qualification(summaries, adjacent)
    status = qualification["status"] if parity_status == "PASS" else PARITY_BLOCKER_STATUS
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows = [
        {"platform_tolerance_pct": tolerance, "market": market, **summaries[tolerance][market]}
        for tolerance in TOLERANCE_SEQUENCE
        for market in ("CN", "US", "ALL")
    ]
    adjacent_rows = [
        {"transition": transition, "market": market, **row}
        for transition, market_rows in adjacent.items()
        for market, row in market_rows.items()
    ]
    _write_csv(output_dir / "candidate_level_results.csv", candidate_rows)
    _write_csv(output_dir / "adjacent_matching_summary.csv", adjacent_rows)
    _write_csv(output_dir / "qualification_matrix.csv", qualification["matrix"])
    _write_csv(output_dir / "provider_qc_exceptions.csv", dataset_manifest.get("provider_qc_exceptions", []))

    payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "evidence_version": OUTPUT_VERSION,
        "status": status,
        "historical_pr29_v3_status": "NOT_READY_FOR_FORMAL_FREEZE_DUE_TO_EVENT_MATCHING_PROTOCOL_UNDERSPECIFICATION",
        "historical_pr29_v3_is_not_structural_rejection": True,
        "protocol": {
            "version": protocol["protocol_version"],
            "sha256": protocol["integrity"]["protocol_sha256"],
            "matching_identity": protocol["matching_identity"],
            "max_window_sessions": protocol["matching_window"]["max_distance"],
            "objective": protocol["matching_objective"],
            "order_invariants": protocol["order_invariants"],
            "deterministic_tie_break": protocol["deterministic_tie_break"],
        },
        "universe": {
            "version": universe_manifest["universe_version"],
            "manifest_sha256": universe_manifest["integrity"]["manifest_sha256"],
            "symbol_list_sha256": universe_manifest["symbol_list_sha256"],
            "counts": universe_manifest["counts"],
            "source_snapshot_identities": universe_manifest["source_snapshot_bundle"]["source_snapshot_identities"],
            "exclusion_proofs": universe_manifest["exclusion_proofs"],
        },
        "dataset": {
            "version": dataset_manifest["dataset_version"],
            "manifest_sha256": dataset_manifest["integrity"]["manifest_sha256"],
            "aggregate_dataset_sha256": dataset_manifest["aggregate_dataset_sha256"],
            "replay_input_manifest_sha256": replay_manifest.aggregate_hash,
            "coverage_status": dataset_manifest["coverage_status"],
            "aggregate_symbol_count": dataset_manifest["aggregate_symbol_count"],
            "aggregate_valid_bar_count": dataset_manifest["aggregate_valid_bar_count"],
            "market_coverage": dataset_manifest["market_coverage"],
            "provider_split": dataset_manifest["provider_split"],
            "provider_contract": dataset_manifest["provider_contract"],
            "provider_qc_exceptions": dataset_manifest.get("provider_qc_exceptions", []),
        },
        "replay": {
            "schema_version": replay_manifest.schema_version,
            "aggregate_sha256": replay_manifest.aggregate_hash,
            "total_symbol_count": replay_manifest.total_symbol_count,
            "total_bar_count": replay_manifest.total_bar_count,
            "setup_parameters": {**SETUP_PARAMETERS, "tolerance_sequence": list(TOLERANCE_SEQUENCE)},
            "decision_parameters": dict(DECISION_PARAMETERS),
            "legacy_main_baseline": "main@40a3e5f980bf82a85717748ae106847793d1469f",
        },
        "coverage_qc": {
            "symbols": dataset_manifest["symbols"],
            "market_coverage": dataset_manifest["market_coverage"],
            "provider_qc_exceptions": dataset_manifest.get("provider_qc_exceptions", []),
        },
        "candidate_level_results": {
            f"{tolerance:.1%}": {market: summaries[tolerance][market] for market in ("CN", "US", "ALL")}
            for tolerance in TOLERANCE_SEQUENCE
        },
        "adjacent_event_matching": adjacent,
        "qualification": qualification,
        "parity": parity,
        "research_boundaries": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "ibkr_used": False,
            "setup03_modified": False,
            "production_parameter_selected": False,
            "returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "p_and_l_accessed": False,
            "winrate_accessed": False,
            "profit_factor_accessed": False,
            "expectancy_accessed": False,
            "prohibited_metrics_accessed": False,
            "prohibited_metrics_statement": "No returns, MFE, MAE, P&L, win rate, profit factor, or expectancy code path was executed.",
        },
        "files": {
            "candidate_level_results_csv": "candidate_level_results.csv",
            "adjacent_matching_summary_csv": "adjacent_matching_summary.csv",
            "qualification_matrix_csv": "qualification_matrix.csv",
            "provider_qc_exceptions_csv": "provider_qc_exceptions.csv",
        },
    }
    capsule_path = output_dir / "phase5j_v3_holdout_decision_capsule.json"
    hashes = _write_capsule(capsule_path, payload)
    report_path = output_dir / "phase5j_v3_holdout_decision_report.md"
    report_path.write_text(_render_report(payload, hashes["file_sha256"]), encoding="utf-8")
    payload["integrity"] = {
        "capsule_file_sha256": hashes["file_sha256"],
        "canonical_payload_sha256": hashes["canonical_payload_sha256"],
        "report_sha256": _sha256_file(report_path),
    }
    return {
        "payload": payload,
        "capsule_path": capsule_path,
        "report_path": report_path,
        "capsule_hashes": hashes,
    }


__all__ = ["run_holdout_evidence"]
