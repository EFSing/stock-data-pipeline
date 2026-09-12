"""Presentation-only projection for the read-only Daily Decision Chain.

The dashboard deliberately consumes the existing production result mapping (or
the existing ``DailyTradingDecisionReport`` via ``to_dict``).  It does not
evaluate a setup, calculate a price, mutate the input, or create a second
trading state machine.  The returned projection is JSON-compatible so it can
also be inspected independently of the HTML renderer.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import html
import json
from pathlib import Path
from typing import Any


STAGE_ORDER = (
    "WATCH",
    "ARMED",
    "CONFIRMED",
    "STRATEGY_PROPOSAL",
    "ENTRY_ALLOWED",
    "POSITION_MANAGEMENT",
    "FAILED",
    "DATA_BLOCKED",
    "NO_TRADE",
)

STAGE_LABELS = {
    "WATCH": "观察中",
    "ARMED": "接近确认",
    "CONFIRMED": "今日确认",
    "STRATEGY_PROPOSAL": "已形成交易方案",
    "ENTRY_ALLOWED": "可入场",
    "POSITION_MANAGEMENT": "持仓管理",
    "FAILED": "已失效",
    "DATA_BLOCKED": "数据异常",
    "NO_TRADE": "今天不交易",
}

STATUS_LABELS = {
    "WATCH": "观察中",
    "ARMED": "接近确认",
    "CONFIRMED": "今日确认",
    "STRATEGY_PROPOSAL": "已形成交易方案",
    "ENTRY_ALLOWED": "可入场",
    "PORTFOLIO_ALLOWED": "可入场",
    "POSITION_MANAGEMENT": "持仓管理",
    "FAILED": "已失效",
    "DATA_BLOCKED": "数据异常",
    "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED": "数据异常",
    "NO_TRADE": "今天不交易",
    "WAIT_CONFIRMATION": "等待确认",
}

ACTION_LABELS = {
    "WATCH": "观察中",
    "ARMED": "接近确认",
    "WAIT_CONFIRMATION": "等待确认",
    "ENTRY_ALLOWED": "可入场",
    "NO_TRADE": "今天不交易",
    "HOLD": "继续持有",
    "NO_ADD": "暂不加仓",
    "PROFIT_PROTECTION": "保护利润",
    "EXIT": "退出",
}

WAVE_LABELS = {
    "WAVE_2_TO_3_CANDIDATE": "2浪调整结束候选，等待3浪启动",
    "WAVE_3_CONTINUATION_CANDIDATE": "3浪延续候选",
    "ABC_CORRECTION_CANDIDATE": "ABC调整候选",
    "UPTREND_UNKNOWN_WAVE": "上升趋势，浪型未确定",
    "DOWNTREND_OR_INVALID_FOR_LONG": "下行趋势或不适合做多",
    "NO_VALID_SCENARIO": "暂无有效波浪情景",
}

MARKET_LABELS = {
    "CN": "中国市场",
    "US": "美国市场",
}

_PRIMARY_SETUP_BY_WAVE = {
    "WAVE_2_TO_3_CANDIDATE": "SETUP_01",
    "WAVE_3_CONTINUATION_CANDIDATE": "SETUP_02",
}
_DATA_BLOCKED_FINAL_STATUSES = {
    "DATA_BLOCKED",
    "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED",
}
_DATA_BLOCKED_STATUSES = {"DATA_BAD", "DATA_STALE", "DATA_UNAVAILABLE", "DATA_BLOCKED"}
_DATA_BLOCKING_REASONS = {
    "DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION",
    "T1_EXECUTION_DATA_REQUIRED",
}
_POSITION_OBSERVED = "POSITION_MANAGEMENT_OBSERVED"


def _as_payload(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise TypeError("dashboard input must be a mapping or expose to_dict()")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _raw_text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).strip()


def _text(value: Any, default: str = "") -> str:
    result = _raw_text(value)
    return result if result else default


def _display(value: Any, default: str = "—") -> str:
    text = _text(value)
    return text if text else default


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        text = _raw_text(value)
        if text and text not in {"—", "-"}:
            return value
    return None


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _raw_text(value).lower() in {"true", "1", "yes", "y", "是"}


def _normalised_symbol(value: Any) -> str:
    return _text(value).upper()


def _normalised_market(value: Any) -> str:
    return _text(value).upper()


def _attribute(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _lookup(root: Mapping[str, Any], key: str, symbol: str) -> Mapping[str, Any]:
    values = _mapping(root.get(key))
    direct = values.get(symbol)
    if direct is None:
        direct = values.get(symbol.upper())
    if direct is not None:
        return _mapping(direct)
    for candidate, value in values.items():
        if _normalised_symbol(candidate) == symbol.upper():
            return _mapping(value)
    return {}


def dashboard_universe_metadata(inputs: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Build HTML-only metadata from existing production input objects.

    This helper is intentionally separate from the production result contract.
    The runner uses it only while writing HTML, so formal names and position
    facts remain available to the page without adding fields to the returned
    Daily Decision JSON.
    """

    symbol_metadata: dict[str, dict[str, Any]] = {}
    position_metadata: dict[str, dict[str, Any]] = {}
    for item in inputs:
        symbol = _normalised_symbol(_attribute(item, "symbol"))
        if not symbol:
            continue
        history = _sequence(_attribute(item, "qfq_history"))
        name = next(
            (
                _text(_attribute(quote, "name"))
                for quote in reversed(history)
                if _text(_attribute(quote, "name"))
            ),
            "",
        )
        if name:
            symbol_metadata[symbol] = {"name": name}
        open_state = _attribute(item, "open_position_state")
        if open_state is None:
            continue
        origin = _attribute(open_state, "origin")
        portfolio_position = _attribute(open_state, "portfolio_position")
        metadata: dict[str, Any] = {}
        if origin is not None:
            targets = _attribute(origin, "target_prices")
            if not targets:
                targets = tuple(
                    _attribute(target, "price")
                    for target in _sequence(_attribute(origin, "targets"))
                )
            metadata.update({
                "actual_entry": _attribute(origin, "actual_entry"),
                "initial_execution_stop": _attribute(origin, "initial_execution_stop"),
                "targets": list(targets),
                "source_setup": _attribute(origin, "source_setup"),
                "entry_date": (
                    _attribute(origin, "entry_date").isoformat()
                    if hasattr(_attribute(origin, "entry_date"), "isoformat")
                    else _attribute(origin, "entry_date")
                ),
            })
        if portfolio_position is not None:
            metadata.update({
                "actual_entry": _attribute(portfolio_position, "actual_entry"),
                "current_price": _attribute(portfolio_position, "current_price"),
                "active_protective_stop": _attribute(portfolio_position, "active_protective_stop"),
                "quantity": _attribute(portfolio_position, "quantity"),
                "risk_group": _first_value(
                    _attribute(portfolio_position, "normalized_risk_group"),
                    _attribute(portfolio_position, "risk_group"),
                ),
            })
        cleaned = {key: value for key, value in metadata.items() if value is not None}
        if cleaned:
            position_metadata[symbol] = cleaned
    return {
        "symbol_metadata": {
            symbol: symbol_metadata[symbol] for symbol in sorted(symbol_metadata)
        },
        "position_metadata": {
            symbol: position_metadata[symbol] for symbol in sorted(position_metadata)
        },
    }


