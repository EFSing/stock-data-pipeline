"""CLI for the research-only D1 immutable collector reference backend."""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from research.setup01_d1_prospective import (
    FilesystemD1Store,
    build_session_snapshot,
    canonical_bytes,
    render_research_report,
)
from research.setup01_d1_drive_store import GoogleDriveApi, GoogleDriveD1Store
from research.setup01_d1_gcs_store import (
    GoogleCloudStorageApi,
    GoogleCloudStorageD1Store,
)
from research.setup01_d1_vps_store import VpsD1Store
from research.setup01_d1_source_contract import (
    D1_SOURCE_CONTRACT_V1,
    D1_SOURCE_CONTRACT_V2,
    D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1,
    source_contract_descriptor,
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


def gcs_collect(input_path: Path, report_output: Path | None = None) -> dict[str, Any]:
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
    committed = GoogleCloudStorageD1Store.from_env().commit(snapshot)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_research_report(snapshot), encoding="utf-8")
    return {
        "status": committed.status,
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "object_name": committed.object_name,
        "object_generation": committed.object_generation,
        "commit_name": committed.commit_name,
        "commit_generation": committed.commit_generation,
        "prospective_eligible": snapshot["prospective_eligible"],
        "research_only": True,
        "production_state_write": False,
    }


def vps_collect(input_path: Path, report_output: Path | None = None) -> dict[str, Any]:
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
    receipt = VpsD1Store.from_env().commit(snapshot).as_receipt()
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_research_report(snapshot), encoding="utf-8")
    return {
        **receipt,
        "prospective_eligible": snapshot["prospective_eligible"],
        "research_only": True,
        "production_state_write": False,
    }

