"""Run the frozen DEVELOPMENT_EXPOSED Position Management replay."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.position_management_replay import build_position_management_replay


DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "position_management_exit_v1"


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


def run_position_management_replay(
    *,
    manifest_path: str | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> dict[str, Any]:
    document = build_position_management_replay(
        manifest_path=manifest_path,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    output_path = Path(output_dir)
    _write_json(output_path / "position_management_replay.json", document)
    _write_csv(
        output_path / "position_management_positions.csv",
        [
            {
                key: value
                for key, value in position.items()
                if key != "days"
            }
            for position in document["positions"]
        ],
    )
    _write_csv(
        output_path / "position_management_position_days.csv",
        [
            {
                "source_setup": position["source_setup"],
                "source_event_identity": position["source_event_identity"],
                "symbol": position["symbol"],
                **day,
            }
            for position in document["positions"]
            for day in position["days"]
        ],
    )
    print(
        "POSITION_MANAGEMENT_REPLAY_SUMMARY "
        + json.dumps(
            {key: value for key, value in document.items() if key != "positions"},
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--swing-lookback", type=int, default=5)
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()
    document = run_position_management_replay(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        swing_lookback=args.swing_lookback,
        atr_period=args.atr_period,
    )
    raise SystemExit(0 if document["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