def _report_entries(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_reports = _sequence(payload.get("reports"))
    if raw_reports:
        entries: list[dict[str, Any]] = []
        for raw_entry in raw_reports:
            entry = _mapping(raw_entry)
            report = _mapping(entry.get("报告") or entry.get("report"))
            if not report and "results" in entry:
                report = entry
            entries.append(
                {
                    "account_id": _text(entry.get("账户ID"), "—"),
                    "market": _normalised_market(entry.get("市场")),
                    "report": report,
                    "universe": _mapping(entry.get("universe")),
                    "candidate": _mapping(entry.get("Candidate")),
                    "entry": entry,
                }
            )
        return tuple(entries)
    if "results" in payload:
        return (
            {
                "account_id": _text(payload.get("账户ID"), "—"),
                "market": _normalised_market(payload.get("市场")),
                "report": payload,
                "universe": _mapping(payload.get("universe")),
                "candidate": _mapping(payload.get("Candidate")),
                "entry": payload,
            },
        )
    return ()


def _provenance_labels(
    result: Mapping[str, Any], universe: Mapping[str, Any], symbol: str
) -> tuple[str, ...]:
    values: list[Any] = []
    values.append(result.get("provenance"))
    values.append(_lookup(universe, "provenance", symbol))
    values.append(_lookup(universe, "provenance_metadata", symbol))
    labels: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("source", "")
        if isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = (value,)
        for candidate in candidates:
            for label in _raw_text(candidate).replace(",", "+").split("+"):
                label = label.strip()
                if label and label not in labels:
                    labels.append(label)
    ordered = [
        label
        for label in (
            "FORMAL_STRATEGY_POOL",
            "ACTIVE_STRATEGY_POSITION",
            "DYNAMIC_CANDIDATE",
        )
        if label in labels
    ]
    return tuple(ordered or labels)


def _metadata(
    result: Mapping[str, Any], universe: Mapping[str, Any], symbol: str
) -> tuple[str, str]:
    symbol_metadata = _lookup(universe, "symbol_metadata", symbol)
    candidate_metadata = _lookup(universe, "candidate_metadata", symbol)
    return (
        _display(
            _first_value(
                result.get("name"),
                symbol_metadata.get("name"),
                candidate_metadata.get("name"),
                result.get("stock_name"),
            )
        ),
        _display(
            _first_value(
                result.get("sector"),
                symbol_metadata.get("sector"),
                candidate_metadata.get("sector"),
                result.get("industry"),
            )
        ),
    )


def _decision_action(decision: Mapping[str, Any]) -> str:
    return _raw_text(decision.get("action"))


def _event_is_new(result: Mapping[str, Any]) -> bool:
    return bool(
        _bool(result.get("event_was_new"))
        or _sequence(result.get("new_confirmed_event_identities"))
        or _text(result.get("new_confirmed_event_identity"))
    )


def _is_data_blocked(result: Mapping[str, Any], position_management: Mapping[str, Any]) -> bool:
    data_status = _text(result.get("data_status"))
    final_status = _text(result.get("final_status"))
    blocking = {_raw_text(value).split(":", 1)[0] for value in _sequence(result.get("blocking_prerequisites"))}
    return (
        data_status in _DATA_BLOCKED_STATUSES
        or final_status in _DATA_BLOCKED_FINAL_STATUSES
        or bool(blocking & _DATA_BLOCKING_REASONS)
        or (
            bool(position_management)
            and _text(position_management.get("status")) not in {"", _POSITION_OBSERVED}
        )
    )


def _is_position(
    result: Mapping[str, Any],
    universe: Mapping[str, Any],
    symbol: str,
    position_management: Mapping[str, Any],
    labels: Sequence[str],
) -> bool:
    return bool(
        position_management
        or "ACTIVE_STRATEGY_POSITION" in labels
        or _lookup(universe, "position_metadata", symbol)
        or _mapping(result.get("position"))
        or _mapping(result.get("position_context"))
    )


def _is_entry_allowed(
    decision: Mapping[str, Any], result: Mapping[str, Any]
) -> bool:
    if _decision_action(decision) != "ENTRY_ALLOWED":
        return False
    final_status = _text(result.get("final_status"))
    portfolio_status = _text(_mapping(result.get("portfolio_result")).get("status"))
    return final_status in {"ENTRY_ALLOWED", "PORTFOLIO_ALLOWED"} or portfolio_status == "PORTFOLIO_ALLOWED"


def _setup(result: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    primary_wave = _text(result.get("primary_wave_scenario"))
    mapped = _PRIMARY_SETUP_BY_WAVE.get(primary_wave)
    if mapped:
        return mapped
    event_identity = _text(decision.get("event_identity"))
    for setup in ("SETUP_01", "SETUP_02"):
        if setup in event_identity:
            return setup
    states = []
    for setup, state in (("SETUP_01", result.get("setup01_state")), ("SETUP_02", result.get("setup02_state"))):
        if _text(state) not in {"", "NONE"}:
            states.append(setup)
    return " / ".join(states)


def _stage(
    result: Mapping[str, Any],
    decision: Mapping[str, Any],
    position_management: Mapping[str, Any],
    *,
    is_position: bool,
    is_data_blocked: bool,
    event_is_new: bool,
) -> str:
    if is_data_blocked:
        return "DATA_BLOCKED"
    if is_position:
        return "POSITION_MANAGEMENT"
    if _is_entry_allowed(decision, result):
        return "ENTRY_ALLOWED"
    if _decision_action(decision) == "ENTRY_ALLOWED" or _text(result.get("final_status")) == "STRATEGY_PROPOSAL":
        return "STRATEGY_PROPOSAL"
    if event_is_new:
        return "CONFIRMED"
    if _text(result.get("final_status")) == "FAILED" or _text(result.get("setup01_state")) == "FAILED" or _text(result.get("setup02_state")) == "FAILED":
        return "FAILED"
    states = {_text(result.get("setup01_state")), _text(result.get("setup02_state"))}
    if "ARMED" in states:
        return "ARMED"
    if "WATCH" in states:
        return "WATCH"
    return "NO_TRADE"


def _translate_reason(value: Any) -> str:
    text = _raw_text(value)
    if not text:
        return ""
    translations = (
        ("STRATEGY_PROPOSAL_APPROVAL_REQUIRED", "等待人工批准该交易方案"),
        ("ALLOCATION_BUDGET_REQUIRED", "等待提供策略风险预算"),
        ("T1_EXECUTION_DATA_REQUIRED", "等待补齐 T+1 执行数据"),
        ("PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED", "等待交易日历前置条件"),
        ("POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT", "等待补齐持仓来源记录"),
        ("PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED", "等待补齐持仓风险记录"),
        ("PORTFOLIO_PENDING_RESERVATION_UNRESOLVED", "等待处理未完成的组合风险预留"),
        ("PORTFOLIO_EXISTING_POSITION_CONFLICT", "等待解决现有持仓记录冲突"),
        ("QFQ_HISTORY_MUST_REACH_COMPLETED_SESSION_T", "等待历史行情覆盖到数据日期"),
        ("UPSTREAM_EVALUATION_FAILED", "等待上游结构分析恢复"),
        ("DECISION_EVALUATION_FAILED", "等待交易方案计算恢复"),
        ("等待新的 CONFIRMED event", "等待新的确认事件"),
        ("T 日没有新的 CONFIRMED event", "今天没有新的确认事件"),
    )
    for prefix, label in translations:
        if text == prefix or text.startswith(prefix + ":"):
            return label
    if text.startswith("DATA_QUALITY_"):
        return "等待数据质量恢复"
    return text


def _reason_text(result: Mapping[str, Any]) -> str:
    values = [
        *(_sequence(result.get("reasons"))),
        *(_sequence(result.get("blocking_prerequisites"))),
    ]
    translated: list[str] = []
    for value in values:
        text = _translate_reason(value)
        if text and text not in translated:
            translated.append(text)
    return "；".join(translated)


def _confirmation_value(result: Mapping[str, Any], decision: Mapping[str, Any]) -> Any:
    return _first_value(
        result.get("confirmation_level"),
        result.get("confirmation_threshold"),
        result.get("trigger_threshold"),
        decision.get("confirmation_level"),
        decision.get("confirmation_threshold"),
        decision.get("trigger_threshold"),
    )


def _earliest_execution_session(result: Mapping[str, Any], decision: Mapping[str, Any]) -> Any:
    return _first_value(
        result.get("earliest_execution_session"),
        result.get("expected_execution_date"),
        decision.get("earliest_execution_session"),
        decision.get("expected_execution_date"),
    )


def _waiting(
    stage: str,
    result: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    candidate_only: bool,
    position_management: Mapping[str, Any],
) -> str:
    if stage == "WATCH":
        return "下一步：等待结构进一步形成"
    if stage == "ARMED":
        confirmation = _confirmation_value(result, decision)
        if confirmation is not None:
            return f"确认价：{_display(confirmation)}"
        return _reason_text(result) or "等待确认条件"
    if stage == "CONFIRMED":
        return _reason_text(result) or "等待交易方案形成"
    if stage == "STRATEGY_PROPOSAL":
        if candidate_only:
            return "候选观察池：尚未进入正式策略池"
        return _reason_text(result) or "等待人工确认与后续执行条件"
    if stage == "ENTRY_ALLOWED":
        execution_session = _earliest_execution_session(result, decision)
        if execution_session is not None:
            return f"最早执行 session：{_display(execution_session)}"
        return "交易方案已具备，按现有执行阶段推进"
    if stage == "POSITION_MANAGEMENT":
        action = _text(position_management.get("action"))
        return {
            "HOLD": "继续持有，观察保护止损与目标",
            "NO_ADD": "暂不加仓，继续观察持仓管理结果",
            "PROFIT_PROTECTION": "按现有持仓管理结果保护利润",
            "EXIT": "按现有持仓管理结果执行退出",
        }.get(action, _reason_text(result) or "按现有持仓管理结果处理")
    if stage == "FAILED":
        return "结构已失效，今天不交易"
    if stage == "DATA_BLOCKED":
        return "等待数据恢复或补齐生产前置条件"
    if _text(result.get("primary_action")) == "WAIT_CONFIRMATION":
        return "等待确认"
    return _reason_text(result) or "今天不交易"


def _targets(decision: Mapping[str, Any]) -> tuple[Any, ...]:
    values = _sequence(decision.get("targets"))
    if not values:
        values = tuple(decision.get(key) for key in ("T1", "T2", "T3"))
    return tuple(values[:3])


def _rr_display(decision: Mapping[str, Any]) -> str:
    rr = _mapping(decision.get("rr"))
    ratios = _sequence(rr.get("rr_ratios"))
    if ratios:
        return " / ".join(f"{_display(value)}R" for value in ratios)
    return _display(rr.get("rr"))


def _price_plan(decision: Mapping[str, Any]) -> dict[str, Any]:
    target_values = _targets(decision)
    return {
        "planned_entry": _display(decision.get("planned_entry"), "尚未形成"),
        "execution_stop": _display(decision.get("execution_stop")),
        "target_1": _display(target_values[0] if len(target_values) > 0 else None),
        "target_2": _display(target_values[1] if len(target_values) > 1 else None),
        "target_3": _display(target_values[2] if len(target_values) > 2 else None),
        "rr": _rr_display(decision),
        "rr_quality": _display(_mapping(decision.get("rr")).get("quality")),
        "confirmation_level": _display(decision.get("confirmation_level")),
        "entry_zone_low": _display(decision.get("entry_zone_low")),
        "entry_zone_high": _display(decision.get("entry_zone_high")),
        "has_decision": bool(decision),
    }


def _position_projection(
    result: Mapping[str, Any], universe: Mapping[str, Any], symbol: str,
    position_management: Mapping[str, Any],
) -> dict[str, Any]:
    position = _mapping(result.get("position")) or _mapping(result.get("position_context"))
    stored = _lookup(universe, "position_metadata", symbol)
    targets = _first_value(
        position_management.get("targets"),
        position.get("targets"),
        stored.get("targets"),
    )
    target_values = _sequence(targets)
    return {
        "actual_entry": _display(
            _first_value(
                position_management.get("actual_entry"),
                position.get("actual_entry"),
                stored.get("actual_entry"),
            )
        ),
        "current_price": _display(
            _first_value(
                position_management.get("current_price"),
                position.get("current_price"),
                stored.get("current_price"),
            )
        ),
        "active_protective_stop": _display(
            _first_value(
                position_management.get("active_protective_stop"),
                position_management.get("active_stop_at_open"),
                position.get("active_protective_stop"),
                stored.get("active_protective_stop"),
            )
        ),
        "targets": tuple(target_values[:3]),
        "current_r": _display(
            _first_value(position_management.get("current_r"), position.get("current_r"), stored.get("current_r"))
        ),
        "mfe_r": _display(
            _first_value(position_management.get("mfe_r"), position.get("mfe_r"), stored.get("mfe_r"))
        ),
        "mae_r": _display(
            _first_value(position_management.get("mae_r"), position.get("mae_r"), stored.get("mae_r"))
        ),
        "mfe_drawdown_r": _display(
            _first_value(
                position_management.get("mfe_drawdown_r"),
                position.get("mfe_drawdown_r"),
                stored.get("mfe_drawdown_r"),
            )
        ),
        "action": _display(
            _first_value(position_management.get("action"), position.get("action"), stored.get("action"))
        ),
        "action_label": ACTION_LABELS.get(
            _text(_first_value(position_management.get("action"), position.get("action"), stored.get("action"))),
            _display(_first_value(position_management.get("action"), position.get("action"), stored.get("action"))),
        ),
        "target_status": _display(position_management.get("target_status")),
        "wave5_context": _display(
            _first_value(position_management.get("wave5_context"), result.get("wave5_context"))
        ),
    }


def _make_row(entry: Mapping[str, Any], result_value: Any) -> dict[str, Any] | None:
    result = _mapping(result_value)
    symbol = _normalised_symbol(result.get("symbol"))
    if not symbol:
        return None
    universe = _mapping(entry.get("universe"))
    market = _normalised_market(result.get("market")) or _normalised_market(entry.get("market"))
    decision = _mapping(result.get("individual_decision"))
    position_management = _mapping(result.get("position_management"))
    labels = _provenance_labels(result, universe, symbol)
    provenance_metadata = _lookup(universe, "provenance_metadata", symbol)
    candidate_only = (
        labels == ("DYNAMIC_CANDIDATE",)
        or provenance_metadata.get("source") == "DYNAMIC_CANDIDATE"
    )
    is_position = _is_position(result, universe, symbol, position_management, labels)
    data_blocked = _is_data_blocked(result, position_management)
    event_is_new = _event_is_new(result)
    stage = _stage(
        result,
        decision,
        position_management,
        is_position=is_position,
        is_data_blocked=data_blocked,
        event_is_new=event_is_new,
    )
    name, sector = _metadata(result, universe, symbol)
    setup = _setup(result, decision)
    final_status = _text(result.get("final_status"))
    action = _text(result.get("primary_action")) or _decision_action(decision)
    return {
        "account_id": _text(entry.get("account_id"), "—"),
        "symbol": symbol,
        "market": market or "—",
        "market_label": MARKET_LABELS.get(market, market or "—"),
        "name": name,
        "sector": sector,
        "stage_key": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "status_key": final_status or stage,
        "status_label": STATUS_LABELS.get(final_status, STAGE_LABELS.get(stage, final_status or "—")),
        "action_key": action or "—",
        "action_label": ACTION_LABELS.get(action, STATUS_LABELS.get(action, action or "—")),
        "primary_wave": _text(result.get("primary_wave_scenario"), "UNKNOWN"),
        "primary_wave_label": WAVE_LABELS.get(
            _text(result.get("primary_wave_scenario")),
            f"波浪状态：{_text(result.get('primary_wave_scenario'), 'UNKNOWN')}",
        ),
        "alternate_wave": _text(result.get("alternate_wave_scenario"), "UNKNOWN"),
        "alternate_wave_label": WAVE_LABELS.get(
            _text(result.get("alternate_wave_scenario")),
            f"波浪状态：{_text(result.get('alternate_wave_scenario'), 'UNKNOWN')}",
        ),
        "setup": setup or "—",
        "setup01_state": _text(result.get("setup01_state"), "NONE"),
        "setup02_state": _text(result.get("setup02_state"), "NONE"),
        "identity_labels": _identity_labels(labels, candidate_only, is_position),
        "provenance_labels": tuple(labels),
        "candidate_only": candidate_only,
        "is_position": is_position,
        "data_blocked": data_blocked,
        "event_is_new": event_is_new,
        "waiting": _waiting(
            stage,
            result,
            decision,
            candidate_only=candidate_only,
            position_management=position_management,
        ),
        "plan": _price_plan(decision),
        "position": _position_projection(result, universe, symbol, position_management),
        "decision": decision,
        "portfolio_result": _mapping(result.get("portfolio_result")),
        "position_management": position_management,
        "reasons": tuple(_raw_text(value) for value in _sequence(result.get("reasons")) if _raw_text(value)),
        "blocking_prerequisites": tuple(
            _raw_text(value)
            for value in _sequence(result.get("blocking_prerequisites"))
            if _raw_text(value)
        ),
        "raw_result": result,
    }


def _identity_labels(labels: Sequence[str], candidate_only: bool, is_position: bool) -> tuple[str, ...]:
    result: list[str] = []
    if candidate_only:
        result.append("候选观察池")
        result.append("尚未进入正式策略池")
    else:
        if "FORMAL_STRATEGY_POOL" in labels:
            result.append("正式策略池")
        if is_position or "ACTIVE_STRATEGY_POSITION" in labels:
            result.append("持仓管理")
        if "DYNAMIC_CANDIDATE" in labels:
            result.append("候选来源")
    return tuple(result or ("未标注",))


def _candidate_total(payload: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> int:
    by_market: dict[str, int] = {}
    candidate_markets = _mapping(payload.get("candidate_markets"))
    if candidate_markets:
        for market, value in candidate_markets.items():
            candidate = _mapping(value)
            symbols = {_normalised_symbol(item) for item in _sequence(candidate.get("candidate_included_symbols")) if _normalised_symbol(item)}
            count = candidate.get("candidate_included_count")
            try:
                numeric_count = int(count) if count is not None else 0
            except (TypeError, ValueError):
                numeric_count = 0
            by_market[_normalised_market(market)] = max(numeric_count, len(symbols))
    else:
        for entry in entries:
            market = _normalised_market(entry.get("market"))
            candidate = entry.get("candidate", {})
            symbols = {_normalised_symbol(item) for item in _sequence(candidate.get("candidate_included_symbols")) if _normalised_symbol(item)}
            count = candidate.get("candidate_included_count")
            try:
                numeric_count = int(count) if count is not None else 0
            except (TypeError, ValueError):
                numeric_count = 0
            if market:
                by_market[market] = max(by_market.get(market, 0), numeric_count, len(symbols))
    total = sum(by_market.values())
    if total:
        return total
    identities = {
        (row["market"], row["symbol"])
        for row in rows
        if row["candidate_only"] or "DYNAMIC_CANDIDATE" in row["provenance_labels"]
    }
    return len(identities)


def _preflight_market_status(payload: Mapping[str, Any], market: str) -> bool:
    preflight = _mapping(payload.get("preflight"))
    for account in _sequence(preflight.get("accounts")):
        account = _mapping(account)
        if _normalised_market(account.get("市场")) == market or _normalised_market(account.get("market")) == market:
            readiness = _text(account.get("production readiness")) or _text(account.get("production_readiness"))
            if readiness and readiness != "READY":
                return True
    return False


def _market_status(
    payload: Mapping[str, Any], market: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    candidate_markets = _mapping(payload.get("candidate_markets"))
    candidate = _mapping(candidate_markets.get(market))
    candidate_status = _text(candidate.get("status"))
    blocked = any(row["data_blocked"] for row in rows if row["market"] == market)
    blocked = blocked or candidate_status == "FAILED" or _preflight_market_status(payload, market)
    if blocked:
        return {"status_key": "DATA_BLOCKED", "status_label": "数据异常"}
    if not rows and (candidate_status in {"", "NOT_RUN"}):
        return {"status_key": "NOT_RUN", "status_label": "未运行"}
    return {"status_key": "DATA_OK", "status_label": "数据正常"}


def build_dashboard_projection(value: Any) -> dict[str, Any]:
    """Build a deterministic, presentation-only dashboard projection."""

    payload = _as_payload(value)
    entries = _report_entries(payload)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        report = _mapping(entry.get("report"))
        for result in _sequence(report.get("results")):
            projected = _make_row(entry, result)
            if projected is not None:
                rows.append(projected)
    stage_rank = {stage: index for index, stage in enumerate(STAGE_ORDER)}
    rows.sort(key=lambda row: (stage_rank.get(row["stage_key"], len(STAGE_ORDER)), row["market"], row["symbol"], row["account_id"]))

    preflight = _mapping(payload.get("preflight"))
    as_of_date = _first_value(payload.get("as_of_date"), preflight.get("T"))
    if as_of_date is None:
        as_of_date = next((row["raw_result"].get("as_of_date") for row in rows if row["raw_result"].get("as_of_date")), None)
    generated_at = _first_value(payload.get("generated_at"), next((row["raw_result"].get("generated_at") for row in rows if row["raw_result"].get("generated_at")), None))
    known_markets = {row["market"] for row in rows if row["market"] and row["market"] != "—"}
    known_markets.update(_normalised_market(item) for item in _mapping(payload.get("candidate_markets")))
    known_markets.update(
        _normalised_market(_mapping(account).get("市场") or _mapping(account).get("market"))
        for account in _sequence(preflight.get("accounts"))
    )
    markets = ["CN", "US"]
    markets.extend(sorted(known_markets - set(markets)))
    market_rows = []
    for market in markets:
        status = _market_status(payload, market, rows)
        market_rows.append(
            {
                "market": market,
                "label": MARKET_LABELS.get(market, market),
                **status,
            }
        )

    summary = {
        "candidate_total": _candidate_total(payload, entries, rows),
        "watch_count": sum(row["stage_key"] == "WATCH" for row in rows),
        "armed_count": sum(row["stage_key"] == "ARMED" for row in rows),
        "new_confirmed_count": sum(row["event_is_new"] for row in rows),
        "strategy_proposal_count": sum(row["stage_key"] == "STRATEGY_PROPOSAL" for row in rows),
        "entry_allowed_count": sum(row["stage_key"] == "ENTRY_ALLOWED" for row in rows),
        "position_count": sum(row["is_position"] for row in rows),
        "data_blocked_count": sum(row["stage_key"] == "DATA_BLOCKED" for row in rows),
    }
    sectors = sorted({row["sector"] for row in rows if row["sector"] != "—"}, key=str.casefold)
    return {
        "title": "每日交易决策工作台",
        "as_of_date": _display(as_of_date),
        "generated_at": _display(generated_at),
        "summary": summary,
        "markets": market_rows,
        "rows": rows,
        "sectors": sectors,
        "stage_order": STAGE_ORDER,
    }


def _escape(value: Any) -> str:
    return html.escape(_display(value), quote=True)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _metric(label: str, value: Any, tone: str = "") -> str:
    return (
        f'<div class="metric {tone}"><div class="metric-label">{_escape(label)}</div>'
        f'<div class="metric-value">{_escape(value)}</div></div>'
    )


def _field(label: str, value: Any, *, extra_class: str = "") -> str:
    return (
        f'<div class="field {extra_class}"><div class="field-label">{_escape(label)}</div>'
        f'<div class="field-value">{_escape(value)}</div></div>'
    )


def _render_plan(row: Mapping[str, Any]) -> str:
    plan = _mapping(row.get("plan"))
    return (
        '<section class="panel plan-panel"><h3>交易方案</h3><div class="field-grid plan-grid">'
        + "".join(
            _field(label, plan.get(key), extra_class="highlight" if key == "planned_entry" else "")
            for label, key in (
                ("计划入场", "planned_entry"),
                ("Execution Stop", "execution_stop"),
                ("Target 1", "target_1"),
                ("Target 2", "target_2"),
                ("Target 3", "target_3"),
                ("R/R", "rr"),
            )
        )
        + "</div></section>"
    )


def _render_position(row: Mapping[str, Any]) -> str:
    position = _mapping(row.get("position"))
    return (
        '<section class="panel position-panel"><h3>持仓管理</h3><div class="field-grid">'
        + "".join(
            _field(label, position.get(key))
            for label, key in (
                ("实际入场", "actual_entry"),
                ("当前价格", "current_price"),
                ("当前保护止损", "active_protective_stop"),
                ("Target 1", "target_1"),
                ("Target 2", "target_2"),
                ("Target 3", "target_3"),
                ("Current R", "current_r"),
                ("MFE", "mfe_r"),
                ("MAE", "mae_r"),
                ("MFE Drawdown", "mfe_drawdown_r"),
                ("管理动作", "action_label"),
            )
        )
        + "</div></section>"
    )


def _position_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    position = _mapping(row.get("position"))
    targets = _sequence(position.get("targets"))
    return {
        **position,
        "target_1": _display(targets[0] if len(targets) > 0 else None),
        "target_2": _display(targets[1] if len(targets) > 1 else None),
        "target_3": _display(targets[2] if len(targets) > 2 else None),
    }


def _render_details(row: Mapping[str, Any]) -> str:
    position = _position_fields(row)
    result = _mapping(row.get("raw_result"))
    decision = _mapping(row.get("decision"))
    wave_evidence = _first_value(
        result.get("wave_evidence"),
        result.get("wave_evidence_summary"),
        result.get("evidence"),
        decision.get("gate_detail"),
    )
    wave_invalidation = _first_value(
        result.get("wave_invalidation"),
        result.get("structural_invalidation"),
        result.get("invalidation"),
        decision.get("structural_invalidation"),
        decision.get("wave_scenario_invalidation"),
    )
    fibonacci_regions = _first_value(
        result.get("fibonacci_candidate_regions"),
        result.get("fibonacci_retracement_regions"),
        result.get("fibonacci_extension_regions"),
        decision.get("fibonacci_candidate_regions"),
        decision.get("target_candidates"),
    )
    fibonacci_text = (
        _json_text(fibonacci_regions)
        if isinstance(fibonacci_regions, (Mapping, list, tuple))
        else _display(fibonacci_regions)
    )
    return (
        '<details class="details"><summary>查看专业详情</summary>'
        '<div class="detail-grid">'
        '<section><h4>Primary / Alternate Wave</h4>'
        f'<p>{_escape(row.get("primary_wave_label"))} <code>{_escape(row.get("primary_wave"))}</code></p>'
        f'<p>{_escape(row.get("alternate_wave_label"))} <code>{_escape(row.get("alternate_wave"))}</code></p>'
        f'<p>Wave evidence：{_escape(wave_evidence)}</p>'
        f'<p>Invalidation：{_escape(wave_invalidation)}</p>'
        f'<p>周线／日线：{_escape(result.get("weekly_state"))} / {_escape(result.get("daily_state"))}</p>'
        f'<p>Fibonacci 候选区域：{_escape(fibonacci_text)}</p></section>'
        '<section><h4>Setup / Decision</h4>'
        f'<p>SETUP_01：{_escape(row.get("setup01_state"))}；SETUP_02：{_escape(row.get("setup02_state"))}</p>'
        f'<p>Setup：{_escape(row.get("setup"))}</p>'
        f'<p>Gate / confirmation：{_escape(_mapping(row.get("decision")).get("gate_reason"))} / {_escape(_mapping(row.get("decision")).get("confirmation_level"))}</p>'
        f'<p>Entry zone：{_escape(_mapping(row.get("plan")).get("entry_zone_low"))} — {_escape(_mapping(row.get("plan")).get("entry_zone_high"))}</p></section>'
        '<section><h4>Risk / Portfolio Risk</h4>'
        f'<p>R/R quality：{_escape(_mapping(row.get("plan")).get("rr_quality"))}</p>'
        f'<p>Portfolio Risk：{_escape(_mapping(row.get("portfolio_result")).get("status"))} / {_escape(_mapping(row.get("portfolio_result")).get("reason"))}</p>'
        f'<p>Risk group：{_escape(_mapping(row.get("portfolio_result")).get("risk_group"))}</p></section>'
        '<section><h4>Position Management</h4>'
        f'<p>状态：{_escape(_mapping(row.get("position_management")).get("status"))}</p>'
        f'<p>Wave5：{_escape(position.get("wave5_context"))}；Target status：{_escape(position.get("target_status"))}</p>'
        f'<p>Waiting / blocking：{_escape(row.get("waiting"))}</p></section>'
        '</div>'
        f'<h4>原始 Daily Decision 字段</h4><pre>{html.escape(_json_text(result), quote=False)}</pre>'
        '</details>'
    )


def _render_row(row: Mapping[str, Any]) -> str:
    identity = "".join(
        f'<span class="badge {"warning" if row["candidate_only"] else ""}">{_escape(value)}</span>'
        for value in row["identity_labels"]
    )
    if row["event_is_new"]:
        identity += '<span class="badge positive">今日确认</span>'
    position = _position_fields(row)
    position_block = _render_position({**row, "position": position}) if row["is_position"] else ""
    stage_class = row["stage_key"].lower().replace("_", "-")
    return (
        f'<article class="stock-card" data-market="{_escape(row["market"])}" '
        f'data-stage="{_escape(row["stage_key"])}" data-setup="{_escape(row["setup"])}" '
        f'data-sector="{_escape(row["sector"] if row["sector"] != "—" else "")}">'
        '<div class="card-top"><div>'
        f'<span class="ticker">{_escape(row["symbol"])}</span>'
        f'<span class="market-chip">{_escape(row["market"])} · {_escape(row["market_label"])}</span>'
        '</div>'
        f'<span class="stage stage-{stage_class}">{_escape(row["stage_label"])}</span></div>'
        f'<h2>{_escape(row["name"])}</h2><div class="sector">{_escape(row["sector"])}</div>'
        '<div class="field-grid card-facts">'
        + _field("当前阶段", row["stage_label"])
        + _field("Primary Wave", row["primary_wave_label"])
        + _field("Setup", row["setup"])
        + _field("决策动作", row["action_label"])
        + '</div><div class="identity-row">'
        + identity
        + f'</div><div class="waiting"><strong>下一步</strong><span>{_escape(row["waiting"])}</span></div>'
        + _render_plan(row)
        + position_block
        + _render_details(row)
        + '</article>'
    )


def _render_market_cards(markets: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        '<div class="market-card">'
        f'<div><span class="market-name">{_escape(item.get("market"))}</span>'
        f'<span class="market-label">{_escape(item.get("label"))}</span></div>'
        f'<span class="data-status status-{_escape(item.get("status_key"))}">{_escape(item.get("status_label"))}</span>'
        '</div>'
        for item in markets
    )


def render_dashboard_html(value: Any) -> str:
    """Render a standalone UTF-8 HTML dashboard from an existing result."""

    projection = build_dashboard_projection(value)
    summary = projection["summary"]
    sector_options = "".join(
        f'<option value="{_escape(sector)}">{_escape(sector)}</option>'
        for sector in projection["sectors"]
    )
    stage_options = "".join(
        f'<option value="{_escape(stage)}">{_escape(STAGE_LABELS.get(stage, stage))}</option>'
        for stage in projection["stage_order"]
    )
    stage_nav = "".join(
        f'<button type="button" class="stage-link" data-stage="{_escape(stage)}">{_escape(STAGE_LABELS.get(stage, stage))}</button>'
        for stage in projection["stage_order"][:6]
    )
    cards = "".join(_render_row(row) for row in projection["rows"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(projection['title'])} · {_escape(projection['as_of_date'])}</title>
<style>
:root {{ color-scheme: light; --ink:#162334; --muted:#66758a; --line:#dce4ee; --paper:#f5f7fb; --card:#fff; --teal:#0f766e; --teal-soft:#d9f2ed; --amber:#b45309; --amber-soft:#fff0d5; --red:#b42318; --red-soft:#fee4e2; --blue:#275dad; --blue-soft:#e4efff; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 "Segoe UI","Microsoft YaHei",sans-serif; }}
.shell {{ width:min(1440px,calc(100% - 32px)); margin:0 auto; padding:28px 0 56px; }}
.hero {{ background:linear-gradient(135deg,#12263d,#21516c); color:#fff; border-radius:22px; padding:30px 34px; box-shadow:0 16px 36px #13263d24; }}
.eyebrow {{ color:#b8e5dc; font-size:12px; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ margin:8px 0 4px; font-size:clamp(28px,4vw,44px); letter-spacing:-.03em; }}
.hero-meta {{ color:#d9e8f2; display:flex; gap:18px; flex-wrap:wrap; }} .readonly-note {{ margin:20px 0 0; color:#e9f4f8; font-size:13px; }}
.summary-grid {{ display:grid; grid-template-columns:repeat(8,minmax(0,1fr)); gap:10px; margin:18px 0 12px; }} .metric {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:13px 14px; min-height:88px; }}
.metric-label,.field-label {{ color:var(--muted); font-size:12px; }} .metric-value {{ margin-top:5px; font-size:26px; font-weight:750; }} .metric:nth-child(4) .metric-value,.metric:nth-child(5) .metric-value {{ color:var(--teal); }} .metric:nth-child(8) .metric-value {{ color:var(--red); }}
.market-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-bottom:20px; }} .market-card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 18px; display:flex; justify-content:space-between; align-items:center; }}
.market-name {{ font-weight:750; font-size:19px; margin-right:10px; }} .market-label {{ color:var(--muted); font-size:13px; }} .data-status {{ border-radius:999px; padding:4px 11px; font-weight:700; font-size:13px; }} .status-DATA_OK {{ background:var(--teal-soft); color:var(--teal); }} .status-DATA_BLOCKED {{ background:var(--red-soft); color:var(--red); }} .status-NOT_RUN {{ background:#edf1f6; color:var(--muted); }}
.stage-nav {{ display:flex; gap:8px; flex-wrap:wrap; margin:4px 0 14px; align-items:center; }} .stage-nav-label {{ color:var(--muted); font-weight:700; margin-right:3px; }} .stage-link {{ border:0; background:transparent; color:var(--blue); font:inherit; font-weight:700; cursor:pointer; padding:6px 2px; }} .stage-link:not(:last-child)::after {{ content:"→"; color:#aab6c5; margin-left:9px; }} .stage-link:hover {{ color:var(--teal); }}
.filters {{ display:flex; gap:10px; flex-wrap:wrap; background:#eaf0f6; border:1px solid var(--line); border-radius:14px; padding:12px; margin-bottom:18px; }} .filters label {{ display:flex; align-items:center; gap:7px; color:var(--muted); font-size:13px; }} select {{ border:1px solid #cbd6e2; border-radius:8px; background:#fff; color:var(--ink); padding:7px 30px 7px 9px; font:inherit; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:16px; }} .stock-card {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:19px; box-shadow:0 8px 22px #18324b0c; }} .stock-card[hidden] {{ display:none; }}
.card-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }} .ticker {{ font-size:20px; font-weight:800; letter-spacing:.02em; }} .market-chip {{ color:var(--muted); font-size:12px; margin-left:8px; }} .stage {{ white-space:nowrap; border-radius:999px; padding:4px 10px; font-size:13px; font-weight:750; }} .stage-watch,.stage-armed {{ background:var(--amber-soft); color:var(--amber); }} .stage-confirmed,.stage-strategy-proposal,.stage-entry-allowed {{ background:var(--blue-soft); color:var(--blue); }} .stage-position-management {{ background:var(--teal-soft); color:var(--teal); }} .stage-failed,.stage-data-blocked {{ background:var(--red-soft); color:var(--red); }} .stage-no-trade {{ background:#edf1f6; color:var(--muted); }}
.stock-card h2 {{ margin:12px 0 0; font-size:22px; }} .sector {{ color:var(--muted); min-height:24px; }} .field-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }} .card-facts {{ margin:16px 0; }} .field {{ min-width:0; }} .field-value {{ margin-top:2px; font-weight:650; overflow-wrap:anywhere; }} .highlight .field-value {{ color:var(--teal); }}
.identity-row {{ display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 14px; }} .badge {{ border:1px solid #c8d6e2; border-radius:999px; padding:3px 8px; color:#486074; font-size:12px; background:#f7fafc; }} .badge.warning {{ color:var(--amber); border-color:#f2ca8c; background:var(--amber-soft); }} .badge.positive {{ color:var(--teal); border-color:#9ed7ca; background:var(--teal-soft); }}
.waiting {{ display:flex; gap:9px; align-items:flex-start; padding:11px 12px; background:#f1f6fa; border-radius:11px; margin-bottom:12px; }} .waiting strong {{ white-space:nowrap; color:var(--blue); }} .waiting span {{ overflow-wrap:anywhere; }} .panel {{ border-top:1px solid var(--line); padding-top:13px; margin-top:13px; }} .panel h3 {{ margin:0 0 9px; font-size:14px; }} .plan-panel h3 {{ color:var(--blue); }} .position-panel h3 {{ color:var(--teal); }} .details {{ border-top:1px solid var(--line); margin-top:14px; padding-top:10px; }} .details summary {{ cursor:pointer; color:var(--blue); font-weight:700; }} .detail-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:12px; }} .detail-grid section {{ background:#f8fafc; border-radius:10px; padding:10px 12px; }} .detail-grid h4,.details h4 {{ margin:0 0 5px; font-size:13px; }} .detail-grid p {{ margin:3px 0; font-size:13px; overflow-wrap:anywhere; }} code {{ color:#5c6d80; font-size:11px; }} pre {{ max-height:300px; overflow:auto; white-space:pre-wrap; background:#111d2a; color:#dce9f4; border-radius:10px; padding:12px; font:12px/1.5 Consolas,monospace; }}
.empty {{ color:var(--muted); text-align:center; padding:40px; background:#fff; border:1px dashed #c5d1df; border-radius:14px; }} .footer {{ color:var(--muted); font-size:12px; margin-top:22px; }}
@media (max-width:1050px) {{ .summary-grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); }} }} @media (max-width:620px) {{ .shell {{ width:min(100% - 20px,1440px); padding-top:10px; }} .hero {{ padding:24px 20px; border-radius:16px; }} .summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .market-grid {{ grid-template-columns:1fr; }} .cards {{ grid-template-columns:1fr; }} .stock-card {{ padding:15px; }} .detail-grid {{ grid-template-columns:1fr; }} .field-grid {{ gap:8px; }} .ticker {{ font-size:18px; }} }}
</style>
</head>
<body>
<main class="shell">
<header class="hero"><div class="eyebrow">READ-ONLY · PRODUCTION DAILY DECISION CHAIN</div><h1>{_escape(projection['title'])}</h1><div class="hero-meta"><span>数据日期：{_escape(projection['as_of_date'])}</span><span>生成时间：{_escape(projection['generated_at'])}</span></div><div class="readonly-note">页面只展示既有 Daily Decision、Risk 和 Position Management 结果；中文阶段名称属于展示映射，不会产生新信号或订单。</div></header>
<section class="summary-grid" aria-label="今日摘要">
{_metric('Candidate 总数', summary['candidate_total'])}
{_metric('观察中', summary['watch_count'])}
{_metric('接近确认', summary['armed_count'])}
{_metric('今日新确认', summary['new_confirmed_count'], 'positive')}
{_metric('已形成交易方案', summary['strategy_proposal_count'])}
{_metric('可入场', summary['entry_allowed_count'], 'positive')}
{_metric('当前持仓', summary['position_count'])}
{_metric('数据异常', summary['data_blocked_count'], 'danger')}
</section>
<section class="market-grid" aria-label="市场数据状态">{_render_market_cards(projection['markets'])}</section>
<nav class="stage-nav" aria-label="阶段导航"><span class="stage-nav-label">阶段查看：</span>{stage_nav}</nav>
<section class="filters" aria-label="股票筛选"><label>市场<select id="market-filter"><option value="">全部</option><option value="CN">CN</option><option value="US">US</option></select></label><label>当前阶段<select id="stage-filter"><option value="">全部</option>{stage_options}</select></label><label>Setup<select id="setup-filter"><option value="">全部</option><option value="SETUP_01">SETUP_01</option><option value="SETUP_02">SETUP_02</option></select></label><label>行业／板块<select id="sector-filter"><option value="">全部</option>{sector_options}</select></label><span id="visible-count" class="stage-nav-label"></span></section>
<section id="cards" class="cards" aria-live="polite">{cards}</section><div id="empty" class="empty" hidden>没有符合当前筛选条件的股票。</div>
<div class="footer">内部状态、协议和原始诊断字段请展开股票卡片查看。Dashboard 不替代用户最终交易决定。</div>
</main>
<script>
(() => {{
  const cards = Array.from(document.querySelectorAll('.stock-card'));
  const market = document.getElementById('market-filter');
  const stage = document.getElementById('stage-filter');
  const setup = document.getElementById('setup-filter');
  const sector = document.getElementById('sector-filter');
  const empty = document.getElementById('empty');
  const count = document.getElementById('visible-count');
  const apply = () => {{
    let visible = 0;
    cards.forEach(card => {{
      const setupValues = card.dataset.setup.split(/\s*\/\s*/);
      const matches = (!market.value || card.dataset.market === market.value)
        && (!stage.value || card.dataset.stage === stage.value)
        && (!setup.value || setupValues.includes(setup.value))
        && (!sector.value || card.dataset.sector === sector.value);
      card.hidden = !matches;
      if (matches) visible += 1;
    }});
    empty.hidden = visible !== 0;
    count.textContent = `显示 ${{visible}} / ${{cards.length}}`;
  }};
  [market, stage, setup, sector].forEach(input => input.addEventListener('change', apply));
  document.querySelectorAll('.stage-link').forEach(button => button.addEventListener('click', () => {{ stage.value = button.dataset.stage; apply(); }}));
  apply();
}})();
</script>
</body>
</html>
"""


def load_dashboard_json(path: str | Path) -> Mapping[str, Any]:
    """Load a previously saved production result JSON for rendering."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_dashboard_html(
    value: Any,
    output_dir: str | Path = "reports/daily_dashboard",
) -> tuple[Path, ...]:
    """Write ``latest.html`` and a deterministic date-versioned HTML file."""

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    projection = build_dashboard_projection(value)
    content = render_dashboard_html(value)
    latest = target_dir / "latest.html"
    latest.write_text(content, encoding="utf-8")
    versioned: list[Path] = [latest]
    raw_date = projection.get("as_of_date")
    try:
        version_date = date.fromisoformat(str(raw_date))
    except (TypeError, ValueError):
        version_date = None
    if version_date is not None:
        dated = target_dir / f"{version_date.isoformat()}.html"
        dated.write_text(content, encoding="utf-8")
        versioned.append(dated)
    return tuple(versioned)


__all__ = [
    "ACTION_LABELS",
    "MARKET_LABELS",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STATUS_LABELS",
    "WAVE_LABELS",
    "dashboard_universe_metadata",
    "build_dashboard_projection",
    "load_dashboard_json",
    "render_dashboard_html",
    "write_dashboard_html",
]
