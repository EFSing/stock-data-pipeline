"""Run the development-only SETUP_01 structural replay.

The input is the already frozen DEVELOPMENT_ONLY holdout replay input.  This
runner emits lifecycle/event diagnostics only; it deliberately has no outcome,
Decision, production Sheet, or Final OOS path.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from research.development_holdout_dataset import load_frozen_holdout
from trading.models import SetupState
from trading.setup01 import SETUP01_PROTOCOL_VERSION, SETUP01_TYPE, setup01_evaluation_to_dict
from trading.setup01_replay import (
    replay_setup01_history,
    setup01_event_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_dataset_manifest.json"
DEFAULT_INPUT = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_input.jsonl.gz"
DEFAULT_WRAPPER = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_manifest.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup01_wave2_to_wave3_v1"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8-sig")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_setup01_structural_replay(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    replay_input_path: str | Path = DEFAULT_INPUT,
    replay_wrapper_path: str | Path = DEFAULT_WRAPPER,
    output_dir: str | Path = DEFAULT_OUTPUT,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> dict[str, Any]:
    manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
        Path(manifest_path), Path(replay_input_path), Path(replay_wrapper_path)
    )
    reports = []
    errors: list[dict[str, str]] = []
    state_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    alternate_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    event_market_counts: dict[str, Counter[str]] = {}
    block_reasons: Counter[str] = Counter()

    for symbol in sorted(symbol_quotes):
        quotes = symbol_quotes[symbol]
        try:
            report = replay_setup01_history(
                quotes,
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
        except Exception as exc:
            errors.append({"symbol": symbol, "market": quotes[0].market, "error": str(exc)})
            continue
        reports.append(report)
        for day in report.days:
            state_counts[day.setup01.state.value] += 1
            primary_counts[day.setup01.primary_wave_scenario] += 1
            alternate_counts[day.setup01.alternate_wave_scenario] += 1
            if day.setup01.state is SetupState.NONE:
                block_reasons[day.setup01.reason] += 1
        for event in report.events:
            event_counts[event.event_type.value] += 1
            market_events = event_market_counts.setdefault(report.market, Counter())
            market_events[event.event_type.value] += 1

    current_candidates = []
    current_rows = []
    market_distribution: dict[str, dict[str, int]] = {}
    for report in reports:
        current = setup01_evaluation_to_dict(report.current)
        row = {
            "symbol": report.symbol,
            "market": report.market,
            **current,
        }
        current_rows.append(row)
        if report.current.state in {
            SetupState.WATCH,
            SetupState.ARMED,
        }:
            current_candidates.append(row)
        market = market_distribution.setdefault(
            report.market,
            {state.value: 0 for state in (SetupState.NONE, SetupState.WATCH, SetupState.ARMED, SetupState.CONFIRMED, SetupState.FAILED)},
        )
        market[report.current.state.value] += 1

    output_path = Path(output_dir)
    events = setup01_event_rows(reports)
    document: dict[str, Any] = {
        "setup_type": SETUP01_TYPE,
        "protocol_version": SETUP01_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_STRUCTURAL_REPLAY",
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_input_aggregate_hash": replay_manifest.aggregate_hash,
        "daily_swing_lookback": daily_swing_lookback,
        "weekly_swing_lookback": weekly_swing_lookback,
        "symbols_requested": len(symbol_quotes),
        "evaluated": len(reports),
        "errors": len(errors),
        "total_replay_days": sum(len(report.days) for report in reports),
        "lifecycle_events": len(events),
        "confirmed_events": event_counts[SetupState.CONFIRMED.value],
        "failed_events": event_counts[SetupState.FAILED.value],
        "state_day_counts": dict(sorted(state_counts.items())),
        "primary_wave_scenario_counts": dict(sorted(primary_counts.items())),
        "alternate_wave_scenario_counts": dict(sorted(alternate_counts.items())),
        "event_type_counts": dict(sorted(event_counts.items())),
        "event_market_distribution": {
            market: dict(sorted(counts.items()))
            for market, counts in sorted(event_market_counts.items())
        },
        "market_distribution": market_distribution,
        "unknown_block_reasons": [
            {"reason": reason, "count": count}
            for reason, count in block_reasons.most_common()
        ],
        "current_setup01_candidates": current_candidates,
        "current_rows": current_rows,
        "errors_detail": errors,
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "returns_accessed": False,
            "forward_returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "decision_accessed": False,
            "entry_allowed_emitted": False,
            "sheets_written": False,
            "setup03_reopened": False,
            "setup02_started": False,
        },
        "status": "SUCCESS" if not errors else "PARTIAL_DATA_QUALITY",
    }
    _write_json(output_path / "setup01_structural_replay_report.json", document)
    _write_csv(output_path / "setup01_structural_replay_current.csv", current_rows)
    _write_csv(output_path / "setup01_structural_replay_events.csv", events)
    _write_csv(output_path / "setup01_structural_replay_errors.csv", errors)
    print("SETUP01_STRUCTURAL_REPLAY_SUMMARY " + json.dumps({
        key: value for key, value in document.items()
        if key not in {"current_setup01_candidates", "current_rows", "errors_detail"}
    }, ensure_ascii=False))
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--replay-input", default=str(DEFAULT_INPUT))
    parser.add_argument("--replay-wrapper", default=str(DEFAULT_WRAPPER))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--daily-lookback", type=int, default=5)
    parser.add_argument("--weekly-lookback", type=int, default=5)
    args = parser.parse_args()
    document = run_setup01_structural_replay(
        manifest_path=args.manifest,
        replay_input_path=args.replay_input,
        replay_wrapper_path=args.replay_wrapper,
        output_dir=args.output_dir,
        daily_swing_lookback=args.daily_lookback,
        weekly_swing_lookback=args.weekly_lookback,
    )
    raise SystemExit(1 if document["errors"] else 0)


if __name__ == "__main__":
    main()
