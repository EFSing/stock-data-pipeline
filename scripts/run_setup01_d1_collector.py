"""CLI for the research-only D1 immutable collector reference backend."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any

from research.setup01_d1_prospective import (
    FilesystemD1Store,
    build_session_snapshot,
    render_research_report,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("collector input must be a JSON object")
    return value


def collect(input_path: Path, store_path: Path, report_output: Path | None = None) -> dict[str, Any]:
    value = _load(input_path)
    snapshot = build_session_snapshot(
        market=value["market"],
        session_date=date.fromisoformat(value["session_date"]),
        acquired_at=value["acquired_at"],
        capture_status=value["capture_status"],
        diagnostic_backfill=bool(value.get("diagnostic_backfill", False)),
        source_identity=value["source_identity"],
        universe_snapshot=value["universe_snapshot"],
        raw_source_snapshot=value["raw_source_snapshot"],
        normalized_prefix_snapshot=value["normalized_prefix_snapshot"],
        decision_snapshot=value["decision_snapshot"],
        research_observation_report=value["research_observation_report"],
    )
    committed = FilesystemD1Store(store_path).commit(snapshot)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_research_report(snapshot), encoding="utf-8")
    return {
        "status": committed.status,
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "prospective_eligible": snapshot["prospective_eligible"],
        "research_only": True,
        "production_state_write": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SETUP_01 D1 prospective research collector")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--input", type=Path, required=True)
    collect_parser.add_argument("--store", type=Path, required=True)
    collect_parser.add_argument("--report-output", type=Path)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--store", type=Path, required=True)
    recover_parser = sub.add_parser("recover")
    recover_parser.add_argument("--store", type=Path, required=True)
    recover_parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "collect":
        result = collect(args.input, args.store, args.report_output)
    elif args.command == "verify":
        result = FilesystemD1Store(args.store).verify()
    else:
        result = FilesystemD1Store(args.store).recover_to(args.target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"COMMITTED", "IDEMPOTENT_REPLAY", "VERIFIED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
