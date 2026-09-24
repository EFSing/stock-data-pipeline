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
from research.setup01_d1_drive_store import GoogleDriveApi, GoogleDriveD1Store


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


def drive_collect(input_path: Path, report_output: Path | None = None) -> dict[str, Any]:
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
    committed = GoogleDriveD1Store.from_env().commit(snapshot)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_research_report(snapshot), encoding="utf-8")
    return {
        "status": committed.status,
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "object_file_id": committed.object_file_id,
        "commit_file_id": committed.commit_file_id,
        "prospective_eligible": snapshot["prospective_eligible"],
        "research_only": True,
        "production_state_write": False,
    }


def daily_report_input(
    report_path: Path, *, diagnostic_backfill: bool = False
) -> dict[str, Any]:
    """Project one natural CN/US daily report into the frozen five components."""
    payload = _load(report_path)
    metadata = payload.get("cloud_daily_report") or {}
    market = str(metadata.get("market") or payload.get("market") or "").upper()
    session_date = str(metadata.get("as_of_date") or payload.get("as_of_date") or "")
    generated_at = str(metadata.get("generated_at") or payload.get("generated_at") or "")
    if market not in {"CN", "US"}:
        raise ValueError("daily report market must be CN or US")
    date.fromisoformat(session_date)
    if metadata.get("calendar_gate") != "EXACT_COMPLETED_SESSION" or not metadata.get("session_identity"):
        raise ValueError("D1 collection requires an exact completed exchange session")
    status = str(metadata.get("status") or "FAILED")
    quality = metadata.get("data_quality") or {}
    complete = status == "SUCCESS" and quality.get("operationally_complete") is True
    capture_status = "COMPLETE" if complete else "DATA_MISSING"
    prospective = payload.get("prospective_observation") or {}
    observed_rows = list(prospective.get("observations") or ())
    members = []
    for row in observed_rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or any(item["symbol"] == symbol for item in members):
            continue
        members.append({
            "symbol": symbol,
            "market": market,
            "membership_status": str(row.get("provenance_bucket") or "OBSERVED"),
            "source_date": session_date,
            "sector": "UNAVAILABLE_IN_DAILY_REPORT",
            "tradable": row.get("data_status") == "DATA_OK",
        })
    provider_status = metadata.get("provider_status") or {}
    fingerprint = metadata.get("input_fingerprint")
    return {
        "market": market,
        "session_date": session_date,
        "acquired_at": generated_at,
        "capture_status": capture_status,
        "diagnostic_backfill": bool(diagnostic_backfill),
        "source_identity": {
            "provider": "CLOUD_DAILY_REPORT_EPHEMERAL_MARKET_DATA",
            "source_date": session_date,
            "obtained_at": generated_at,
            "input_fingerprint": fingerprint,
        },
        "universe_snapshot": {
            "source": prospective.get("seed_source"),
            "source_as_of": prospective.get("seed_source_as_of"),
            "members": members,
        },
        "raw_source_snapshot": {
            "persisted_raw_bars": False,
            "provider_status": provider_status,
            "input_fingerprint": fingerprint,
            "daily_report_git_sha": metadata.get("git_sha"),
        },
        "normalized_prefix_snapshot": {
            "adjustment": "QFQ",
            "persisted_raw_bars": False,
            "input_fingerprint": fingerprint,
            "session_identity": metadata.get("session_identity"),
            "data_quality": quality,
        },
        "decision_snapshot": {
            "formal_entry_allowed": [
                row for row in observed_rows
                if (row.get("decision") or {}).get("action") == "ENTRY_ALLOWED"
            ],
            "observations": observed_rows,
            "production_state_write": False,
        },
        "research_observation_report": {
            "observations": [],
            "daily_report_observation": prospective,
            "dual_path_note": (
                "No fabricated dual-path event: PATH_A/PATH_B facts are emitted only when "
                "the causal observer has a qualifying H1 lifecycle in the observed prefix."
            ),
        },
    }


def drive_collect_daily_report(
    report_path: Path, report_output: Path | None = None, *, diagnostic_backfill: bool = False
) -> dict[str, Any]:
    value = daily_report_input(report_path, diagnostic_backfill=diagnostic_backfill)
    snapshot = build_session_snapshot(
        market=value["market"], session_date=date.fromisoformat(value["session_date"]),
        acquired_at=value["acquired_at"], capture_status=value["capture_status"],
        diagnostic_backfill=value["diagnostic_backfill"], source_identity=value["source_identity"],
        universe_snapshot=value["universe_snapshot"], raw_source_snapshot=value["raw_source_snapshot"],
        normalized_prefix_snapshot=value["normalized_prefix_snapshot"],
        decision_snapshot=value["decision_snapshot"],
        research_observation_report=value["research_observation_report"],
    )
    committed = GoogleDriveD1Store.from_env().commit(snapshot)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_research_report(snapshot), encoding="utf-8")
    return {
        "status": committed.status,
        "capture_status": snapshot["capture_status"],
        "prospective_eligible": snapshot["prospective_eligible"],
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "object_file_id": committed.object_file_id,
        "commit_file_id": committed.commit_file_id,
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
    drive_access_parser = sub.add_parser("drive-access-check")
    drive_access_parser.add_argument("--write-readback-probe", action="store_true")
    drive_collect_parser = sub.add_parser("drive-collect")
    drive_collect_parser.add_argument("--input", type=Path, required=True)
    drive_collect_parser.add_argument("--report-output", type=Path)
    drive_daily_parser = sub.add_parser("drive-collect-daily-report")
    drive_daily_parser.add_argument("--daily-report", type=Path, required=True)
    drive_daily_parser.add_argument("--report-output", type=Path, required=True)
    drive_daily_parser.add_argument("--diagnostic-backfill", action="store_true")
    sub.add_parser("drive-verify")
    drive_recover_parser = sub.add_parser("drive-recover")
    drive_recover_parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "collect":
        result = collect(args.input, args.store, args.report_output)
    elif args.command == "verify":
        result = FilesystemD1Store(args.store).verify()
    elif args.command == "recover":
        result = FilesystemD1Store(args.store).recover_to(args.target)
    elif args.command == "drive-access-check":
        result = GoogleDriveD1Store.from_env().verify_access(
            write_probe=args.write_readback_probe
        )
        result["service_account_email"] = GoogleDriveApi.service_account_email_from_env()
    elif args.command == "drive-collect":
        result = drive_collect(args.input, args.report_output)
    elif args.command == "drive-collect-daily-report":
        result = drive_collect_daily_report(
            args.daily_report,
            args.report_output,
            diagnostic_backfill=args.diagnostic_backfill,
        )
    elif args.command == "drive-verify":
        result = GoogleDriveD1Store.from_env().verify()
    else:
        result = GoogleDriveD1Store.from_env().recover_to(args.target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {
        "ACCESS_VERIFIED", "COMMITTED", "IDEMPOTENT_REPLAY", "VERIFIED"
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
