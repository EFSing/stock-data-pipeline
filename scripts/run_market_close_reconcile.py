"""Reconcile one market's Daily Report and prospective D1 close window.

The trigger is deliberately dumb: GitHub schedule, Cloudflare, and the VPS
watchdog all arrive here with only a market.  This module owns exact session
resolution, the prospective deadline, durable-session existence checks, and
the final read-back after a collector run.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from research.setup01_d1_activation import session_is_in_activation_window
from research.setup01_d1_prospective import D1ProspectiveWindowError
from research.setup01_d1_vps_store import VpsD1Store, VpsObjectMissing
from scripts.run_setup01_d1_natural_collector import collect_natural_session
from trading.production_prerequisites import (
    ExactExchangeCalendarProvider,
    LATEST_ELIGIBLE_COMPLETED_EXCHANGE_SESSION,
    RECONCILE_BEFORE_NEXT_SESSION_OPEN,
)


RECONCILIATION_PROTOCOL_VERSION = "MARKET_CLOSE_RECONCILIATION_V1"
RECONCILIATION_STATUSES = {
    "COMMITTED",
    "IDEMPOTENT_REPLAY",
    "NOOP_ALREADY_COMMITTED",
    "NOOP_BEFORE_ACTIVATION",
    "NOOP_AFTER_D1_WINDOW",
    "NO_COMPLETED_SESSION",
    "MISSED_PROSPECTIVE_SESSION",
    "D1_ACTIVATION_REQUIRED",
    "SESSION_RESOLUTION_ERROR",
    "COLLECTION_FAILED",
    "READBACK_FAILED",
}


class ReconciliationStore(Protocol):
    def load_activation_record(self, market: str) -> Mapping[str, Any]: ...

    def load(self, market: str, session_date: date | str) -> Mapping[str, Any]: ...


def _error_text(exc: BaseException | str) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ").strip()[:300] or type(exc).__name__


def _is_missing(exc: BaseException) -> bool:
    return isinstance(exc, VpsObjectMissing) or "OBJECT_MISSING" in str(exc)


def _base_receipt(market: str, generated_at: datetime) -> dict[str, Any]:
    return {
        "protocol_version": RECONCILIATION_PROTOCOL_VERSION,
        "market": market,
        "generated_at": generated_at.isoformat(),
        "trigger_source": str(os.environ.get("MARKET_CLOSE_TRIGGER_SOURCE") or "unknown"),
        "resolution": LATEST_ELIGIBLE_COMPLETED_EXCHANGE_SESSION,
        "prospective_deadline": RECONCILE_BEFORE_NEXT_SESSION_OPEN,
        "research_only": True,
        "production_state_write": False,
        "paper_write": False,
        "broker_order": False,
    }


def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_github_step_summary(receipt: Mapping[str, Any]) -> None:
    """Publish the structured diagnostic on Actions without touching D1 state."""

    summary_path = str(os.environ.get("GITHUB_STEP_SUMMARY") or "").strip()
    if not summary_path:
        return
    try:
        with Path(summary_path).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_report_text(receipt))
    except OSError:
        # The receipt/artifact and exit status remain the authoritative local
        # diagnostics; an unavailable optional Actions summary must not mask
        # the reconciliation result.
        return


def _report_text(receipt: Mapping[str, Any]) -> str:
    market = receipt.get("market", "—")
    session = receipt.get("session_date", "—")
    status = receipt.get("status", "—")
    lines = [
        f"# Market-close reconciliation — {market} {session}",
        "",
        f"状态：`{status}`",
        f"解析：`{receipt.get('resolution', '—')}`",
        f"prospective 边界：`{receipt.get('prospective_deadline', '—')}`",
        "",
    ]
    if receipt.get("error"):
        lines.append(f"错误：`{receipt['error']}`")
    if receipt.get("detail"):
        lines.extend(["", "```json", json.dumps(receipt["detail"], ensure_ascii=False, indent=2, default=str), "```"])
    return "\n".join(lines) + "\n"


def reconcile_market(
    market: str,
    *,
    now: datetime | None = None,
    store: ReconciliationStore | None = None,
    calendar_provider: ExactExchangeCalendarProvider | None = None,
    collector: Callable[..., Mapping[str, Any]] = collect_natural_session,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Reconcile one market without accepting a historical date override."""

    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("market must be CN or US")
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("market reconciliation requires timezone-aware now")
    durable = store or VpsD1Store.from_env()
    calendar = calendar_provider or ExactExchangeCalendarProvider()
    receipt = _base_receipt(normalized_market, generated_at)

    try:
        identity = calendar.latest_completed_session(normalized_market, now=generated_at)
        window = calendar.completed_session_window(
            normalized_market, identity.trade_date, now=generated_at
        )
    except Exception as exc:  # noqa: BLE001 - the receipt is the operational diagnostic
        error = _error_text(exc)
        receipt.update({
            "status": "NO_COMPLETED_SESSION" if error == "COMPLETED_SESSION_REQUIRED" else "SESSION_RESOLUTION_ERROR",
            "error": error,
        })
        return receipt

    receipt.update({
        "session_date": identity.trade_date.isoformat(),
        "session_identity": identity.identity,
        "session_resolution": window.as_dict(),
    })

    try:
        durable.load(normalized_market, identity.trade_date)
    except Exception as exc:  # noqa: BLE001 - missing is the normal reconciliation branch
        if not _is_missing(exc):
            receipt.update({"status": "READBACK_FAILED", "error": _error_text(exc)})
            return receipt
    else:
        receipt.update({"status": "NOOP_ALREADY_COMMITTED", "event_identity": f"D1|{normalized_market}|{identity.trade_date.isoformat()}|SESSION_SNAPSHOT"})
        return receipt

    try:
        activation = durable.load_activation_record(normalized_market)
    except Exception as exc:  # noqa: BLE001 - activation absence is fail closed
        receipt.update({
            "status": "D1_ACTIVATION_REQUIRED" if _is_missing(exc) else "READBACK_FAILED",
            "error": _error_text(exc),
        })
        return receipt

    try:
        in_activation_window = session_is_in_activation_window(
            activation, identity.trade_date.isoformat()
        )
    except Exception as exc:  # noqa: BLE001 - immutable activation validation is a hard boundary
        receipt.update({"status": "SESSION_RESOLUTION_ERROR", "error": _error_text(exc)})
        return receipt
    if not in_activation_window:
        first = str(activation.get("first_eligible_full_exchange_session") or "")
        if first and identity.trade_date.isoformat() < first:
            receipt.update({"status": "NOOP_BEFORE_ACTIVATION"})
        else:
            receipt.update({"status": "NOOP_AFTER_D1_WINDOW"})
        return receipt

    if not window.collection_window_open:
        receipt.update({
            "status": "MISSED_PROSPECTIVE_SESSION",
            "error": "next exchange session has already opened; no historical backfill permitted",
        })
        return receipt

    try:
        committed = dict(collector(
            normalized_market,
            now=generated_at,
            store=durable,
            runtime=runtime,
            backend="vps",
            calendar_provider=calendar,
        ))
    except D1ProspectiveWindowError as exc:
        receipt.update({
            "status": exc.reason,
            "error": exc.reason,
            "detail": dict(exc.detail),
        })
        return receipt
    except Exception as exc:  # noqa: BLE001 - preserve a structured operational receipt
        receipt.update({"status": "COLLECTION_FAILED", "error": _error_text(exc)})
        return receipt

    try:
        loaded = durable.load(normalized_market, identity.trade_date)
        if str(loaded.get("session_date")) != identity.trade_date.isoformat():
            raise ValueError("read-back session date mismatch")
        if committed.get("event_sha256") and loaded.get("event_sha256") != committed.get("event_sha256"):
            raise ValueError("read-back event hash mismatch")
    except Exception as exc:  # noqa: BLE001 - a commit is not accepted without read-back
        receipt.update({"status": "READBACK_FAILED", "error": _error_text(exc), "collector": committed})
        return receipt

    receipt.update({
        "status": str(committed.get("status") or "COMMITTED"),
        "collector": committed,
        "readback": {"status": "VERIFIED", "session_date": identity.trade_date.isoformat()},
    })
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile one CN/US market close")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)
    receipt = reconcile_market(args.market)
    _write_receipt(args.output, receipt)
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(_report_text(receipt), encoding="utf-8")
    _write_github_step_summary(receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if receipt.get("status") in {
        "COMMITTED", "IDEMPOTENT_REPLAY", "NOOP_ALREADY_COMMITTED",
        "NOOP_BEFORE_ACTIVATION", "NOOP_AFTER_D1_WINDOW", "NO_COMPLETED_SESSION",
    } else 2 if receipt.get("status") == "MISSED_PROSPECTIVE_SESSION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
