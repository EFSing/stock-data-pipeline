"""D1 prospective, research-only observation and immutable persistence.

The module never discovers historical samples and never writes production state.
Callers provide the point-in-time components observed for one completed session;
the store commits those bytes once and rejects a conflicting rerun.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping, Sequence


PROTOCOL_VERSION = "SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1"
SCHEMA_VERSION = "setup01-d1-session-snapshot-v1"
REQUIRED_COMPONENTS = (
    "universe_snapshot",
    "raw_source_snapshot",
    "normalized_prefix_snapshot",
    "decision_snapshot",
    "research_observation_report",
)
CAPTURE_STATUSES = {"COMPLETE", "DATA_MISSING", "LATE_SOURCE"}


class D1IntegrityError(RuntimeError):
    """Raised when an immutable identity is reused with different bytes."""


def prospective_window(market: str, activation_timestamp: datetime) -> dict[str, str]:
    """Resolve the fixed 12-calendar-month half-open window for one market."""
    if activation_timestamp.tzinfo is None or activation_timestamp.utcoffset() is None:
        raise ValueError("activation_timestamp must be timezone-aware")
    normalized = market.upper()
    if normalized not in {"CN", "US"}:
        raise ValueError("market must be CN or US")
    import exchange_calendars as xc
    import pandas as pd
    calendar = xc.get_calendar("XSHG" if normalized == "CN" else "XNYS")
    instant = pd.Timestamp(activation_timestamp)
    local_day = instant.tz_convert(calendar.tz).date()
    candidates = calendar.sessions_in_range(pd.Timestamp(local_day), pd.Timestamp(local_day + timedelta(days=14)))
    start_session = next((session for session in candidates if calendar.session_open(session) > instant), None)
    if start_session is None:
        raise ValueError("no eligible full session found after activation")
    start_date = start_session.date()
    try:
        end_boundary = start_date.replace(year=start_date.year + 1)
    except ValueError:
        end_boundary = start_date.replace(year=start_date.year + 1, day=28)
    result = {
        "market": normalized,
        "activation_timestamp": activation_timestamp.isoformat(),
        "start_session_date": start_date.isoformat(),
        "end_boundary_local_date": end_boundary.isoformat(),
    }
    try:
        sessions = calendar.sessions_in_range(start_session, pd.Timestamp(end_boundary))
        eligible = [session for session in sessions if session.date() < end_boundary]
        if not eligible:
            raise ValueError("fixed window contains no sessions")
        final_session = eligible[-1]
        result["last_eligible_session_date"] = final_session.date().isoformat()
        result["final_cutoff_bjt"] = calendar.session_close(final_session).tz_convert("Asia/Shanghai").isoformat()
        result["calendar_horizon_status"] = "RESOLVED"
    except Exception as exc:
        # Future exchange holiday schedules may not yet exist in the installed
        # calendar package. The calendar-date boundary remains frozen; the last
        # eligible session must be resolved later without extending the window.
        if exc.__class__.__name__ != "DateOutOfBounds":
            raise
        result["last_eligible_session_date"] = "PENDING_FUTURE_EXCHANGE_CALENDAR"
        result["final_cutoff_bjt"] = "PENDING_FUTURE_EXCHANGE_CALENDAR"
        result["calendar_horizon_status"] = "PENDING_FUTURE_EXCHANGE_CALENDAR"
    return result


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def content_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _aware_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("acquired_at must be timezone-aware")
    return parsed.isoformat()


def _component(value: Any) -> dict[str, Any]:
    return {"sha256": content_sha256(value), "payload": value}


def _contains_private_key(value: Any) -> bool:
    forbidden = {"holdings", "holding", "account_id", "broker_account", "broker_account_id"}
    if isinstance(value, Mapping):
        return any(str(key).lower() in forbidden or _contains_private_key(item)
                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_private_key(item) for item in value)
    return False


def build_session_snapshot(
    *,
    market: str,
    session_date: date,
    acquired_at: str,
    capture_status: str,
    source_identity: Mapping[str, Any],
    universe_snapshot: Mapping[str, Any],
    raw_source_snapshot: Mapping[str, Any],
    normalized_prefix_snapshot: Mapping[str, Any],
    decision_snapshot: Mapping[str, Any],
    research_observation_report: Mapping[str, Any],
    diagnostic_backfill: bool = False,
) -> dict[str, Any]:
    """Build a hash-bound session object without implying a real trade fill."""
    normalized_market = market.upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("market must be CN or US")
    if capture_status not in CAPTURE_STATUSES:
        raise ValueError(f"unsupported capture_status: {capture_status}")
    acquired = _aware_iso(acquired_at)
    if not (source_identity.get("provider") and source_identity.get("source_date")
            and source_identity.get("obtained_at")):
        raise ValueError("source identity requires provider, source_date and obtained_at")
    _aware_iso(str(source_identity["obtained_at"]))
    members = universe_snapshot.get("members")
    if not isinstance(members, list):
        raise ValueError("universe snapshot requires a members list")
    for member in members:
        if not isinstance(member, Mapping) or not all(key in member for key in (
                "symbol", "market", "membership_status", "source_date", "sector", "tradable")):
            raise ValueError("universe member identity is incomplete")
    if not normalized_prefix_snapshot.get("adjustment"):
        raise ValueError("normalized prefix adjustment convention is required")
    for value in (source_identity, universe_snapshot, raw_source_snapshot,
                  normalized_prefix_snapshot, decision_snapshot, research_observation_report):
        if _contains_private_key(value):
            raise ValueError("private holdings/account data is forbidden in D1 store")
    components = {
        "universe_snapshot": _component(dict(universe_snapshot)),
        "raw_source_snapshot": _component(dict(raw_source_snapshot)),
        "normalized_prefix_snapshot": _component(dict(normalized_prefix_snapshot)),
        "decision_snapshot": _component(dict(decision_snapshot)),
        "research_observation_report": _component(dict(research_observation_report)),
    }
    event_id = f"D1|{normalized_market}|{session_date.isoformat()}|SESSION_SNAPSHOT"
    prospective_eligible = capture_status == "COMPLETE" and not diagnostic_backfill
    body = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "event_id": event_id,
        "market": normalized_market,
        "session_date": session_date.isoformat(),
        "acquired_at": acquired,
        "capture_status": capture_status,
        "prospective_eligible": prospective_eligible,
        "diagnostic_backfill": bool(diagnostic_backfill),
        "source_identity": dict(source_identity),
        "data_classification": "PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
        "production_entry_allowed_written": False,
        "production_state_write": False,
        "paper_write": False,
        "broker_order": False,
        "components": components,
    }
    body["event_sha256"] = content_sha256(body)
    return body


def validate_session_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise D1IntegrityError("snapshot schema mismatch")
    if snapshot.get("protocol_version") != PROTOCOL_VERSION:
        raise D1IntegrityError("snapshot protocol mismatch")
    market = str(snapshot.get("market") or "")
    session = str(snapshot.get("session_date") or "")
    date.fromisoformat(session)
    expected_id = f"D1|{market}|{session}|SESSION_SNAPSHOT"
    if snapshot.get("event_id") != expected_id:
        raise D1IntegrityError("event identity mismatch")
    components = snapshot.get("components")
    if not isinstance(components, Mapping) or set(components) != set(REQUIRED_COMPONENTS):
        raise D1IntegrityError("snapshot components incomplete")
    for name in REQUIRED_COMPONENTS:
        item = components[name]
        if not isinstance(item, Mapping) or item.get("sha256") != content_sha256(item.get("payload")):
            raise D1IntegrityError(f"component hash mismatch: {name}")
    without_hash = dict(snapshot)
    actual = without_hash.pop("event_sha256", None)
    if actual != content_sha256(without_hash):
        raise D1IntegrityError("event hash mismatch")
    if snapshot.get("capture_status") not in CAPTURE_STATUSES:
        raise D1IntegrityError("capture status mismatch")
    eligible = snapshot.get("capture_status") == "COMPLETE" and not snapshot.get("diagnostic_backfill")
    if snapshot.get("prospective_eligible") is not eligible:
        raise D1IntegrityError("prospective eligibility mismatch")
    if snapshot.get("data_classification") != "PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS":
        raise D1IntegrityError("private/public isolation marker mismatch")


@dataclass(frozen=True)
class CommitResult:
    status: str
    event_id: str
    event_sha256: str
    commit_path: Path


class FilesystemD1Store:
    """Reference immutable store used for local/CI verification and recovery.

    A durable mounted object store may implement the same byte contract. A local
    directory or runner artifact alone is not evidence of approved persistence.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _object_path(self, digest: str) -> Path:
        return self.root / "objects" / digest[:2] / f"{digest}.json"

    def _commit_path(self, market: str, session_date: str) -> Path:
        return self.root / "sessions" / market / f"{session_date}.json"

    @staticmethod
    def _write_once(path: Path, payload: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(payload)
            return True
        except FileExistsError:
            if path.read_bytes() != payload:
                raise D1IntegrityError(f"immutable path mismatch: {path}")
            return False

    def commit(self, snapshot: Mapping[str, Any]) -> CommitResult:
        validate_session_snapshot(snapshot)
        digest = str(snapshot["event_sha256"])
        object_bytes = canonical_bytes(snapshot)
        self._write_once(self._object_path(digest), object_bytes)
        pointer = {
            "schema_version": "setup01-d1-session-commit-v1",
            "protocol_version": PROTOCOL_VERSION,
            "event_id": snapshot["event_id"],
            "event_sha256": digest,
            "market": snapshot["market"],
            "session_date": snapshot["session_date"],
            "object_relative_path": self._object_path(digest).relative_to(self.root).as_posix(),
        }
        pointer["commit_sha256"] = content_sha256(pointer)
        commit_path = self._commit_path(str(snapshot["market"]), str(snapshot["session_date"]))
        created = self._write_once(commit_path, canonical_bytes(pointer))
        return CommitResult("COMMITTED" if created else "IDEMPOTENT_REPLAY", str(snapshot["event_id"]), digest, commit_path)

    def load(self, market: str, session_date: date) -> dict[str, Any]:
        pointer = json.loads(self._commit_path(market.upper(), session_date.isoformat()).read_text(encoding="utf-8"))
        without_hash = dict(pointer)
        actual = without_hash.pop("commit_sha256", None)
        if actual != content_sha256(without_hash):
            raise D1IntegrityError("commit hash mismatch")
        object_path = self.root / pointer["object_relative_path"]
        snapshot = json.loads(object_path.read_text(encoding="utf-8"))
        validate_session_snapshot(snapshot)
        if snapshot["event_sha256"] != pointer["event_sha256"]:
            raise D1IntegrityError("commit/object hash mismatch")
        return snapshot

    def verify(self, expected_sessions: Mapping[str, Iterable[date]] | None = None) -> dict[str, Any]:
        found: dict[str, set[str]] = {"CN": set(), "US": set()}
        errors: list[str] = []
        for market in ("CN", "US"):
            directory = self.root / "sessions" / market
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    session = date.fromisoformat(path.stem)
                    self.load(market, session)
                    if path.stem in found[market]:
                        errors.append(f"DUPLICATE_SESSION:{market}:{path.stem}")
                    found[market].add(path.stem)
                except Exception as exc:
                    errors.append(f"INVALID_SESSION:{market}:{path.name}:{exc}")
        missing: list[str] = []
        if expected_sessions:
            for market, sessions in expected_sessions.items():
                for session in sessions:
                    key = session.isoformat()
                    if key not in found.get(market.upper(), set()):
                        missing.append(f"{market.upper()}:{key}")
        return {
            "status": "VERIFIED" if not errors and not missing else "FAILED",
            "protocol_version": PROTOCOL_VERSION,
            "session_counts": {market: len(values) for market, values in found.items()},
            "missing_sessions": missing,
            "errors": errors,
        }

    def recover_to(self, target: str | Path) -> dict[str, Any]:
        source_check = self.verify()
        if source_check["status"] != "VERIFIED":
            raise D1IntegrityError("source store failed verification")
        destination = Path(target)
        if destination.exists() and any(destination.iterdir()):
            raise D1IntegrityError("recovery target must be empty")
        destination.mkdir(parents=True, exist_ok=True)
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.copytree(child, destination / child.name)
            else:
                shutil.copy2(child, destination / child.name)
        recovered = FilesystemD1Store(destination).verify()
        if recovered != source_check:
            raise D1IntegrityError("recovery verification mismatch")
        return recovered


def render_research_report(snapshot: Mapping[str, Any]) -> str:
    """Render an independent Chinese research report from committed facts."""
    validate_session_snapshot(snapshot)
    report = snapshot["components"]["research_observation_report"]["payload"]
    observations = list(report.get("observations") or ())
    def count(kind: str) -> int:
        return sum(item.get("event_type") == kind for item in observations)
    lines = [
        f"# SETUP_01 D1 只读研究观察 — {snapshot['market']} {snapshot['session_date']}",
        "",
        f"状态：{snapshot['capture_status']}；前瞻合格：{'是' if snapshot['prospective_eligible'] else '否'}",
        "研究候选与正式 ENTRY_ALLOWED 严格分离；本报告不写策略池、Paper 或 broker。",
        "",
        f"- 当日新增 H1 突破：{count('H1_BREAKOUT')}",
        f"- 路径 A 延续信号 K：{count('PATH_A_SIGNAL')}",
        f"- 路径 B 回踩候选/触及/反转 K：{count('PATH_B_CANDIDATE')}/{count('PATH_B_TOUCH')}/{count('PATH_B_SIGNAL')}",
        f"- next-session 执行/跳过：{count('MODEL_EXECUTION')}/{count('MODEL_EXECUTION_SKIPPED')}",
        f"- 数据缺失/迟到：{count('DATA_MISSING')}/{count('LATE_SOURCE')}",
        "",
        "## 研究事件",
        "",
    ]
    if not observations:
        lines.append("无新增事件。")
    for item in observations:
        levels = item.get("levels") or {}
        diagnostics = item.get("diagnostics") or {}
        lines.append(
            f"- {item.get('symbol', '—')}｜{item.get('event_type', '—')}｜"
            f"支撑 {levels.get('support_zone', '—')}｜触发 {levels.get('entry_trigger', '—')}｜"
            f"上限 {levels.get('entry_ceiling', '—')}｜止损 {levels.get('stop', '—')}｜"
            f"T1 {levels.get('T1', '—')}｜5%/2R 诊断 "
            f"{diagnostics.get('five_pct_pass', '—')}/{diagnostics.get('two_r_pass', '—')}｜"
            f"模型结果 {item.get('model_outcome', '—')}"
        )
    lines.extend([
        "",
        "## 完整性",
        "",
        f"事件 ID：`{snapshot['event_id']}`  ",
        f"事件 SHA-256：`{snapshot['event_sha256']}`  ",
        f"协议：`{snapshot['protocol_version']}`",
    ])
    return "\n".join(lines) + "\n"


def session_event_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    validate_session_snapshot(snapshot)
    observations: Sequence[Mapping[str, Any]] = snapshot["components"]["research_observation_report"]["payload"].get("observations") or ()
    return {
        "market": snapshot["market"],
        "session_date": snapshot["session_date"],
        "prospective_eligible": snapshot["prospective_eligible"],
        "new_events": len(observations),
        "research_candidates": sum(bool(item.get("research_only_candidate")) for item in observations),
        "formal_entry_allowed": sum(bool(item.get("formal_entry_allowed")) for item in observations),
        "event_sha256": snapshot["event_sha256"],
    }


__all__ = [
    "CAPTURE_STATUSES", "CommitResult", "D1IntegrityError", "FilesystemD1Store",
    "PROTOCOL_VERSION", "build_session_snapshot", "canonical_bytes", "content_sha256",
    "prospective_window", "render_research_report", "session_event_summary", "validate_session_snapshot",
]
