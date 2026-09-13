"""Prospective paper-trade lifecycle and normalized performance ledger.

Paper tracking is deliberately separate from the production DecisionStateStore.
It accepts only a new CONFIRMED event whose existing individual Decision is
ENTRY_ALLOWED for SETUP_01 or SETUP_02, then reuses the frozen T+1 executors
and Position Management replay.  It does not allocate capital, approve a
production event, promote a Candidate, or submit an order.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
import math
from statistics import median
from types import SimpleNamespace
from typing import Any, Protocol

from trading.models import DecisionAction, SetupState
from trading.position_management import (
    PositionAnchor,
    PositionOrigin,
    PositionTarget,
    position_origin_from_execution,
    replay_position,
)
from trading.setup01_decision import (
    EXECUTED as SETUP01_EXECUTED,
    evaluate_setup01_decision,
    execute_setup01_t1_open,
)
from trading.setup01_replay import replay_setup01_history
from trading.setup02_decision import (
    EXECUTED as SETUP02_EXECUTED,
    evaluate_setup02_decision,
    execute_setup02_t1_open,
)
from trading.setup02_replay import replay_setup02_history
from trading.trade_logic_explanation import (
    build_trade_logic_explanation,
    explain_execution_outcome,
    explain_exit_reason,
    explain_position_day,
)


PAPER_PROTOCOL_VERSION = "PROSPECTIVE-PAPER-TRADE-LIFECYCLE-2026-09-13-v1"
PAPER_LEDGER_SHEET = "策略模拟账本"
PAPER_TRACKING_APPROVAL_POLICY = "AUTO_APPROVE_FOR_PAPER_TRACKING"
PAPER_APPROVAL_POLICY = "AUTO_APPROVE_TECHNICAL_ENTRY_ALLOWED"
PAPER_PLAN_CREATED = "PAPER_PLAN_CREATED"
PAPER_T1_EXECUTED = "PAPER_T1_EXECUTED"
PAPER_T1_SKIPPED = "PAPER_T1_SKIPPED"
PAPER_CLOSED = "PAPER_CLOSED"
PAPER_COVERAGE = "PAPER_COVERAGE"
PAPER_PLAN_STATUS = "PENDING_T1"
PAPER_OPEN_STATUS = "OPEN"
PAPER_SKIPPED_STATUS = "SKIPPED"
PAPER_CLOSED_STATUS = "CLOSED"
FORMAL_PROVENANCE = "FORMAL_STRATEGY_POOL"
CANDIDATE_PROVENANCE = "DYNAMIC_CANDIDATE"
PAPER_TRACKED_PROVENANCE = "PAPER_TRACKED"
PAPER_LEDGER_READ_ONLY = "PAPER_LEDGER_READ_ONLY"
PAPER_HISTORY_CONTINUITY_REQUIRED = "READY_FOR_DECISION_PAPER_HISTORY_CONTINUITY"
_SUPPORTED_SETUPS = {"SETUP_01", "SETUP_02"}
_EXECUTED_OUTCOMES = {SETUP01_EXECUTED, SETUP02_EXECUTED, "EXECUTED"}
_R_TOLERANCE = 1e-9


# The scalar columns make the worksheet useful to a human while payload_json
# preserves the complete immutable event contract for deterministic replay.
PAPER_LEDGER_HEADERS = (
    "event_key",
    "lifecycle_event_type",
    "paper_status",
    "event_identity",
    "symbol",
    "market",
    "name",
    "sector",
    "source_provenance",
    "source_setup",
    "signal_date",
    "expected_execution_date",
    "decision_protocol_version",
    "confirmation_level",
    "planned_entry",
    "entry_zone_low",
    "entry_zone_high",
    "structural_invalidation",
    "execution_stop",
    "initial_risk_per_share",
    "initial_rr",
    "T1",
    "T2",
    "T3",
    "target_provenance",
    "decision_gate_reason",
    "decision_gate_detail",
    "paper_approval_policy",
    "paper_tracking_approval_policy",
    "execution_date",
    "t1_open",
    "execution_outcome",
    "actual_entry",
    "actual_rr",
    "position_origin_json",
    "skip_reason",
    "terminal_status",
    "exit_date",
    "exit_price",
    "exit_reason",
    "realized_r",
    "return_pct",
    "holding_days",
    "final_mfe",
    "final_mae",
    "max_mfe_drawdown",
    "result",
    "why_entry",
    "why_execution",
    "why_hold",
    "why_exit",
    "tracking_start_date",
    "latest_processed_session",
    "coverage_status",
    "coverage_gap",
    "expected_next_session",
    "payload_json",
    "written_at",
)


class PaperLifecycleError(ValueError):
    """A paper ledger contract cannot be completed safely."""


class PaperLedgerStore(Protocol):
    def append_event(
        self,
        lifecycle_event_type: str,
        event_identity: str,
        payload: Mapping[str, Any],
    ) -> bool: ...

    def records(self) -> list[dict[str, Any]]: ...


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    if isinstance(raw, (date, datetime)):
        raw = raw.isoformat()
    result = str(raw).strip()
    return result or default


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10].replace("/", "-"))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _serialise(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _serialise(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialise(item) for item in value]
    return value

def _json(value: Any) -> str:
    return json.dumps(
        _serialise(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return _json(value)
    raw = getattr(value, "value", value)
    return raw


def _event_key(event_identity: str, lifecycle_event_type: str) -> str:
    return f"{event_identity}|{lifecycle_event_type}"


def _event_row(
    lifecycle_event_type: str,
    event_identity: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not lifecycle_event_type or not event_identity:
        raise PaperLifecycleError("paper lifecycle event requires identity and type")
    data = dict(payload)
    row = {header: "" for header in PAPER_LEDGER_HEADERS}
    row.update(
        {
            "event_key": _event_key(event_identity, lifecycle_event_type),
            "lifecycle_event_type": lifecycle_event_type,
            "paper_status": _text(data.get("paper_status")),
            "event_identity": event_identity,
            "payload_json": _json(data),
            "written_at": _cell(data.get("written_at")),
        }
    )
    for header in PAPER_LEDGER_HEADERS:
        if header in data and header not in {"payload_json", "event_key", "lifecycle_event_type"}:
            row[header] = _cell(data[header])
    return row


def _payload_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, Mapping):
        return dict(payload)
    raw = row.get("payload_json")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PaperLifecycleError("corrupted paper ledger payload_json") from exc
        if not isinstance(parsed, Mapping):
            raise PaperLifecycleError("corrupted paper ledger payload_json")
        return dict(parsed)
    return {
        str(key): value
        for key, value in row.items()
        if key not in {"payload", "payload_json"} and value not in (None, "")
    }


def _normalise_loaded_row(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    event_type = _text(data.get("lifecycle_event_type"))
    identity = _text(data.get("event_identity"))
    if not event_type or not identity:
        raise PaperLifecycleError("corrupted paper ledger identity")
    expected_key = _event_key(identity, event_type)
    actual_key = _text(data.get("event_key"), expected_key)
    if actual_key != expected_key:
        raise PaperLifecycleError("corrupted paper ledger event_key")
    data["event_key"] = expected_key
    data["payload"] = _payload_from_row(data)
    return data


class InMemoryPaperLedgerStore:
    """Deterministic fake ledger for tests and generic operational shadows."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def append_event(
        self,
        lifecycle_event_type: str,
        event_identity: str,
        payload: Mapping[str, Any],
    ) -> bool:
        row = _event_row(lifecycle_event_type, event_identity, payload)
        key = row["event_key"]
        prior = self._rows.get(key)
        if prior is not None:
            if prior.get("payload_json") != row.get("payload_json"):
                raise PaperLifecycleError(f"paper lifecycle identity conflict: {key}")
            return False
        self._rows[key] = row
        return True

    def records(self) -> list[dict[str, Any]]:
        return [dict(self._rows[key]) for key in sorted(self._rows)]

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.records())

    @property
    def event_count(self) -> int:
        return len(self._rows)


