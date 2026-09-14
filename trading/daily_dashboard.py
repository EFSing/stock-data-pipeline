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
import re
from typing import Any

from trading.trade_logic_explanation import strategy_rules_for_dashboard


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

DEFAULT_FOCUS_STAGES = (
    "DATA_BLOCKED",
    "POSITION_MANAGEMENT",
    "ENTRY_ALLOWED",
    "STRATEGY_PROPOSAL",
    "CONFIRMED",
    "ARMED",
)

NAV_VIEW_ORDER = (
    "focus",
    "ARMED",
    "WATCH",
    "CONFIRMED",
    "STRATEGY_PROPOSAL",
    "ENTRY_ALLOWED",
    "POSITION_MANAGEMENT",
    "all",
)

STAGE_LABELS = {
    "WATCH": "观察中",
    "ARMED": "接近确认",
    "CONFIRMED": "今天出现新的确认",
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
    "CONFIRMED": "出现新的确认",
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
    "WAIT_CONFIRMATION": "继续观察",
    "ENTRY_ALLOWED": "当前满足入场条件",
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

WAVE_SHORT_LABELS = {
    "WAVE_2_TO_3_CANDIDATE": "2浪→3浪",
    "WAVE_3_CONTINUATION_CANDIDATE": "3浪延续",
    "ABC_CORRECTION_CANDIDATE": "ABC调整",
    "UPTREND_UNKNOWN_WAVE": "上升趋势·浪型未定",
    "DOWNTREND_OR_INVALID_FOR_LONG": "下行／不适合做多",
    "NO_VALID_SCENARIO": "暂无有效浪型",
    "RANGE": "结构整理中",
    "TRANSITION": "结构过渡中",
    "UNKNOWN": "波浪尚未确定",
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


def _numeric(value: Any) -> float | None:
    """Return a finite number for presentation-only formatting."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _format_number(
    value: Any,
    decimals: int,
    *,
    signed: bool = False,
    trim: bool = True,
) -> str:
    number = _numeric(value)
    if number is None:
        return _display(value)
    if abs(number) < 0.5 * 10 ** (-decimals):
        number = 0.0
    text = f"{number:.{decimals}f}"
    if trim:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        text = "0"
    if signed and number >= 0:
        text = "+" + text
    return text


def _format_price(value: Any, default: str = "—") -> str:
    if value is None or _raw_text(value) in {"", "—", "-"}:
        return default
    return _format_number(value, 4)


def _format_r(value: Any, default: str = "—") -> str:
    if value is None or _raw_text(value) in {"", "—", "-"}:
        return default
    return f"{_format_number(value, 2, signed=True, trim=False)}R"


def _format_rr(value: Any, default: str = "—") -> str:
    if value is None or _raw_text(value) in {"", "—", "-"}:
        return default
    return _format_number(value, 2, trim=False)


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
            "PAPER_TRACKED",
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


def _setup_states(result: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        state
        for state in (
            _text(result.get("setup01_state")),
            _text(result.get("setup02_state")),
        )
        if state not in {"", "NONE"}
    )


def _is_overall_failure(result: Mapping[str, Any]) -> bool:
    """Only project an explicit overall failure, never a setup-local failure."""

    explicit = _text(
        _first_value(
            result.get("overall_status"),
            result.get("overall_stage"),
            result.get("overall_final_status"),
        )
    )
    if explicit == "FAILED":
        return True
    if _text(result.get("final_status")) != "FAILED":
        return False
    states = _setup_states(result)
    # A single SETUP_01/02 FAILED row is local by default.  An unscoped final
    # failure is overall only when every reported setup has failed (or no setup
    # state was supplied at all).
    return not states or len(states) > 1 and all(state == "FAILED" for state in states)


def _has_persistent_confirmation(result: Mapping[str, Any]) -> bool:
    return not _event_is_new(result) and "CONFIRMED" in _setup_states(result)


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


def _setup_label(setup: str) -> str:
    """Return a compact Chinese setup label for the default stock row."""

    labels = {
        "SETUP_01": "2浪→3浪",
        "SETUP_02": "3浪延续",
    }
    return " / ".join(labels.get(item, item) for item in setup.split(" / ") if item)


def _human_wave_stage_label(
    result: Mapping[str, Any],
    *,
    primary_wave: str,
    stage: str,
    event_is_new: bool,
    data_blocked: bool,
) -> str:
    """Map the finite existing wave scenarios to mobile-facing language."""

    if data_blocked:
        return "当前浪型不可判断｜数据异常"
    if primary_wave == "WAVE_2_TO_3_CANDIDATE":
        if stage == "WATCH":
            return "2浪调整中｜继续观察"
        if stage == "ARMED":
            return "2浪末期｜等待3浪启动"
        if stage == "CONFIRMED" and event_is_new:
            return "3浪启动条件已确认"
        if stage in {"STRATEGY_PROPOSAL", "ENTRY_ALLOWED"}:
            return "3浪交易条件已确认｜已形成交易计划"
        if stage == "POSITION_MANAGEMENT":
            return "3浪结构持仓管理中"
        if _has_persistent_confirmation(result):
            return "3浪条件此前已确认｜今天没有新的交易信号"
    if primary_wave == "WAVE_3_CONTINUATION_CANDIDATE":
        if stage == "WATCH":
            return "3浪进行中｜观察延续结构"
        if stage == "ARMED":
            return "3浪进行中｜等待延续确认"
        if stage == "CONFIRMED" and event_is_new:
            return "3浪延续条件已确认"
        if stage in {"STRATEGY_PROPOSAL", "ENTRY_ALLOWED"}:
            return "3浪交易条件已确认｜已形成交易计划"
        if stage == "POSITION_MANAGEMENT":
            return "3浪结构持仓管理中"
        if _has_persistent_confirmation(result):
            return "3浪条件此前已确认｜今天没有新的交易信号"
    if primary_wave == "ABC_CORRECTION_CANDIDATE":
        return "ABC调整中｜3浪启动尚未确认"
    return WAVE_LABELS.get(primary_wave, f"波浪状态：{primary_wave}")


def _missing_condition(
    stage: str,
    result: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    candidate_only: bool,
    position_management: Mapping[str, Any],
) -> str:
    if stage == "ARMED":
        confirmation = _confirmation_value(result, decision)
        if confirmation is not None:
            return f"还差：收盘价有效突破前一段上涨高点 {_format_price(confirmation)}"
    return _waiting(
        stage,
        result,
        decision,
        candidate_only=candidate_only,
        position_management=position_management,
    )


def _invalidation_text(result: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    value = _first_value(
        result.get("wave_invalidation"),
        result.get("structural_invalidation"),
        result.get("invalidation"),
        decision.get("structural_invalidation"),
        decision.get("wave_scenario_invalidation"),
    )
    if isinstance(value, (Mapping, list, tuple)):
        return _json_text(value)
    return _display(value, "未提供明确结构失效条件")


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
    # A setup-local failure is not a whole-symbol failure.  Only an explicit
    # overall failure may project a symbol-level failure.
    if _is_overall_failure(result):
        return "FAILED"
    states = set(_setup_states(result))
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
        return "继续观察，暂不买入"
    if stage == "ARMED":
        confirmation = _confirmation_value(result, decision)
        if confirmation is not None:
            return f"等待收盘突破 {_format_price(confirmation)}。"
        return _reason_text(result) or "等待确认条件。"
    if stage == "CONFIRMED":
        # T-day confirmation is already followed by the existing individual
        # Decision calculation.  Do not imply that a plan is still forming.
        if _event_is_new(result):
            return "今天出现确认，但当前入场条件没有通过。"
        return _reason_text(result) or "今天没有新的交易信号。"
    if stage == "STRATEGY_PROPOSAL":
        if candidate_only:
            return "候选观察池，尚未进入正式策略池。"
        return _reason_text(result) or "交易方案已经形成，正式实盘仍需人工批准。"
    if stage == "ENTRY_ALLOWED":
        execution_session = _earliest_execution_session(result, decision)
        if execution_session is not None:
            return f"当前满足入场条件，等待 {_display(execution_session)}。"
        return "当前满足入场条件，按现有执行阶段推进。"
    if stage == "POSITION_MANAGEMENT":
        action = _text(position_management.get("action"))
        return {
            "HOLD": "继续持有。",
            "NO_ADD": "继续持有，暂不加仓。",
            "PROFIT_PROTECTION": "保护利润，按现有持仓管理规则推进。",
            "EXIT": "按现有持仓管理结果执行退出。",
        }.get(action, _reason_text(result) or "按现有持仓管理结果处理。")
    if stage == "FAILED":
        return "当前交易结构已失效。"
    if stage == "DATA_BLOCKED":
        return "数据异常，本日不生成交易信号。"
    if _text(result.get("primary_action")) == "WAIT_CONFIRMATION":
        return "继续观察，等待确认。"
    if _has_persistent_confirmation(result):
        return "今天没有新的交易信号。"
    return _reason_text(result) or "今天不交易。"


def _plain_why(
    stage: str,
    result: Mapping[str, Any],
    *,
    primary_wave_label: str,
    candidate_only: bool,
) -> str:
    if stage == "WATCH":
        return f"当前关注“{primary_wave_label}”结构，但确认条件还没有出现。"
    if stage == "ARMED":
        return f"当前接近“{primary_wave_label}”确认，仍需满足确认条件。"
    if stage == "CONFIRMED":
        return f"今天出现新的“{primary_wave_label}”确认信号。"
    if stage == "STRATEGY_PROPOSAL":
        if candidate_only:
            return "候选标的已经形成技术方案，但还没有进入正式策略池。"
        return "现有结构、入场区间和目标风险收益已经形成交易方案。"
    if stage == "ENTRY_ALLOWED":
        return "现有交易方案满足入场条件，仍需按 T+1 执行规则检查。"
    if stage == "POSITION_MANAGEMENT":
        return "该标的已经进入持仓管理，当前只评估持仓动作。"
    if stage == "FAILED":
        return "最终整体状态明确显示交易结构已经失效。"
    if stage == "DATA_BLOCKED":
        return "行情或生产前置数据没有达到可用要求。"
    if _has_persistent_confirmation(result):
        return "此前已经确认，但今天没有新的确认事件。"
    return _reason_text(result) or "当前没有满足入场条件的交易方案。"


def _targets(decision: Mapping[str, Any]) -> tuple[Any, ...]:
    values = _sequence(decision.get("targets"))
    if not values:
        values = tuple(decision.get(key) for key in ("T1", "T2", "T3"))
    return tuple(values[:3])


def _rr_display(decision: Mapping[str, Any]) -> str:
    rr = _mapping(decision.get("rr"))
    ratios = _sequence(rr.get("rr_ratios"))
    if ratios:
        return " / ".join(_format_rr(value) for value in ratios)
    return _format_rr(rr.get("rr"))


def _price_plan(decision: Mapping[str, Any]) -> dict[str, Any]:
    target_values = _targets(decision)
    return {
        "planned_entry": _format_price(decision.get("planned_entry"), "尚未形成"),
        "execution_stop": _format_price(decision.get("execution_stop")),
        "target_1": _format_price(target_values[0] if len(target_values) > 0 else None),
        "target_2": _format_price(target_values[1] if len(target_values) > 1 else None),
        "target_3": _format_price(target_values[2] if len(target_values) > 2 else None),
        "rr": _rr_display(decision),
        "rr_quality": _display(_mapping(decision.get("rr")).get("quality")),
        "confirmation_level": _format_price(decision.get("confirmation_level")),
        "entry_zone_low": _format_price(decision.get("entry_zone_low")),
        "entry_zone_high": _format_price(decision.get("entry_zone_high")),
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
        "actual_entry": _format_price(
            _first_value(
                position_management.get("actual_entry"),
                position.get("actual_entry"),
                stored.get("actual_entry"),
            )
        ),
        "current_price": _format_price(
            _first_value(
                position_management.get("current_price"),
                position.get("current_price"),
                stored.get("current_price"),
            )
        ),
        "active_protective_stop": _format_price(
            _first_value(
                position_management.get("active_protective_stop"),
                position_management.get("active_stop_at_open"),
                position.get("active_protective_stop"),
                stored.get("active_protective_stop"),
            )
        ),
        "next_session_protective_stop": _format_price(
            _first_value(
                position_management.get("next_session_protective_stop"),
                position_management.get("active_stop_next_session"),
                position.get("next_session_protective_stop"),
                position.get("active_stop_next_session"),
                stored.get("next_session_protective_stop"),
            )
        ),
        "targets": tuple(_format_price(value) for value in target_values[:3]),
        "current_r": _format_r(
            _first_value(position_management.get("current_r"), position.get("current_r"), stored.get("current_r"))
        ),
        "mfe_r": _format_r(
            _first_value(position_management.get("mfe_r"), position.get("mfe_r"), stored.get("mfe_r"))
        ),
        "mae_r": _format_r(
            _first_value(position_management.get("mae_r"), position.get("mae_r"), stored.get("mae_r"))
        ),
        "mfe_drawdown_r": _format_r(
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
        "management_reason": _reason_text(result),
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
    primary_wave = _text(result.get("primary_wave_scenario"), "UNKNOWN")
    confirmation = _confirmation_value(result, decision)
    primary_wave_label = WAVE_LABELS.get(
        primary_wave,
        f"波浪状态：{primary_wave}",
    )
    current_wave_label = _human_wave_stage_label(
        result,
        primary_wave=primary_wave,
        stage=stage,
        event_is_new=event_is_new,
        data_blocked=data_blocked,
    )
    next_step = _waiting(
        stage,
        result,
        decision,
        candidate_only=candidate_only,
        position_management=position_management,
    )
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
        # The default view follows the projected overall stage.  Raw final
        # status remains available below in the technical/audit section.
        "status_label": STAGE_LABELS.get(stage, stage),
        "action_key": action or "—",
        "action_label": ACTION_LABELS.get(action, STATUS_LABELS.get(action, action or "—")),
        "primary_wave": primary_wave,
        "primary_wave_label": primary_wave_label,
        "current_wave_label": current_wave_label,
        "primary_wave_short_label": WAVE_SHORT_LABELS.get(primary_wave, "波浪尚未确定"),
        "alternate_wave": _text(result.get("alternate_wave_scenario"), "UNKNOWN"),
        "alternate_wave_label": WAVE_LABELS.get(
            _text(result.get("alternate_wave_scenario")),
            f"波浪状态：{_text(result.get('alternate_wave_scenario'), 'UNKNOWN')}",
        ),
        "setup": setup or "—",
        "setup_label": _setup_label(setup) or "—",
        "setup01_state": _text(result.get("setup01_state"), "NONE"),
        "setup02_state": _text(result.get("setup02_state"), "NONE"),
        "identity_labels": _identity_labels(labels, candidate_only, is_position),
        "provenance_labels": tuple(labels),
        "candidate_only": candidate_only,
        "is_position": is_position,
        "data_blocked": data_blocked,
        "event_is_new": event_is_new,
        "default_focus": stage in DEFAULT_FOCUS_STAGES or event_is_new,
        "confirmation_level": _format_price(confirmation),
        "today_conclusion": STAGE_LABELS.get(stage, stage),
        "why": _plain_why(
            stage,
            result,
            primary_wave_label=primary_wave_label,
            candidate_only=candidate_only,
        ),
        "waiting": next_step,
        "next_step": next_step,
        "missing_condition": _missing_condition(
            stage,
            result,
            decision,
            candidate_only=candidate_only,
            position_management=position_management,
        ),
        "invalidation": _invalidation_text(result, decision),
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
        if "PAPER_TRACKED" in labels:
            result.append("模拟跟踪")
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
    cloud_daily = _mapping(payload.get("cloud_daily_report"))
    if _normalised_market(cloud_daily.get("market")) == market:
        cloud_status = _text(cloud_daily.get("status"))
        if cloud_status == "SKIPPED_NON_SESSION":
            return {"status_key": "SKIPPED_NON_SESSION", "status_label": "非交易日，已跳过"}
        if cloud_status in {"FAILED", "INCOMPLETE_SESSION", "PARTIAL_DATA_QUALITY"}:
            return {"status_key": "DATA_BLOCKED", "status_label": "数据异常"}
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


def _paper_projection(payload: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Expose the already-computed paper ledger view without recalculating it."""

    root = _mapping(payload.get("paper_tracking"))
    result = _mapping(root.get("result"))
    enabled = _bool(root.get("enabled")) or bool(result)
    if not result:
        # This fallback keeps older/multi-account callers renderable when only
        # a per-account paper payload was attached to each report entry.
        all_trades: dict[str, Mapping[str, Any]] = {}
        coverages: dict[str, Mapping[str, Any]] = {}
        first_performance: Mapping[str, Any] = {}
        first_grouped: Mapping[str, Any] = {}
        errors: list[Any] = []
        for entry in entries:
            value = _mapping(entry.get("entry")).get("模拟交易")
            paper = _mapping(value)
            for trade in _sequence(paper.get("trades")):
                trade = _mapping(trade)
                identity = _text(trade.get("event_identity"))
                if identity:
                    all_trades[identity] = trade
            for coverage in _sequence(paper.get("coverage")):
                coverage = _mapping(coverage)
                market = _normalised_market(coverage.get("market"))
                if market:
                    coverages[market] = coverage
            if not first_performance:
                first_performance = _mapping(paper.get("performance"))
                first_grouped = _mapping(paper.get("grouped_performance"))
            errors.extend(_sequence(paper.get("errors")))
            enabled = enabled or bool(paper)
        result = {
            "trades": list(all_trades.values()),
            "coverage": list(coverages.values()),
            "performance": first_performance,
            "grouped_performance": first_grouped,
            "errors": list(dict.fromkeys(str(item) for item in errors)),
        }
    trades = tuple(_mapping(item) for item in _sequence(result.get("trades")))
    status_counts: dict[str, int] = {}
    for trade in trades:
        status = _text(trade.get("status"), "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    coverages = tuple(_mapping(item) for item in _sequence(result.get("coverage")))
    gaps = tuple(
        coverage for coverage in coverages
        if _text(coverage.get("coverage_status")) not in {"", "CONTINUOUS"}
        or _text(coverage.get("coverage_gap"))
    )
    return {
        **result,
        "enabled": enabled,
        "trades": list(trades),
        "coverage": list(coverages),
        "status_counts": status_counts,
        "coverage_warning": bool(gaps),
        "coverage_warning_text": (
            "样本覆盖存在缺口，当前胜率不是完整连续样本"
            if gaps
            else "当前市场处理覆盖连续"
        ),
        "performance": _mapping(result.get("performance")),
        "grouped_performance": _mapping(result.get("grouped_performance")),
        "errors": list(_sequence(result.get("errors"))),
    }


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
    presentation_order = DEFAULT_FOCUS_STAGES + tuple(
        stage for stage in STAGE_ORDER if stage not in DEFAULT_FOCUS_STAGES
    )
    stage_rank = {stage: index for index, stage in enumerate(presentation_order)}
    rows.sort(key=lambda row: (stage_rank.get(row["stage_key"], len(STAGE_ORDER)), row["market"], row["symbol"], row["account_id"]))

    preflight = _mapping(payload.get("preflight"))
    cloud_daily = _mapping(payload.get("cloud_daily_report"))
    as_of_date = _first_value(payload.get("as_of_date"), preflight.get("T"))
    if as_of_date is None:
        as_of_date = next((row["raw_result"].get("as_of_date") for row in rows if row["raw_result"].get("as_of_date")), None)
    generated_at = _first_value(payload.get("generated_at"), next((row["raw_result"].get("generated_at") for row in rows if row["raw_result"].get("generated_at")), None))
    known_markets = {row["market"] for row in rows if row["market"] and row["market"] != "—"}
    known_markets.update(_normalised_market(item) for item in _mapping(payload.get("candidate_markets")))
    cloud_market = _normalised_market(cloud_daily.get("market"))
    if cloud_market:
        known_markets.add(cloud_market)
    known_markets.update(
        _normalised_market(_mapping(account).get("市场") or _mapping(account).get("market"))
        for account in _sequence(preflight.get("accounts"))
    )
    if cloud_market:
        # A Cloud Daily Report is intentionally one-exchange scoped.  Keep
        # the legacy two-market overview only for the old all-market/manual
        # dashboard payloads.
        markets = [cloud_market]
    else:
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
    paper = _paper_projection(payload, entries)
    rules = [
        {"question": question, "answer": answer}
        for question, answer in strategy_rules_for_dashboard()
    ]
    return {
        "title": "收盘交易决策日报" if cloud_daily else "每日交易决策工作台",
        "demo_label": _text(payload.get("demo_label")),
        "as_of_date": _display(as_of_date),
        "generated_at": _display(generated_at),
        "summary": summary,
        "markets": market_rows,
        "rows": rows,
        "sectors": sectors,
        "stage_order": STAGE_ORDER,
        "paper": paper,
        "strategy_rules": rules,
        "workspace_order": ("today", "paper", "performance", "rules", "diagnostics"),
        "cloud_daily_report": dict(cloud_daily),
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


def _metric_link(label: str, value: Any, view: str, tone: str = "") -> str:
    return (
        f'<button type="button" class="metric metric-link {tone}" '
        f'data-view="{_escape(view)}"><span class="metric-label">{_escape(label)}</span>'
        f'<span class="metric-value">{_escape(value)}</span></button>'
    )


def _field(label: str, value: Any, *, extra_class: str = "") -> str:
    return (
        f'<div class="field {extra_class}"><div class="field-label">{_escape(label)}</div>'
        f'<div class="field-value">{_escape(value)}</div></div>'
    )


def _has_display_value(value: Any) -> bool:
    return _raw_text(value) not in {"", "—", "-", "尚未形成"}


def _render_field_grid(
    fields: Sequence[tuple[str, Any]], *, extra_class: str = ""
) -> str:
    visible_fields = tuple((label, value) for label, value in fields if _has_display_value(value))
    if not visible_fields:
        return ""
    return '<div class="field-grid {0}">{1}</div>'.format(
        extra_class,
        "".join(_field(label, value) for label, value in visible_fields),
    )


def _render_plan(row: Mapping[str, Any]) -> str:
    plan = _mapping(row.get("plan"))
    if row.get("stage_key") not in {"STRATEGY_PROPOSAL", "ENTRY_ALLOWED"}:
        return ""
    if not plan.get("has_decision"):
        return ""
    fields = (
        ("确认价", plan.get("confirmation_level")),
        ("入场区间", _entry_zone_text(plan)),
        ("执行止损", plan.get("execution_stop")),
        ("目标价 T1", plan.get("target_1")),
        ("目标价 T2", plan.get("target_2")),
        ("目标价 T3", plan.get("target_3")),
        ("第一目标 R/R", _first_rr_text(plan.get("rr"))),
    )
    field_grid = _render_field_grid(fields, extra_class="plan-grid")
    if not field_grid:
        return ""
    return (
        '<section class="panel plan-panel"><h3>关键价格</h3>'
        + field_grid
        + "</section>"
    )


def _entry_zone_text(plan: Mapping[str, Any]) -> str:
    low = plan.get("entry_zone_low")
    high = plan.get("entry_zone_high")
    if not _has_display_value(low) and not _has_display_value(high):
        return ""
    if _has_display_value(low) and _has_display_value(high):
        return f"{low} – {high}"
    return _display(low if _has_display_value(low) else high)


def _first_rr_text(value: Any) -> str:
    text = _raw_text(value)
    if not text:
        return ""
    return _format_rr(text.split("/", 1)[0].strip())


def _render_position(row: Mapping[str, Any]) -> str:
    position = _mapping(row.get("position"))
    field_grid = _render_field_grid(
        tuple(
            (label, position.get(key))
            for label, key in (
                ("实际入场", "actual_entry"),
                ("当前价格", "current_price"),
                ("当前保护止损", "active_protective_stop"),
                ("下一交易日保护止损", "next_session_protective_stop"),
                ("目标价 T1", "target_1"),
                ("目标价 T2", "target_2"),
                ("目标价 T3", "target_3"),
                ("当前 R", "current_r"),
                ("最高浮盈 MFE", "mfe_r"),
                ("最大不利 MAE", "mae_r"),
                ("MFE 回撤", "mfe_drawdown_r"),
                ("持有／退出原因", "management_reason"),
                ("现在要做什么", "action_label"),
            )
        )
    )
    if not field_grid:
        return ""
    return (
        '<section class="panel position-panel"><h3>持仓管理</h3>'
        + field_grid
        + "</section>"
    )


def _position_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    position = _mapping(row.get("position"))
    targets = _sequence(position.get("targets"))
    return {
        **position,
        "target_1": _format_price(targets[0] if len(targets) > 0 else None),
        "target_2": _format_price(targets[1] if len(targets) > 1 else None),
        "target_3": _format_price(targets[2] if len(targets) > 2 else None),
    }


def _compact_price(row: Mapping[str, Any]) -> str:
    stage = _text(row.get("stage_key"))
    plan = _mapping(row.get("plan"))
    if stage in {"STRATEGY_PROPOSAL", "ENTRY_ALLOWED"} and plan.get("has_decision"):
        values = []
        if _has_display_value(plan.get("planned_entry")):
            values.append(f"入场：{_display(plan.get('planned_entry'))}")
        if _has_display_value(plan.get("execution_stop")):
            values.append(f"止损：{_display(plan.get('execution_stop'))}")
        return " · ".join(values)
    if stage == "POSITION_MANAGEMENT":
        position = _mapping(row.get("position"))
        values = []
        if _has_display_value(position.get("current_price")):
            values.append(f"当前价格：{_display(position.get('current_price'))}")
        if _has_display_value(position.get("active_protective_stop")):
            values.append(f"保护止损：{_display(position.get('active_protective_stop'))}")
        return " · ".join(values)
    return ""


def _compact_position(row: Mapping[str, Any]) -> str:
    position = _mapping(row.get("position"))
    values = []
    for label, key in (("当前", "current_r"), ("MFE", "mfe_r"), ("MAE", "mae_r")):
        if _has_display_value(position.get(key)):
            values.append(f"{label} {_display(position.get(key))}")
    return "持仓管理：" + " · ".join(values) if values else "持仓管理中"


def _dashboard_search_text(row: Mapping[str, Any]) -> str:
    return f'{_raw_text(row.get("symbol"))} {_raw_text(row.get("name"))}'


def dashboard_search_matches(row: Mapping[str, Any], query: Any) -> bool:
    """Return whether a UI search query matches a ticker or company name."""

    needle = _raw_text(query).casefold()
    if not needle:
        return True
    haystack = _dashboard_search_text(row).casefold()
    return needle in haystack


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
    confirmation = _first_value(
        decision.get("confirmation_level"),
        decision.get("confirmation_threshold"),
        result.get("confirmation_level"),
        result.get("confirmation_threshold"),
    )
    reason_values = [
        *(_sequence(result.get("reasons"))),
        *(_sequence(_mapping(result.get("position_management")).get("reasons"))),
    ]
    reasons_text = "；".join(
        translated
        for value in reason_values
        if (translated := _translate_reason(value))
    )
    blocking_text = "；".join(
        translated
        for value in _sequence(result.get("blocking_prerequisites"))
        if (translated := _translate_reason(value))
    )
    return (
        '<details class="details"><summary>查看交易依据（查看详情）</summary><div class="detail-body">'
        '<section class="plain-summary">'
        f'<section><h3>当前波浪</h3><p>{_escape(row.get("current_wave_label"))}</p><p>{_escape(row.get("today_conclusion"))}</p></section>'
        f'<section><h3>为什么</h3><p>{_escape(row.get("why"))}</p></section>'
        f'<section><h3>还差什么 / 现在要做什么</h3><p>{_escape(row.get("missing_condition"))}</p></section>'
        f'<section><h3>失效条件</h3><p>{_escape(row.get("invalidation"))}</p></section>'
        f'<section><h3>备选情景</h3><p>{_escape(row.get("alternate_wave_label"))}</p></section>'
        '</section>'
        + _render_plan(row)
        + (_render_position({**row, "position": position}) if row.get("is_position") else "")
        + '<details class="technical-details"><summary>开发者原始数据（查看技术详情 / 审计信息）</summary><div class="detail-body">'
        + '<div class="detail-grid">'
        '<section><h4>Wave / 结构</h4>'
        f'<p>Primary：{_escape(row.get("primary_wave"))}</p>'
        f'<p>Alternate：{_escape(row.get("alternate_wave"))}</p>'
        f'<p>Wave evidence：{_escape(wave_evidence)}</p>'
        f'<p>Invalidation：{_escape(wave_invalidation)}</p>'
        f'<p>周线／日线：{_escape(result.get("weekly_state"))} / {_escape(result.get("daily_state"))}</p>'
        f'<p>Fibonacci 候选区域：{_escape(fibonacci_text)}</p></section>'
        '<section><h4>Setup / Decision</h4>'
        f'<p>SETUP_01：{_escape(row.get("setup01_state"))}；SETUP_02：{_escape(row.get("setup02_state"))}</p>'
        f'<p>Setup：{_escape(row.get("setup"))}</p>'
        f'<p>Gate / confirmation：{_escape(_mapping(row.get("decision")).get("gate_reason"))} / {_escape(confirmation)}</p>'
        f'<p>Entry zone：{_escape(_mapping(row.get("plan")).get("entry_zone_low"))} — {_escape(_mapping(row.get("plan")).get("entry_zone_high"))}</p></section>'
        '<section><h4>Risk / Portfolio Risk</h4>'
        f'<p>R/R quality：{_escape(_mapping(row.get("plan")).get("rr_quality"))}</p>'
        f'<p>Portfolio Risk：{_escape(_mapping(row.get("portfolio_result")).get("status"))} / {_escape(_mapping(row.get("portfolio_result")).get("reason"))}</p>'
        f'<p>Risk group：{_escape(_mapping(row.get("portfolio_result")).get("risk_group"))}</p></section>'
        '<section><h4>Position Management</h4>'
        f'<p>状态：{_escape(_mapping(row.get("position_management")).get("status"))}</p>'
        f'<p>Wave5：{_escape(position.get("wave5_context"))}；Target status：{_escape(position.get("target_status"))}</p>'
        f'<p>Waiting / blocking：{_escape(row.get("waiting"))}</p>'
        f'<p>Reasons：{_escape(reasons_text)}</p>'
        f'<p>Blockers：{_escape(blocking_text)}</p></section>'
        '</div>'
        f'<p>最终状态原值：{_escape(row.get("status_key"))}；动作原值：{_escape(row.get("action_key"))}</p>'
        f'<h4>原始 Daily Decision 字段</h4><pre>{html.escape(_json_text(result), quote=False)}</pre>'
        '</div></details>'
        '</div></details>'
    )


def _render_row(row: Mapping[str, Any]) -> str:
    identity = "".join(
        f'<span class="badge {"warning" if row["candidate_only"] else ""}">{_escape(value)}</span>'
        for value in row["identity_labels"]
    )
    if row["event_is_new"]:
        identity += '<span class="badge positive">今天出现确认</span>'
    stage_class = row["stage_key"].lower().replace("_", "-")
    compact_price = _compact_price(row)
    if row.get("stage_key") == "POSITION_MANAGEMENT":
        compact_plan = _compact_position(row)
    elif compact_price:
        compact_plan = compact_price
    else:
        compact_plan = "尚未形成交易计划"
    search_text = _dashboard_search_text(row)
    price_block = (
        f'<span class="row-price">{_escape(compact_plan)}</span>'
    )
    return (
        f'<article class="stock-row"{"" if row["default_focus"] else " hidden"} '
        f'data-market="{_escape(row["market"])}" '
        f'data-stage="{_escape(row["stage_key"])}" data-setup="{_escape(row["setup"])}" '
        f'data-sector="{_escape(row["sector"] if row["sector"] != "—" else "")}" '
        f'data-focus="{"1" if row["default_focus"] else "0"}" '
        f'data-confirmed="{"1" if row["event_is_new"] else "0"}" '
        f'data-search="{_escape(search_text)}">'
        '<div class="row-top"><div class="row-identity">'
        f'<span class="ticker">{_escape(row["symbol"])}</span>'
        f'<span class="company">{_escape(row["name"])}</span>'
        f'<span class="sector">{_escape(row["sector"])}</span>'
        f'<span class="market-chip">{_escape(row["market"])}</span>'
        '</div>'
        f'<span class="stage stage-{stage_class}">{_escape(row["stage_label"])}</span></div>'
        '<div class="row-bottom"><div class="row-signals">'
        f'<span class="row-why">{_escape(row["why"])}</span>'
        f'<span class="row-wave">{_escape(row["current_wave_label"])}</span>'
        f'<span class="row-next">{_escape(row["missing_condition"])}</span>'
        + price_block
        + '</div><div class="row-actions"><div class="identity-row">'
        + identity
        + '</div></div>'
        + _render_details(row)
        + '</div>'
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


_PAPER_STATUS_LABELS = {
    "PENDING_T1": "等待 T+1 执行",
    "OPEN": "模拟持仓中",
    "SKIPPED": "已跳过入场",
    "CLOSED": "已结束",
}

_PAPER_RESULT_LABELS = {
    "WIN": "盈利",
    "LOSS": "亏损",
    "FLAT": "持平",
}


def _paper_source_label(value: Any) -> str:
    return {
        "FORMAL_STRATEGY_POOL": "正式策略池",
        "DYNAMIC_CANDIDATE": "动态候选（仅模拟）",
        "PAPER_TRACKED": "已有模拟计划",
    }.get(_text(value), _display(value))


def _paper_human_text(value: Any, default: str = "—") -> str:
    """Shorten persisted numeric prose without changing the audit payload."""

    text = _text(value)
    if not text:
        return default
    return re.sub(
        r"(?<![A-Za-z])[-+]?\d+\.\d{5,}",
        lambda match: _format_number(match.group(), 4),
        text,
    )


def _paper_percent(value: Any, *, signed: bool = False, default: str = "—") -> str:
    number = _numeric(value)
    if number is None:
        return default
    return f"{_format_number(number * 100, 2, signed=signed, trim=False)}%"


def _paper_actual_rr(value: Any, default: str = "—") -> str:
    mapping = _mapping(value)
    ratios = _sequence(mapping.get("rr_ratios"))
    return _format_rr(ratios[0], default) if ratios else default


def _paper_targets(trade: Mapping[str, Any]) -> str:
    values = tuple(_sequence(trade.get("targets")))[:3]
    labels = [f"T{index} {_format_price(value)}" for index, value in enumerate(values, start=1)]
    return " / ".join(labels) or "尚未提供"


def _paper_target_status_label(value: Any) -> str:
    return {
        "T1_REACHED": "已触及 T1，但当前规则不是到价自动止盈。",
        "T2_REACHED": "已触及 T2，但当前规则不是到价自动止盈。",
        "T3_REACHED": "已触及 T3，但当前规则不是到价自动止盈。",
        "NOT_REACHED": "尚未触及目标价。",
    }.get(_text(value), "尚未记录目标状态。")


def _paper_action_text(trade: Mapping[str, Any]) -> str:
    action = _text(trade.get("action"))
    label = ACTION_LABELS.get(action, action or "继续观察")
    reason = _paper_human_text(
        trade.get("why_protect") if action == "PROFIT_PROTECTION" else trade.get("why_hold")
    )
    if reason and reason != "—":
        return f"{label}。{reason}"
    return label


def _render_paper_trade(trade: Mapping[str, Any]) -> str:
    status = _text(trade.get("status"), "UNKNOWN")
    status_label = _PAPER_STATUS_LABELS.get(status, status)
    source_setup = _text(trade.get("source_setup"))
    source_setup_label = _setup_label(source_setup)
    source = _paper_source_label(trade.get("source_provenance"))
    execution_outcome = _text(trade.get("execution_outcome"))
    target_status = _text(trade.get("target_status"))
    action = _text(trade.get("action"))
    exit_reason = _text(trade.get("exit_reason"))
    result = _text(trade.get("result"))
    symbol = _escape(trade.get("symbol"))
    name = _escape(trade.get("name"))
    logic = _mapping(trade.get("logic_explanation"))
    why_entry = _paper_human_text(trade.get("why_entry") or logic.get("why_plan"))
    actual_rr = _paper_actual_rr(trade.get("actual_rr"))
    targets = _paper_targets(trade)
    entry_zone = f"{_format_price(trade.get('entry_zone_low'))} — {_format_price(trade.get('entry_zone_high'))}"
    if status == "PENDING_T1":
        fill_text = f"计划已形成，等待 {_display(trade.get('expected_execution_date'), '下一交易日')} 开盘检查；现在还没有模拟成交。"
        state_fields = (
            ("计划入场", _format_price(trade.get("planned_entry"))),
            ("允许入场区间", entry_zone),
            ("执行止损", _format_price(trade.get("execution_stop"))),
            ("第一目标计划 R/R", _format_rr(trade.get("initial_rr"))),
            ("目标价", targets),
            ("目标规则", "目标价只记录状态，不自动止盈。"),
        )
        next_text = "等待下一交易日开盘，暂不把计划当成已成交。"
    elif status == "OPEN":
        fill_text = (
            f"{_display(trade.get('execution_date'))} 开盘 {_format_price(trade.get('actual_entry'))}，"
            f"已通过 T+1 执行检查；实际第一目标 R/R 为 {actual_rr}，模拟成交已成立。"
        )
        state_fields = (
            ("实际买入价", _format_price(trade.get("actual_entry"))),
            ("当前价格", _format_price(trade.get("current_price"))),
            ("当前收益", _paper_percent(trade.get("current_return_pct"), signed=True)),
            ("当前 R", _format_r(trade.get("current_r"))),
            ("MFE / MAE", f"{_format_r(trade.get('current_mfe'))} / {_format_r(trade.get('current_mae'))}"),
            ("当前保护止损", _format_price(trade.get("current_stop"))),
            ("目标价", targets),
            ("目标状态", _paper_target_status_label(target_status)),
            ("目标规则", "目标价只记录状态，不自动止盈。"),
        )
        next_text = _paper_action_text(trade)
    elif status == "SKIPPED":
        fill_text = f"T+1 开盘 {_format_price(trade.get('t1_open'))}，没有模拟成交；{_paper_human_text(trade.get('why_execution') or trade.get('skip_reason'))}"
        state_fields = (
            ("计划入场", _format_price(trade.get("planned_entry"))),
            ("T+1 开盘", _format_price(trade.get("t1_open"))),
            ("跳过原因", _paper_human_text(trade.get("skip_reason") or trade.get("why_execution"))),
        )
        next_text = "继续观察后续新的确认事件；这笔计划不会补记为成交。"
    elif status == "CLOSED":
        result_label = _PAPER_RESULT_LABELS.get(result, result or "已结束")
        fill_text = (
            f"{_display(trade.get('execution_date'))} 开盘 {_format_price(trade.get('actual_entry'))} 模拟买入，"
            f"{_display(trade.get('exit_date'))} 以 {_format_price(trade.get('exit_price'))} 模拟卖出。"
        )
        state_fields = (
            ("交易结果", result_label),
            ("实现 R", _format_r(trade.get("realized_r"))),
            ("本次收益", _paper_percent(trade.get("return_pct"), signed=True)),
            ("持有天数", trade.get("holding_days")),
            ("目标状态", _paper_target_status_label(target_status)),
            ("目标规则", "目标价只记录状态，不自动止盈。"),
        )
        next_text = _paper_human_text(trade.get("why_exit"), "已按现有持仓管理规则结束。")
    else:
        fill_text = "当前状态尚未形成完整的模拟成交记录。"
        state_fields = (("状态", status_label),)
        next_text = "等待完整的 T+1 或持仓管理记录。"
    default_html = (
        '<section class="paper-human-grid">'
        f'<section><h4>为什么买／为什么关注</h4><p>{_escape(why_entry)}</p></section>'
        f'<section><h4>有没有真正模拟成交</h4><p>{_escape(fill_text)}</p></section>'
        f'<section><h4>现在怎么样</h4>{_render_field_grid(state_fields)}</section>'
        f'<section><h4>{"为什么卖" if status == "CLOSED" else "现在要做什么"}</h4><p>{_escape(next_text)}</p></section>'
        '</section>'
    )
    origin = trade.get("position_origin_json")
    technical = {
        "event_identity": _text(trade.get("event_identity")),
        "signal_date": _text(trade.get("signal_date")),
        "expected_execution_date": _text(trade.get("expected_execution_date")),
        "source_setup": source_setup,
        "source_provenance": _text(trade.get("source_provenance")),
        "planned_entry": trade.get("planned_entry"),
        "entry_zone": [trade.get("entry_zone_low"), trade.get("entry_zone_high")],
        "structural_invalidation": trade.get("structural_invalidation"),
        "execution_stop": trade.get("execution_stop"),
        "planned_risk_per_share": trade.get("planned_risk_per_share"),
        "initial_risk_per_share_actual": trade.get("initial_risk_per_share"),
        "initial_rr": trade.get("initial_rr"),
        "execution_outcome": execution_outcome,
        "actual_rr": trade.get("actual_rr"),
        "target_status": target_status,
        "action": action,
        "exit_reason": exit_reason,
        "result": result,
        "paper_approval_policy": trade.get("paper_approval_policy"),
        "paper_tracking_approval_policy": trade.get("paper_tracking_approval_policy"),
        "promotion_required": trade.get("promotion_required"),
        "state_persistence_eligible": trade.get("state_persistence_eligible"),
        "production_execution_eligible": trade.get("production_execution_eligible"),
        "logic_explanation": logic,
    }
    technical_html = (
        '<details class="paper-technical-details"><summary>查看技术详情 / 审计信息</summary>'
        '<section class="paper-technical-fields">'
        + _render_field_grid(
            (
                ("事件 identity", trade.get("event_identity")),
                ("计划风险 / 计划 1R", trade.get("planned_risk_per_share")),
                ("实际成交 1R", trade.get("initial_risk_per_share")),
                ("PositionOrigin", "已冻结" if origin else None),
                ("来源标记", trade.get("source_provenance")),
                ("决策与状态原值", status),
            )
        )
        + '</section><pre>'
        + html.escape(_json_text(technical), quote=False)
        + '</pre>'
        + (f'<pre>{html.escape(_display(origin), quote=False)}</pre>' if origin else "")
        + '</details>'
    )
    return (
        f'<article class="paper-trade paper-status-{_escape(status)}" '
        f'data-paper-status="{_escape(status)}">'
        '<div class="paper-trade-top">'
        f'<div><span class="ticker">{symbol}</span> <span class="company">{name}</span>'
        f'<div class="paper-trade-meta"><span>{_escape(trade.get("market"))}</span>'
        f'<span>{_escape(source_setup_label)}</span><span>{_escape(source)}</span></div></div>'
        f'<span class="paper-status">{_escape(status_label)}</span></div>'
        + default_html
        + technical_html
        + '</article>'
    )


def _render_paper_workspace(paper: Mapping[str, Any]) -> str:
    if not _bool(paper.get("enabled")):
        return (
            '<section id="paper-workspace" class="workspace-panel" hidden>'
            '<div class="workspace-heading"><h2>模拟交易</h2>'
            '<p>未启用前瞻模拟账本。只有显式运行 <code>--run --paper-track</code> 才会写入策略模拟账本。</p></div>'
            '</section>'
        )
    performance = _mapping(paper.get("performance"))
    status_counts = _mapping(paper.get("status_counts"))
    metrics = (
        ("计划数", performance.get("plans", status_counts.get("PENDING_T1", 0))),
        ("已执行", performance.get("executed", 0)),
        ("等待 T+1", status_counts.get("PENDING_T1", 0)),
        ("模拟持仓", performance.get("open", 0)),
        ("已结束", performance.get("closed", 0)),
        ("已跳过", performance.get("skipped", 0)),
    )
    metric_html = "".join(_metric(label, value) for label, value in metrics)
    trades = tuple(_mapping(item) for item in _sequence(paper.get("trades")))
    cards = "".join(_render_paper_trade(trade) for trade in trades)
    if not cards:
        cards = '<div class="empty">当前没有符合条件的模拟交易计划。</div>'
    coverage = "".join(
        '<div class="coverage-card">'
        f'<strong>{_escape(item.get("market"))}</strong>'
        f'<span>{_escape(item.get("tracking_start_date"))} → {_escape(item.get("latest_processed_session"))}</span>'
        f'<span class="coverage-{_escape(_text(item.get("coverage_status"), "GAP_DETECTED"))}">{_escape("样本连续" if _text(item.get("coverage_status")) == "CONTINUOUS" else "样本存在缺口")}</span>'
        f'<span>{_escape("记录连续，可正常参考。" if _text(item.get("coverage_status")) == "CONTINUOUS" and not _text(item.get("coverage_gap")) else "该市场的模拟记录不是完整连续样本，当前胜率仅供参考。")}</span></div>'
        for item in (_mapping(value) for value in _sequence(paper.get("coverage")))
    )
    warning = (
        f'<div class="paper-warning">{_escape(paper.get("coverage_warning_text"))}</div>'
        if _bool(paper.get("coverage_warning")) else ""
    )
    errors = _sequence(paper.get("errors"))
    error_html = (
        '<div class="paper-warning">' + _escape("；".join(_text(item) for item in errors)) + '</div>'
        if errors else ""
    )
    return (
        '<section id="paper-workspace" class="workspace-panel" hidden>'
        '<div class="workspace-heading"><h2>模拟交易</h2>'
        '<p>前瞻、逐事件、只读生产决策输入；不使用组合 P&amp;L，不产生生产批准或券商订单。</p></div>'
        f'<section class="paper-summary">{metric_html}</section>'
        f'{warning}{error_html}'
        '<h3 class="workspace-subheading">当前与历史模拟计划</h3>'
        f'<section class="paper-trades">{cards}</section>'
        '<h3 class="workspace-subheading">市场覆盖</h3>'
        f'<section class="coverage-grid">{coverage or "<div class=empty>尚无覆盖记录。</div>"}</section>'
        '</section>'
    )


def _render_today_paper_focus(paper: Mapping[str, Any], as_of_date: Any) -> str:
    if not _bool(paper.get("enabled")):
        return ""
    today = _text(as_of_date)
    trades = tuple(
        _mapping(item) for item in _sequence(paper.get("trades"))
        if _text(_mapping(item).get("status")) in {"PENDING_T1", "OPEN"}
        or (
            _text(_mapping(item).get("status")) == "CLOSED"
            and _text(_mapping(item).get("exit_date")) == today
        )
    )
    if not trades:
        return ""
    cards = "".join(
        '<article class="paper-focus-card">'
        f'<div><strong>{_escape(item.get("symbol"))}</strong> '
        f'<span>{_escape(item.get("name"))}</span> '
        f'<span class="paper-focus-meta">{_escape(item.get("market"))} · {_escape(_setup_label(_text(item.get("source_setup"))))} · {_escape(_paper_source_label(item.get("source_provenance")))}</span></div>'
        f'<span class="paper-status">{_escape(_PAPER_STATUS_LABELS.get(_text(item.get("status")), _text(item.get("status"))))}</span>'
        f'<div class="paper-focus-values"><span>计划入场：{_escape(_format_price(item.get("planned_entry")))}</span>'
        f'<span>实际入场：{_escape(_format_price(item.get("actual_entry")))}</span>'
        f'<span>R：{_escape(_format_r(item.get("realized_r") if _text(item.get("status")) == "CLOSED" else item.get("current_r")))}</span>'
        '</div></article>'
        for item in trades
    )
    return (
        '<section class="today-paper-focus"><div class="results-heading">'
        '<h2>今日模拟交易重点</h2><span>等待 T+1、模拟持仓与今日结束记录</span></div>'
        f'<div class="paper-focus-cards">{cards}</div></section>'
    )


def _format_stat(value: Any, *, kind: str = "text") -> str:
    if value is None or value == "":
        return "样本不足"
    if kind == "percent":
        return _paper_percent(value, default="样本不足")
    if kind == "percent_signed":
        return _paper_percent(value, signed=True, default="样本不足")
    if kind == "r":
        return _format_r(value, "样本不足")
    if kind == "days":
        return f"{_format_number(value, 1)} 天"
    return _display(value, "样本不足")


def _render_performance_workspace(paper: Mapping[str, Any]) -> str:
    performance = _mapping(paper.get("performance"))
    grouped = _mapping(paper.get("grouped_performance"))
    fields = (
        ("已形成方案", performance.get("plans", 0)),
        ("实际模拟成交", performance.get("executed", 0)),
        ("跳过", performance.get("skipped", 0)),
        ("当前持仓", performance.get("open", 0)),
        ("已结束", performance.get("closed", 0)),
        ("胜率", _format_stat(performance.get("win_rate"), kind="percent")),
        ("平均 R", _format_stat(performance.get("average_r"), kind="r")),
        ("平均持有天数", _format_stat(performance.get("average_holding_days"), kind="days")),
        ("中位数 R", _format_stat(performance.get("median_r"), kind="r")),
        ("平均收益", _format_stat(performance.get("average_return_pct"), kind="percent_signed")),
        ("平均 MFE / MAE", f"{_format_stat(performance.get('average_mfe'), kind='r')} / {_format_stat(performance.get('average_mae'), kind='r')}"),
    )
    summary = _render_field_grid(fields, extra_class="performance-summary-grid")
    groups: list[str] = []
    for dimension, label in (("setup", "Setup"), ("market", "市场"), ("provenance", "来源")):
        buckets = _mapping(grouped.get(dimension))
        cards = []
        for key, stats_value in buckets.items():
            stats = _mapping(stats_value)
            group_label = _paper_source_label(key) if dimension == "provenance" else key
            cards.append(
                '<article class="performance-group"><h4>'
                f'{_escape(group_label)}</h4>'
                + _render_field_grid(
                    (
                        ("方案", stats.get("plans", 0)),
                        ("执行", stats.get("executed", 0)),
                        ("结束", stats.get("closed", 0)),
                        ("胜率", _format_stat(stats.get("win_rate"), kind="percent")),
                        ("平均 R", _format_stat(stats.get("average_r"), kind="r")),
                        ("中位数 R", _format_stat(stats.get("median_r"), kind="r")),
                        ("平均收益", _format_stat(stats.get("average_return_pct"), kind="percent_signed")),
                    ),
                    extra_class="performance-group-grid",
                )
                + '</article>'
            )
        group = (
            f'<section class="performance-table"><h3>{_escape(label)}</h3>'
            f'<div class="performance-groups">{"".join(cards) or "<p class=empty>尚无已记录样本</p>"}</div></section>'
        )
        groups.append(group)
    warning = (
        f'<div class="paper-warning">{_escape(paper.get("coverage_warning_text"))}</div>'
        if _bool(paper.get("coverage_warning")) else ""
    )
    return (
        '<section id="performance-workspace" class="workspace-panel" hidden>'
        '<div class="workspace-heading"><h2>绩效统计</h2>'
        '<p>只统计已经结束的模拟交易；未成交方案和当前持仓不进入胜率分母。</p></div>'
        f'{summary}{warning}{"".join(groups)}'
        '<p class="paper-stat-note">胜率只统计已结束的盈利／亏损交易；模拟持仓中和未成交方案不进入胜率分母。样本不足时不显示误导性的 0%。</p>'
        '</section>'
    )


def _render_rules_workspace(rules: Sequence[Mapping[str, Any]]) -> str:
    cards = "".join(
        '<article class="rule-card">'
        f'<h3>{_escape(item.get("question"))}</h3><p>{_escape(item.get("answer"))}</p>'
        '</article>'
        for item in rules
    )
    return (
        '<section id="rules-workspace" class="workspace-panel" hidden>'
        '<div class="workspace-heading"><h2>策略规则</h2>'
        '<p>本页只解释当前已实现的 Wave → Setup → Decision → T+1 → Position Management 规则。</p></div>'
        f'<section class="rules-grid">{cards}</section></section>'
    )


def render_dashboard_html(value: Any) -> str:
    """Render a standalone UTF-8 HTML dashboard from an existing result."""

    projection = build_dashboard_projection(value)
    summary = projection["summary"]
    paper = _mapping(projection.get("paper"))
    sector_options = "".join(
        f'<option value="{_escape(sector)}">{_escape(sector)}</option>'
        for sector in projection["sectors"]
    )
    stage_options = "".join(
        f'<option value="{_escape(stage)}">{_escape(STAGE_LABELS.get(stage, stage))}</option>'
        for stage in projection["stage_order"]
    )
    nav_specs = (
        ("focus", "今日重点", sum(row["default_focus"] for row in projection["rows"])),
        ("ARMED", "接近确认", summary["armed_count"]),
        ("WATCH", "观察中", summary["watch_count"]),
        ("confirmed", "新确认", summary["new_confirmed_count"]),
        ("STRATEGY_PROPOSAL", "交易方案", summary["strategy_proposal_count"]),
        ("ENTRY_ALLOWED", "可入场", summary["entry_allowed_count"]),
        ("POSITION_MANAGEMENT", "持仓", summary["position_count"]),
        ("all", "全部/诊断", len(projection["rows"])),
    )
    stage_nav = "".join(
        f'<button type="button" class="stage-link" data-view="{_escape(view)}" '
        f'aria-pressed="false">{_escape(label)} <span class="nav-count">{_escape(count)}</span></button>'
        for view, label, count in nav_specs
    )
    cards = "".join(_render_row(row) for row in projection["rows"])
    demo_label = _text(projection.get("demo_label"))
    demo_banner = (
        f'<div class="demo-banner">{_escape(demo_label)}</div>'
        if demo_label
        else ""
    )
    cloud_status = _text(_mapping(projection.get("cloud_daily_report")).get("status"))
    cloud_banner_labels = {
        "SKIPPED_NON_SESSION": "本日非交易日，已跳过（不使用上一交易日替代）",
        "INCOMPLETE_SESSION": "交易时段尚未完成，本日不生成新的交易信号",
        "PARTIAL_DATA_QUALITY": "数据异常，本日不生成新的交易信号",
        "FAILED": "日报生成异常，本日不生成新的交易信号",
    }
    cloud_banner = (
        f'<div class="cloud-status-banner status-{_escape(cloud_status)}">'
        f'{_escape(cloud_banner_labels[cloud_status])}</div>'
        if cloud_status in cloud_banner_labels
        else ""
    )
    workspace_specs = (
        ("today", "今日重点"),
        ("paper", "模拟交易"),
        ("performance", "绩效统计"),
        ("rules", "策略规则"),
        ("diagnostics", "全部/诊断"),
    )
    workspace_nav = "".join(
        f'<button type="button" class="workspace-link" data-workspace="{_escape(key)}" '
        f'aria-pressed="{"true" if key == "today" else "false"}">{_escape(label)}</button>'
        for key, label in workspace_specs
    )
    paper_note = (
        "本页同时展示显式开启的前瞻模拟账本；账本写入不等于生产批准。"
        if _bool(paper.get("enabled"))
        else "默认运行保持只读；模拟账本只有显式 --paper-track 才会写入。"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(projection['title'])} · {_escape(projection['as_of_date'])}</title>
<style>
:root {{ color-scheme:light; --ink:#162334; --muted:#66758a; --line:#dce4ee; --paper:#f5f7fb; --card:#fff; --teal:#0f766e; --teal-soft:#d9f2ed; --amber:#b45309; --amber-soft:#fff0d5; --red:#b42318; --red-soft:#fee4e2; --blue:#275dad; --blue-soft:#e4efff; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 "Segoe UI","Microsoft YaHei",sans-serif; overflow-x:hidden; }}
.shell {{ width:min(1440px,calc(100% - 32px)); margin:0 auto; padding:18px 0 48px; }}
.hero {{ background:linear-gradient(135deg,#12263d,#21516c); color:#fff; border-radius:18px; padding:22px 28px; box-shadow:0 12px 28px #13263d20; }}
.demo-banner {{ display:inline-block; margin-bottom:7px; border:1px solid #f4d28f; border-radius:999px; padding:3px 9px; background:#fff0d5; color:#7a4300; font-size:12px; font-weight:750; }} .cloud-status-banner {{ margin:7px 0 4px; border-radius:10px; padding:9px 11px; background:#fff0d5; color:#7a4300; font-weight:750; }} .cloud-status-banner.status-SUCCESS {{ background:var(--teal-soft); color:var(--teal); }} .cloud-status-banner.status-SKIPPED_NON_SESSION {{ background:#edf1f6; color:var(--muted); }} .cloud-status-banner.status-INCOMPLETE_SESSION,.cloud-status-banner.status-PARTIAL_DATA_QUALITY,.cloud-status-banner.status-FAILED {{ background:var(--red-soft); color:var(--red); }}
.eyebrow {{ color:#b8e5dc; font-size:11px; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ margin:5px 0 3px; font-size:clamp(26px,3.4vw,38px); letter-spacing:-.03em; }}
.hero-meta {{ color:#d9e8f2; display:flex; gap:16px; flex-wrap:wrap; font-size:13px; }} .readonly-note {{ margin:11px 0 0; color:#e9f4f8; font-size:12px; }}
.summary-primary {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; margin:12px 0 7px; }} .summary-secondary {{ display:flex; gap:8px; margin:0 0 9px; }}
.metric {{ appearance:none; background:var(--card); border:1px solid var(--line); border-radius:11px; padding:10px 12px; min-height:66px; color:var(--ink); text-align:left; }} .metric-link {{ cursor:pointer; font:inherit; }} .metric-link:hover {{ border-color:#8ca9c2; box-shadow:0 3px 10px #18324b12; }}
.metric-label,.field-label {{ color:var(--muted); font-size:12px; }} .metric-value {{ display:block; margin-top:3px; font-size:23px; line-height:1.1; font-weight:750; }} .summary-primary .metric:nth-child(1) .metric-value,.summary-primary .metric:nth-child(2) .metric-value {{ color:var(--teal); }} .summary-primary .metric:nth-child(6) .metric-value {{ color:var(--red); }}
.summary-secondary .metric {{ min-height:48px; padding:8px 12px; display:flex; align-items:center; gap:10px; }} .summary-secondary .metric-value {{ margin:0; font-size:20px; }}
.market-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-bottom:8px; }} .market-card {{ background:#fff; border:1px solid var(--line); border-radius:11px; padding:8px 13px; display:flex; justify-content:space-between; align-items:center; }}
.market-name {{ font-weight:750; margin-right:8px; }} .market-label {{ color:var(--muted); font-size:12px; }} .data-status {{ border-radius:999px; padding:3px 9px; font-weight:700; font-size:12px; }} .status-DATA_OK {{ background:var(--teal-soft); color:var(--teal); }} .status-DATA_BLOCKED {{ background:var(--red-soft); color:var(--red); }} .status-NOT_RUN {{ background:#edf1f6; color:var(--muted); }}
.stage-nav {{ position:sticky; top:0; z-index:20; display:flex; flex-wrap:wrap; gap:4px; margin:8px 0 9px; padding:7px 8px; align-items:center; background:#f5f7fbeF; border:1px solid var(--line); border-radius:11px; box-shadow:0 4px 14px #18324b12; backdrop-filter:blur(8px); }} .stage-nav-label {{ color:var(--muted); font-weight:700; margin-right:2px; white-space:nowrap; }} .stage-link {{ min-height:44px; border:1px solid transparent; border-radius:8px; background:transparent; color:var(--blue); font:inherit; font-size:13px; font-weight:700; cursor:pointer; padding:6px 8px; white-space:nowrap; }} .stage-link:hover,.stage-link[aria-pressed="true"] {{ color:var(--teal); background:#e8f5f2; border-color:#b9ddd5; }} .nav-count {{ color:var(--muted); font-weight:650; }}
.filters {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; background:#eaf0f6; border:1px solid var(--line); border-radius:11px; padding:9px 10px; margin-bottom:10px; }} .filters label {{ display:flex; align-items:center; gap:6px; color:var(--muted); font-size:13px; }} .search-field {{ flex:1 1 250px; }} select,input[type="search"] {{ min-height:44px; border:1px solid #cbd6e2; border-radius:8px; background:#fff; color:var(--ink); padding:6px 9px; font:inherit; min-width:100px; }} input[type="search"] {{ width:100%; min-width:200px; }}
.results-heading {{ display:flex; align-items:baseline; gap:10px; margin:13px 2px 7px; }} .results-heading h2 {{ margin:0; font-size:20px; }} .results-heading span {{ color:var(--muted); font-size:12px; }} .cards {{ display:flex; flex-direction:column; gap:7px; }} .stock-row {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 13px; box-shadow:0 3px 12px #18324b08; }} .stock-row[hidden] {{ display:none; }}
.row-top {{ display:flex; justify-content:space-between; align-items:center; gap:10px; min-width:0; }} .row-identity {{ display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 9px; min-width:0; }} .ticker {{ font-size:16px; font-weight:800; letter-spacing:.02em; }} .company {{ font-weight:750; }} .sector {{ color:var(--muted); font-size:13px; }} .market-chip {{ color:var(--muted); font-size:12px; border-left:1px solid var(--line); padding-left:9px; }} .stage {{ white-space:nowrap; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:750; }} .stage-watch,.stage-armed {{ background:var(--amber-soft); color:var(--amber); }} .stage-confirmed,.stage-strategy-proposal,.stage-entry-allowed {{ background:var(--blue-soft); color:var(--blue); }} .stage-position-management {{ background:var(--teal-soft); color:var(--teal); }} .stage-failed,.stage-data-blocked {{ background:var(--red-soft); color:var(--red); }} .stage-no-trade {{ background:#edf1f6; color:var(--muted); }}
.row-bottom {{ display:flex; flex-wrap:wrap; align-items:center; gap:5px 12px; margin-top:5px; }} .row-signals {{ display:flex; flex:1 1 420px; flex-wrap:wrap; align-items:center; gap:4px 11px; min-width:0; }} .row-signals > span {{ font-size:13px; }} .row-why {{ color:#53687b; font-weight:650; overflow-wrap:anywhere; }} .row-wave {{ color:var(--blue); font-weight:750; }} .row-setup {{ color:#53687b; font:12px Consolas,monospace; }} .row-next {{ color:var(--muted); overflow-wrap:anywhere; }} .row-price {{ color:var(--teal); font-weight:700; }} .row-actions {{ display:flex; flex:0 0 auto; align-items:center; gap:8px; margin-left:auto; }} .identity-row {{ display:flex; flex-wrap:wrap; gap:4px; margin:0; }} .badge {{ border:1px solid #c8d6e2; border-radius:999px; padding:2px 6px; color:#486074; font-size:11px; background:#f7fafc; white-space:nowrap; }} .badge.warning {{ color:var(--amber); border-color:#f2ca8c; background:var(--amber-soft); }} .badge.positive {{ color:var(--teal); border-color:#9ed7ca; background:var(--teal-soft); }}
.details {{ flex:0 0 auto; margin:0; border:0; padding:0; }} .details[open] {{ flex-basis:100%; }} .details summary {{ min-height:44px; display:inline-flex; align-items:center; cursor:pointer; color:var(--blue); font-size:13px; font-weight:750; white-space:nowrap; list-style:none; padding:8px 0; }} .details summary::-webkit-details-marker {{ display:none; }} .details summary::before {{ content:"＋ "; }} .details[open] summary::before {{ content:"− "; }} .detail-body {{ border-top:1px solid var(--line); margin-top:8px; padding-top:10px; }} .field-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }} .field {{ min-width:0; }} .field-value {{ margin-top:2px; font-weight:650; overflow-wrap:anywhere; }} .panel {{ border-top:1px solid var(--line); padding-top:11px; margin-top:11px; }} .panel h3 {{ margin:0 0 8px; font-size:14px; }} .plan-panel h3 {{ color:var(--blue); }} .position-panel h3 {{ color:var(--teal); }} .detail-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:10px; }} .detail-grid section {{ background:#f8fafc; border-radius:9px; padding:9px 11px; }} .detail-grid h4,.details h4 {{ margin:0 0 4px; font-size:13px; }} .detail-grid p {{ margin:3px 0; font-size:13px; overflow-wrap:anywhere; }} code {{ color:#5c6d80; font-size:11px; }} pre {{ max-height:300px; overflow:auto; white-space:pre-wrap; background:#111d2a; color:#dce9f4; border-radius:9px; padding:11px; font:12px/1.5 Consolas,monospace; }}
.workspace-nav {{ display:flex; flex-wrap:wrap; gap:5px; margin:10px 0 8px; padding:6px; background:#e8eef5; border:1px solid var(--line); border-radius:12px; }} .workspace-link {{ min-height:44px; border:1px solid transparent; border-radius:9px; background:transparent; color:var(--blue); font:inherit; font-weight:750; padding:8px 12px; cursor:pointer; white-space:nowrap; }} .workspace-link:hover,.workspace-link[aria-pressed="true"] {{ color:#fff; background:var(--blue); border-color:var(--blue); }} .workspace-panel {{ margin-top:10px; }} .workspace-panel[hidden] {{ display:none; }} .workspace-heading {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px; margin:13px 2px 8px; }} .workspace-heading h2 {{ margin:0; font-size:21px; }} .workspace-heading p {{ margin:0; color:var(--muted); font-size:13px; }} .workspace-subheading {{ margin:17px 2px 7px; font-size:16px; }} .paper-summary {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; }} .paper-summary .metric {{ min-height:61px; }} .paper-trades {{ display:flex; flex-direction:column; gap:9px; }} .paper-trade {{ background:#fff; border:1px solid var(--line); border-left:4px solid #8ca9c2; border-radius:12px; padding:12px 14px; }} .paper-status-OPEN {{ border-left-color:var(--teal); }} .paper-status-CLOSED {{ border-left-color:var(--blue); }} .paper-status-SKIPPED {{ border-left-color:var(--muted); }} .paper-status-PENDING_T1 {{ border-left-color:var(--amber); }} .paper-trade-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }} .paper-trade-meta {{ display:flex; flex-wrap:wrap; gap:4px 10px; color:var(--muted); font-size:12px; margin-top:3px; }} .paper-status {{ background:#edf1f6; color:#506276; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:750; white-space:nowrap; }} .paper-human-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:11px; }} .paper-human-grid > section {{ background:#f8fafc; border-radius:9px; padding:10px 12px; }} .paper-human-grid h4 {{ margin:0 0 5px; font-size:13px; color:var(--blue); }} .paper-human-grid p {{ margin:0; font-size:13px; overflow-wrap:anywhere; }} .paper-technical-details {{ margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }} .paper-technical-details summary {{ cursor:pointer; color:var(--blue); font-size:12px; font-weight:750; }} .paper-technical-fields {{ margin-top:8px; }} .paper-technical-details pre {{ margin-top:8px; }} .paper-stat-note {{ color:var(--muted); font-size:12px; margin:12px 2px 0; }} .paper-warning {{ background:var(--amber-soft); color:#7a4300; border:1px solid #f2ca8c; border-radius:9px; padding:8px 10px; margin:8px 0; font-size:13px; }} .coverage-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }} .coverage-card {{ display:flex; flex-direction:column; gap:2px; background:#fff; border:1px solid var(--line); border-radius:9px; padding:9px 11px; font-size:13px; }} .coverage-card span {{ color:var(--muted); }} .coverage-CONTINUOUS {{ color:var(--teal) !important; font-weight:750; }} .coverage-GAP_DETECTED {{ color:var(--amber) !important; font-weight:750; }} .performance-summary-grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); margin-bottom:13px; }} .performance-table {{ margin-top:12px; }} .performance-table h3 {{ margin:0 0 5px; font-size:15px; }} .performance-groups {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }} .performance-group {{ background:#fff; border:1px solid var(--line); border-radius:9px; padding:9px 11px; }} .performance-group h4 {{ margin:0 0 7px; font-size:14px; color:var(--blue); }} .performance-group-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; }} .rules-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }} .rule-card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:11px 13px; }} .rule-card h3 {{ margin:0 0 4px; font-size:14px; color:var(--blue); }} .rule-card p {{ margin:0; font-size:13px; }} .empty {{ color:var(--muted); text-align:center; padding:30px; background:#fff; border:1px dashed #c5d1df; border-radius:12px; }} .footer {{ color:var(--muted); font-size:12px; margin-top:18px; }}
@media (max-width:1050px) {{ .summary-primary {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }} @media (max-width:620px) {{ .shell {{ width:min(100% - 20px,1440px); padding-top:10px; }} .hero {{ padding:18px 20px; border-radius:15px; }} .summary-primary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .summary-secondary {{ flex-direction:column; }} .market-grid {{ grid-template-columns:1fr; }} .row-top {{ align-items:flex-start; }} .stage {{ margin-top:1px; }} .row-signals {{ flex-basis:100%; }} .row-actions {{ width:100%; justify-content:space-between; margin-left:0; }} .detail-grid {{ grid-template-columns:1fr; }} .field-grid {{ gap:7px; }} .ticker {{ font-size:15px; }} }}
.today-paper-focus {{ margin-bottom:12px; }} .paper-focus-cards {{ display:flex; flex-direction:column; gap:7px; }} .paper-focus-card {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:3px 10px; align-items:center; background:#fff; border:1px solid var(--line); border-left:4px solid var(--teal); border-radius:10px; padding:9px 12px; }} .paper-focus-card span {{ color:var(--muted); font-size:13px; }} .paper-focus-meta {{ display:block; font-size:12px !important; }} .paper-focus-values {{ grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:4px 14px; }}
@media (max-width:1050px) {{ .paper-summary {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} .performance-summary-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media (max-width:620px) {{ .paper-summary,.performance-summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .paper-grid,.paper-human-grid,.rules-grid,.performance-groups {{ grid-template-columns:1fr; }} .coverage-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main class="shell">
<header class="hero"><div class="eyebrow">每日收盘报告 · 只读</div>{demo_banner}{cloud_banner}<h1>{_escape(projection['title'])}</h1><div class="hero-meta"><span>数据日期：{_escape(projection['as_of_date'])}</span><span>生成时间：{_escape(projection['generated_at'])}</span></div><div class="readonly-note">页面只展示既有结构分析、交易决策、风险和持仓管理结果；中文阶段名称只是展示映射，不会产生新信号或订单。{_escape(paper_note)}</div></header>
<section class="summary-primary" aria-label="今日重点摘要">
{_metric('可入场', summary['entry_allowed_count'], 'positive')}
{_metric('已形成交易方案', summary['strategy_proposal_count'])}
{_metric('今日确认', summary['new_confirmed_count'], 'positive')}
{_metric('接近确认', summary['armed_count'])}
{_metric('当前持仓', summary['position_count'])}
{_metric('数据异常', summary['data_blocked_count'], 'danger')}
</section>
<section class="summary-secondary" aria-label="次级摘要">
{_metric_link('观察中', summary['watch_count'], 'WATCH')}
{_metric('Candidate 总数', summary['candidate_total'])}
</section>
<section class="market-grid" aria-label="市场数据状态">{_render_market_cards(projection['markets'])}</section>
<nav class="workspace-nav" aria-label="工作台导航">{workspace_nav}</nav>
{_render_paper_workspace(paper)}
{_render_performance_workspace(paper)}
{_render_rules_workspace(projection.get('strategy_rules', ( )))}
<section id="decision-workspace" class="workspace-panel">
{_render_today_paper_focus(paper, projection.get('as_of_date'))}
<nav class="stage-nav" aria-label="阶段导航"><span class="stage-nav-label">阶段查看：</span>{stage_nav}</nav>
<section class="filters" aria-label="股票筛选"><label class="search-field">搜索<input id="search-filter" type="search" placeholder="ticker 或公司名称" autocomplete="off"></label><label>市场<select id="market-filter"><option value="">全部</option><option value="CN">中国市场（CN）</option><option value="US">美国市场（US）</option></select></label><label>当前阶段<select id="stage-filter"><option value="">全部</option>{stage_options}</select></label><label>浪型策略<select id="setup-filter"><option value="">全部</option><option value="SETUP_01">2浪→3浪</option><option value="SETUP_02">3浪延续</option></select></label><label>行业／板块<select id="sector-filter"><option value="">全部</option>{sector_options}</select></label><span id="visible-count" class="stage-nav-label"></span></section>
<div class="results-heading"><h2 id="results-title">今日重点</h2><span id="results-description">先处理可入场、方案、确认、接近确认、持仓与异常</span></div>
<section id="cards" class="cards" aria-live="polite">{cards}</section><div id="empty" class="empty" hidden>没有符合当前筛选条件的股票。</div>
</section>
<div class="footer">默认只展示今日重点；观察中与低优先级结果请通过顶部导航查看。点击“查看交易依据”查看原因、价格计划和失效条件；开发者原始数据默认收起。页面不替代用户最终交易决定。</div>
</main>
<script>
(() => {{
  const cards = Array.from(document.querySelectorAll('.stock-row'));
  const search = document.getElementById('search-filter');
  const market = document.getElementById('market-filter');
  const stage = document.getElementById('stage-filter');
  const setup = document.getElementById('setup-filter');
  const sector = document.getElementById('sector-filter');
  const empty = document.getElementById('empty');
  const count = document.getElementById('visible-count');
  const resultsTitle = document.getElementById('results-title');
  const resultsDescription = document.getElementById('results-description');
  const navButtons = Array.from(document.querySelectorAll('.stage-link'));
  const workspaceButtons = Array.from(document.querySelectorAll('.workspace-link'));
  const decisionWorkspace = document.getElementById('decision-workspace');
  const workspacePanels = {{
    paper: document.getElementById('paper-workspace'),
    performance: document.getElementById('performance-workspace'),
    rules: document.getElementById('rules-workspace'),
  }};
  let activeView = 'focus';
  const viewDescriptions = {{
    focus: '先处理可入场、方案、确认、接近确认、持仓与异常',
    ARMED: '只看接近确认的股票',
    WATCH: '只看观察中的股票',
    confirmed: '只看今天新确认的事件',
    STRATEGY_PROPOSAL: '只看已经形成交易方案的股票',
    ENTRY_ALLOWED: '只看可以入场的股票',
    POSITION_MANAGEMENT: '只看当前持仓',
    all: '包含全部结果，以及低优先级诊断状态',
  }};
  const normalise = value => String(value || '').trim().toLocaleLowerCase();
  const matchesView = card => {{
    if (activeView === 'focus') return card.dataset.focus === '1';
    if (activeView === 'confirmed') return card.dataset.confirmed === '1';
    if (activeView === 'all') return true;
    return card.dataset.stage === activeView;
  }};
  const setActiveView = view => {{
    activeView = view;
    navButtons.forEach(button => {{
      button.setAttribute('aria-pressed', button.dataset.view === activeView ? 'true' : 'false');
    }});
  }};
  const setWorkspace = workspace => {{
    workspaceButtons.forEach(button => {{
      button.setAttribute('aria-pressed', button.dataset.workspace === workspace ? 'true' : 'false');
    }});
    const showDecision = workspace === 'today' || workspace === 'diagnostics';
    decisionWorkspace.hidden = !showDecision;
    Object.entries(workspacePanels).forEach(([key, panel]) => {{
      if (panel) panel.hidden = key !== workspace;
    }});
    if (workspace === 'today') setActiveView('focus');
    if (workspace === 'diagnostics') setActiveView('all');
  }};
  const requestedView = new URLSearchParams(window.location.search).get('view') || window.location.hash.slice(1);
  const initialView = requestedView && navButtons.some(button => button.dataset.view === requestedView)
    ? requestedView
    : 'focus';
  const requestedWorkspace = new URLSearchParams(window.location.search).get('workspace');
  const initialWorkspace = requestedWorkspace && (requestedWorkspace === 'paper' || requestedWorkspace === 'performance' || requestedWorkspace === 'rules' || requestedWorkspace === 'diagnostics')
    ? requestedWorkspace
    : 'today';
  const apply = () => {{
    let visible = 0;
    const searchValue = normalise(search.value);
    cards.forEach(card => {{
      const setupValues = card.dataset.setup.split(/\\s*[/]\\s*/);
      const matches = matchesView(card)
        && (!searchValue || normalise(card.dataset.search).includes(searchValue))
        && (!market.value || card.dataset.market === market.value)
        && (!stage.value || card.dataset.stage === stage.value)
        && (!setup.value || setupValues.includes(setup.value))
        && (!sector.value || card.dataset.sector === sector.value);
      card.hidden = !matches;
      if (matches) visible += 1;
    }});
    empty.hidden = visible !== 0;
    const viewLabel = activeView === 'focus' ? '今日重点' : activeView === 'all' ? '全部/诊断' : activeView === 'confirmed' ? '今日确认' : ({{ARMED:'接近确认', WATCH:'观察中', STRATEGY_PROPOSAL:'交易方案', ENTRY_ALLOWED:'可入场', POSITION_MANAGEMENT:'持仓'}}[activeView] || activeView);
    resultsTitle.textContent = viewLabel;
    resultsDescription.textContent = viewDescriptions[activeView] || '';
    count.textContent = `${{viewLabel}}：${{visible}} / ${{cards.length}}`;
  }};
  [market, setup, sector].forEach(input => input.addEventListener('change', apply));
  stage.addEventListener('change', () => {{
    setActiveView('all');
    apply();
  }});
  search.addEventListener('input', apply);
  navButtons.forEach(button => button.addEventListener('click', () => {{
    setWorkspace('today');
    stage.value = '';
    setActiveView(button.dataset.view);
    apply();
  }}));
  workspaceButtons.forEach(button => button.addEventListener('click', () => {{
    setWorkspace(button.dataset.workspace);
    stage.value = '';
    if (button.dataset.workspace === 'diagnostics') setActiveView('all');
    apply();
  }}));
  document.querySelectorAll('.metric-link').forEach(button => button.addEventListener('click', () => {{
    setWorkspace('today');
    stage.value = '';
    setActiveView(button.dataset.view);
    apply();
  }}));
  setWorkspace(initialWorkspace);
  if (initialWorkspace === 'today') setActiveView(initialView);
  apply();
}})();
</script>
</body>
</html>
"""


def load_dashboard_json(path: str | Path) -> Mapping[str, Any]:
    """Load a previously saved production result JSON for rendering."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_daily_report_email_html(value: Any) -> str:
    """Render the independent static email presentation for a daily report."""

    # Keep the email renderer in its own module while retaining a convenient
    # presentation-layer import for callers already using this module.
    from trading.daily_report_email import render_daily_report_email_html as render

    return render(value)


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
    "DEFAULT_FOCUS_STAGES",
    "MARKET_LABELS",
    "NAV_VIEW_ORDER",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STATUS_LABELS",
    "WAVE_LABELS",
    "WAVE_SHORT_LABELS",
    "dashboard_universe_metadata",
    "dashboard_search_matches",
    "build_dashboard_projection",
    "load_dashboard_json",
    "render_daily_report_email_html",
    "render_dashboard_html",
    "write_dashboard_html",
]
