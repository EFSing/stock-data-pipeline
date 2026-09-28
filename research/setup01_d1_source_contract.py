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
from research.setup01_d1_prospective import (
    build_session_snapshot,
    content_sha256,
    render_research_report,
)
from research.setup01_dual_path_observer import BreakoutAnchor, observe_dual_path
from trading.models import SetupState
from trading.setup01_replay import replay_setup01_history


D1_SOURCE_CONTRACT_VERSION = "SETUP01_D1_SOURCE_OBSERVER_CONTRACT_V1"


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
                    "event_id": f"{D1_SOURCE_CONTRACT_VERSION}|{market}|{symbol}|{session_date.isoformat()}|NO_SIGNAL",
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
                    "event_id": f"{D1_SOURCE_CONTRACT_VERSION}|{market}|{symbol}|{session_date.isoformat()}|NO_SIGNAL",
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
                "event_id": f"{D1_SOURCE_CONTRACT_VERSION}|{market}|{symbol}|{session_date.isoformat()}|DATA_MISSING",
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


def source_contract_descriptor() -> dict[str, Any]:
    """Return the code-level readiness descriptor used before first natural data."""

    return {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": "VERIFIED",
        "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "required_components": [
            "universe_snapshot",
            "raw_source_snapshot",
            "normalized_prefix_snapshot",
            "decision_snapshot",
            "research_observation_report",
        ],
        "raw_source": "PUBLIC_CANDIDATE_RUNTIME_STAGE_A_PREFIX",
        "normalized_prefix": "PUBLIC_CANDIDATE_RUNTIME_QFQ_EXACT_T_PREFIX",
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
) -> dict[str, Any]:
    """Project a Candidate runtime into the five D1 source/observer inputs."""

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
    status = "VERIFIED" if not incomplete else "INCOMPLETE"
    raw_source = {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": status,
        "market": market,
        "session_date": session_date.isoformat(),
        "acquired_at": acquired_at,
        "source_identity": {
            "seed_source": str(getattr(runtime, "qfq_contract", {}).get("seed") or "UNKNOWN"),
            "raw_history_source": "EXISTING_CANDIDATE_RUNTIME_STAGE_A",
            "qfq_source": str(getattr(runtime, "qfq_contract", {}).get("qfq") or "UNKNOWN"),
            "seed_source_as_of": _safe(getattr(runtime, "seed_source_as_of", None)),
        },
        "raw_prefix_by_symbol": raw_by_symbol,
        "raw_prefix_sha256": content_sha256(raw_by_symbol),
        "provider_contract": _safe(getattr(runtime, "qfq_contract", {})),
    }
    normalized = {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": status,
        "adjustment": "前复权",
        "market": market,
        "session_date": session_date.isoformat(),
        "causal_prefix": True,
        "future_rows_rejected": True,
        "qfq_prefix_by_symbol": _safe(qfq_by_symbol),
        "qfq_prefix_sha256": content_sha256(qfq_by_symbol),
        "exact_session_identity": _safe(session_identity),
    }
    decision_rows = []
    for symbol in sorted(set(included_symbols) | set(qfq_by_symbol)):
        decision_rows.append({
            "symbol": symbol,
            "market": market,
            "session_date": session_date.isoformat(),
            "data_status": "DATA_OK" if symbol in deep_ready else "DATA_BLOCKED",
            "research_overlay_only": True,
            "formal_entry_allowed": False,
            "real_fill_evidence": False,
            "production_state_write": False,
        })
    decision = {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": status,
        "session_identity": _safe(session_identity),
        "rows": decision_rows,
        "runtime_status": getattr(runtime, "status", None),
        "runtime_protocol": _safe(getattr(runtime, "qfq_contract", {})),
    }
    research = {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": status,
        "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "session_identity": _safe(session_identity),
        "observations": _safe(observer_outputs),
        "follow_up_set": _safe(follow_up),
        "observer_input_sha256": content_sha256(qfq_by_symbol),
        "observer_output_sha256": content_sha256(observer_outputs),
        "cost_scenario": _cost_scenario(),
        "errors": sorted(set(incomplete)),
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
    }
    return {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": status,
        "market": market,
        "session_date": session_date.isoformat(),
        "acquired_at": acquired_at,
        "session_identity": _safe(session_identity),
        "source_identity": {
            "provider": "SETUP01_D1_PUBLIC_CANDIDATE_RUNTIME",
            "source_date": session_date.isoformat(),
            "obtained_at": acquired_at,
            "session_identity": _safe(session_identity),
            "source_contract_version": D1_SOURCE_CONTRACT_VERSION,
            **({"activation_record_sha256": activation_record.get("record_sha256")} if activation_record else {}),
        },
        "universe_snapshot": {
            "source": str(getattr(runtime, "qfq_contract", {}).get("seed") or "UNKNOWN"),
            "source_as_of": _safe(getattr(runtime, "seed_source_as_of", None)),
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
) -> dict[str, Any]:
    """Build the immutable snapshot used by the durable natural collector."""

    contract = build_d1_source_contract(
        runtime,
        session_identity=session_identity,
        acquired_at=acquired_at,
        activation_record=activation_record,
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
    "D1_SOURCE_CONTRACT_VERSION",
    "build_d1_snapshot_from_candidate_runtime",
    "build_d1_source_contract",
    "source_contract_descriptor",
]
