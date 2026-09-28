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
from research.setup01_d1_prospective import render_research_report
from research.setup01_d1_source_contract import (
    build_d1_snapshot_from_candidate_runtime,
    source_contract_descriptor,
)
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


def collect_natural_session(
    market: str,
    *,
    now: datetime | None = None,
    store: GoogleCloudStorageD1Store | None = None,
    runtime: ProductionCandidateRuntime | None = None,
) -> dict[str, Any]:
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("D1 natural collector requires timezone-aware now")
    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("D1 market must be CN or US")
    durable = store or GoogleCloudStorageD1Store.from_env()
    calendar = ExactExchangeCalendarProvider()
    # The natural run date is resolved from the exchange-local current date;
    # there is intentionally no --date override for a formal collector.
    trade_date = calendar.market_local_date(normalized_market, now=generated_at)
    identity = calendar.completed_session(normalized_market, trade_date, now=generated_at)
    activation = durable.load_activation_record(normalized_market)
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
    )
    committed = durable.commit(snapshot)
    report_markdown = render_research_report(snapshot)
    return {
        "status": committed.status,
        "backend_identity": GCS_BACKEND_IDENTITY,
        "market": normalized_market,
        "session_date": trade_date.isoformat(),
        "event_id": committed.event_id,
        "event_sha256": committed.event_sha256,
        "object_name": committed.object_name,
        "object_generation": committed.object_generation,
        "commit_name": committed.commit_name,
        "commit_generation": committed.commit_generation,
        "source_contract_version": source_contract_descriptor()["contract_version"],
        "research_only": True,
        "research_only_candidate": True,
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
        "production_state_write": False,
        "paper_write": False,
        "broker_order": False,
        "session_counts": durable.verify()["session_counts"],
        "report_markdown": report_markdown,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SETUP_01 D1 natural GCS collector")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect_natural_session(args.market)
    report_markdown = str(result.pop("report_markdown"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report_markdown, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"COMMITTED", "IDEMPOTENT_REPLAY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
