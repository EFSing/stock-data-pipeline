"""Small durable operational markers kept outside formal D1 evidence."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from typing import Any, Mapping, Protocol


FINAL_REPORT_NOTIFICATION_MARKER_VERSION = "DAILY_REPORT_FINAL_NOTIFICATION_IDEMPOTENCY_V2"
DEGRADED_ALERT_MARKER_VERSION = "DAILY_REPORT_DEGRADED_ALERT_IDEMPOTENCY_V1"
# Kept as a compatibility export for callers that only need the operational
# marker family name.  New claims are dispatched to the final or alert
# contract below and never reuse the legacy V1 marker as a final claim.
REPORT_NOTIFICATION_MARKER_VERSION = FINAL_REPORT_NOTIFICATION_MARKER_VERSION


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


def _safe_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def _marker_name(
    market: str, session_date: str, protocol_version: str, *, alert: bool = False,
    state_key: str | None = None,
) -> str:
    if alert:
        suffix = _safe_component(state_key or "UNKNOWN_STATE")
        return (
            f"system/operational/daily-report-alerts/{market}/{session_date}/"
            f"{_safe_component(protocol_version)}-{suffix}.json"
        )
    return (
        f"system/operational/daily-report-notifications/final-v2/"
        f"{market}/{session_date}/{_safe_component(protocol_version)}.json"
    )


def _report_context(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").strip().upper()
    session_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "").strip()
    report_protocol = str(cloud.get("protocol_version") or "").strip()
    return market, session_date, report_protocol


def _configured_store(
    *, store: OperationalMarkerStore | None, environ: Mapping[str, str],
) -> tuple[OperationalMarkerStore | None, dict[str, Any] | None]:
    resolved_store = store
    if resolved_store is not None:
        return resolved_store, None
    if not _configured(environ):
        return None, {"status": "NOT_CONFIGURED", "configured": False}
    try:
        from research.setup01_d1_vps_store import VpsD1Store

        return VpsD1Store.from_env(environ=environ), None
    except Exception as exc:  # noqa: BLE001 - notification must not alter report result
        return None, {
            "status": "IDEMPOTENCY_UNAVAILABLE",
            "configured": True,
            "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
        }


def _claim_marker(
    *,
    payload: Mapping[str, Any],
    store: OperationalMarkerStore | None,
    environ: Mapping[str, str],
    marker_version: str,
    role: str,
    alert: bool,
    state_key: str | None = None,
) -> dict[str, Any]:
    market, session_date, report_protocol = _report_context(payload)
    if market not in {"CN", "US"} or not session_date:
        return {"status": "NOT_CONFIGURED", "configured": False}

    resolved_store, unavailable = _configured_store(store=store, environ=environ)
    if unavailable is not None:
        return unavailable

    if alert:
        stable_state = state_key or "UNKNOWN_STATE"
        identity = f"{market}|{session_date}|{marker_version}|{stable_state}"
    else:
        # Final delivery is exactly once per market/session, independent of
        # the legacy report protocol string or a future report presentation
        # revision.
        identity = f"{market}|{session_date}|{marker_version}"
    marker_name = _marker_name(
        market, session_date, marker_version, alert=alert, state_key=state_key,
    )
    marker = {
        "schema_version": marker_version,
        "identity": identity,
        "market": market,
        "session_date": session_date,
        "report_protocol_version": report_protocol,
        "delivery_kind": "DEGRADED_ALERT" if alert else "FINAL_REPORT",
        "delivery_readiness_state": state_key if alert else "FINAL_REPORT_ELIGIBLE",
        "policy": "AT_MOST_ONE_ALERT_PER_DEGRADED_STATE" if alert else "AT_MOST_ONE_FINAL_REPORT_NOTIFICATION",
        "legacy_v1_marker_policy": "IGNORED_FOR_FORWARD_COMPATIBILITY",
        "d1_evidence_namespace": "SEPARATE_FROM_FORMAL_D1_SESSION_GRAPH",
    }
    try:
        receipt = resolved_store.put_bytes(
            marker_name,
            _canonical(marker),
            role=role,
            market=market,
            session_date=session_date,
            protocol=marker_version,
        )
    except Exception as exc:  # noqa: BLE001 - caller records diagnostics and fail-closes delivery
        return {
            "status": "IDEMPOTENCY_UNAVAILABLE",
            "configured": True,
            "identity": identity,
            "marker_name": marker_name,
            "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
        }
    raw_status = str(receipt.get("status") or "").upper()
    if raw_status == "IDEMPOTENT_REPLAY":
        result_status = "NOOP_DEGRADED_ALERT_ALREADY_SENT" if alert else "NOOP_REPORT_ALREADY_SENT"
    else:
        result_status = "CLAIMED"
    return {
        "status": result_status,
        "configured": True,
        "identity": identity,
        "marker_name": marker_name,
        "marker_version": marker_version,
        "marker_sha256": sha256(_canonical(marker)).hexdigest(),
        "legacy_v1_marker_policy": "IGNORED_FOR_FORWARD_COMPATIBILITY",
    }


def claim_final_report_notification(
    payload: Mapping[str, Any], *, store: OperationalMarkerStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Claim the final-report identity only after readiness is final-eligible."""

    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    readiness = str(cloud.get("delivery_readiness") or "").strip().upper()
    if readiness and readiness != "FINAL_REPORT_ELIGIBLE":
        return {
            "status": "NOT_ELIGIBLE_FINAL_REPORT",
            "configured": True,
            "delivery_readiness": readiness,
        }
    return _claim_marker(
        payload=payload,
        store=store,
        environ=environ or os.environ,
        marker_version=FINAL_REPORT_NOTIFICATION_MARKER_VERSION,
        role="OPERATIONAL_REPORT_NOTIFICATION_CLAIM",
        alert=False,
    )


def claim_degraded_alert(
    payload: Mapping[str, Any], *, store: OperationalMarkerStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Claim one diagnostic alert per stable degraded/readiness state."""

    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    readiness = str(cloud.get("delivery_readiness") or "").strip().upper()
    if readiness in {"", "FINAL_REPORT_ELIGIBLE"}:
        return {"status": "NOT_ELIGIBLE_DEGRADED_ALERT", "configured": True}
    if str(cloud.get("delivery_notification_mode") or "").strip().upper() == "NONE":
        return {
            "status": "NOT_NOTIFYABLE",
            "configured": True,
            "delivery_readiness": readiness,
        }
    reason = str(cloud.get("delivery_readiness_reason") or "UNKNOWN_REASON").strip().upper()
    state_key = f"{readiness}|{_safe_component(reason)}"
    return _claim_marker(
        payload=payload,
        store=store,
        environ=environ or os.environ,
        marker_version=DEGRADED_ALERT_MARKER_VERSION,
        role="OPERATIONAL_REPORT_DEGRADED_ALERT_CLAIM",
        alert=True,
        state_key=state_key,
    )


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
    readiness = str(cloud.get("delivery_readiness") or "").strip().upper()
    if readiness and readiness != "FINAL_REPORT_ELIGIBLE":
        return claim_degraded_alert(payload, store=store, environ=environ)
    return claim_final_report_notification(payload, store=store, environ=environ)


__all__ = [
    "DEGRADED_ALERT_MARKER_VERSION",
    "FINAL_REPORT_NOTIFICATION_MARKER_VERSION",
    "REPORT_NOTIFICATION_MARKER_VERSION",
    "claim_degraded_alert",
    "claim_final_report_notification",
    "claim_report_notification",
]