def daily_report_input(
    report_path: Path, *, diagnostic_backfill: bool = False
) -> dict[str, Any]:
    """Project report metadata for diagnostics, never formal D1 evidence.

    The Cloud report deliberately omits raw/QFQ bars and the Path A/B observer
    prefix. Its fingerprint cannot substitute for those frozen components.
    """
    if not diagnostic_backfill:
        raise ValueError("D1_SOURCE_CONTRACT_NOT_READY: raw/QFQ prefix and causal Path A/B observer required")
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
    capture_status = "DATA_MISSING"
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
        "diagnostic_backfill": True,
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
            "source_contract_status": "DIAGNOSTIC_REPORT_PROJECTION_ONLY",
            "provider_status": provider_status,
            "input_fingerprint": fingerprint,
            "daily_report_git_sha": metadata.get("git_sha"),
        },
        "normalized_prefix_snapshot": {
            "adjustment": "QFQ",
            "persisted_raw_bars": False,
            "source_contract_status": "DIAGNOSTIC_REPORT_PROJECTION_ONLY",
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
    storage_validation_parser = sub.add_parser("drive-validate-storage")
    storage_validation_parser.add_argument("--expected-folder-id-sha256", required=True)
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
    sub.add_parser("gcs-access-check").add_argument("--write-readback-probe", action="store_true")
    gcs_validation_parser = sub.add_parser("gcs-validate-storage")
    gcs_validation_parser.add_argument("--expected-bucket-identity-sha256")
    gcs_activation_parser = sub.add_parser("gcs-create-activation")
    gcs_activation_parser.add_argument("--market", choices=("CN", "US"), required=True)
    gcs_activation_parser.add_argument("--activation-timestamp", required=True)
    gcs_activation_parser.add_argument("--code-sha", required=True)
    gcs_activation_parser.add_argument(
        "--source-contract-version",
        choices=(
            D1_SOURCE_CONTRACT_V1,
            D1_SOURCE_CONTRACT_V2,
            D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1,
        ),
        required=True,
    )
    gcs_collect_parser = sub.add_parser("gcs-collect")
    gcs_collect_parser.add_argument("--input", type=Path, required=True)
    gcs_collect_parser.add_argument("--report-output", type=Path)
    sub.add_parser("gcs-verify")
    gcs_recover_parser = sub.add_parser("gcs-recover")
    gcs_recover_parser.add_argument("--target", type=Path, required=True)
    sub.add_parser("vps-identity")
    sub.add_parser("vps-status")
    vps_validation_parser = sub.add_parser("vps-validate-storage")
    vps_validation_parser.add_argument("--expected-storage-identity-sha256", required=True)
    vps_activation_parser = sub.add_parser("vps-create-activation")
    vps_activation_parser.add_argument("--market", choices=("CN", "US"), required=True)
    vps_activation_parser.add_argument("--activation-timestamp", required=True)
    vps_activation_parser.add_argument("--code-sha", required=True)
    vps_activation_parser.add_argument(
        "--source-contract-version",
        choices=(
            D1_SOURCE_CONTRACT_V1,
            D1_SOURCE_CONTRACT_V2,
            D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1,
        ),
        required=True,
    )
    vps_collect_parser = sub.add_parser("vps-collect")
    vps_collect_parser.add_argument("--input", type=Path, required=True)
    vps_collect_parser.add_argument("--report-output", type=Path)
    vps_verify_parser = sub.add_parser("vps-verify")
    vps_verify_parser.add_argument("--full-objects", action="store_true")
    vps_export_parser = sub.add_parser("vps-export")
    vps_export_parser.add_argument("--target", type=Path, required=True)
    vps_recover_parser = sub.add_parser("vps-recover")
    vps_recover_parser.add_argument("--target", type=Path, required=True)
    vps_migrate_parser = sub.add_parser("vps-migrate")
    vps_migrate_parser.add_argument("--from", dest="source", type=Path, required=True)
    vps_manifest_parser = sub.add_parser("vps-manifest")
    vps_manifest_parser.add_argument("--publish", action="store_true")
    vps_manifest_parser.add_argument("--output", type=Path)
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
    elif args.command == "drive-validate-storage":
        store = GoogleDriveD1Store.from_env()
        if sha256(store.folder_id.encode("utf-8")).hexdigest() != args.expected_folder_id_sha256:
            raise ValueError("configured D1 folder ID differs from user-provided folder")
        print(json.dumps({"folder_identity": "MATCH"}), flush=True)
        result = store.validate_durable_storage(
            expected_folder_id_sha256=args.expected_folder_id_sha256
        )
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
    elif args.command == "gcs-access-check":
        store = GoogleCloudStorageD1Store.from_env()
        result = store.verify_access(write_probe=args.write_readback_probe)
        result["service_account_email"] = GoogleCloudStorageApi.service_account_email_from_env()
        result["service_account_project_id"] = GoogleCloudStorageApi.project_id_from_env()
    elif args.command == "gcs-validate-storage":
        result = GoogleCloudStorageD1Store.from_env().validate_durable_storage(
            expected_bucket_identity_sha256=args.expected_bucket_identity_sha256
        )
    elif args.command == "gcs-create-activation":
        store = GoogleCloudStorageD1Store.from_env()
        contract = source_contract_descriptor(args.source_contract_version)
        record = store.create_activation_record(
            market=args.market,
            activation_timestamp=args.activation_timestamp,
            code_sha=args.code_sha,
            source_contract=contract,
            observer_version=contract["observer_version"],
            source_contract_version=args.source_contract_version,
        )
        result = {"status": "ACTIVATION_CREATED", "record": record}
    elif args.command == "gcs-collect":
        result = gcs_collect(args.input, args.report_output)
    elif args.command == "gcs-verify":
        result = GoogleCloudStorageD1Store.from_env().verify()
    elif args.command == "gcs-recover":
        result = GoogleCloudStorageD1Store.from_env().recover_to(args.target)
    elif args.command == "vps-identity":
        store = VpsD1Store.from_env()
        result = {
            "status": "IDENTITY_VERIFIED",
            **store.identity(),
            "transport_identity": dict(store.transport_identity),
        }
    elif args.command == "vps-status":
        result = VpsD1Store.from_env().status()
    elif args.command == "vps-validate-storage":
        result = VpsD1Store.from_env().validate_durable_storage(
            expected_storage_identity_sha256=args.expected_storage_identity_sha256
        )
    elif args.command == "vps-create-activation":
        store = VpsD1Store.from_env()
        contract = source_contract_descriptor(args.source_contract_version)
        record = store.create_activation_record(
            market=args.market,
            activation_timestamp=args.activation_timestamp,
            code_sha=args.code_sha,
            source_contract=contract,
            observer_version=contract["observer_version"],
            source_contract_version=args.source_contract_version,
        )
        result = {"status": "ACTIVATION_CREATED", "record": record}
    elif args.command == "vps-collect":
        result = vps_collect(args.input, args.report_output)
    elif args.command == "vps-verify":
        result = VpsD1Store.from_env().verify(full_objects=bool(args.full_objects))
    elif args.command == "vps-export":
        result = VpsD1Store.from_env().export_to(args.target)
    elif args.command == "vps-recover":
        result = VpsD1Store.from_env().recover_to(args.target)
    elif args.command == "vps-migrate":
        result = VpsD1Store.from_env().migrate_from(args.source)
    elif args.command == "vps-manifest":
        store = VpsD1Store.from_env()
        if args.publish:
            result = store.publish_manifest()
        else:
            result = {"status": "MANIFEST_BUILT", "manifest": store.build_manifest()}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical_bytes(result["manifest"]))
    else:
        result = GoogleDriveD1Store.from_env().recover_to(args.target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {
        "ACCESS_VERIFIED",
        "ACTIVATION_CREATED",
        "COMMITTED",
        "IDENTITY_VERIFIED",
        "IDEMPOTENT_REPLAY",
        "MANIFEST_BUILT",
        "MIGRATED_AND_VERIFIED",
        "STORAGE_STATUS",
        "VERIFIED",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
