"""Small durable operational markers kept outside formal D1 evidence."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from typing import Any, Mapping, Protocol


FINAL_REPORT_NOTIFICATION_MARKER_VERSION = "DAILY_REPORT_FINAL_NOTIFICATION_IDEMPOTENCY_V2"
DEGRADED_ALERT_MARKER_VERSION = "DAILY_REPORT_DEGRADED_ALERT_IDEMPOTENCY_V1"
# This is the marker schema used by the pre-readiness implementation.  Its
# namespace remains readable forever: an existing V1 marker is evidence that
# the market/session was already notified unless an explicit recovery identity
# authorizes a one-time V1 -> V2 migration.
LEGACY_REPORT_NOTIFICATION_MARKER_VERSION = "DAILY_REPORT_NOTIFICATION_IDEMPOTENCY_V1"
LEGACY_RECOVERY_MIGRATION_VERSION = "DAILY_REPORT_LEGACY_V1_TO_V2_RECOVERY_V1"
# Kept as a compatibility export for callers that only need the operational
# marker family name.  New claims use the V2 final contract.
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

    def read_bytes(
        self,
        name: str,
        *,
        expected_sha256: str | None = None,
        sink: Any | None = None,
    ) -> tuple[bytes, Mapping[str, Any]]: ...

    def scan(
        self, prefix: str = "", *, with_hash: bool = False,
    ) -> list[Mapping[str, Any]]: ...


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


def _legacy_marker_prefix(market: str, session_date: str) -> str:
    return f"system/operational/daily-report-notifications/{market}/{session_date}/"


def _legacy_marker_identity(
    market: str, session_date: str, marker_name: str,
) -> str | None:
    prefix = _legacy_marker_prefix(market, session_date)
    if not marker_name.startswith(prefix) or not marker_name.endswith(".json"):
        return None
    protocol = marker_name[len(prefix):-len(".json")]
    if not protocol:
        return None
    return f"{market}|{session_date}|{protocol}"


def _migration_marker_name(
    market: str, session_date: str, legacy_identity: str,
) -> str:
    return (
        "system/operational/daily-report-notification-migrations/v1-to-v2/"
        f"{market}/{session_date}/{_safe_component(legacy_identity)}.json"
    )


def _report_context(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").strip().upper()
    session_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "").strip()
    report_protocol = str(cloud.get("protocol_version") or "").strip()
    return market, session_date, report_protocol


def _legacy_v1_markers(
    store: OperationalMarkerStore, *, market: str, session_date: str,
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    """Read and validate legacy V1 notification evidence for one session.

    The scan is deliberately limited to one market/session prefix and marker
    payloads are read back and schema-checked. A storage/read failure is not
    treated as proof that no legacy marker exists.
    """

    prefix = _legacy_marker_prefix(market, session_date)
    try:
        entries = store.scan(prefix, with_hash=False)
        markers: list[dict[str, str]] = []
        for entry in entries:
            marker_name = str(entry.get("name") or "")
            identity = _legacy_marker_identity(market, session_date, marker_name)
            if identity is None:
                continue
            raw_payload, receipt = store.read_bytes(marker_name)
            try:
                marker = json.loads(raw_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"legacy marker unreadable: {marker_name}") from exc
            if not isinstance(marker, Mapping):
                raise RuntimeError(f"legacy marker is not an object: {marker_name}")
            if marker.get("schema_version") != LEGACY_REPORT_NOTIFICATION_MARKER_VERSION:
                continue
            if str(marker.get("market") or market).upper() != market:
                raise RuntimeError(f"legacy marker market mismatch: {marker_name}")
            if str(marker.get("session_date") or session_date) != session_date:
                raise RuntimeError(f"legacy marker session mismatch: {marker_name}")
            if marker.get("identity") and str(marker["identity"]) != identity:
                raise RuntimeError(f"legacy marker identity mismatch: {marker_name}")
            marker_sha256 = str(receipt.get("sha256") or sha256(raw_payload).hexdigest())
            markers.append({
                "identity": identity,
                "marker_name": marker_name,
                "marker_sha256": marker_sha256,
            })
        return markers, None
    except Exception as exc:  # noqa: BLE001 - fail closed around idempotency evidence
        return [], {
            "status": "IDEMPOTENCY_UNAVAILABLE",
            "configured": True,
            "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
            "legacy_marker_prefix": prefix,
        }


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
    legacy_recovery_identity: str | None = None,
    legacy_migration_marker_name: str | None = None,
    legacy_marker_names: tuple[str, ...] = (),
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
        "legacy_v1_marker_policy": "BLOCKED_BY_DEFAULT_IF_PRESENT",
        "d1_evidence_namespace": "SEPARATE_FROM_FORMAL_D1_SESSION_GRAPH",
    }
    if legacy_marker_names:
        marker["legacy_recovery_identity"] = legacy_recovery_identity
        marker["legacy_migration_marker_name"] = legacy_migration_marker_name
        marker["legacy_marker_names"] = list(legacy_marker_names)
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
    result = {
        "status": result_status,
        "configured": True,
        "identity": identity,
        "marker_name": marker_name,
        "marker_version": marker_version,
        "marker_sha256": sha256(_canonical(marker)).hexdigest(),
        "legacy_v1_marker_policy": "BLOCKED_BY_DEFAULT_IF_PRESENT",
    }
    if legacy_marker_names:
        result["legacy_recovery_identity"] = legacy_recovery_identity
        result["legacy_migration_marker_name"] = legacy_migration_marker_name
        result["legacy_marker_names"] = list(legacy_marker_names)
    return result


def _claim_legacy_recovery_migration(
    *,
    store: OperationalMarkerStore,
    market: str,
    session_date: str,
    legacy_identity: str,
    legacy_markers: list[dict[str, str]],
) -> dict[str, Any]:
    matching = [item for item in legacy_markers if item.get("identity") == legacy_identity]
    if not matching:
        return {
            "status": "LEGACY_RECOVERY_NOT_AUTHORIZED",
            "configured": True,
            "legacy_recovery_identity": legacy_identity,
            "legacy_marker_identities": [item["identity"] for item in legacy_markers],
        }
    migration_name = _migration_marker_name(market, session_date, legacy_identity)
    migration = {
        "schema_version": LEGACY_RECOVERY_MIGRATION_VERSION,
        "identity": f"{market}|{session_date}|{legacy_identity}",
        "market": market,
        "session_date": session_date,
        "legacy_marker_identity": legacy_identity,
        "legacy_marker_names": [item["marker_name"] for item in matching],
        "recovery_mode": "EXPLICIT_ONE_TIME_LEGACY_V1_TO_V2",
        "policy": "DEFAULT_OFF_OPERATOR_AUTHORIZATION_REQUIRED",
        "d1_evidence_namespace": "SEPARATE_FROM_FORMAL_D1_SESSION_GRAPH",
    }
    try:
        receipt = store.put_bytes(
            migration_name,
            _canonical(migration),
            role="OPERATIONAL_REPORT_LEGACY_MIGRATION_CLAIM",
            market=market,
            session_date=session_date,
            protocol=LEGACY_RECOVERY_MIGRATION_VERSION,
        )
    except Exception as exc:  # noqa: BLE001 - do not bypass migration audit
        return {
            "status": "IDEMPOTENCY_UNAVAILABLE",
            "configured": True,
            "legacy_recovery_identity": legacy_identity,
            "migration_marker_name": migration_name,
            "error": str(exc).replace("\r", " ").replace("\n", " ")[:240],
        }
    return {
        "status": str(receipt.get("status") or "CREATED").upper(),
        "migration_marker_name": migration_name,
        "legacy_recovery_identity": legacy_identity,
        "legacy_marker_names": [item["marker_name"] for item in matching],
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
    market, session_date, _ = _report_context(payload)
    if market not in {"CN", "US"} or not session_date:
        return {"status": "NOT_CONFIGURED", "configured": False}
    resolved_store, unavailable = _configured_store(
        store=store,
        environ=environ if environ is not None else os.environ,
    )
    if unavailable is not None:
        return unavailable
    assert resolved_store is not None
    legacy_markers, legacy_error = _legacy_v1_markers(
        resolved_store, market=market, session_date=session_date,
    )
    if legacy_error is not None:
        return legacy_error
    recovery_identity = str(
        cloud.get("legacy_recovery_identity")
        or payload.get("legacy_recovery_identity")
        or ""
    ).strip()
    migration_name = None
    if legacy_markers:
        if not recovery_identity:
            return {
                "status": "LEGACY_V1_MARKER_PRESENT",
                "configured": True,
                "legacy_v1_marker_policy": "BLOCKED_BY_DEFAULT_IF_PRESENT",
                "legacy_marker_identities": [item["identity"] for item in legacy_markers],
                "legacy_marker_names": [item["marker_name"] for item in legacy_markers],
                "recovery_required": True,
            }
        migration = _claim_legacy_recovery_migration(
            store=resolved_store,
            market=market,
            session_date=session_date,
            legacy_identity=recovery_identity,
            legacy_markers=legacy_markers,
        )
        if migration["status"] not in {"CREATED", "IDEMPOTENT_REPLAY"}:
            return migration
        migration_name = str(migration["migration_marker_name"])
    return _claim_marker(
        payload=payload,
        store=resolved_store,
        environ=environ if environ is not None else os.environ,
        marker_version=FINAL_REPORT_NOTIFICATION_MARKER_VERSION,
        role="OPERATIONAL_REPORT_NOTIFICATION_CLAIM",
        alert=False,
        legacy_recovery_identity=recovery_identity or None,
        legacy_migration_marker_name=migration_name,
        legacy_marker_names=tuple(item["marker_name"] for item in legacy_markers),
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
        environ=environ if environ is not None else os.environ,
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
    "LEGACY_RECOVERY_MIGRATION_VERSION",
    "LEGACY_REPORT_NOTIFICATION_MARKER_VERSION",
    "REPORT_NOTIFICATION_MARKER_VERSION",
    "claim_degraded_alert",
    "claim_final_report_notification",
    "claim_report_notification",
]
