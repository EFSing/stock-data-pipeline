"""Public market-data source and observer contract for D1.

This module is intentionally independent from the holdings-aware Cloud Daily
Report path.  It consumes the bounded public Candidate runtime result, keeps
raw and QFQ prefixes in memory, and projects only the hash-bound components
needed by the D1 immutable snapshot.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from core import Quote
from market_data_contract import (
    CN_SINGLE_SOURCE_PROVIDER,
    CN_ADJUSTMENT_ENGINE_VERSION,
    CN_PROVIDER_FORWARD_ADJUSTMENT_ENGINE_VERSION,
    CN_PROVIDER_FORWARD_QFQ_CONTRACT_VERSION,
    DATA_ADJUSTMENT_UNVERIFIED,
    DATA_INVALID,
    DATA_MISSING,
    DATA_OK,
    DATA_STALE,
    PROVIDER_GLOBAL_FAILURE,
    PROVIDER_SYMBOL_ERROR,
    US_ADJUSTMENT_ENGINE_VERSION,
    US_SINGLE_SOURCE_PROVIDER,
)
from research.setup01_d1_prospective import (
    build_session_snapshot,
    content_sha256,
    render_research_report,
)
from research.setup01_dual_path_observer import BreakoutAnchor, observe_dual_path
from trading.models import SetupState
from trading.setup01_replay import replay_setup01_history


D1_SOURCE_CONTRACT_V1 = "SETUP01_D1_SOURCE_OBSERVER_CONTRACT_V1"
D1_SOURCE_CONTRACT_V2 = "SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2"
D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1 = "SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1"
SOURCE_MIGRATION_STATUS = "SUPERSEDED_BEFORE_FIRST_FORMAL_EVIDENCE"
SOURCE_MIGRATION_REASON = "USER_APPROVED_SINGLE_SOURCE_MARKET_DATA_MIGRATION"
CN_PROVIDER_FORWARD_MIGRATION_STATUS = "ACTIVATION_PENDING_D1_AUTHORIZATION"
CN_PROVIDER_FORWARD_MIGRATION_REASON = "USER_APPROVED_CN_PROVIDER_FORWARD_QFQ_MIGRATION"
# The legacy default remains available for frozen V1 fixtures.  The natural
# collector explicitly requests V2 after a new activation epoch is approved.
D1_SOURCE_CONTRACT_VERSION = D1_SOURCE_CONTRACT_V1


def _safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _float(row: Mapping[str, Any], key: str, *, required: bool = True) -> float | None:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"QFQ row missing {key}")
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"QFQ row has invalid {key}") from exc


def _row_date(row: Mapping[str, Any]) -> date:
    value = row.get("交易日期") or row.get("trade_date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _quote(row: Mapping[str, Any]) -> Quote:
    symbol = str(row.get("统一代码") or row.get("symbol") or "").strip().upper()
    market = str(row.get("市场") or row.get("market") or "").strip().upper()
    if not symbol or market not in {"CN", "US"}:
        raise ValueError("QFQ row identity is incomplete")
    return Quote(
        symbol=symbol,
        name=str(row.get("名称") or row.get("name") or symbol),
        market=market,
        trade_date=_row_date(row),
        source=str(row.get("数据源") or row.get("source") or "D1"),
        open=_float(row, "开盘"),
        high=_float(row, "最高"),
        low=_float(row, "最低"),
        close=_float(row, "收盘"),
        preclose=_float(row, "昨收", required=False),
        pct_change=_float(row, "涨跌幅", required=False),
        volume=_float(row, "成交量", required=False),
        amount=_float(row, "成交额", required=False),
        turnover_rate=_float(row, "换手率", required=False),
        currency=str(row.get("币种") or row.get("currency") or ("CNY" if market == "CN" else "USD")),
    )


def _rows_by_symbol(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("统一代码") or row.get("symbol") or "").strip().upper()
        if symbol:
            result.setdefault(symbol, []).append(dict(_safe(row)))
    for values in result.values():
        values.sort(key=lambda row: str(row.get("交易日期") or row.get("trade_date") or ""))
    return result


def _prefix_status(
    rows: Sequence[Mapping[str, Any]],
    *,
    session_date: date,
) -> str:
    """Classify one serialized raw/QFQ prefix without comparing vendors."""

    if not rows:
        return DATA_MISSING
    dates: list[date] = []
    try:
        for row in rows:
            dates.append(_row_date(row))
    except (TypeError, ValueError):
        return DATA_INVALID
    if any(left >= right for left, right in zip(dates, dates[1:])):
        return DATA_INVALID
    if any(value > session_date for value in dates):
        return DATA_INVALID
    if dates[-1] < session_date:
        return DATA_STALE
    if dates[-1] > session_date:
        return DATA_INVALID
    return DATA_OK


def _symbol_runtime_error_text(
    symbol: str,
    *,
    market: str,
    deep_errors: Mapping[str, Any],
    runtime_errors: Sequence[str],
) -> str:
    values = [str(value) for value in (deep_errors.get(symbol) or ())]
    symbol_prefixes = (
        f"{symbol}:".upper(),
        f"{market}|{symbol}:".upper(),
    )
    for value in runtime_errors:
        normalized = str(value).upper()
        if normalized.startswith(symbol_prefixes) or any(
            marker in normalized for marker in ("PROVIDER_GLOBAL_FAILURE", "AUTH_MISSING", "SCHEMA_INVALID")
        ):
            values.append(str(value))
    return "|".join(values).upper()


def _status_from_runtime_error(text: str) -> str | None:
    if not text:
        return None
    if any(marker in text for marker in ("PROVIDER_GLOBAL_FAILURE", "AUTH_MISSING", "SCHEMA_INVALID")):
        return PROVIDER_GLOBAL_FAILURE
    if "ADJUSTMENT_UNVERIFIED" in text:
        return DATA_ADJUSTMENT_UNVERIFIED
    if "PROVIDER_SYMBOL_ERROR" in text or "SYMBOL_ERROR" in text:
        return PROVIDER_SYMBOL_ERROR
    if "STALE" in text or "EXACT_T" in text:
        return DATA_STALE
    if "MISSING" in text or "UNAVAILABLE" in text:
        return DATA_MISSING
    if "INVALID" in text or "DATA_BAD" in text:
        return DATA_INVALID
    return None


def _seed_row(seed: Any) -> dict[str, Any]:
    board_rule = getattr(seed, "board_rule", None)
    return {
        "market": str(getattr(seed, "market", "")).upper(),
        "symbol": str(getattr(seed, "symbol", "")).upper(),
        "name": str(getattr(seed, "name", "")),
        "sector": getattr(seed, "sector", None),
        "asset_class": getattr(seed, "asset_class", None),
        "exchange": getattr(seed, "exchange", None),
        "currency": getattr(seed, "currency", None),
        "source": getattr(seed, "source", None),
        "source_as_of": _safe(getattr(seed, "source_as_of", None)),
        "reference_price": getattr(seed, "reference_price", None),
        "metadata_status": getattr(seed, "metadata_status", None),
        "source_symbol": getattr(seed, "source_symbol", None),
        "provenance": list(getattr(seed, "provenance", ()) or ()),
        "index_memberships": list(getattr(seed, "index_memberships", ()) or ()),
        "source_snapshot_timestamps": list(
            getattr(seed, "source_snapshot_timestamps", ()) or ()
        ),
        "board_rule": None if board_rule is None else {
            "board": getattr(board_rule, "board", None),
            "minimum_quantity": getattr(board_rule, "minimum_quantity", None),
            "evidence_url": getattr(board_rule, "evidence_url", None),
        },
    }


def _candidate_row(runtime: Any, symbol: str) -> Mapping[str, Any]:
    for record in getattr(getattr(runtime, "universe", None), "records", ()):
        if str(getattr(record, "symbol", "")).upper() == symbol:
            return record.to_row()
    return {}


def _anchor_rows(quotes: list[Quote], *, session_date: date, first_session: date | None) -> list[dict[str, Any]]:
    if not quotes:
        return []
    replay = replay_setup01_history(quotes, as_of_date=session_date)
    anchors: list[dict[str, Any]] = []
    for event in replay.events:
        if event.event_type is not SetupState.CONFIRMED or event.trade_date > session_date:
            continue
        if first_session is not None and event.trade_date < first_session:
            continue
        setup = event.setup01
        if not (setup.wave1_origin and setup.wave1_peak and setup.wave2_low):
            continue
        anchors.append({
            "event_identity": event.event_identity,
            "breakout_date": event.trade_date.isoformat(),
            "LOW0": setup.wave1_origin.price,
            "H1": setup.wave1_peak.price,
            "wave2_low": setup.wave2_low.price,
            "confirmation_level": setup.confirmation_level,
        })
    return anchors


def _observer_rows(
    *,
    market: str,
    session_date: date,
    qfq_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    first_session: date | None,
    contract_version: str = D1_SOURCE_CONTRACT_VERSION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    outputs: list[dict[str, Any]] = []
    follow_up: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in sorted(qfq_by_symbol):
        raw_rows = list(qfq_by_symbol[symbol])
        try:
            quotes = sorted((_quote(row) for row in raw_rows), key=lambda row: row.trade_date)
            if any(row.trade_date > session_date for row in quotes):
                raise ValueError("future QFQ row is forbidden")
            if not quotes or quotes[-1].trade_date != session_date:
                raise ValueError("QFQ prefix does not reach exact session T")
            anchors = _anchor_rows(quotes, session_date=session_date, first_session=first_session)
            events: list[dict[str, Any]] = []
            for item in anchors:
                anchor = BreakoutAnchor(
                    event_identity=str(item["event_identity"]),
                    breakout_date=date.fromisoformat(str(item["breakout_date"])),
                    low0=float(item["LOW0"]),
                    h1=float(item["H1"]),
                    wave2_low=float(item["wave2_low"]),
                )
                events.extend(observe_dual_path(quotes, anchor, as_of_date=session_date))
            seen: set[str] = set()
            unique_events = []
            for event in events:
                if event["event_id"] not in seen:
                    seen.add(event["event_id"])
                    unique_events.append(event)
            event_types = {str(event.get("event_type")) for event in unique_events}
            for item in anchors:
                anchor_events = [
                    event for event in unique_events
                    if event.get("lifecycle_id", "").startswith(str(item["event_identity"]))
                    or event.get("event_id", "").find(str(item["event_identity"])) >= 0
                ]
                if not any(event.get("event_type") in {"RESEARCH_EXIT", "OBSERVATION_TIMEOUT"} for event in anchor_events):
                    follow_up.append({
                        "symbol": symbol,
                        "market": market,
                        "lifecycle_id": item["event_identity"],
                        "as_of_date": session_date.isoformat(),
                        "reason": "OPEN_RESEARCH_LIFECYCLE_REQUIRES_NEXT_SESSION_OBSERVATION",
                    })
            outputs.extend(unique_events)
            if not anchors:
                outputs.append({
                    "event_id": f"{contract_version}|{market}|{symbol}|{session_date.isoformat()}|NO_SIGNAL",
                    "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
                    "symbol": symbol,
                    "market": market,
                    "session_date": session_date.isoformat(),
                    "event_type": "NO_SIGNAL",
                    "reason": "NO_H1_BREAKOUT_ANCHOR_IN_CAUSAL_PREFIX",
                    "research_only_candidate": False,
                    "formal_entry_allowed": False,
                    "real_fill_evidence": False,
                })
            elif not ({"PATH_A_SIGNAL", "PATH_B_SIGNAL"} & event_types):
                outputs.append({
                    "event_id": f"{contract_version}|{market}|{symbol}|{session_date.isoformat()}|NO_SIGNAL",
                    "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
                    "symbol": symbol,
                    "market": market,
                    "session_date": session_date.isoformat(),
                    "event_type": "NO_SIGNAL",
                    "reason": "NO_PATH_A_OR_PATH_B_SIGNAL_IN_CAUSAL_PREFIX",
                    "research_only_candidate": False,
                    "formal_entry_allowed": False,
                    "real_fill_evidence": False,
                })
        except Exception as exc:
            errors.append(f"{market}|{symbol}:{type(exc).__name__}:{exc}")
            outputs.append({
                "event_id": f"{contract_version}|{market}|{symbol}|{session_date.isoformat()}|DATA_MISSING",
                "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
                "symbol": symbol,
                "market": market,
                "session_date": session_date.isoformat(),
                "event_type": "DATA_MISSING",
                "model_outcome": "OBSERVER_INPUT_INCOMPLETE",
                "research_only_candidate": False,
                "formal_entry_allowed": False,
                "real_fill_evidence": False,
            })
    return outputs, follow_up, errors


def _cost_scenario() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "research" / "protocols" / "setup01_post_breakout_d1_prospective_v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value.get("cost_scenarios") or {})


def source_contract_descriptor(
    contract_version: str = D1_SOURCE_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Return the code-level readiness descriptor used before first natural data."""

    contract_version = str(contract_version)
    if contract_version == D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1:
        return {
            "contract_version": contract_version,
            "status": "VERIFIED",
            "migration_status": CN_PROVIDER_FORWARD_MIGRATION_STATUS,
            "migration_reason": CN_PROVIDER_FORWARD_MIGRATION_REASON,
            "formal_evidence_required_before_activation": 0,
            "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
            "required_components": [
                "universe_snapshot",
                "raw_source_snapshot",
                "normalized_prefix_snapshot",
                "decision_snapshot",
                "research_observation_report",
            ],
            "raw_source": "SINGLE_SOURCE_MARKET_DATA_V1_RAW_STAGE_A_PREFIX",
            "normalized_prefix": (
                "CN_PROVIDER_FORWARD_QFQ_CONTRACT_V2_QFQ_EXACT_T_PREFIX"
            ),
            "adjustment_engine_version": CN_PROVIDER_FORWARD_ADJUSTMENT_ENGINE_VERSION,
            "qfq_contract_version": CN_PROVIDER_FORWARD_QFQ_CONTRACT_VERSION,
            "causal_observer": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
            "public_private_isolation": "PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
            "cost_scenario": _cost_scenario(),
        }
    return {
        "contract_version": contract_version,
        "status": "VERIFIED",
        **(
            {
                "migration_status": SOURCE_MIGRATION_STATUS,
                "migration_reason": SOURCE_MIGRATION_REASON,
                "formal_evidence_required_before_activation": 0,
            }
            if contract_version == D1_SOURCE_CONTRACT_V2
            else {}
        ),
        "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "required_components": [
            "universe_snapshot",
            "raw_source_snapshot",
            "normalized_prefix_snapshot",
            "decision_snapshot",
            "research_observation_report",
        ],
        "raw_source": (
            "SINGLE_SOURCE_MARKET_DATA_V1_RAW_STAGE_A_PREFIX"
            if contract_version == D1_SOURCE_CONTRACT_V2
            else "PUBLIC_CANDIDATE_RUNTIME_STAGE_A_PREFIX"
        ),
        "normalized_prefix": (
            "SINGLE_SOURCE_MARKET_DATA_V1_QFQ_EXACT_T_PREFIX"
            if contract_version == D1_SOURCE_CONTRACT_V2
            else "PUBLIC_CANDIDATE_RUNTIME_QFQ_EXACT_T_PREFIX"
        ),
        "causal_observer": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "public_private_isolation": "PUBLIC_MARKET_RESEARCH_ONLY_NO_HOLDINGS",
        "cost_scenario": _cost_scenario(),
    }


