"""Small durable operational markers kept outside formal D1 evidence."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from typing import Any, Mapping, Protocol


REPORT_NOTIFICATION_MARKER_VERSION = "DAILY_REPORT_NOTIFICATION_IDEMPOTENCY_V1"


class OperationalMarkerStore(Protocol):
    def put_bytes(
        self,
        name: str,
        payload: bytes,
        *,
        role: str,
        market: str | None = None,
        session_date: str | None = None,
        protocol: str | None = None,
    ) -> Mapping[str, Any]: ...


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _configured(values: Mapping[str, str]) -> bool:
    return all(str(values.get(key) or "").strip() for key in (
        "D1_VPS_HOST",
        "D1_VPS_SSH_PRIVATE_KEY",
        "D1_VPS_KNOWN_HOSTS",
        "D1_VPS_HOST_KEY_FINGERPRINT",
    ))


def _marker_name(market: str, session_date: str, protocol_version: str) -> str:
    safe_protocol = "".join(char if char.isalnum() or char in "-_." else "_" for char in protocol_version)
    return f"system/operational/daily-report-notifications/{market}/{session_date}/{safe_protocol}.json"


def claim_report_notification(
    payload: Mapping[str, Any],
    *,
    store: OperationalMarkerStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Claim at most one notification identity for a market/session report.

    The claim is create-only and is written before SMTP/Bark delivery.  That
    ordering intentionally prefers at-most-one normal notification over an
    unbounded retry after a process crash between delivery and bookkeeping.
    """

    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").strip().upper()
    session_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "").strip()
    protocol_version = str(cloud.get("protocol_version") or "").strip()
    if market not in {"CN", "US"} or not session_date or not protocol_version:
        return {"status": "NOT_CONFIGURED", "configured": False}

    values = environ or os.environ
    resolved_store = store
    if resolved_store is None:
        if not _configured(values):
            return {"status": "NOT_CONFIGURED", "configured": False}
        try:
            from research.setup01_d1_vps_store import VpsD1Store

            resolved_store = VpsD1Store.from_env(environ=values)
        except Exception as exc:  # noqa: BLE001 - notification must not alter report result
            return {
                "status": "IDEMPOTENCY_UNAVAILABLE",
                "configured": True,
                "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
            }

    identity = f"{market}|{session_date}|{protocol_version}"
    marker = {
        "schema_version": REPORT_NOTIFICATION_MARKER_VERSION,
        "identity": identity,
        "market": market,
        "session_date": session_date,
        "report_protocol_version": protocol_version,
        "policy": "AT_MOST_ONE_NORMAL_NOTIFICATION",
        "d1_evidence_namespace": "SEPARATE_FROM_FORMAL_D1_SESSION_GRAPH",
    }
    try:
        receipt = resolved_store.put_bytes(
            _marker_name(market, session_date, protocol_version),
            _canonical(marker),
            role="OPERATIONAL_REPORT_NOTIFICATION_CLAIM",
            market=market,
            session_date=session_date,
            protocol=REPORT_NOTIFICATION_MARKER_VERSION,
        )
    except Exception as exc:  # noqa: BLE001 - caller records diagnostics and fail-closes delivery
        return {
            "status": "IDEMPOTENCY_UNAVAILABLE",
            "configured": True,
            "identity": identity,
            "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
        }
    raw_status = str(receipt.get("status") or "").upper()
    return {
        "status": "NOOP_REPORT_ALREADY_SENT" if raw_status == "IDEMPOTENT_REPLAY" else "CLAIMED",
        "configured": True,
        "identity": identity,
        "marker_name": _marker_name(market, session_date, protocol_version),
        "marker_sha256": sha256(_canonical(marker)).hexdigest(),
    }


__all__ = ["REPORT_NOTIFICATION_MARKER_VERSION", "claim_report_notification"]
