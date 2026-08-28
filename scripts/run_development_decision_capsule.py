"""Run the true main-baseline parity audit and write the decision capsule.

This command consumes only the already-frozen development replay input.  It
never calls a provider, changes the dataset/universe, or enters formal
validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.development_decision_capsule import (
    DECISION_PARAMETERS,
    SETUP_PARAMETERS,
    _build_statistics,
    build_capsule_payload,
    load_frozen_capsule_inputs,
    render_capsule_report,
    run_legacy_main_parity,
    write_capsule,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=PROJECT_ROOT / "artifacts/development_strategy_stability_v2/development_dataset_manifest.json",
    )
    parser.add_argument(
        "--universe-manifest",
        type=Path,
        default=PROJECT_ROOT / "research/development/universe_manifest.json",
    )
    parser.add_argument(
        "--replay-input",
        type=Path,
        default=PROJECT_ROOT / "artifacts/development_strategy_stability_v2/development_replay_input.jsonl.gz",
    )
    parser.add_argument(
        "--capsule",
        type=Path,
        default=PROJECT_ROOT / "research/development/development_strategy_decision_capsule_v2.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "research/development/development_strategy_decision_capsule_v2.md",
    )
    args = parser.parse_args(argv)

    dataset_manifest, universe_manifest, symbol_quotes, replay_manifest = load_frozen_capsule_inputs(
        dataset_manifest_path=args.dataset_manifest,
        universe_manifest_path=args.universe_manifest,
        replay_input_path=args.replay_input,
    )
    parity = run_legacy_main_parity(
        symbol_quotes,
        setup_parameters=SETUP_PARAMETERS,
        decision_parameters=DECISION_PARAMETERS,
    )
    if parity["LEGACY_MAIN_PARITY_MISMATCHES"]:
        print(json.dumps({
            "status": "BLOCKER_REPLAY_SEMANTIC_DRIFT",
            "LEGACY_MAIN_PARITY_MISMATCHES": parity["LEGACY_MAIN_PARITY_MISMATCHES"],
        }, ensure_ascii=False))
        return 2

    compact_reports = parity.pop("compact_reports")
    statistics = _build_statistics(compact_reports)
    payload = build_capsule_payload(
        dataset_manifest=dataset_manifest,
        universe_manifest=universe_manifest,
        replay_manifest=replay_manifest,
        parity=parity,
        statistics=statistics,
    )
    hashes = write_capsule(args.capsule, payload)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        render_capsule_report(
            payload,
            capsule_path=args.capsule,
            capsule_file_sha256=hashes["file_sha256"],
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": payload["status"],
        "capsule": str(args.capsule),
        "capsule_file_sha256": hashes["file_sha256"],
        "capsule_canonical_payload_sha256": hashes["canonical_payload_sha256"],
        "report": str(args.report),
        "legacy_main_parity": {
            "cells": parity["scope"]["cells"],
            "bar_comparisons": parity["scope"]["bar_comparisons"],
            "event_comparisons": parity["scope"]["event_comparisons"],
            "mismatches": parity["LEGACY_MAIN_PARITY_MISMATCHES"],
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