class SheetsPaperLedgerStore:
    """Append-only system-owned worksheet adapter, independent of strategy state."""

    def __init__(
        self,
        client: Any,
        *,
        write_enabled: bool = False,
        sheet_name: str = PAPER_LEDGER_SHEET,
    ) -> None:
        self.client = client
        self.write_enabled = bool(write_enabled)
        self.sheet_name = sheet_name
        self._rows: dict[str, dict[str, Any]] = {}
        if self.write_enabled and (
            callable(getattr(client, "ensure_worksheet", None))
            or getattr(client, "book", None) is not None
        ):
            self._ensure_worksheet()
        try:
            rows = list(client.records(sheet_name))
        except Exception:
            if not self.write_enabled:
                raise
            self._ensure_worksheet()
            rows = list(client.records(sheet_name))
        for raw in rows:
            row = _normalise_loaded_row(raw)
            if row["event_key"] in self._rows:
                raise PaperLifecycleError(f"duplicate persisted paper event: {row['event_key']}")
            self._rows[row["event_key"]] = row

    def _ensure_worksheet(self) -> None:
        ensure = getattr(self.client, "ensure_worksheet", None)
        if callable(ensure):
            ensure(self.sheet_name, list(PAPER_LEDGER_HEADERS))
            return
        book = getattr(self.client, "book", None)
        if book is None:
            raise PaperLifecycleError("paper ledger worksheet is missing")
        try:
            worksheet = book.worksheet(self.sheet_name)
        except Exception:
            worksheet = book.add_worksheet(
                title=self.sheet_name,
                rows="1000",
                cols=str(len(PAPER_LEDGER_HEADERS)),
            )
            worksheet.update([list(PAPER_LEDGER_HEADERS)], "A1", value_input_option="RAW")

    def append_event(
        self,
        lifecycle_event_type: str,
        event_identity: str,
        payload: Mapping[str, Any],
    ) -> bool:
        row = _event_row(lifecycle_event_type, event_identity, payload)
        key = row["event_key"]
        prior = self._rows.get(key)
        if prior is not None:
            if prior.get("payload_json") != row.get("payload_json"):
                raise PaperLifecycleError(f"paper lifecycle identity conflict: {key}")
            return False
        if not self.write_enabled:
            raise PaperLifecycleError(PAPER_LEDGER_READ_ONLY)
        append = getattr(self.client, "append_rows", None)
        if not callable(append):
            raise PaperLifecycleError("paper ledger client lacks append_rows")
        append(self.sheet_name, list(PAPER_LEDGER_HEADERS), [row])
        self._rows[key] = row
        return True

    def records(self) -> list[dict[str, Any]]:
        return [dict(self._rows[key]) for key in sorted(self._rows)]

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.records())


@dataclass(frozen=True)
class PaperPlan:
    event_identity: str
    symbol: str
    market: str
    name: str
    sector: str
    source_provenance: str
    source_setup: str
    signal_date: date
    expected_execution_date: date | None
    decision_protocol_version: str
    confirmation_level: float | None
    planned_entry: float | None
    entry_zone_low: float | None
    entry_zone_high: float | None
    structural_invalidation: float | None
    execution_stop: float | None
    initial_risk_per_share: float | None
    initial_rr: float | None
    targets: tuple[float, ...]
    target_provenance: tuple[Any, ...]
    decision_gate_reason: str
    decision_gate_detail: str
    paper_approval_policy: str = PAPER_APPROVAL_POLICY
    paper_tracking_approval_policy: str = PAPER_TRACKING_APPROVAL_POLICY
    promotion_required: bool = False
    state_persistence_eligible: bool = False
    production_execution_eligible: bool = False
    why_entry: str = ""
    logic_explanation: Mapping[str, Any] = field(default_factory=dict)
    decision: Any = field(default=None, repr=False, compare=False)
    source_event: Any = field(default=None, repr=False, compare=False)

    @property
    def status(self) -> str:
        return PAPER_PLAN_STATUS

    def to_dict(self) -> dict[str, Any]:
        return _serialise({
            "event_identity": self.event_identity,
            "symbol": self.symbol,
            "market": self.market,
            "name": self.name,
            "sector": self.sector,
            "source_provenance": self.source_provenance,
            "source_setup": self.source_setup,
            "signal_date": self.signal_date,
            "expected_execution_date": self.expected_execution_date,
            "decision_protocol_version": self.decision_protocol_version,
            "confirmation_level": self.confirmation_level,
            "planned_entry": self.planned_entry,
            "entry_zone_low": self.entry_zone_low,
            "entry_zone_high": self.entry_zone_high,
            "structural_invalidation": self.structural_invalidation,
            "execution_stop": self.execution_stop,
            "initial_risk_per_share": self.initial_risk_per_share,
            "initial_rr": self.initial_rr,
            "targets": self.targets,
            "target_provenance": self.target_provenance,
            "decision_gate_reason": self.decision_gate_reason,
            "decision_gate_detail": self.decision_gate_detail,
            "paper_approval_policy": self.paper_approval_policy,
            "paper_tracking_approval_policy": self.paper_tracking_approval_policy,
            "promotion_required": self.promotion_required,
            "state_persistence_eligible": self.state_persistence_eligible,
            "production_execution_eligible": self.production_execution_eligible,
            "why_entry": self.why_entry,
            "logic_explanation": self.logic_explanation,
        })


@dataclass(frozen=True)
class PaperCoverage:
    market: str
    tracking_start_date: date
    latest_processed_session: date
    coverage_status: str
    coverage_gap: str | None = None
    expected_next_session: date | None = None

    @property
    def continuous(self) -> bool:
        return self.coverage_status == "CONTINUOUS"

    def to_dict(self) -> dict[str, Any]:
        return _serialise({
            "market": self.market,
            "tracking_start_date": self.tracking_start_date,
            "latest_processed_session": self.latest_processed_session,
            "coverage_status": self.coverage_status,
            "coverage_gap": self.coverage_gap,
            "expected_next_session": self.expected_next_session,
            "continuous": self.continuous,
        })


@dataclass(frozen=True)
class PaperTrade:
    event_identity: str
    symbol: str
    market: str
    name: str
    sector: str
    source_provenance: str
    source_setup: str
    signal_date: date
    status: str
    expected_execution_date: date | None = None
    decision_protocol_version: str = ""
    confirmation_level: float | None = None
    planned_entry: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    structural_invalidation: float | None = None
    execution_stop: float | None = None
    initial_risk_per_share: float | None = None
    initial_rr: float | None = None
    targets: tuple[Any, ...] = ()
    target_provenance: tuple[Any, ...] = ()
    decision_gate_reason: str = ""
    decision_gate_detail: str = ""
    paper_approval_policy: str = PAPER_APPROVAL_POLICY
    paper_tracking_approval_policy: str = PAPER_TRACKING_APPROVAL_POLICY
    promotion_required: bool = False
    state_persistence_eligible: bool = False
    production_execution_eligible: bool = False
    execution_date: date | None = None
    t1_open: float | None = None
    execution_outcome: str | None = None
    actual_entry: float | None = None
    actual_rr: Any = None
    position_origin_json: str | None = None
    skip_reason: str | None = None
    terminal_status: str | None = None
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    realized_r: float | None = None
    return_pct: float | None = None
    holding_days: int | None = None
    final_mfe: float | None = None
    final_mae: float | None = None
    max_mfe_drawdown: float | None = None
    result: str | None = None
    current_r: float | None = None
    current_mfe: float | None = None
    current_mae: float | None = None
    current_mfe_drawdown: float | None = None
    current_stop: float | None = None
    target_status: str | None = None
    action: str | None = None
    position_reasons: tuple[str, ...] = ()
    why_entry: str = ""
    why_execution: str = ""
    why_hold: str = ""
    why_protect: str = ""
    why_exit: str = ""
    logic_explanation: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialise({item.name: getattr(self, item.name) for item in fields(self)})


