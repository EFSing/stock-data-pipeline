"""Run the DEVELOPMENT_EXPOSED SETUP_02 structural replay.

The runner reloads the existing frozen 40-symbol development dataset and
emits only structural lifecycle statistics.  It has no Decision, execution,
outcome, production Sheet, or OOS path.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from research.development_dataset import DATASET_MANIFEST_PATH, load_frozen_dataset
from trading.models import SetupState
from trading.setup02 import (
    SETUP02_PROTOCOL_VERSION,
    SETUP02_TYPE,
    setup02_evaluation_to_dict,
)
from trading.setup02_replay import (
    Setup02ReplayReport,
    replay_setup02_history,
    setup02_event_identity,
    setup02_event_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = DATASET_MANIFEST_PATH
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup02_wave3_continuation_v1"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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


def _state_count_row(report: Setup02ReplayReport) -> dict[str, Any]:
    return {
        "symbol": report.symbol,
        "market": report.market,
        "replay_days": len(report.days),
        **{
            f"{state.value}_days": report.state_day_counts.get(state, 0)
            for state in (
                SetupState.NONE,
                SetupState.WATCH,
                SetupState.ARMED,
                SetupState.CONFIRMED,
                SetupState.FAILED,
            )
        },
        "CONFIRMED_events": len(report.confirmed_event_dates),
        "FAILED_events": len(report.failed_event_dates),
        "current_state": report.current.state.value,
        "current_as_of_date": report.current.as_of_date.isoformat(),
        "current_reason": report.current.reason,
    }


def _identity_audit(reports: list[Setup02ReplayReport]) -> dict[str, Any]:
    identities: list[str] = []
    mismatches: list[dict[str, str]] = []
    for report in reports:
        for event in report.events:
            identities.append(event.event_identity)
            expected = setup02_event_identity(
                event.symbol,
                event.trade_date,
                event.event_type,
                event.setup02.lifecycle_index,
            )
            if expected != event.event_identity:
                mismatches.append(
                    {
                        "event_identity": event.event_identity,
                        "expected_identity": expected,
                    }
                )
    duplicate_count = len(identities) - len(set(identities))
    return {
        "event_count": len(identities),
        "unique_event_identity_count": len(set(identities)),
        "duplicate_identity_count": duplicate_count,
        "identity_mismatch_count": len(mismatches),
        "identity_mismatches": mismatches,
        "exactly_once": duplicate_count == 0 and not mismatches,
    }


def run_setup02_structural_replay(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    output_dir: str | Path = DEFAULT_OUTPUT,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> dict[str, Any]:
    manifest, symbol_quotes = load_frozen_dataset(Path(manifest_path))
    reports: list[Setup02ReplayReport] = []
    errors: list[dict[str, str]] = []
    state_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    alternate_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    event_market_counts: dict[str, Counter[str]] = {}
    failure_reasons: Counter[str] = Counter()
    block_reasons: Counter[str] = Counter()
    fib_regions: Counter[str] = Counter()

    for symbol in sorted(symbol_quotes):
        quotes = symbol_quotes[symbol]
        try:
            report = replay_setup02_history(
                quotes,
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
        except Exception as exc:
            errors.append(
                {"symbol": symbol, "market": quotes[0].market, "error": str(exc)}
            )
            continue
        reports.append(report)
        for day in report.days:
            snapshot = day.setup02
            state_counts[snapshot.state.value] += 1
            primary_counts[snapshot.primary_wave_scenario] += 1
            alternate_counts[snapshot.alternate_wave_scenario] += 1
            if snapshot.state is SetupState.NONE:
                block_reasons[snapshot.reason] += 1
            if snapshot.fib_retracement_region is not None:
                fib_regions[snapshot.fib_retracement_region] += 1
        for event in report.events:
            event_counts[event.event_type.value] += 1
            market_events = event_market_counts.setdefault(report.market, Counter())
            market_events[event.event_type.value] += 1
            if event.event_type is SetupState.FAILED:
                failure_reasons[event.setup02.reason] += 1

    current_candidates: list[dict[str, Any]] = []
    current_rows: list[dict[str, Any]] = []
    per_symbol_rows = [_state_count_row(report) for report in reports]
    for report in reports:
        current = setup02_evaluation_to_dict(report.current)
        row = {"symbol": report.symbol, "market": report.market, **current}
        current_rows.append(row)
        if report.current.state in {SetupState.WATCH, SetupState.ARMED}:
            current_candidates.append(row)

    output_path = Path(output_dir)
    events = setup02_event_rows(reports)
    identity_audit = _identity_audit(reports)
    document: dict[str, Any] = {
        "setup_type": SETUP02_TYPE,
        "protocol_version": SETUP02_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_STRUCTURAL_REPLAY",
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_input_aggregate_hash": manifest.get("replay_input_manifest_sha256"),
        "daily_swing_lookback": daily_swing_lookback,
        "weekly_swing_lookback": weekly_swing_lookback,
        "symbols_requested": len(symbol_quotes),
        "evaluated": len(reports),
        "errors": len(errors),
        "total_replay_days": sum(len(report.days) for report in reports),
        "state_day_counts": dict(sorted(state_counts.items())),
        "confirmed_events": event_counts[SetupState.CONFIRMED.value],
        "failed_events": event_counts[SetupState.FAILED.value],
        "event_type_counts": dict(sorted(event_counts.items())),
        "event_market_distribution": {
            market: dict(sorted(counts.items()))
            for market, counts in sorted(event_market_counts.items())
        },
        "primary_wave_scenario_counts": dict(sorted(primary_counts.items())),
        "alternate_wave_scenario_counts": dict(sorted(alternate_counts.items())),
        "per_symbol_distribution": per_symbol_rows,
        "current_setup02_candidates": current_candidates,
        "fib_retracement_region_counts": dict(sorted(fib_regions.items())),
        "failure_reason_counts": [
            {"reason": reason, "count": count}
            for reason, count in failure_reasons.most_common()
        ],
        "block_reason_counts": [
            {"reason": reason, "count": count}
            for reason, count in block_reasons.most_common()
        ],
        "identity_audit": identity_audit,
        "current_rows": current_rows,
        "errors_detail": errors,
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "decision_accessed": False,
            "production_execution": False,
            "sheets_written": False,
            "outcome_accessed": False,
            "setup01_modified": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS" if not errors else "PARTIAL_DATA_QUALITY",
    }
    _write_json(output_path / "setup02_structural_replay_report.json", document)
    _write_csv(output_path / "setup02_structural_replay_current.csv", current_rows)
    _write_csv(output_path / "setup02_structural_replay_symbols.csv", per_symbol_rows)
    _write_csv(output_path / "setup02_structural_replay_events.csv", events)
    _write_csv(output_path / "setup02_structural_replay_errors.csv", errors)
    print(
        "SETUP02_STRUCTURAL_REPLAY_SUMMARY "
        + json.dumps(
            {
                key: value
                for key, value in document.items()
                if key not in {"current_setup02_candidates", "current_rows", "errors_detail"}
            },
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--daily-lookback", type=int, default=5)
    parser.add_argument("--weekly-lookback", type=int, default=5)
    args = parser.parse_args()
    document = run_setup02_structural_replay(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        daily_swing_lookback=args.daily_lookback,
        weekly_swing_lookback=args.weekly_lookback,
    )
    raise SystemExit(1 if document["errors"] else 0)


if __name__ == "__main__":
    main()
