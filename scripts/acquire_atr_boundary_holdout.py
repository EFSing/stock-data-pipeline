"""Acquire the frozen ATR boundary clean holdout without running SETUP_03."""
from __future__ import annotations

import json

from research.atr_boundary_dataset import acquire_and_freeze


def main() -> int:
    def progress(row: dict) -> None:
        print(json.dumps({
            "market": row["market"],
            "canonical_symbol": row["canonical_symbol"],
            "qc_status": row["qc_status"],
            "bar_count": row["bar_count"],
        }, ensure_ascii=False, sort_keys=True), flush=True)

    manifest = acquire_and_freeze(progress=progress)
    print(json.dumps({
        "coverage_status": manifest["coverage_status"],
        "dataset_version": manifest["dataset_version"],
        "aggregate_symbol_count": manifest["aggregate_symbol_count"],
        "aggregate_valid_bar_count": manifest["aggregate_valid_bar_count"],
        "provider_qc_exception_count": len(manifest["provider_qc_exceptions"]),
        "dataset_manifest_path": "research/atr_boundary_clean_holdout/dataset_manifest.json",
        "replay_manifest_path": "research/atr_boundary_clean_holdout/replay_manifest.json",
        "frozen_input_path": "artifacts/atr_boundary_clean_holdout/replay_input.jsonl.gz",
    }, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["coverage_status"] == "READY_FOR_ATR_BOUNDARY_STRUCTURE_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