@dataclass(frozen=True)
class PaperPerformanceStats:
    plans: int
    executed: int
    skipped: int
    open: int
    closed: int
    wins: int
    losses: int
    flats: int
    win_rate: float | None
    average_r: float | None
    median_r: float | None
    average_return_pct: float | None
    average_holding_days: float | None
    average_mfe: float | None
    average_mae: float | None

    def to_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class PaperProcessingResult:
    created_plans: tuple[PaperPlan, ...]
    executed: tuple[dict[str, Any], ...]
    skipped: tuple[dict[str, Any], ...]
    closed: tuple[dict[str, Any], ...]
    trades: tuple[PaperTrade, ...]
    coverage: tuple[PaperCoverage, ...]
    performance: PaperPerformanceStats
    grouped_performance: Mapping[str, Mapping[str, PaperPerformanceStats]]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": PAPER_PROTOCOL_VERSION,
            "created_plans": [item.to_dict() for item in self.created_plans],
            "executed": list(_serialise(self.executed)),
            "skipped": list(_serialise(self.skipped)),
            "closed": list(_serialise(self.closed)),
            "trades": [item.to_dict() for item in self.trades],
            "coverage": [item.to_dict() for item in self.coverage],
            "performance": self.performance.to_dict(),
            "grouped_performance": {
                dimension: {key: value.to_dict() for key, value in groups.items()}
                for dimension, groups in self.grouped_performance.items()
            },
            "errors": list(self.errors),
        }


def _source_setup(result: Any, decision: Any, event: Any | None = None) -> str:
    primary = _text(_field(result, "primary_wave_scenario"))
    if primary == "WAVE_2_TO_3_CANDIDATE":
        return "SETUP_01"
    if primary == "WAVE_3_CONTINUATION_CANDIDATE":
        return "SETUP_02"
    if event is not None:
        if _field(event, "setup01") is not None:
            return "SETUP_01"
        if _field(event, "setup02") is not None:
            return "SETUP_02"
    identity = _text(_field(decision, "event_identity"))
    for setup in sorted(_SUPPORTED_SETUPS):
        if setup in identity:
            return setup
    return ""


def _provenance(value: Any, result: Any) -> tuple[str, dict[str, Any]]:
    value = value if value is not None else _field(result, "provenance")
    metadata = dict(value) if isinstance(value, Mapping) else {}
    source = _text(metadata.get("source"))
    if not source:
        source = _text(value)
    if "FORMAL_STRATEGY_POOL" in source:
        return FORMAL_PROVENANCE, metadata
    if "PAPER_TRACKED" in source:
        return PAPER_TRACKED_PROVENANCE, metadata
    if "DYNAMIC_CANDIDATE" in source:
        return CANDIDATE_PROVENANCE, metadata
    return source or FORMAL_PROVENANCE, metadata


def _input_key(value: Any) -> tuple[str, str]:
    return _text(_field(value, "market")).upper(), _text(_field(value, "symbol")).upper()


def _input_history(value: Any) -> tuple[Any, ...]:
    return tuple(_field(value, "qfq_history", ()) or ())


def _name_sector(result: Any, input_value: Any, metadata: Mapping[str, Any]) -> tuple[str, str]:
    history = _input_history(input_value)
    history_name = next((_text(_field(item, "name")) for item in reversed(history) if _text(_field(item, "name"))), "")
    return (
        _text(metadata.get("name")) or _text(_field(result, "name")) or history_name,
        _text(metadata.get("sector")) or _text(_field(result, "sector")) or _text(_field(result, "industry")),
    )


def _expected_execution_date(input_value: Any, signal_date: date) -> date | None:
    session = _field(input_value, "completed_session_identity")
    value = _date(_field(session, "next_session_date"))
    if value is not None:
        return value
    dates = tuple(_date(item) for item in _field(session, "session_dates", ()) or ())
    dates = tuple(item for item in dates if item is not None)
    later = tuple(item for item in dates if item > signal_date)
    return min(later) if later else None


def _input_has_exact_qfq(input_value: Any, as_of_date: date) -> bool:
    if _text(_field(input_value, "data_quality_status")) != "DATA_OK":
        return False
    history = _input_history(input_value)
    dates = tuple(_date(_field(item, "trade_date")) for item in history)
    return bool(history) and not any(item is None for item in dates) and max(dates) == as_of_date


def _decision_action(decision: Any) -> str:
    return _text(_field(decision, "action"))


def _target_values(decision: Any) -> tuple[float, ...]:
    values = _sequence(_field(decision, "targets"))
    result: list[float] = []
    for value in values[:3]:
        numeric = _number(value)
        if numeric is not None:
            result.append(numeric)
    return tuple(result)


def _rr_values(decision: Any) -> tuple[Any, ...]:
    rr = _field(decision, "rr")
    return _sequence(_field(rr, "rr_ratios"))


def _target_provenance(decision: Any) -> tuple[Any, ...]:
    return tuple(_serialise(item) for item in _sequence(_field(decision, "target_candidates"))[:3])


def _new_event_identity(result: Any) -> str | None:
    if not bool(_field(result, "event_was_new", False)):
        return None
    direct = _text(_field(result, "new_confirmed_event_identity"))
    if direct:
        return direct
    values = _sequence(_field(result, "new_confirmed_event_identities"))
    return _text(values[0]) if values else None


def _event_from_replay(
    source_setup: str,
    event_identity: str,
    input_value: Any,
    signal_date: date,
) -> Any | None:
    history = _input_history(input_value)
    if not history:
        return None
    try:
        replay = (
            replay_setup01_history(list(history), as_of_date=signal_date)
            if source_setup == "SETUP_01"
            else replay_setup02_history(list(history), as_of_date=signal_date)
        )
    except (TypeError, ValueError):
        return None
    return next(
        (event for event in replay.events if event.event_identity == event_identity),
        None,
    )


