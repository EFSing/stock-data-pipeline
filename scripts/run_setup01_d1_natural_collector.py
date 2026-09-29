"""Collect one natural D1 session from the public Candidate runtime.

This workflow is deliberately separate from the holdings-aware Cloud Daily
Report.  It reads public Candidate seed/history sources only, and a durable
commit failure never changes or fails the production daily report path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from research.setup01_d1_gcs_store import GCS_BACKEND_IDENTITY, GoogleCloudStorageD1Store
from research.setup01_d1_activation import session_is_in_activation_window
from research.setup01_d1_prospective import (
    D1IntegrityError,
    D1ProspectiveWindowError,
    render_research_report,
)
from research.setup01_d1_source_contract import (
    D1_SOURCE_CONTRACT_V1,
    D1_SOURCE_CONTRACT_V2,
    build_d1_snapshot_from_candidate_runtime,
    source_contract_descriptor,
)
from research.setup01_d1_vps_store import VPS_BACKEND_IDENTITY, VpsD1Store
from trading.production_candidate_runtime import ProductionCandidateRuntime
from trading.production_prerequisites import ExactExchangeCalendarProvider


def _session_payload(identity: Any) -> dict[str, Any]:
    return {
        "market": str(identity.market).upper(),
        "trade_date": identity.trade_date.isoformat(),
        "identity": str(identity.identity),
        "exact_exchange_calendar": bool(identity.exact_exchange_calendar),
        "next_session_date": identity.next_session_date.isoformat(),
    }


def _migration_gate(durable: Any, market: str) -> dict[str, Any]:
    """Prevent the immutable V1 activation from producing first evidence."""

    verification = durable.verify()
    counts = {
        str(key).upper(): int(value)
        for key, value in (verification.get("session_counts") or {}).items()
    }
    if verification.get("status") != "VERIFIED":
        raise D1IntegrityError("D1_SOURCE_MIGRATION_STATE_UNVERIFIED")
    if any(value > 0 for value in counts.values()):
        raise D1IntegrityError(
            "D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE:"
            + json.dumps(counts, ensure_ascii=False, sort_keys=True)
        )
    activation = durable.load_activation_record(market)
    version = str(
        activation.get("source_contract_version")
        or (activation.get("source_contract") or {}).get("contract_version")
        or ""
    )
    if version == D1_SOURCE_CONTRACT_V1:
        raise D1IntegrityError("D1_SOURCE_MIGRATION_PENDING")
    if version != D1_SOURCE_CONTRACT_V2:
        raise D1IntegrityError("D1_SOURCE_MIGRATION_ACTIVATION_VERSION_UNKNOWN")
    return {"session_counts": counts, "activation_source_contract_version": version}


def collect_natural_session(
    market: str,
    *,
    now: datetime | None = None,
    store: object | None = None,
    runtime: ProductionCandidateRuntime | None = None,
    backend: str = "vps",
    calendar_provider: ExactExchangeCalendarProvider | None = None,
) -> dict[str, Any]:
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("D1 natural collector requires timezone-aware now")
    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("D1 market must be CN or US")
    normalized_backend = str(backend).strip().lower()
    if normalized_backend not in {"vps", "gcs"}:
        raise ValueError("D1 durable backend must be vps or gcs")
    durable = store or (
        VpsD1Store.from_env() if normalized_backend == "vps" else GoogleCloudStorageD1Store.from_env()
    )
    migration_state = _migration_gate(durable, normalized_market)
    calendar = calendar_provider or ExactExchangeCalendarProvider()
    # Formal natural collection always resolves the latest real exchange
    # close.  There is intentionally no --date override: a delayed trigger
    # must never turn the runner's current civil date into an incomplete T.
    identity = calendar.latest_completed_session(normalized_market, now=generated_at)
    trade_date = identity.trade_date
    activation = durable.load_activation_record(normalized_market)
    if not session_is_in_activation_window(activation, trade_date.isoformat()):
        raise D1ProspectiveWindowError(
            "D1_PRE_ACTIVATION_OR_POST_WINDOW_SESSION",
            detail={
                "market": normalized_market,
                "session_date": trade_date.isoformat(),
                "first_eligible_session": activation.get("first_eligible_full_exchange_session"),
                "end_boundary": activation.get("end_boundary_local_date"),
            },
        )
    window = calendar.completed_session_window(
        normalized_market, trade_date, now=generated_at
    )
    if not window.collection_window_open:
        raise D1ProspectiveWindowError(
            "MISSED_PROSPECTIVE_SESSION",
            detail=window.as_dict(),
        )
    candidate_runtime = runtime or ProductionCandidateRuntime()
    result = candidate_runtime.run(
        market=normalized_market,
        as_of_date=trade_date,
        completed_session_identity=identity,
        now=generated_at,
        reuse_symbols=(),
        paper_active_symbols=(),
    )
    snapshot = build_d1_snapshot_from_candidate_runtime(
        result,
        session_identity=_session_payload(identity),
        acquired_at=generated_at.isoformat(),
        activation_record=activation,
        contract_version=D1_SOURCE_CONTRACT_V2,
    )
    committed = durable.commit(snapshot)
    report_markdown = render_research_report(snapshot)
    receipt = {
        "status": committed.status,
        "backend_identity": (
            VPS_BACKEND_IDENTITY if normalized_backend == "vps" else GCS_BACKEND_IDENTITY
        ),
        "market": normalized_market,
        "session_date": trade_date.isoformat(),
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "object_name": committed.object_name,
        "object_sha256": getattr(committed, "object_sha256", None),
        "object_generation": getattr(committed, "object_generation", None),
        "commit_name": committed.commit_name,
        "commit_generation": getattr(committed, "commit_generation", None),
        "pointer_sha256": getattr(committed, "pointer_sha256", None),
        "source_contract_version": source_contract_descriptor(D1_SOURCE_CONTRACT_V2)["contract_version"],
        "source_migration_status": source_contract_descriptor(D1_SOURCE_CONTRACT_V2)["migration_status"],
        "source_migration_reason": source_contract_descriptor(D1_SOURCE_CONTRACT_V2)["migration_reason"],
        "research_only": True,
        "research_only_candidate": True,
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
        "production_state_write": False,
        "paper_write": False,
        "broker_order": False,
        "session_counts": durable.verify()["session_counts"],
        "migration_state": migration_state,
        "session_resolution": window.as_dict(),
        "report_markdown": report_markdown,
    }
    if hasattr(committed, "as_receipt"):
        receipt["disk"] = dict(committed.as_receipt().get("disk") or {})
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SETUP_01 D1 natural durable collector")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--backend", choices=("vps", "gcs"), default="vps")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect_natural_session(args.market, backend=args.backend)
    report_markdown = str(result.pop("report_markdown"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report_markdown, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"COMMITTED", "IDEMPOTENT_REPLAY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
