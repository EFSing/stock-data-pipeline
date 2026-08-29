"""Run the frozen Phase 5J-v4 lifecycle attribution workflow."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.development_holdout_dataset import (
    DATASET_MANIFEST_PATH,
    FROZEN_INPUT_PATH,
    HOLDOUT_ARTIFACT_DIR,
    REPLAY_MANIFEST_PATH,
    load_frozen_holdout,
)
from research.phase5j_v4_evidence import (
    adjacent_exact_metrics,
    aggregate_counterfactuals,
    anchor_divergence_summary,
    candidate_summaries,
    causal_consistency,
    cascade_summary,
    evidence_state_and_recommendation,
    historical_symptom_concordance,
    load_setup_module_from_source,
    origin_main_parity_for_symbol,
    render_chinese_report,
    root_cause_summary,
    sha256_file,
    write_capsule,
)
from research.phase5j_v4_lifecycle_attribution import (
    ADJACENT_PAIRS,
    ATTRIBUTION_SCHEMA_VERSION,
    TOLERANCES,
    build_symbol_trace,
    classify_lineage,
    counterfactual_summary,
    find_divergence_episodes,
    summarize_propagation,
    write_csv,
)
from research.phase5j_v4_protocol import canonical_json, load_protocol


DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "phase5j_v4_lifecycle_attribution"
DEFAULT_TRACKED_DIR = PROJECT_ROOT / "research" / "development"
HISTORICAL_CAPSULE_PATH = DEFAULT_TRACKED_DIR / "development_strategy_decision_capsule_v2.json"

PRIOR_FROZEN_PATHS = (
    "research/setup03_phase5j_v3_event_matching_protocol.json",
    "research/development_holdout/universe_manifest.json",
    "research/development_holdout/dataset_manifest.json",
    "research/development_holdout/replay_manifest.json",
    "research/development/development_holdout_decision_capsule_v1.json",
    "research/development/development_holdout_decision_capsule_v1.md",
    "research/development/development_strategy_decision_capsule_v2.json",
    "research/development/development_strategy_decision_capsule_v2.md",
    "research/development/development_strategy_decision_capsule_v3.json",
    "research/development/development_strategy_decision_capsule_v3.md",
)


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT)


def _relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _prior_frozen_parity(base_ref: str) -> dict[str, Any]:
    rows = []
    for relative in PRIOR_FROZEN_PATHS:
        current = (PROJECT_ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        baseline = _git("show", f"{base_ref}:{relative}").replace(b"\r\n", b"\n")
        current_hash = f"sha256:{hashlib.sha256(current).hexdigest()}"
        baseline_hash = f"sha256:{hashlib.sha256(baseline).hexdigest()}"
        normalized_identical = current == baseline
        rows.append({
            "path": relative,
            "current_sha256": current_hash,
            "base_sha256": baseline_hash,
            "identical": normalized_identical,
            "comparison": "SHA-256 of Git-normalized LF bytes; stable across Windows and Linux checkouts",
        })
    return {"rows": rows, "mismatches": sum(not row["identical"] for row in rows)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run frozen Phase 5J-v4 lifecycle attribution")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--tracked-dir", type=Path, default=DEFAULT_TRACKED_DIR)
    parser.add_argument("--base-ref", default="origin/main")
    return parser


def main() -> int:
    args = _parser().parse_args()
    protocol = load_protocol()
    manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
        DATASET_MANIFEST_PATH, FROZEN_INPUT_PATH, REPLAY_MANIFEST_PATH
    )
    if (
        manifest["integrity"]["manifest_sha256"]
        != protocol["evidence_scope"]["exact_causal_replay"]["dataset_manifest_sha256"]
        or replay_manifest.aggregate_hash
        != protocol["evidence_scope"]["exact_causal_replay"]["replay_aggregate_sha256"]
    ):
        raise ValueError("Phase 5J-v4 exact holdout binding failed")

    base_sha = _git("rev-parse", args.base_ref).decode().strip()
    baseline_source = _git("show", f"{args.base_ref}:trading/setup.py").decode("utf-8")
    baseline_setup = load_setup_module_from_source(baseline_source)
    prior_frozen = _prior_frozen_parity(args.base_ref)
    if prior_frozen["mismatches"]:
        raise ValueError("prior frozen tracked artifact changed relative to current main")

    historical_expected = next(
        item["file_sha256"]
        for item in protocol["evidence_scope"]["historical_structure_symptom_evidence"]["allowed_files"]
        if item["path"].endswith("development_strategy_decision_capsule_v2.json")
    )
    if sha256_file(HISTORICAL_CAPSULE_PATH) != historical_expected:
        raise ValueError("tracked PR #29 symptom capsule hash changed")
    historical_capsule = json.loads(HISTORICAL_CAPSULE_PATH.read_text(encoding="utf-8"))

    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    args.tracked_dir.mkdir(parents=True, exist_ok=True)
    trace_path = args.artifact_dir / "phase5j_v4_lifecycle_trace.jsonl.gz"
    all_lifecycles: list[dict[str, Any]] = []
    all_episodes: list[dict[str, Any]] = []
    all_lineage: list[dict[str, Any]] = []
    all_propagation: list[dict[str, Any]] = []
    all_counterfactuals: list[dict[str, Any]] = []
    parity = {"bar_comparisons": 0, "event_comparisons": 0, "setup_mismatches": 0, "event_mismatches": 0}

    with trace_path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as trace_handle:
            for symbol in sorted(symbol_quotes):
                quotes = symbol_quotes[symbol]
                traces = {tolerance: build_symbol_trace(quotes, tolerance) for tolerance in TOLERANCES}
                for tolerance in TOLERANCES:
                    trace = traces[tolerance]
                    all_lifecycles.extend(trace["lifecycles"])
                    for row in trace["rows"]:
                        trace_handle.write(canonical_json(row).encode("utf-8") + b"\n")
                    cell_parity = origin_main_parity_for_symbol(
                        quotes, tolerance, trace["rows"], baseline_setup
                    )
                    for key in parity:
                        parity[key] += cell_parity[key]
                for lower, upper in ADJACENT_PAIRS:
                    episodes = find_divergence_episodes(traces[lower]["rows"], traces[upper]["rows"])
                    first_bar = episodes[0]["first_divergence_bar"] if episodes else None
                    lineage = classify_lineage(
                        traces[lower]["lifecycles"],
                        traces[upper]["lifecycles"],
                        first_divergence_bar=first_bar,
                    )
                    for row in lineage:
                        row["adjacent_lower_tolerance"] = lower
                        row["adjacent_upper_tolerance"] = upper
                    propagation = summarize_propagation(episodes, lineage)
                    counterfactuals = counterfactual_summary(lineage, propagation)
                    for row in counterfactuals:
                        row.update({
                            "market": quotes[0].market,
                            "symbol": symbol,
                            "lower_tolerance": lower,
                            "upper_tolerance": upper,
                        })
                    all_episodes.extend(episodes)
                    all_lineage.extend(lineage)
                    all_propagation.extend(propagation)
                    all_counterfactuals.extend(counterfactuals)

    parity["status"] = "PASS" if parity["setup_mismatches"] == parity["event_mismatches"] == 0 else "MISMATCH"
    parity["base_ref"] = args.base_ref
    parity["base_sha"] = base_sha
    parity["cells"] = len(symbol_quotes) * len(TOLERANCES)
    parity["production_setup_output_unchanged"] = parity["setup_mismatches"] == 0
    parity["confirmed_failed_event_output_unchanged"] = parity["event_mismatches"] == 0
    if parity["status"] != "PASS":
        raise ValueError("production output parity mismatch")

    bars_by_market = {
        market: sum(len(quotes) for quotes in symbol_quotes.values() if quotes[0].market == market)
        for market in ("CN", "US")
    }
    symbols_by_market = {
        market: sorted(symbol for symbol, quotes in symbol_quotes.items() if quotes[0].market == market)
        for market in ("CN", "US")
    }
    candidates = candidate_summaries(all_lifecycles, bars_by_market, symbols_by_market)
    adjacent = adjacent_exact_metrics(candidates)
    roots = root_cause_summary(all_episodes)
    cascades = cascade_summary(all_propagation, all_lineage)
    anchors = anchor_divergence_summary(all_lineage)
    counterfactuals = aggregate_counterfactuals(all_counterfactuals)
    concordance = historical_symptom_concordance(candidates, adjacent, historical_capsule)
    decision_state = evidence_state_and_recommendation(roots, cascades)
    consistency = causal_consistency(roots)

    trace_hash = sha256_file(trace_path)
    output_paths = {
        "per_symbol_lifecycle_attribution": args.tracked_dir / "phase5j_v4_per_symbol_lifecycle_attribution.csv",
        "root_cause_summary": args.tracked_dir / "phase5j_v4_root_cause_summary.csv",
        "cascade_table": args.tracked_dir / "phase5j_v4_cascade_table.csv",
        "anchor_divergence_summary": args.tracked_dir / "phase5j_v4_anchor_divergence_summary.csv",
        "counterfactual_summary": args.tracked_dir / "phase5j_v4_counterfactual_summary.csv",
        "historical_symptom_concordance": args.tracked_dir / "phase5j_v4_historical_symptom_concordance.csv",
    }
    output_hashes = {
        "lifecycle_trace_gzip": {"path": _relative_path(trace_path), "sha256": trace_hash},
        "per_symbol_lifecycle_attribution": {"path": _relative_path(output_paths["per_symbol_lifecycle_attribution"]), "sha256": write_csv(output_paths["per_symbol_lifecycle_attribution"], all_lineage)},
        "root_cause_summary": {"path": _relative_path(output_paths["root_cause_summary"]), "sha256": write_csv(output_paths["root_cause_summary"], roots)},
        "cascade_table": {"path": _relative_path(output_paths["cascade_table"]), "sha256": write_csv(output_paths["cascade_table"], cascades)},
        "anchor_divergence_summary": {"path": _relative_path(output_paths["anchor_divergence_summary"]), "sha256": write_csv(output_paths["anchor_divergence_summary"], anchors)},
        "counterfactual_summary": {"path": _relative_path(output_paths["counterfactual_summary"]), "sha256": write_csv(output_paths["counterfactual_summary"], counterfactuals)},
        "historical_symptom_concordance": {"path": _relative_path(output_paths["historical_symptom_concordance"]), "sha256": write_csv(output_paths["historical_symptom_concordance"], concordance)},
    }
    graph_path = args.tracked_dir / "phase5j_v4_cascade_graph.json"
    graph_payload = {
        "schema_version": "setup03-phase5j-v4-cascade-graph-v1",
        "nodes": all_episodes,
        "edges": all_propagation,
    }
    graph_path.write_text(json.dumps(graph_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    output_hashes["cascade_graph"] = {"path": _relative_path(graph_path), "sha256": sha256_file(graph_path)}

    v3_capsule = json.loads((DEFAULT_TRACKED_DIR / "development_holdout_decision_capsule_v1.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": ATTRIBUTION_SCHEMA_VERSION,
        "status": "PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION",
        "identity": {
            "protocol_version": protocol["protocol_version"],
            "protocol_sha256": protocol["integrity"]["protocol_sha256"],
            "dataset_version": manifest["dataset_version"],
            "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
            "normalized_aggregate_sha256": manifest["aggregate_dataset_sha256"],
            "replay_aggregate_sha256": replay_manifest.aggregate_hash,
            "symbol_count": replay_manifest.total_symbol_count,
            "bar_count": replay_manifest.total_bar_count,
        },
        "boundaries": {
            "development_only": True,
            "single_frozen_dataset": True,
            "historical_pr29_role": "HISTORICAL_STRUCTURE_SYMPTOM_EVIDENCE",
            "historical_pr29_is_causal_replication": False,
            "early_development_v1_refetched": False,
            "third_development_dataset_created": False,
            "a1_formal_ohlcv_accessed": False,
            "final_oos_accessed": False,
            "forward_returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "p_and_l_accessed": False,
            "winrate_accessed": False,
            "profit_factor_accessed": False,
            "expectancy_accessed": False,
            "production_setup03_semantics_modified": False,
            "read_only_setup_instrumentation_added": True,
            "phase5j_v3_matching_modified": False,
            "phase5j_v3_qualification_modified": False,
        },
        "parity": {
            **parity,
            "second_holdout_unchanged": replay_manifest.total_symbol_count == 40 and replay_manifest.total_bar_count == 86305 and replay_manifest.aggregate_hash == "sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2",
            "prior_frozen_artifact_hashes": prior_frozen,
            "phase5j_v3_qualification_unchanged": v3_capsule["qualification"]["qualified_candidates"] == [] and v3_capsule["qualification"]["lexicographic_candidate"] is None and v3_capsule["qualification"]["status"] == "SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION",
            "final_oos_untouched": True,
        },
        "trace_conservation": {
            "tolerance_count": len(TOLERANCES),
            "expected_trace_rows": replay_manifest.total_bar_count * len(TOLERANCES),
            "actual_trace_rows": parity["bar_comparisons"],
            "lifecycle_count": len(all_lifecycles),
            "first_divergence_episode_count": len(all_episodes),
            "lineage_row_count": len(all_lineage),
        },
        "candidate_structure": candidates,
        "adjacent_exact_metrics": adjacent,
        "first_divergences": all_episodes,
        "lineage": all_lineage,
        "root_cause_summary": roots,
        "cascade_summary": cascades,
        "anchor_divergence_summary": anchors,
        "counterfactual_summary": counterfactuals,
        "historical_symptom_concordance": concordance,
        "causal_consistency": consistency,
        "decision_state": decision_state,
        "artifact_hashes": output_hashes,
    }
    capsule_path = args.tracked_dir / "phase5j_v4_lifecycle_attribution_capsule_v1.json"
    capsule_hashes = write_capsule(capsule_path, payload)
    report_path = args.tracked_dir / "phase5j_v4_lifecycle_attribution_report_v1.md"
    report_path.write_text(render_chinese_report(payload, capsule_hashes["file_sha256"]), encoding="utf-8")
    hash_manifest = {
        "schema_version": "setup03-phase5j-v4-artifact-hashes-v1",
        "protocol_sha256": protocol["integrity"]["protocol_sha256"],
        "capsule": {"path": _relative_path(capsule_path), **capsule_hashes},
        "report": {"path": _relative_path(report_path), "sha256": sha256_file(report_path)},
        "artifacts": output_hashes,
    }
    hash_manifest_path = args.tracked_dir / "phase5j_v4_artifact_hashes.json"
    hash_manifest_path.write_text(json.dumps(hash_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": payload["status"],
        "base_sha": base_sha,
        "protocol_sha256": protocol["integrity"]["protocol_sha256"],
        "capsule_file_sha256": capsule_hashes["file_sha256"],
        "trace_sha256": trace_hash,
        "parity": parity,
        "decision_state": decision_state,
        "cascade_summary": [row for row in cascades if row["market"] == "POOLED"],
        "historical_symptom_concordance": concordance,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
