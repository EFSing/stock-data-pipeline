"""Acquire yfinance development data and build the stability evidence pack.

This entry point never calls IBKR, Tencent, Sina, Google Sheets, or final OOS.
The first step is always loading the already frozen development universe.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.development_dataset import (
    DEVELOPMENT_ARTIFACT_DIR,
    DEVELOPMENT_DATASET_VERSION,
    acquire_and_freeze_dataset,
    audit_historical_yfinance_ordering,
    load_frozen_dataset,
)
from research.development_stability import (
    ARM_PROXIMITY_PCT,
    DECISION_PARAMETERS,
    PLATFORM_WINDOW,
    RISK_CAPITAL,
    SETUP_SWING_LOOKBACK,
    run_development_stability,
    run_precompute_replay_parity,
)
from research.development_universe import (
    DEVELOPMENT_UNIVERSE_PATH,
    write_development_universe_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("freeze-universe", "acquire-and-diagnose"),
        default="acquire-and-diagnose",
    )
    parser.add_argument("--output-dir", type=Path, default=DEVELOPMENT_ARTIFACT_DIR)
    parser.add_argument("--reuse-frozen", action="store_true", help="run diagnostics from the existing frozen dataset")
    args = parser.parse_args(argv)

    universe = write_development_universe_manifest(DEVELOPMENT_UNIVERSE_PATH)
    print(json.dumps({
        "universe_version": universe["universe_version"],
        "universe_manifest_sha256": universe["integrity"]["manifest_sha256"],
        "symbol_list_sha256": universe["symbol_list_sha256"],
        "a1_intersection": universe["a1_exclusion_proof"]["intersection"],
    }, ensure_ascii=False))
    if args.mode == "freeze-universe":
        return 0

    ordering_diagnostic = audit_historical_yfinance_ordering(output_dir=args.output_dir)
    if args.reuse_frozen:
        dataset, symbol_quotes = load_frozen_dataset(args.output_dir / "development_dataset_manifest.json")
    else:
        dataset, symbol_quotes = acquire_and_freeze_dataset(
            DEVELOPMENT_UNIVERSE_PATH,
            args.output_dir,
            ordering_diagnostic=ordering_diagnostic,
        )
    if not symbol_quotes:
        raise RuntimeError("DEVELOPMENT_DATA_SOURCE_COVERAGE_BLOCKER: no valid yfinance symbols")
    setup_parameters = {
        "swing_lookback": SETUP_SWING_LOOKBACK,
        "platform_window": PLATFORM_WINDOW,
        "platform_tolerance_pct": 0.03,
        "arm_proximity_pct": ARM_PROXIMITY_PCT,
    }
    parity = run_precompute_replay_parity(
        symbol_quotes,
        output_dir=args.output_dir,
        setup_parameters=setup_parameters,
        decision_parameters=DECISION_PARAMETERS,
        risk_capital=RISK_CAPITAL,
    )
    evidence = run_development_stability(
        symbol_quotes,
        output_dir=args.output_dir,
        dataset_manifest=dataset,
        setup_parameters=setup_parameters,
        precompute_swings=bool(parity["optimization_enabled"]),
        precompute_parity=parity,
    )
    print(json.dumps({
        "dataset_version": DEVELOPMENT_DATASET_VERSION,
        "dataset_manifest_sha256": dataset["integrity"]["manifest_sha256"],
        "aggregate_dataset_sha256": dataset["aggregate_dataset_sha256"],
        "provider_split": dataset["provider_split"],
        "ohlc_diagnostic": ordering_diagnostic,
        "precompute_parity": {
            "status": parity["status"],
            "total_mismatch_count": parity["total_mismatch_count"],
            "json_path": parity["json_path"],
            "json_sha256": parity["json_sha256"],
        },
        "evidence_manifest": str(evidence["evidence_manifest_path"]),
        "status": evidence["evidence_manifest"]["status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
