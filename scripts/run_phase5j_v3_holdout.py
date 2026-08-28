"""Acquire or reuse the frozen Phase 5J-v3 development holdout and audit it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.development_holdout_dataset import (
    BLOCKER_STATUS,
    DATASET_MANIFEST_PATH,
    FROZEN_INPUT_PATH,
    HOLDOUT_ARTIFACT_DIR,
    READY_STATUS,
    acquire_and_freeze_holdout,
    load_frozen_holdout,
)
from research.development_holdout_evidence import run_holdout_evidence
from research.development_holdout_universe import load_holdout_universe_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-frozen",
        action="store_true",
        help="read the already frozen provider output instead of fetching again",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HOLDOUT_ARTIFACT_DIR,
        help="artifact directory; defaults to the ignored phase5j_v3 holdout directory",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    universe = load_holdout_universe_manifest()
    if args.reuse_frozen:
        manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
            args.output_dir / DATASET_MANIFEST_PATH.name,
            args.output_dir / FROZEN_INPUT_PATH.name,
        )
    else:
        manifest, symbol_quotes = acquire_and_freeze_holdout(output_dir=args.output_dir)
        if manifest["coverage_status"] != READY_STATUS:
            print(json.dumps({
                "status": BLOCKER_STATUS,
                "dataset_status": manifest["coverage_status"],
                "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
                "provider_qc_exceptions": manifest["provider_qc_exceptions"],
            }, ensure_ascii=False, indent=2))
            return 2
        _, _, replay_manifest = load_frozen_holdout(
            args.output_dir / DATASET_MANIFEST_PATH.name,
            args.output_dir / FROZEN_INPUT_PATH.name,
        )

    if manifest["coverage_status"] != READY_STATUS:
        print(json.dumps({
            "status": BLOCKER_STATUS,
            "dataset_status": manifest["coverage_status"],
            "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
            "provider_qc_exceptions": manifest["provider_qc_exceptions"],
        }, ensure_ascii=False, indent=2))
        return 2

    result = run_holdout_evidence(
        symbol_quotes,
        dataset_manifest=manifest,
        universe_manifest=universe,
        replay_manifest=replay_manifest,
        output_dir=args.output_dir,
    )
    payload = result["payload"]
    print(json.dumps({
        "status": payload["status"],
        "dataset_manifest_sha256": payload["dataset"]["manifest_sha256"],
        "aggregate_dataset_sha256": payload["dataset"]["aggregate_dataset_sha256"],
        "replay_input_manifest_sha256": payload["dataset"]["replay_input_manifest_sha256"],
        "qualified_candidates": payload["qualification"]["qualified_candidates"],
        "lexicographic_candidate": payload["qualification"]["lexicographic_candidate"],
        "report": str(result["report_path"]),
        "capsule": str(result["capsule_path"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