def _build_plan(
    result: Any,
    input_value: Any,
    *,
    provenance_value: Any = None,
    event: Any | None = None,
) -> PaperPlan:
    decision = _field(result, "individual_decision")
    if decision is None or _decision_action(decision) != DecisionAction.ENTRY_ALLOWED.value:
        raise PaperLifecycleError("paper plan requires existing ENTRY_ALLOWED Decision")
    event_identity = _new_event_identity(result) or _text(_field(decision, "event_identity"))
    if not event_identity:
        raise PaperLifecycleError("paper plan requires existing event_identity")
    signal_date = _date(_field(result, "as_of_date")) or _date(_field(decision, "trade_date"))
    if signal_date is None:
        raise PaperLifecycleError("paper plan requires signal date")
    source_setup = _source_setup(result, decision, event)
    if source_setup not in _SUPPORTED_SETUPS:
        raise PaperLifecycleError("paper plan source setup is not supported")
    if event is not None:
        event_date = _date(_field(event, "trade_date"))
        if event_date is not None and event_date != signal_date:
            raise PaperLifecycleError("paper plan event date differs from signal session")
    if not _input_has_exact_qfq(input_value, signal_date):
        raise PaperLifecycleError("paper plan requires DATA_OK QFQ through signal session")
    source_provenance, metadata = _provenance(provenance_value, result)
    session_identity = _field(input_value, "completed_session_identity")
    if not bool(_field(session_identity, "exact_exchange_calendar", False)):
        raise PaperLifecycleError("paper plan requires exact exchange-calendar session")
    expected_execution_date = _expected_execution_date(input_value, signal_date)
    if expected_execution_date is None:
        raise PaperLifecycleError("paper plan requires exact T+1 market session")
    name, sector = _name_sector(result, input_value, metadata)
    symbol = _text(_field(result, "symbol")) or _text(_field(decision, "symbol"))
    market = _text(_field(result, "market")) or _text(_field(decision, "market"))
    if not symbol or not market:
        raise PaperLifecycleError("paper plan requires symbol and market")
    rr_values = _rr_values(decision)
    rr = _field(decision, "rr")
    logic = build_trade_logic_explanation(decision, source_setup=source_setup, event=event)
    return PaperPlan(
        event_identity=event_identity,
        symbol=symbol,
        market=market,
        name=name,
        sector=sector,
        source_provenance=source_provenance,
        source_setup=source_setup,
        signal_date=signal_date,
        expected_execution_date=expected_execution_date,
        decision_protocol_version=_text(_field(decision, "protocol_version")),
        confirmation_level=_number(_field(decision, "confirmation_level")),
        planned_entry=_number(_field(decision, "planned_entry")),
        entry_zone_low=_number(_field(decision, "entry_zone_low")),
        entry_zone_high=_number(_field(decision, "entry_zone_high")),
        structural_invalidation=_number(_field(decision, "structural_invalidation")),
        execution_stop=_number(_field(decision, "execution_stop")),
        initial_risk_per_share=_number(_field(rr, "risk_per_share")),
        initial_rr=_number(rr_values[0] if rr_values else None),
        targets=_target_values(decision),
        target_provenance=_target_provenance(decision),
        decision_gate_reason=_text(_field(decision, "gate_reason")),
        decision_gate_detail=_text(_field(decision, "gate_detail")),
        promotion_required=bool(metadata.get("promotion_required", source_provenance == CANDIDATE_PROVENANCE)),
        state_persistence_eligible=bool(metadata.get("state_persistence_eligible", source_provenance == FORMAL_PROVENANCE)),
        production_execution_eligible=bool(metadata.get("production_execution_eligible", source_provenance == FORMAL_PROVENANCE)),
        why_entry=logic.why_plan,
        logic_explanation=logic.to_dict(),
        decision=decision,
        source_event=event,
    )


def _plan_payload(plan: PaperPlan) -> dict[str, Any]:
    return {
        "paper_status": PAPER_PLAN_STATUS,
        **plan.to_dict(),
        "lifecycle_event_type": PAPER_PLAN_CREATED,
        "event_key": _event_key(plan.event_identity, PAPER_PLAN_CREATED),
    }


def _plan_from_payload(payload: Mapping[str, Any]) -> PaperPlan:
    targets = tuple(_number(item) for item in _sequence(payload.get("targets")))
    targets = tuple(item for item in targets if item is not None)
    return PaperPlan(
        event_identity=_text(payload.get("event_identity")),
        symbol=_text(payload.get("symbol")),
        market=_text(payload.get("market")),
        name=_text(payload.get("name")),
        sector=_text(payload.get("sector")),
        source_provenance=_text(payload.get("source_provenance")),
        source_setup=_text(payload.get("source_setup")),
        signal_date=_date(payload.get("signal_date")) or date.min,
        expected_execution_date=_date(payload.get("expected_execution_date")),
        decision_protocol_version=_text(payload.get("decision_protocol_version")),
        confirmation_level=_number(payload.get("confirmation_level")),
        planned_entry=_number(payload.get("planned_entry")),
        entry_zone_low=_number(payload.get("entry_zone_low")),
        entry_zone_high=_number(payload.get("entry_zone_high")),
        structural_invalidation=_number(payload.get("structural_invalidation")),
        execution_stop=_number(payload.get("execution_stop")),
        initial_risk_per_share=_number(payload.get("initial_risk_per_share")),
        initial_rr=_number(payload.get("initial_rr")),
        targets=targets,
        target_provenance=tuple(_sequence(payload.get("target_provenance"))),
        decision_gate_reason=_text(payload.get("decision_gate_reason")),
        decision_gate_detail=_text(payload.get("decision_gate_detail")),
        paper_approval_policy=_text(payload.get("paper_approval_policy"), PAPER_APPROVAL_POLICY),
        paper_tracking_approval_policy=_text(
            payload.get("paper_tracking_approval_policy"), PAPER_TRACKING_APPROVAL_POLICY
        ),
        promotion_required=bool(payload.get("promotion_required", False)),
        state_persistence_eligible=bool(payload.get("state_persistence_eligible", False)),
        production_execution_eligible=bool(payload.get("production_execution_eligible", False)),
        why_entry=_text(payload.get("why_entry")),
        logic_explanation=dict(payload.get("logic_explanation") or {}),
    )


def _decision_for_plan(plan: PaperPlan) -> Any:
    candidates = []
    for item in plan.target_provenance:
        if isinstance(item, Mapping):
            candidates.append(SimpleNamespace(
                price=_number(item.get("price")),
                source=_text(item.get("source"), "PERSISTED_TARGET"),
                reason=_text(item.get("reason")),
                provenance=tuple(item.get("provenance") or ()),
            ))
    if len(candidates) != len(plan.targets):
        candidates = [
            SimpleNamespace(price=price, source="PERSISTED_TARGET", reason="", provenance=())
            for price in plan.targets
        ]
    rr = SimpleNamespace(
        rr_ratios=(plan.initial_rr,) if plan.initial_rr is not None else (),
        risk_per_share=plan.initial_risk_per_share,
    )
    return SimpleNamespace(
        protocol_version=plan.decision_protocol_version,
        event_identity=plan.event_identity,
        symbol=plan.symbol,
        market=plan.market,
        trade_date=plan.signal_date,
        event_type=SetupState.CONFIRMED,
        action=DecisionAction.ENTRY_ALLOWED,
        confirmation_level=plan.confirmation_level,
        planned_entry=plan.planned_entry,
        entry_zone_low=plan.entry_zone_low,
        entry_zone_high=plan.entry_zone_high,
        structural_invalidation=plan.structural_invalidation,
        execution_stop=plan.execution_stop,
        targets=plan.targets,
        target_candidates=tuple(candidates),
        rr=rr,
    )


def _origin_to_dict(origin: PositionOrigin) -> dict[str, Any]:
    return {
        "source_setup": origin.source_setup,
        "source_event_identity": origin.source_event_identity,
        "symbol": origin.symbol,
        "market": origin.market,
        "entry_date": origin.entry_date.isoformat(),
        "actual_entry": origin.actual_entry,
        "initial_execution_stop": origin.initial_execution_stop,
        "initial_structural_invalidation": origin.initial_structural_invalidation,
        "initial_risk_per_share": origin.initial_risk_per_share,
        "targets": [
            {
                "price": target.price,
                "source": target.source,
                "provenance": [_serialise(item) for item in target.provenance],
            }
            for target in origin.targets
        ],
        "wave_anchors": [
            {
                "name": anchor.name,
                "kind": anchor.kind,
                "price": anchor.price,
                "pivot_index": anchor.pivot_index,
                "pivot_date": anchor.pivot_date.isoformat(),
                "confirmed_index": anchor.confirmed_index,
                "confirmed_date": anchor.confirmed_date.isoformat() if anchor.confirmed_date else None,
            }
            for anchor in origin.wave_anchors
        ],
    }


