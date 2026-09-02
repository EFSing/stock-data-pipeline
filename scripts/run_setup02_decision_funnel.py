"""Run the DEVELOPMENT_EXPOSED SETUP_02 Decision/Risk funnel."""
from __future__ import annotations

import argparse
import ast
import csv
import json
from datetime import date
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.development_dataset import DATASET_MANIFEST_PATH, load_frozen_dataset
from research.setup02_decision_funnel import build_setup02_decision_funnel
from trading.models import SetupState, SwingKind, SwingPoint
from trading.setup02 import Setup02Evaluation
from trading.setup02_replay import Setup02ReplayEvent, replay_setup02_history


DEFAULT_MANIFEST = DATASET_MANIFEST_PATH
DEFAULT_INPUT = PROJECT_ROOT / "artifacts" / "development_strategy_stability_v2" / "development_replay_input.jsonl.gz"
DEFAULT_STRUCTURAL_EVENTS = PROJECT_ROOT / "artifacts" / "setup02_wave3_continuation_v1" / "setup02_structural_replay_events.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup02_decision_risk_v1"


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _optional_bool(value: str) -> bool:
    return str(value).strip().lower() == "true"


def _swing(value: str) -> SwingPoint | None:
    if not value:
        return None
    payload = ast.literal_eval(value)
    return SwingPoint(
        kind=SwingKind(str(payload["kind"])),
        price=float(payload["price"]),
        pivot_index=int(payload["pivot_index"]),
        pivot_date=date.fromisoformat(payload["pivot_date"]),
        confirmed_index=_optional_int(str(payload.get("confirmed_index", ""))),
        confirmed_date=_optional_date(str(payload.get("confirmed_date", ""))),
    )


def _event_from_structural_row(row: dict[str, str]) -> Setup02ReplayEvent:
    event_type = SetupState(row["event_type"])
    trade_date = date.fromisoformat(row["trade_date"])
    terminal_type = row.get("terminal_event_type") or None
    diagnostics = ast.literal_eval(row.get("diagnostics", "[]"))
    snapshot = Setup02Evaluation(
        setup_type=row["setup_type"],
        protocol_version=row["protocol_version"],
        state=SetupState(row["state"]),
        as_of_date=date.fromisoformat(row["as_of_date"]),
        continuation_low0=_swing(row.get("continuation_low0", "")),
        continuation_high1=_swing(row.get("continuation_high1", "")),
        continuation_low2=_swing(row.get("continuation_low2", "")),
        continuation_high3=_swing(row.get("continuation_high3", "")),
        fib_retracement_ratio=_optional_float(row.get("fib_retracement_ratio", "")),
        fib_retracement_region=row.get("fib_retracement_region") or None,
        confirmation_level=_optional_float(row.get("confirmation_level", "")),
        structural_invalidation=_optional_float(row.get("structural_invalidation", "")),
        state_entered_index=_optional_int(row.get("state_entered_index", "")),
        state_entered_date=_optional_date(row.get("state_entered_date", "")),
        confirmed_index=_optional_int(row.get("confirmed_index", "")),
        confirmed_date=_optional_date(row.get("confirmed_date", "")),
        failed_index=_optional_int(row.get("failed_index", "")),
        failed_date=_optional_date(row.get("failed_date", "")),
        primary_wave_scenario=row.get("primary_wave_scenario", ""),
        alternate_wave_scenario=row.get("alternate_wave_scenario", ""),
        reason=row.get("reason", ""),
        diagnostics=tuple(str(item) for item in diagnostics),
        lifecycle_index=_optional_int(row.get("lifecycle_index", "")),
        terminal_event_type=SetupState(terminal_type) if terminal_type else None,
        terminal_event_date=_optional_date(row.get("terminal_event_date", "")),
        is_new_confirmed_event_as_of=_optional_bool(row.get("is_new_confirmed_event_as_of", "")),
        is_new_failed_event_as_of=_optional_bool(row.get("is_new_failed_event_as_of", "")),
        is_live_preconfirmation_candidate=_optional_bool(
            row.get("is_live_preconfirmation_candidate", "")
        ),
    )
    return Setup02ReplayEvent(
        event_identity=row["event_identity"],
        symbol=row["symbol"],
        trade_date=trade_date,
        event_type=event_type,
        setup02=snapshot,
        market=row["market"],
    )


def _load_structural_events(path: Path) -> list[Setup02ReplayEvent]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [_event_from_structural_row(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8-sig")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_setup02_decision_funnel(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    structural_events_path: str | Path = DEFAULT_STRUCTURAL_EVENTS,
    output_dir: str | Path = DEFAULT_OUTPUT,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> dict[str, Any]:
    manifest, symbol_quotes = load_frozen_dataset(Path(manifest_path))
    structural_path = Path(structural_events_path)
    event_stream_source = "EXISTING_STRUCTURAL_REPLAY_CONFIRMED_EVENTS"
    errors: list[dict[str, str]] = []
    if structural_path.exists():
        events = _load_structural_events(structural_path)
    else:
        event_stream_source = "CAUSAL_STRUCTURAL_REPLAY_FALLBACK"
        events = []
        for symbol in sorted(symbol_quotes):
            try:
                events.extend(replay_setup02_history(symbol_quotes[symbol]).events)
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "market": symbol_quotes[symbol][0].market,
                        "error": str(exc),
                    }
                )
    document = build_setup02_decision_funnel(
        events,
        symbol_quotes,
        risk_capital=risk_capital,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
        dataset_version=manifest["dataset_version"],
        dataset_manifest_sha256=manifest["integrity"]["manifest_sha256"],
        replay_input_aggregate_hash=manifest.get("replay_input_manifest_sha256"),
        event_stream_source=event_stream_source,
    )
    document["structural_events_path"] = str(structural_path)
    document["replay_errors"] = len(errors)
    document["replay_errors_detail"] = errors
    document["status"] = "SUCCESS" if not errors else "PARTIAL_DATA_QUALITY"
    output_path = Path(output_dir)
    _write_json(output_path / "setup02_decision_execution_funnel.json", document)
    _write_csv(output_path / "setup02_decision_execution_events.csv", document["decisions"])
    _write_csv(output_path / "setup02_decision_execution_funnel.csv", document["per_symbol"])
    _write_csv(output_path / "setup02_target_provenance_audit.csv", document["target_provenance_audit"])
    _write_csv(
        output_path / "setup02_invalid_structure_geometry_audit.csv",
        document["invalid_structure_audit"],
    )
    _write_csv(output_path / "setup02_decision_replay_errors.csv", errors)
    print(
        "SETUP02_DECISION_FUNNEL_SUMMARY "
        + json.dumps(
            {
                key: value
                for key, value in document.items()
                if key not in {
                    "decisions",
                    "replay_errors_detail",
                    "per_symbol",
                    "target_provenance_audit",
                    "invalid_structure_audit",
                }
            },
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--structural-events", default=str(DEFAULT_STRUCTURAL_EVENTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--risk-capital", type=float, default=None)
    parser.add_argument("--swing-lookback", type=int, default=5)
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()
    document = run_setup02_decision_funnel(
        manifest_path=args.manifest,
        structural_events_path=args.structural_events,
        output_dir=args.output_dir,
        risk_capital=args.risk_capital,
        swing_lookback=args.swing_lookback,
        atr_period=args.atr_period,
    )
    raise SystemExit(1 if document["status"] != "SUCCESS" else 0)


if __name__ == "__main__":
    main()