def build_d1_source_contract(
    runtime: Any,
    *,
    session_identity: Mapping[str, Any],
    acquired_at: str,
    activation_record: Mapping[str, Any] | None = None,
    contract_version: str = D1_SOURCE_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Project a Candidate runtime into the five D1 source/observer inputs."""

    contract_version = str(contract_version).strip()
    if contract_version not in {
        D1_SOURCE_CONTRACT_V1,
        D1_SOURCE_CONTRACT_V2,
        D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1,
    }:
        raise ValueError(f"unsupported D1 source contract version: {contract_version}")
    market = str(getattr(runtime, "market", "")).upper()
    session_date = getattr(runtime, "as_of_date", None)
    if market not in {"CN", "US"} or not isinstance(session_date, date):
        raise ValueError("Candidate runtime identity is incomplete")
    seeds = tuple(getattr(runtime, "seeds", ()) or ())
    short_by_symbol = {
        str(symbol).upper(): tuple(values)
        for symbol, values in (getattr(runtime, "short_histories", {}) or {}).items()
    }
    qfq_by_symbol = {
        str(symbol).upper(): tuple(
            _safe({
                "统一代码": quote.symbol,
                "名称": quote.name,
                "市场": quote.market,
                "交易日期": quote.trade_date,
                "复权方式": "前复权",
                "数据源": quote.source,
                "开盘": quote.open,
                "最高": quote.high,
                "最低": quote.low,
                "收盘": quote.close,
                "昨收": quote.preclose,
                "涨跌幅": quote.pct_change,
                "成交量": quote.volume,
                "成交额": quote.amount,
                "换手率": quote.turnover_rate,
                "币种": quote.currency,
            })
            for quote in values
        )
        for symbol, values in (getattr(runtime, "deep_histories", {}) or {}).items()
    }
    raw_by_symbol = {
        symbol: [_safe({
            "统一代码": quote.symbol,
            "名称": quote.name,
            "市场": quote.market,
            "交易日期": quote.trade_date,
            "复权方式": "未复权",
            "数据源": quote.source,
            "开盘": quote.open,
            "最高": quote.high,
            "最低": quote.low,
            "收盘": quote.close,
            "昨收": quote.preclose,
            "涨跌幅": quote.pct_change,
            "成交量": quote.volume,
            "成交额": quote.amount,
            "换手率": quote.turnover_rate,
            "币种": quote.currency,
        }) for quote in values]
        for symbol, values in short_by_symbol.items()
    }
    first_session = None
    if activation_record:
        value = activation_record.get("first_eligible_full_exchange_session")
        if value:
            first_session = date.fromisoformat(str(value))

    observer_outputs, follow_up, observer_errors = _observer_rows(
        market=market,
        session_date=session_date,
        qfq_by_symbol=qfq_by_symbol,
        first_session=first_session,
        contract_version=contract_version,
    )
    members = []
    included_symbols = {
        str(getattr(record, "symbol", "")).upper()
        for record in getattr(getattr(runtime, "universe", None), "included", ())
    }
    deep_ready = {
        str(symbol).upper()
        for symbol in getattr(runtime, "deep_ready_symbols", ())
    }
    for seed in seeds:
        symbol = str(getattr(seed, "symbol", "")).upper()
        candidate = _candidate_row(runtime, symbol)
        members.append({
            "symbol": symbol,
            "market": market,
            "membership_status": "INCLUDED" if symbol in included_symbols else "SEED_EXCLUDED",
            "source_date": str(getattr(seed, "source_as_of", None) or session_date),
            "sector": getattr(seed, "sector", None),
            "tradable": symbol in included_symbols and symbol in deep_ready,
            "candidate_record": _safe(candidate),
            "index_memberships": list(getattr(seed, "index_memberships", ()) or ()),
            "source_snapshot_timestamps": list(
                getattr(seed, "source_snapshot_timestamps", ()) or ()
            ),
            "provenance": list(getattr(seed, "provenance", ()) or ()),
        })

    runtime_errors = [str(value) for value in (getattr(runtime, "errors", ()) or ()) if value]
    missing_raw = sorted(symbol for symbol in included_symbols if not raw_by_symbol.get(symbol))
    missing_qfq = sorted(symbol for symbol in included_symbols if not qfq_by_symbol.get(symbol))
    incomplete = [*runtime_errors, *observer_errors]
    incomplete.extend(f"MISSING_RAW_PREFIX:{symbol}" for symbol in missing_raw)
    incomplete.extend(f"MISSING_QFQ_PREFIX:{symbol}" for symbol in missing_qfq)
    if any(
        values and str(values[-1].get("交易日期"))[:10] != session_date.isoformat()
        for values in qfq_by_symbol.values()
    ):
        incomplete.append("QFQ_PREFIX_NOT_EXACT_T")
    attempted_symbols = sorted(
        {
            str(getattr(seed, "symbol", "")).strip().upper()
            for seed in seeds
            if str(getattr(seed, "symbol", "")).strip()
        }
    )
    universe_snapshot_status = "AVAILABLE" if attempted_symbols else "UNAVAILABLE"
    candidate_status = str(
        getattr(runtime, "candidate_status", "")
        or getattr(runtime, "status", "NOT_RUN")
    ).upper()
    deep_errors = getattr(runtime, "deep_errors", {}) or {}
    provider_contract = _safe(getattr(runtime, "qfq_contract", {}))
    per_symbol_provenance = _safe(getattr(runtime, "source_provenance", {}) or {})
    provider_identity = str(provider_contract.get("market_data_provider") or "UNKNOWN")
    qfq_contract_text = str(provider_contract.get("qfq") or "")
    expected_provider = (
        CN_SINGLE_SOURCE_PROVIDER if market == "CN" else US_SINGLE_SOURCE_PROVIDER
    )
    expected_adjustment_engine = (
        CN_ADJUSTMENT_ENGINE_VERSION
        if market == "CN"
        else US_ADJUSTMENT_ENGINE_VERSION
    )
    single_source_contract = contract_version in {
        D1_SOURCE_CONTRACT_V2,
        D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1,
    }
    if contract_version == D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1 and market != "CN":
        raise ValueError("CN provider-forward D1 contract is CN-only")
    expected_adjustment_engine = (
        CN_PROVIDER_FORWARD_ADJUSTMENT_ENGINE_VERSION
        if contract_version == D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1
        else expected_adjustment_engine
    )
    expected_qfq_contract = (
        CN_PROVIDER_FORWARD_QFQ_CONTRACT_VERSION
        if contract_version == D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1
        else expected_adjustment_engine
    )
    single_source_contract_errors: list[str] = []
    if single_source_contract:
        if provider_identity != expected_provider:
            single_source_contract_errors.append(
                f"PROVIDER_CONTRACT_PROVIDER_MISMATCH:{provider_identity}!={expected_provider}"
            )
        if expected_qfq_contract not in qfq_contract_text:
            single_source_contract_errors.append(
                f"PROVIDER_CONTRACT_ADJUSTMENT_ENGINE_MISMATCH:{qfq_contract_text}"
            )
        identity_market = str(session_identity.get("market") or "").upper()
        identity_date = str(session_identity.get("trade_date") or "")[:10]
        if identity_market != market or identity_date != session_date.isoformat():
            single_source_contract_errors.append("CANDIDATE_SESSION_IDENTITY_MISMATCH")
        if not str(session_identity.get("identity") or "").strip():
            single_source_contract_errors.append("COMPLETED_SESSION_IDENTITY_MISSING")
        if not bool(session_identity.get("exact_exchange_calendar")):
            single_source_contract_errors.append("COMPLETED_SESSION_CALENDAR_NOT_EXACT")
    per_symbol_source_status: dict[str, str] = {}
    for symbol in attempted_symbols:
        qfq_values = qfq_by_symbol.get(symbol, ())
        raw_status = _prefix_status(raw_by_symbol.get(symbol, ()), session_date=session_date)
        qfq_status = _prefix_status(qfq_values, session_date=session_date)
        runtime_status = _status_from_runtime_error(
            _symbol_runtime_error_text(
                symbol,
                market=market,
                deep_errors=deep_errors,
                runtime_errors=runtime_errors,
            )
        )
        if runtime_status is not None:
            per_symbol_source_status[symbol] = runtime_status
        elif raw_status == DATA_OK and qfq_status == DATA_OK:
            per_symbol_source_status[symbol] = DATA_OK
        elif DATA_MISSING in {raw_status, qfq_status}:
            per_symbol_source_status[symbol] = DATA_MISSING
        elif DATA_INVALID in {raw_status, qfq_status}:
            per_symbol_source_status[symbol] = DATA_INVALID
        elif DATA_STALE in {raw_status, qfq_status}:
            per_symbol_source_status[symbol] = DATA_STALE
        else:
            per_symbol_source_status[symbol] = DATA_INVALID
    provider_global_failure = any(
        "PROVIDER_GLOBAL_FAILURE" in value or "AUTH_MISSING" in value or "SCHEMA_INVALID" in value
        for value in runtime_errors
    )
    provider_global_failure = provider_global_failure or any(
        _status_from_runtime_error(
            _symbol_runtime_error_text(
                symbol,
                market=market,
                deep_errors=deep_errors,
                runtime_errors=runtime_errors,
            )
        )
        == PROVIDER_GLOBAL_FAILURE
        for symbol in attempted_symbols
    )
    if single_source_contract:
        # V2 treats symbol failures as data-plane diagnostics.  The formal
        # session remains committable when the provider/session contract is
        # exact and the attempted universe is explicit.  A seed or
        # provider-wide failure still blocks the formal commit.
        blocking_errors = [
            value for value in runtime_errors
            if value.startswith("SEED_METADATA_")
            or value.startswith("CANDIDATE_SESSION_")
            or value.startswith("COMPLETED_SESSION_")
        ]
        blocking_errors.extend(single_source_contract_errors)
        if universe_snapshot_status == "UNAVAILABLE":
            blocking_errors.append("UNIVERSE_SNAPSHOT_UNAVAILABLE")
            incomplete.append("UNIVERSE_SNAPSHOT_UNAVAILABLE")
        status = (
            "VERIFIED"
            if attempted_symbols and not provider_global_failure and not blocking_errors
            else "INCOMPLETE"
        )
    else:
        status = "VERIFIED" if not incomplete else "INCOMPLETE"
    raw_source = {
        "contract_version": contract_version,
        "status": status,
        "market": market,
        "session_date": session_date.isoformat(),
        "acquired_at": acquired_at,
        "source_identity": {
            "seed_source": str(getattr(runtime, "qfq_contract", {}).get("seed") or "UNKNOWN"),
            "raw_history_source": (
                str(provider_contract.get("market_data_provider") or "UNKNOWN")
                if single_source_contract
                else "EXISTING_CANDIDATE_RUNTIME_STAGE_A"
            ),
            "qfq_source": str(provider_contract.get("qfq") or "UNKNOWN"),
            "provider_identity": provider_identity,
            "adjustment_engine_version": (
                expected_adjustment_engine
                if market == "CN" and single_source_contract
                else "YAHOO_CHART_ADJCLOSE_ENGINE_V1"
                if market == "US" and contract_version == D1_SOURCE_CONTRACT_V2
                else None
            ),
            "seed_source_as_of": _safe(getattr(runtime, "seed_source_as_of", None)),
        },
        "attempted_universe": attempted_symbols,
        "usable_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == "DATA_OK"),
        "missing_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == "DATA_MISSING"),
        "invalid_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value != "DATA_OK" and value != "DATA_MISSING"),
        "per_symbol_source_status": dict(sorted(per_symbol_source_status.items())),
        "per_symbol_provenance": per_symbol_provenance,
        "raw_prefix_by_symbol": raw_by_symbol,
        "raw_prefix_sha256": content_sha256(raw_by_symbol),
        "provider_contract": _safe(getattr(runtime, "qfq_contract", {})),
        "universe_snapshot_status": universe_snapshot_status,
        "candidate_status": candidate_status,
    }
    normalized = {
        "contract_version": contract_version,
        "status": status,
        "adjustment": "前复权",
        "market": market,
        "session_date": session_date.isoformat(),
        "causal_prefix": True,
        "future_rows_rejected": True,
        "qfq_prefix_by_symbol": _safe(qfq_by_symbol),
        "qfq_prefix_sha256": content_sha256(qfq_by_symbol),
        "exact_session_identity": _safe(session_identity),
        "provider_identity": provider_identity,
        "adjustment_engine_version": (
            expected_adjustment_engine if single_source_contract
            else "YAHOO_CHART_ADJCLOSE_ENGINE_V1" if market == "US" and single_source_contract
            else None
        ),
        "per_symbol_provenance": per_symbol_provenance,
        "attempted_universe": attempted_symbols,
        "usable_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == "DATA_OK"),
        "missing_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == DATA_MISSING),
        "invalid_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value != DATA_OK and value != DATA_MISSING),
        "universe_snapshot_status": universe_snapshot_status,
        "candidate_status": candidate_status,
    }
    decision_rows = []
    decision_symbols = set(included_symbols) | set(qfq_by_symbol)
    if single_source_contract:
        decision_symbols |= set(attempted_symbols)
    for symbol in sorted(decision_symbols):
        decision_rows.append({
            "symbol": symbol,
            "market": market,
            "session_date": session_date.isoformat(),
            "data_status": per_symbol_source_status.get(symbol, "DATA_MISSING") if single_source_contract else "DATA_OK" if symbol in deep_ready else "DATA_BLOCKED",
            "research_overlay_only": True,
            "formal_entry_allowed": False,
            "real_fill_evidence": False,
            "production_state_write": False,
        })
    decision = {
        "contract_version": contract_version,
        "status": status,
        "session_identity": _safe(session_identity),
        "rows": decision_rows,
        "runtime_status": getattr(runtime, "status", None),
        "runtime_protocol": _safe(getattr(runtime, "qfq_contract", {})),
        "per_symbol_source_status": dict(sorted(per_symbol_source_status.items())),
        "universe_snapshot_status": universe_snapshot_status,
        "candidate_status": candidate_status,
    }
    research = {
        "contract_version": contract_version,
        "status": status,
        "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "session_identity": _safe(session_identity),
        "observations": _safe(observer_outputs),
        "follow_up_set": _safe(follow_up),
        "observer_input_sha256": content_sha256(qfq_by_symbol),
        "observer_output_sha256": content_sha256(observer_outputs),
        "cost_scenario": _cost_scenario(),
        "errors": sorted(set(incomplete)),
        "attempted_universe": attempted_symbols,
        "usable_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == "DATA_OK"),
        "missing_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value == DATA_MISSING),
        "invalid_symbols": sorted(symbol for symbol, value in per_symbol_source_status.items() if value != DATA_OK and value != DATA_MISSING),
        "universe_snapshot_status": universe_snapshot_status,
        "candidate_status": candidate_status,
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
    }
    return {
        "contract_version": contract_version,
        "status": status,
        "market": market,
        "session_date": session_date.isoformat(),
        "acquired_at": acquired_at,
        "session_identity": _safe(session_identity),
        "source_identity": {
            "provider": (
                provider_identity
                if single_source_contract
                else "SETUP01_D1_PUBLIC_CANDIDATE_RUNTIME"
            ),
            "source_date": session_date.isoformat(),
            "obtained_at": acquired_at,
            "session_identity": _safe(session_identity),
            "source_contract_version": contract_version,
            **({"activation_record_sha256": activation_record.get("record_sha256")} if activation_record else {}),
        },
        "universe_snapshot": {
            "status": universe_snapshot_status,
            "source": str(getattr(runtime, "qfq_contract", {}).get("seed") or "UNKNOWN"),
            "source_as_of": _safe(getattr(runtime, "seed_source_as_of", None)),
            "membership_as_of_semantics": "CURRENT_ONLY_SNAPSHOT_NOT_RETROACTIVE",
            "members": members,
        },
        "raw_source_snapshot": raw_source,
        "normalized_prefix_snapshot": normalized,
        "decision_snapshot": decision,
        "research_observation_report": research,
        "cost_scenario": _cost_scenario(),
    }


def build_d1_snapshot_from_candidate_runtime(
    runtime: Any,
    *,
    session_identity: Mapping[str, Any],
    acquired_at: str,
    activation_record: Mapping[str, Any] | None = None,
    contract_version: str = D1_SOURCE_CONTRACT_VERSION,
) -> dict[str, Any]:
    """Build the immutable snapshot used by the durable natural collector."""

    contract = build_d1_source_contract(
        runtime,
        session_identity=session_identity,
        acquired_at=acquired_at,
        activation_record=activation_record,
        contract_version=contract_version,
    )
    capture_status = "COMPLETE" if contract["status"] == "VERIFIED" else "DATA_MISSING"
    report = dict(contract["research_observation_report"])
    # Embed a Chinese, read-only report in the durable object.  Integrity
    # hashes are carried by the enclosing component/event and are rendered
    # separately after load, so the embedded text does not create a hash cycle.
    preview = build_session_snapshot(
        market=contract["market"],
        session_date=date.fromisoformat(contract["session_date"]),
        acquired_at=acquired_at,
        capture_status=capture_status,
        source_identity=contract["source_identity"],
        universe_snapshot=contract["universe_snapshot"],
        raw_source_snapshot=contract["raw_source_snapshot"],
        normalized_prefix_snapshot=contract["normalized_prefix_snapshot"],
        decision_snapshot=contract["decision_snapshot"],
        research_observation_report=report,
    )
    report["report_markdown"] = render_research_report(preview, include_integrity=False)
    return build_session_snapshot(
        market=contract["market"],
        session_date=date.fromisoformat(contract["session_date"]),
        acquired_at=acquired_at,
        capture_status=capture_status,
        source_identity=contract["source_identity"],
        universe_snapshot=contract["universe_snapshot"],
        raw_source_snapshot=contract["raw_source_snapshot"],
        normalized_prefix_snapshot=contract["normalized_prefix_snapshot"],
        decision_snapshot=contract["decision_snapshot"],
        research_observation_report=report,
    )


__all__ = [
    "D1_SOURCE_CONTRACT_V1",
    "D1_SOURCE_CONTRACT_V2",
    "D1_SOURCE_CONTRACT_CN_PROVIDER_FORWARD_V1",
    "D1_SOURCE_CONTRACT_VERSION",
    "SOURCE_MIGRATION_REASON",
    "SOURCE_MIGRATION_STATUS",
    "build_d1_snapshot_from_candidate_runtime",
    "build_d1_source_contract",
    "source_contract_descriptor",
]