def _origin_from_dict(value: Any) -> PositionOrigin:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise PaperLifecycleError("serialized PositionOrigin is malformed")
    targets = tuple(
        PositionTarget(
            price=float(item["price"]),
            source=str(item["source"]),
            provenance=tuple(item.get("provenance") or ()),
        )
        for item in value.get("targets", ())
    )
    anchors = tuple(
        PositionAnchor(
            name=str(item["name"]),
            kind=str(item["kind"]),
            price=float(item["price"]),
            pivot_index=int(item["pivot_index"]),
            pivot_date=_date(item["pivot_date"]) or date.min,
            confirmed_index=(int(item["confirmed_index"]) if item.get("confirmed_index") is not None else None),
            confirmed_date=_date(item.get("confirmed_date")),
        )
        for item in value.get("wave_anchors", ())
    )
    try:
        return PositionOrigin(
            source_setup=str(value["source_setup"]),
            source_event_identity=str(value["source_event_identity"]),
            symbol=str(value["symbol"]),
            market=str(value["market"]),
            entry_date=_date(value["entry_date"]) or date.min,
            actual_entry=float(value["actual_entry"]),
            initial_execution_stop=float(value["initial_execution_stop"]),
            initial_structural_invalidation=float(value["initial_structural_invalidation"]),
            targets=targets,
            wave_anchors=anchors,
            initial_risk_per_share=float(value["initial_risk_per_share"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperLifecycleError("serialized PositionOrigin is malformed") from exc


def _group_events(store: PaperLedgerStore) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = defaultdict(dict)
    for raw in store.records():
        row = _normalise_loaded_row(raw)
        identity = _text(row.get("event_identity"))
        event_type = _text(row.get("lifecycle_event_type"))
        groups[identity][event_type] = row["payload"]
    return dict(groups)


def _trade_from_group(
    identity: str,
    group: Mapping[str, Any],
    override: Mapping[str, Any] | None = None,
) -> PaperTrade | None:
    plan = group.get(PAPER_PLAN_CREATED)
    if not isinstance(plan, Mapping):
        return None
    executed = group.get(PAPER_T1_EXECUTED, {})
    skipped = group.get(PAPER_T1_SKIPPED, {})
    closed = group.get(PAPER_CLOSED, {})
    plan = dict(plan)
    executed = dict(executed) if isinstance(executed, Mapping) else {}
    skipped = dict(skipped) if isinstance(skipped, Mapping) else {}
    closed = dict(closed) if isinstance(closed, Mapping) else {}
    override = dict(override or {})
    if closed:
        status = PAPER_CLOSED_STATUS
    elif skipped:
        status = PAPER_SKIPPED_STATUS
    elif executed:
        status = PAPER_OPEN_STATUS
    else:
        status = PAPER_PLAN_STATUS
    data: dict[str, Any] = {}
    data.update(plan)
    data.update(executed)
    data.update(skipped)
    data.update(closed)
    data.update(override)
    source_setup = _text(data.get("source_setup"))
    why_entry = _text(data.get("why_entry"))
    why_execution = _text(data.get("why_execution"))
    if not why_execution:
        why_execution = explain_execution_outcome(data.get("execution_outcome")) if executed else (
            _text(data.get("skip_reason")) or "等待 exact T+1 market-session OPEN"
        )
    why_exit = _text(data.get("why_exit"))
    if not why_exit and closed:
        why_exit = explain_exit_reason(data.get("exit_reason"))
    return PaperTrade(
        event_identity=identity,
        symbol=_text(data.get("symbol")),
        market=_text(data.get("market")),
        name=_text(data.get("name")),
        sector=_text(data.get("sector")),
        source_provenance=_text(data.get("source_provenance")),
        source_setup=source_setup,
        signal_date=_date(data.get("signal_date")) or date.min,
        status=status,
        expected_execution_date=_date(data.get("expected_execution_date")),
        decision_protocol_version=_text(data.get("decision_protocol_version")),
        confirmation_level=_number(data.get("confirmation_level")),
        planned_entry=_number(data.get("planned_entry")),
        entry_zone_low=_number(data.get("entry_zone_low")),
        entry_zone_high=_number(data.get("entry_zone_high")),
        structural_invalidation=_number(data.get("structural_invalidation")),
        execution_stop=_number(data.get("execution_stop")),
        initial_risk_per_share=_number(data.get("initial_risk_per_share")),
        initial_rr=_number(data.get("initial_rr")),
        targets=tuple(_sequence(data.get("targets"))),
        target_provenance=tuple(_sequence(data.get("target_provenance"))),
        decision_gate_reason=_text(data.get("decision_gate_reason")),
        decision_gate_detail=_text(data.get("decision_gate_detail")),
        paper_approval_policy=_text(data.get("paper_approval_policy"), PAPER_APPROVAL_POLICY),
        paper_tracking_approval_policy=_text(
            data.get("paper_tracking_approval_policy"), PAPER_TRACKING_APPROVAL_POLICY
        ),
        promotion_required=bool(data.get("promotion_required", False)),
        state_persistence_eligible=bool(data.get("state_persistence_eligible", False)),
        production_execution_eligible=bool(data.get("production_execution_eligible", False)),
        execution_date=_date(data.get("execution_date")),
        t1_open=_number(data.get("t1_open")),
        execution_outcome=_text(data.get("execution_outcome")) or None,
        actual_entry=_number(data.get("actual_entry")),
        actual_rr=data.get("actual_rr"),
        position_origin_json=_text(data.get("position_origin_json")) or None,
        skip_reason=_text(data.get("skip_reason")) or None,
        terminal_status=_text(data.get("terminal_status")) or None,
        exit_date=_date(data.get("exit_date")),
        exit_price=_number(data.get("exit_price")),
        exit_reason=_text(data.get("exit_reason")) or None,
        realized_r=_number(data.get("realized_r")),
        return_pct=_number(data.get("return_pct")),
        holding_days=(int(data["holding_days"]) if data.get("holding_days") not in (None, "") else None),
        final_mfe=_number(data.get("final_mfe")),
        final_mae=_number(data.get("final_mae")),
        max_mfe_drawdown=_number(data.get("max_mfe_drawdown")),
        result=_text(data.get("result")) or None,
        current_r=_number(data.get("current_r")),
        current_mfe=_number(data.get("current_mfe")),
        current_mae=_number(data.get("current_mae")),
        current_mfe_drawdown=_number(data.get("current_mfe_drawdown")),
        current_stop=_number(data.get("current_stop")),
        target_status=_text(data.get("target_status")) or None,
        action=_text(data.get("action")) or None,
        position_reasons=tuple(_text(item) for item in _sequence(data.get("position_reasons")) if _text(item)),
        why_entry=why_entry,
        why_execution=why_execution,
        why_hold=_text(data.get("why_hold")),
        why_protect=_text(data.get("why_protect")),
        why_exit=why_exit,
        logic_explanation=dict(data.get("logic_explanation") or {}),
    )


def paper_trades(store: PaperLedgerStore, *, overrides: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[PaperTrade, ...]:
    overrides = overrides or {}
    values = [
        _trade_from_group(identity, group, overrides.get(identity))
        for identity, group in _group_events(store).items()
    ]
    return tuple(sorted((value for value in values if value is not None), key=lambda item: (item.signal_date, item.event_identity)))


def active_paper_symbols(store: PaperLedgerStore) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (trade.market.upper(), trade.symbol.upper())
                for trade in paper_trades(store)
                if trade.status in {PAPER_PLAN_STATUS, PAPER_OPEN_STATUS}
            }
        )
    )


def _trade_matches(trade: PaperTrade, filters: Mapping[str, Any] | None) -> bool:
    for key, value in (filters or {}).items():
        if value in (None, "", (), []):
            continue
        actual = {
            "setup": trade.source_setup,
            "source_setup": trade.source_setup,
            "market": trade.market.upper(),
            "provenance": trade.source_provenance,
            "source_provenance": trade.source_provenance,
            "status": trade.status,
        }.get(key)
        if actual != value:
            return False
    return True


def _classify_r(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if abs(value) <= _R_TOLERANCE:
        return "FLAT"
    return "WIN" if value > 0 else "LOSS"


def calculate_performance(
    values: Iterable[PaperTrade | Mapping[str, Any]],
    *,
    filters: Mapping[str, Any] | None = None,
) -> PaperPerformanceStats:
    trades = [value if isinstance(value, PaperTrade) else _trade_from_mapping(value) for value in values]
    trades = [trade for trade in trades if trade is not None and _trade_matches(trade, filters)]
    closed = [trade for trade in trades if trade.status == PAPER_CLOSED_STATUS]
    rs = [trade.realized_r for trade in closed if trade.realized_r is not None]
    returns = [trade.return_pct for trade in closed if trade.return_pct is not None]
    holding = [float(trade.holding_days) for trade in closed if trade.holding_days is not None]
    mfe = [trade.final_mfe for trade in closed if trade.final_mfe is not None]
    mae = [trade.final_mae for trade in closed if trade.final_mae is not None]
    classifications = [_classify_r(value) for value in rs]
    wins = classifications.count("WIN")
    losses = classifications.count("LOSS")
    flats = classifications.count("FLAT")
    denominator = wins + losses
    return PaperPerformanceStats(
        plans=len(trades),
        executed=sum(trade.status in {PAPER_OPEN_STATUS, PAPER_CLOSED_STATUS} for trade in trades),
        skipped=sum(trade.status == PAPER_SKIPPED_STATUS for trade in trades),
        open=sum(trade.status == PAPER_OPEN_STATUS for trade in trades),
        closed=len(closed),
        wins=wins,
        losses=losses,
        flats=flats,
        win_rate=(wins / denominator if denominator else None),
        average_r=(sum(rs) / len(rs) if rs else None),
        median_r=(float(median(rs)) if rs else None),
        average_return_pct=(sum(returns) / len(returns) if returns else None),
        average_holding_days=(sum(holding) / len(holding) if holding else None),
        average_mfe=(sum(mfe) / len(mfe) if mfe else None),
        average_mae=(sum(mae) / len(mae) if mae else None),
    )


def _trade_from_mapping(value: Mapping[str, Any]) -> PaperTrade | None:
    if not value.get("event_identity"):
        return None
    data = dict(value)
    allowed = {item.name for item in fields(PaperTrade)}
    data = {key: item for key, item in data.items() if key in allowed}
    if not data.get("signal_date"):
        data["signal_date"] = date.min
    for key in ("signal_date", "expected_execution_date", "execution_date", "exit_date"):
        if key in data:
            data[key] = _date(data[key])
    for key in (
        "confirmation_level", "planned_entry", "entry_zone_low", "entry_zone_high",
        "structural_invalidation", "execution_stop", "initial_risk_per_share",
        "initial_rr", "t1_open", "actual_entry", "exit_price", "realized_r",
        "return_pct", "final_mfe", "final_mae", "max_mfe_drawdown", "current_r",
        "current_mfe", "current_mae", "current_mfe_drawdown", "current_stop",
    ):
        if key in data:
            data[key] = _number(data[key])
    return PaperTrade(
        event_identity=str(data["event_identity"]),
        symbol=_text(data.get("symbol")),
        market=_text(data.get("market")),
        name=_text(data.get("name")),
        sector=_text(data.get("sector")),
        source_provenance=_text(data.get("source_provenance")),
        source_setup=_text(data.get("source_setup")),
        signal_date=data["signal_date"],
        status=_text(data.get("status"), PAPER_PLAN_STATUS),
        **{key: value for key, value in data.items() if key not in {
            "event_identity", "symbol", "market", "name", "sector", "source_provenance",
            "source_setup", "signal_date", "status",
        }},
    )


def grouped_performance(values: Iterable[PaperTrade],) -> dict[str, dict[str, PaperPerformanceStats]]:
    trades = tuple(values)
    dimensions = {
        "setup": lambda item: item.source_setup,
        "market": lambda item: item.market.upper(),
        "provenance": lambda item: item.source_provenance,
    }
    output: dict[str, dict[str, PaperPerformanceStats]] = {}
    for dimension, key_fn in dimensions.items():
        buckets: dict[str, list[PaperTrade]] = defaultdict(list)
        for trade in trades:
            key = key_fn(trade)
            if key:
                buckets[key].append(trade)
        output[dimension] = {
            key: calculate_performance(bucket)
            for key, bucket in sorted(buckets.items())
        }
    return output


def _latest_coverages(store: PaperLedgerStore) -> dict[str, PaperCoverage]:
    by_market: dict[str, PaperCoverage] = {}
    historical_gaps: dict[str, str] = {}
    for raw in store.records():
        row = _normalise_loaded_row(raw)
        if _text(row.get("lifecycle_event_type")) != PAPER_COVERAGE:
            continue
        payload = row["payload"]
        market = _text(payload.get("market")).upper()
        latest = _date(payload.get("latest_processed_session"))
        start = _date(payload.get("tracking_start_date"))
        if not market or latest is None or start is None:
            continue
        candidate = PaperCoverage(
            market=market,
            tracking_start_date=start,
            latest_processed_session=latest,
            coverage_status=_text(payload.get("coverage_status"), "GAP_DETECTED"),
            coverage_gap=_text(payload.get("coverage_gap")) or None,
            expected_next_session=_date(payload.get("expected_next_session")),
        )
        if candidate.coverage_status != "CONTINUOUS" or candidate.coverage_gap:
            historical_gaps[market] = candidate.coverage_gap or "historical coverage gap detected"
        prior = by_market.get(market)
        if prior is None or candidate.latest_processed_session >= prior.latest_processed_session:
            by_market[market] = candidate
    for market, coverage in tuple(by_market.items()):
        gap = historical_gaps.get(market)
        if gap and coverage.coverage_status == "CONTINUOUS":
            by_market[market] = PaperCoverage(
                market=coverage.market,
                tracking_start_date=coverage.tracking_start_date,
                latest_processed_session=coverage.latest_processed_session,
                coverage_status="GAP_DETECTED",
                coverage_gap=gap,
                expected_next_session=coverage.expected_next_session,
            )
    return by_market


class PaperLifecycleEngine:
    """Advance paper plans and replay active positions causally."""

    def __init__(self, store: PaperLedgerStore) -> None:
        self.store = store
        self._runtime_decisions: dict[str, Any] = {}
        self._runtime_events: dict[str, Any] = {}
        self._overrides: dict[str, dict[str, Any]] = {}

    def _record_coverage(self, market: str, input_value: Any, as_of_date: date) -> PaperCoverage:
        market = market.upper()
        prior = _latest_coverages(self.store).get(market)
        expected_next = _expected_execution_date(input_value, as_of_date)
        exact_qfq = _input_has_exact_qfq(input_value, as_of_date)
        qfq_gap = None if exact_qfq else (
            f"paper input is not DATA_OK at {as_of_date.isoformat()}"
        )
        if prior is None:
            start = as_of_date
            status = "CONTINUOUS" if exact_qfq else "GAP_DETECTED"
            gap = qfq_gap
        elif as_of_date <= prior.latest_processed_session:
            return prior
        else:
            start = min(prior.tracking_start_date, as_of_date)
            status = (
                "CONTINUOUS"
                if exact_qfq and prior.expected_next_session == as_of_date
                else "GAP_DETECTED"
            )
            gap = None if status == "CONTINUOUS" else "; ".join(
                part for part in (
                    (
                        f"expected {prior.expected_next_session.isoformat() if prior.expected_next_session else 'unknown'} "
                        f"but processed {as_of_date.isoformat()}"
                        if prior.expected_next_session != as_of_date
                        else None
                    ),
                    qfq_gap,
                )
                if part
            )
            if not gap:
                gap = (
                    f"expected {prior.expected_next_session.isoformat() if prior.expected_next_session else 'unknown'} "
                    f"but processed {as_of_date.isoformat()}"
                )
            if prior.coverage_status != "CONTINUOUS":
                status = "GAP_DETECTED"
                gap = prior.coverage_gap or "historical coverage gap detected"
        coverage = PaperCoverage(
            market=market,
            tracking_start_date=start,
            latest_processed_session=as_of_date,
            coverage_status=status,
            coverage_gap=gap,
            expected_next_session=expected_next,
        )
        payload = {
            "paper_status": "COVERAGE",
            **coverage.to_dict(),
            "event_identity": f"COVERAGE|{market}|{as_of_date.isoformat()}",
        }
        self.store.append_event(
            PAPER_COVERAGE,
            payload["event_identity"],
            payload,
        )
        return coverage

    def _advance_pending(
        self,
        trade: PaperTrade,
        input_value: Any,
        *,
        as_of_date: date,
        executed_rows: list[dict[str, Any]],
        skipped_rows: list[dict[str, Any]],
        closed_rows: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        expected = trade.expected_execution_date
        if expected is None:
            errors.append(f"{trade.event_identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:exact T+1 session missing")
            return
        if as_of_date < expected:
            return
        session_identity = _field(input_value, "completed_session_identity")
        if not bool(_field(session_identity, "exact_exchange_calendar", False)):
            errors.append(f"{trade.event_identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:exact calendar missing")
            return
        plan = _plan_from_payload(
            _group_events(self.store)[trade.event_identity][PAPER_PLAN_CREATED]
        )
        decision = self._runtime_decisions.get(trade.event_identity) or _decision_for_plan(plan)
        sessions = (trade.signal_date, expected) if expected is not None else (trade.signal_date,)
        try:
            execution = (
                execute_setup01_t1_open(decision, _input_history(input_value), market_session_dates={trade.market: sessions})
                if trade.source_setup == "SETUP_01"
                else execute_setup02_t1_open(decision, _input_history(input_value), market_session_dates={trade.market: sessions})
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"{trade.event_identity}:T1_EXECUTION_FAILED:{exc}")
            return
        if execution.outcome not in _EXECUTED_OUTCOMES:
            payload = {
                "paper_status": PAPER_SKIPPED_STATUS,
                "event_identity": trade.event_identity,
                "symbol": trade.symbol,
                "market": trade.market,
                "source_setup": trade.source_setup,
                "signal_date": trade.signal_date,
                "expected_execution_date": trade.expected_execution_date,
                "execution_date": execution.execution_date,
                "t1_open": execution.t1_open,
                "execution_outcome": execution.outcome,
                "skip_reason": explain_execution_outcome(execution.outcome),
                "terminal_status": PAPER_SKIPPED_STATUS,
                "why_execution": explain_execution_outcome(execution.outcome),
            }
            if self.store.append_event(PAPER_T1_SKIPPED, trade.event_identity, payload):
                skipped_rows.append(payload)
            return
        event = plan.source_event or self._runtime_events.get(trade.event_identity)
        if event is None:
            event = _event_from_replay(trade.source_setup, trade.event_identity, input_value, trade.signal_date)
        if event is None:
            errors.append(f"{trade.event_identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:source event unavailable for PositionOrigin")
            return
        try:
            origin = position_origin_from_execution(trade.source_setup, event, decision, execution)
            if origin is None:
                raise PaperLifecycleError("EXECUTED execution did not produce PositionOrigin")
        except (TypeError, ValueError, PaperLifecycleError) as exc:
            errors.append(f"{trade.event_identity}:POSITION_ORIGIN_REQUIRED:{exc}")
            return
        actual_rr = _serialise(_field(execution, "actual_rr"))
        payload = {
            "paper_status": PAPER_OPEN_STATUS,
            "event_identity": trade.event_identity,
            "symbol": trade.symbol,
            "market": trade.market,
            "source_setup": trade.source_setup,
            "execution_date": execution.execution_date,
            "t1_open": execution.t1_open,
            "execution_outcome": execution.outcome,
            "actual_entry": execution.actual_entry,
            "actual_rr": actual_rr,
            "position_origin_json": _json(_origin_to_dict(origin)),
            "why_execution": explain_execution_outcome(execution.outcome),
        }
        if self.store.append_event(PAPER_T1_EXECUTED, trade.event_identity, payload):
            executed_rows.append(payload)
        self._runtime_decisions[trade.event_identity] = decision
        self._runtime_events[trade.event_identity] = event
        self._advance_open(trade.event_identity, input_value, as_of_date, closed_rows, errors)

    def _advance_open(
        self,
        identity: str,
        input_value: Any,
        as_of_date: date,
        closed_rows: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        group = _group_events(self.store).get(identity, {})
        executed = group.get(PAPER_T1_EXECUTED)
        if not isinstance(executed, Mapping):
            return
        try:
            session_identity = _field(input_value, "completed_session_identity")
            if not bool(_field(session_identity, "exact_exchange_calendar", False)):
                raise PaperLifecycleError("exact exchange-calendar session missing")
            origin = _origin_from_dict(executed.get("position_origin_json"))
            history = tuple(
                item for item in _input_history(input_value)
                if (_date(_field(item, "trade_date")) or date.max) <= as_of_date
            )
            history_dates = tuple(_date(_field(item, "trade_date")) for item in history)
            if (
                not history
                or any(item is None for item in history_dates)
                or max(history_dates) != as_of_date
            ):
                raise PaperLifecycleError("QFQ history does not reach current completed session")
            replay = replay_position(origin, history)
        except (TypeError, ValueError, PaperLifecycleError) as exc:
            errors.append(f"{identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:{exc}")
            return
        if not replay.days:
            return
        day = replay.days[-1]
        self._overrides[identity] = {
            "current_r": day.current_r,
            "current_mfe": day.mfe_r,
            "current_mae": day.mae_r,
            "current_mfe_drawdown": day.mfe_drawdown_r,
            "current_stop": replay.final_active_stop,
            "target_status": day.target_status.value,
            "action": day.action.value,
            "position_reasons": tuple(day.secondary_reasons),
            "why_hold": explain_position_day(day)[0],
            "why_protect": explain_position_day(day)[1],
            "why_exit": explain_position_day(day)[2],
        }
        if replay.exit_date is None:
            return
        actual_entry = _number(executed.get("actual_entry"))
        risk = _number(_group_events(self.store)[identity].get(PAPER_PLAN_CREATED, {}).get("initial_risk_per_share"))
        exit_price = replay.exit_price
        if actual_entry is None or risk is None or risk <= 0 or exit_price is None:
            errors.append(f"{identity}:CLOSED_PERFORMANCE_FACTS_MISSING")
            return
        realized_r = (float(exit_price) - actual_entry) / risk
        return_pct = float(exit_price) / actual_entry - 1.0
        mfe_values = [day_value.mfe_r for day_value in replay.days]
        mae_values = [day_value.mae_r for day_value in replay.days]
        drawdowns = [day_value.mfe_drawdown_r for day_value in replay.days]
        result = _classify_r(realized_r)
        payload = {
            "paper_status": PAPER_CLOSED_STATUS,
            "event_identity": identity,
            "symbol": origin.symbol,
            "market": origin.market,
            "source_setup": origin.source_setup,
            "exit_date": replay.exit_date,
            "exit_price": exit_price,
            "exit_reason": replay.exit_reason.value if replay.exit_reason else None,
            "realized_r": realized_r,
            "return_pct": return_pct,
            "holding_days": replay.position_days,
            "final_mfe": mfe_values[-1] if mfe_values else None,
            "final_mae": mae_values[-1] if mae_values else None,
            "max_mfe_drawdown": max(drawdowns) if drawdowns else None,
            "result": result,
            "why_exit": explain_exit_reason(replay.exit_reason),
        }
        if self.store.append_event(PAPER_CLOSED, identity, payload):
            closed_rows.append(payload)

    def process_daily(
        self,
        results: Iterable[Any],
        inputs: Iterable[Any],
        *,
        as_of_date: date,
        provenance_by_symbol: Mapping[str, Any] | None = None,
        events_by_identity: Mapping[str, Any] | None = None,
    ) -> PaperProcessingResult:
        """Process one completed session without historical backfill."""

        result_values = tuple(results)
        input_values = tuple(inputs)
        input_by_key = {_input_key(item): item for item in input_values}
        provenance_by_symbol = provenance_by_symbol or {}
        events_by_identity = events_by_identity or {}
        created: list[PaperPlan] = []
        executed_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        closed_rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for result in result_values:
            identity = _new_event_identity(result)
            if not identity:
                continue
            if _date(_field(result, "as_of_date")) != as_of_date:
                errors.append(
                    f"{identity}:PAPER_PLAN_REJECTED:new CONFIRMED must be processed on signal session"
                )
                continue
            decision = _field(result, "individual_decision")
            if decision is None or _decision_action(decision) != DecisionAction.ENTRY_ALLOWED.value:
                continue
            symbol_key = (
                _text(_field(result, "market")).upper(),
                _text(_field(result, "symbol")).upper(),
            )
            input_value = input_by_key.get(symbol_key)
            if input_value is None:
                errors.append(f"{identity}:PAPER_INPUT_MISSING")
                continue
            explicit_event = events_by_identity.get(identity)
            event = explicit_event or _field(result, "selected_event")
            if event is None:
                source_setup = _source_setup(result, decision)
                event = _event_from_replay(
                    source_setup,
                    identity,
                    input_value,
                    _date(_field(result, "as_of_date")) or as_of_date,
                )
            provenance_value = provenance_by_symbol.get(symbol_key)
            if provenance_value is None:
                provenance_value = provenance_by_symbol.get(symbol_key[1])
            try:
                plan = _build_plan(
                    result,
                    input_value,
                    provenance_value=provenance_value,
                    event=event,
                )
            except (TypeError, ValueError, PaperLifecycleError) as exc:
                errors.append(f"{identity}:PAPER_PLAN_REJECTED:{exc}")
                continue
            self._runtime_decisions[identity] = decision
            if event is not None:
                self._runtime_events[identity] = event
            if self.store.append_event(PAPER_PLAN_CREATED, identity, _plan_payload(plan)):
                created.append(plan)
        # Re-read the append-only view so the plan created above participates
        # in the same T-day/T+1 replay pass.
        for trade in paper_trades(self.store):
            if trade.status == PAPER_PLAN_STATUS:
                input_value = input_by_key.get((trade.market.upper(), trade.symbol.upper()))
                if input_value is None:
                    errors.append(
                        f"{trade.event_identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:active paper input missing"
                    )
                else:
                    self._advance_pending(
                        trade,
                        input_value,
                        as_of_date=as_of_date,
                        executed_rows=executed_rows,
                        skipped_rows=skipped_rows,
                        closed_rows=closed_rows,
                        errors=errors,
                    )
            elif trade.status == PAPER_OPEN_STATUS:
                input_value = input_by_key.get((trade.market.upper(), trade.symbol.upper()))
                if input_value is None:
                    errors.append(
                        f"{trade.event_identity}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:active paper input missing"
                    )
                else:
                    self._advance_open(trade.event_identity, input_value, as_of_date, closed_rows, errors)
        coverage_by_market: dict[str, PaperCoverage] = {}
        for input_value in input_values:
            market = _text(_field(input_value, "market")).upper()
            session_identity = _field(input_value, "completed_session_identity")
            if not bool(_field(session_identity, "exact_exchange_calendar", False)):
                if market:
                    errors.append(
                        f"{market}:{PAPER_HISTORY_CONTINUITY_REQUIRED}:exact calendar missing"
                    )
                continue
            if market and market not in coverage_by_market:
                coverage_by_market[market] = self._record_coverage(market, input_value, as_of_date)
        trades = paper_trades(self.store, overrides=self._overrides)
        performance = calculate_performance(trades)
        return PaperProcessingResult(
            created_plans=tuple(created),
            executed=tuple(executed_rows),
            skipped=tuple(skipped_rows),
            closed=tuple(closed_rows),
            trades=trades,
            coverage=tuple(coverage_by_market[market] for market in sorted(coverage_by_market)),
            performance=performance,
            grouped_performance=grouped_performance(trades),
            errors=tuple(dict.fromkeys(errors)),
        )

    def process_report(self, report: Any, inputs: Iterable[Any], **kwargs: Any) -> PaperProcessingResult:
        """Convenience adapter for a DailyTradingDecisionReport."""

        values = _field(report, "results")
        as_of_date = kwargs.pop("as_of_date", None) or _date(_field(report, "as_of_date"))
        if as_of_date is None:
            raise PaperLifecycleError("paper report requires as_of_date")
        return self.process_daily(values or (), inputs, as_of_date=as_of_date, **kwargs)

    def dashboard_payload(self, result: PaperProcessingResult | None = None) -> dict[str, Any]:
        if result is None:
            trades = paper_trades(self.store, overrides=self._overrides)
            result = PaperProcessingResult(
                created_plans=(), executed=(), skipped=(), closed=(), trades=trades,
                coverage=tuple(_latest_coverages(self.store).values()),
                performance=calculate_performance(trades),
                grouped_performance=grouped_performance(trades),
            )
        return result.to_dict()


def paper_ledger_schema() -> dict[str, Any]:
    return {
        "sheet_name": PAPER_LEDGER_SHEET,
        "headers": list(PAPER_LEDGER_HEADERS),
        "identity": "event_identity + lifecycle_event_type",
        "events": [
            PAPER_PLAN_CREATED,
            PAPER_T1_EXECUTED,
            PAPER_T1_SKIPPED,
            PAPER_CLOSED,
            PAPER_COVERAGE,
        ],
    }


__all__ = [
    "CANDIDATE_PROVENANCE",
    "FORMAL_PROVENANCE",
    "InMemoryPaperLedgerStore",
    "PAPER_APPROVAL_POLICY",
    "PAPER_TRACKING_APPROVAL_POLICY",
    "PAPER_CLOSED",
    "PAPER_CLOSED_STATUS",
    "PAPER_COVERAGE",
    "PAPER_HISTORY_CONTINUITY_REQUIRED",
    "PAPER_LEDGER_HEADERS",
    "PAPER_LEDGER_READ_ONLY",
    "PAPER_LEDGER_SHEET",
    "PAPER_OPEN_STATUS",
    "PAPER_PLAN_CREATED",
    "PAPER_PLAN_STATUS",
    "PAPER_PROTOCOL_VERSION",
    "PAPER_SKIPPED_STATUS",
    "PAPER_T1_EXECUTED",
    "PAPER_T1_SKIPPED",
    "PaperCoverage",
    "PaperLedgerStore",
    "PaperLifecycleEngine",
    "PaperLifecycleError",
    "PaperPerformanceStats",
    "PaperPlan",
    "PaperProcessingResult",
    "PaperTrade",
    "PAPER_TRACKED_PROVENANCE",
    "SheetsPaperLedgerStore",
    "active_paper_symbols",
    "calculate_performance",
    "grouped_performance",
    "paper_ledger_schema",
    "paper_trades",
]
