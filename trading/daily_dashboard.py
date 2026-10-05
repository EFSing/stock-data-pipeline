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
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from typing import Any

from trading.daily_decision_chain import project_setup01_wave3_extensions
from trading.risk import relative_distance_pct
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
    "ENTRY_ALLOWED",
    "STRATEGY_PROPOSAL",
    "CONFIRMED",
    "ARMED",
    "POSITION_MANAGEMENT",
    "DATA_BLOCKED",
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
    "ARMED": "等待确认",
    "CONFIRMED": "今天出现新的确认",
    "STRATEGY_PROPOSAL": "已形成交易方案",
    "ENTRY_ALLOWED": "可入场",
    "POSITION_MANAGEMENT": "策略跟踪持仓",
    "FAILED": "已失效",
    "DATA_BLOCKED": "数据异常",
    "NO_TRADE": "今天不交易",
}

# These are the only machine-like abbreviations intentionally retained in the
# ordinary user-facing report.  Full internal enum values, field names and
# protocol labels remain available in the developer/audit section.
USER_VISIBLE_LANGUAGE_AUDIT = "USER_VISIBLE_LANGUAGE_AUDIT"
USER_VISIBLE_ALLOWED_ABBREVIATIONS = (
    "SETUP_01",
    "SETUP_02",
    "T1",
    "T2",
    "T3",
    "R/R",
    "ATR14",
    "CN",
    "US",
)

STATUS_LABELS = {
    "WATCH": "观察中",
    "ARMED": "等待确认",
    "CONFIRMED": "出现新的确认",
    "STRATEGY_PROPOSAL": "已形成交易方案",
    "ENTRY_ALLOWED": "可入场",
    "PORTFOLIO_ALLOWED": "可入场",
    "POSITION_MANAGEMENT": "策略跟踪持仓",
    "FAILED": "已失效",
    "DATA_BLOCKED": "数据异常",
    "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED": "数据异常",
    "NO_TRADE": "今天不交易",
    "WAIT_CONFIRMATION": "等待确认",
}

ACTION_LABELS = {
    "WATCH": "观察中",
    "ARMED": "等待确认",
    "WAIT_CONFIRMATION": "继续观察",
    "ENTRY_ALLOWED": "当前满足入场条件",
    "NO_TRADE": "今天不交易",
    "HOLD": "继续持有",
    "NO_ADD": "暂不加仓",
    "PROFIT_PROTECTION": "保护利润",
    "EXIT": "退出",
}

TARGET_UPSIDE_BAND_LABELS = {
    "BELOW_MINIMUM": "低于最低要求",
    "LOW_UPSIDE": "偏小，但达到最低交易门槛",
    "PREFERRED_UPSIDE": "较充足",
}

_TARGET_SOURCE_LABELS = {
    "CONFIRMED_SWING_HIGH": "最近已确认历史阻力",
    "WAVE3_FIB_EXTENSION": "3浪斐波那契结构投射",
}
_WAVE3_EXTENSION_RATIO_LABELS = {
    1.272: "1.272",
    1.618: "1.618",
    2.0: "2.0",
    2.618: "2.618",
}

WAVE_LABELS = {
    "WAVE_2_TO_3_CANDIDATE": "2浪调整结束候选，等待3浪启动",
    "WAVE_3_CONTINUATION_CANDIDATE": "3浪延续候选",
    "ABC_CORRECTION_CANDIDATE": "三段式调整候选",
    "UPTREND_UNKNOWN_WAVE": "上升趋势，浪型未确定",
    "DOWNTREND_OR_INVALID_FOR_LONG": "下行趋势或不适合做多",
    "NO_VALID_SCENARIO": "暂无有效波浪情景",
}

WAVE_SHORT_LABELS = {
    "WAVE_2_TO_3_CANDIDATE": "2浪→3浪",
    "WAVE_3_CONTINUATION_CANDIDATE": "3浪延续",
    "ABC_CORRECTION_CANDIDATE": "三段式调整",
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
_SETUP_DISPLAY_LABELS = {
    "SETUP_01": "SETUP_01（2浪→3浪）",
    "SETUP_02": "SETUP_02（3浪延续）",
    "SETUP_03": "SETUP_03（平台突破）",
    "SETUP_04": "SETUP_04（极端恐慌反转）",
}
_DATA_BLOCKED_FINAL_STATUSES = {
    "DATA_BLOCKED",
    "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED",
}
_DATA_BLOCKED_STATUSES = {
    "DATA_BAD", "DATA_STALE", "DATA_UNAVAILABLE", "DATA_BLOCKED",
    "DATA_MISSING", "DATA_INVALID", "DATA_ADJUSTMENT_UNVERIFIED",
    "PROVIDER_SYMBOL_ERROR", "PROVIDER_GLOBAL_FAILURE",
    "DATA_UNAVAILABLE_FOR_DECISION",
}
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


def _format_percent(value: Any, default: str = "—", *, signed: bool = False) -> str:
    if value is None or _raw_text(value) in {"", "—", "-"}:
        return default
    number = _numeric(value)
    if number is None:
        return default
    return f"{_format_number(number * 100, 2, signed=signed, trim=False)}%"


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        text = _raw_text(value)
        if text and text not in {"—", "-"}:
            return value
    return None


def _target_source_label(value: Any) -> str:
    parts = [part for part in _text(value).split("+") if part]
    if not parts:
        return "—"
    return " + ".join(_TARGET_SOURCE_LABELS.get(part, part) for part in parts)


def _extension_ratio_label(value: Any) -> str:
    number = _numeric(value)
    if number is None:
        return _format_number(value, 3)
    for canonical, label in _WAVE3_EXTENSION_RATIO_LABELS.items():
        if math.isclose(number, canonical, rel_tol=0.0, abs_tol=1e-12):
            return label
    return _format_number(number, 3)


def _candidate_sources(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for value in (
        candidate.get("source"),
        *(
            _mapping(item).get("source")
            for item in _sequence(candidate.get("provenance"))
        ),
    ):
        for part in _raw_text(value).replace(",", "+").split("+"):
            part = part.strip()
            if part and part not in values:
                values.append(part)
    return tuple(values)


def _candidate_extension_ratio(candidate: Mapping[str, Any]) -> float | None:
    for item in _sequence(candidate.get("provenance")):
        provenance = _mapping(item)
        if "WAVE3_FIB_EXTENSION" not in _candidate_sources(provenance):
            continue
        ratio = _first_value(
            provenance.get("extension_ratio"),
            provenance.get("ratio"),
            candidate.get("extension_ratio"),
            candidate.get("ratio"),
        )
        number = _numeric(ratio)
        if number is not None:
            return number
    return _numeric(
        _first_value(
            candidate.get("extension_ratio"),
            candidate.get("ratio"),
        )
    )


def _candidate_presentation(
    candidate: Mapping[str, Any],
    *,
    reference_price: float | None,
) -> dict[str, Any] | None:
    price = _numeric(candidate.get("price"))
    if price is None:
        return None
    projected = dict(candidate)
    ratio = _candidate_extension_ratio(candidate)
    if ratio is not None:
        projected["ratio"] = ratio
        projected["ratio_label"] = (
            _text(candidate.get("ratio_label")) or _extension_ratio_label(ratio)
        )
    if _numeric(candidate.get("upside_pct")) is None and reference_price not in {
        None,
        0,
    }:
        projected["upside_pct"] = relative_distance_pct(price, reference_price)
    return projected


def _target_projection_from_candidates(
    decision: Mapping[str, Any],
    target_values: Sequence[Any],
) -> dict[str, Any]:
    """Adapt existing target candidates to the shared presentation contract.

    SETUP_01 serializes this projection directly, while SETUP_02 historically
    exposed only ``target_candidates``.  This adapter selects and labels those
    existing candidates; it never creates target prices or changes their order
    for the formal Decision.
    """

    reference_price = _numeric(decision.get("planned_entry"))
    candidates = tuple(
        projected
        for candidate in (
            _mapping(item)
            for item in _sequence(decision.get("target_candidates"))
        )
        if (projected := _candidate_presentation(
            candidate,
            reference_price=reference_price,
        )) is not None
    )
    if not candidates:
        return {}

    formal_t1 = _first_value(target_values[0] if target_values else None)
    effective_candidate = next(
        (
            candidate
            for candidate in candidates
            if _numeric(formal_t1) is not None
            and _numeric(candidate.get("price")) is not None
            and math.isclose(
                float(candidate["price"]),
                float(formal_t1),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ),
        None,
    )
    overhead_candidates = tuple(
        candidate
        for candidate in candidates
        if "CONFIRMED_SWING_HIGH" in _candidate_sources(candidate)
    )
    fib_candidates = tuple(
        candidate
        for candidate in candidates
        if "WAVE3_FIB_EXTENSION" in _candidate_sources(candidate)
        and _candidate_extension_ratio(candidate) is not None
    )
    nearest_overhead = min(
        overhead_candidates,
        key=lambda candidate: float(candidate["price"]),
        default=None,
    )
    fib_extensions = tuple(
        sorted(
            fib_candidates,
            key=lambda candidate: (
                _candidate_extension_ratio(candidate) or math.inf,
                float(candidate["price"]),
                _text(candidate.get("source")),
            ),
        )
    )
    nearest_fib = min(
        fib_extensions,
        key=lambda candidate: (
            float(candidate["price"]),
            _candidate_extension_ratio(candidate) or math.inf,
            _text(candidate.get("source")),
        ),
        default=None,
    )
    return {
        "current_effective_t1": formal_t1,
        "effective_t1_source": (
            effective_candidate.get("source") if effective_candidate else None
        ),
        "effective_t1_candidate": effective_candidate,
        "nearest_overhead_confirmed_swing_high": nearest_overhead,
        "nearest_overhead_confirmed_swing_high_price": (
            nearest_overhead.get("price") if nearest_overhead else None
        ),
        "overhead_resistance_upside_pct": (
            nearest_overhead.get("upside_pct") if nearest_overhead else None
        ),
        "nearest_wave3_fib_extension": nearest_fib,
        "nearest_wave3_fib_extension_price": (
            nearest_fib.get("price") if nearest_fib else None
        ),
        "nearest_wave3_fib_extension_ratio": (
            nearest_fib.get("ratio") if nearest_fib else None
        ),
        "wave3_fib_upside_pct": (
            nearest_fib.get("upside_pct") if nearest_fib else None
        ),
        "wave3_fib_extensions": fib_extensions,
    }


def _target_projection_display(
    decision: Mapping[str, Any],
    target_values: Sequence[Any],
) -> dict[str, Any]:
    """Format the shared Decision target projection without redoing geometry."""

    projection = dict(_mapping(decision.get("target_projection")))
    candidate_projection = _target_projection_from_candidates(
        decision,
        target_values,
    )
    if candidate_projection and not _sequence(projection.get("wave3_fib_extensions")):
        projection = {**candidate_projection, **projection}
        for key, value in candidate_projection.items():
            if key not in projection or projection[key] in (None, "", (), [], {}):
                projection[key] = value
    overhead = _mapping(projection.get("nearest_overhead_confirmed_swing_high"))
    fib = _mapping(projection.get("nearest_wave3_fib_extension"))
    effective_t1 = _first_value(
        projection.get("current_effective_t1"),
        target_values[0] if target_values else None,
    )
    effective_source = projection.get("effective_t1_source")
    if effective_source is None:
        effective_candidate = _mapping(projection.get("effective_t1_candidate"))
        effective_source = effective_candidate.get("source")
    overhead_price = _first_value(
        overhead.get("price"),
        projection.get("nearest_overhead_confirmed_swing_high_price"),
    )
    fib_price = _first_value(
        fib.get("price"),
        projection.get("nearest_wave3_fib_extension_price"),
    )
    fib_ratio = _first_value(
        fib.get("ratio"),
        projection.get("nearest_wave3_fib_extension_ratio"),
    )
    overhead_upside = projection.get("overhead_resistance_upside_pct")
    fib_upside = _first_value(
        fib.get("upside_pct"),
        projection.get("wave3_fib_upside_pct"),
    )
    extension_labels = []
    for item in _sequence(projection.get("wave3_fib_extensions")):
        item = _mapping(item)
        if not item:
            continue
        extension_labels.append(
            f"{_extension_ratio_label(item.get('ratio'))}：{_format_price(item.get('price'))}"
            f"（{_format_percent(item.get('upside_pct'))}）"
        )
    explanation = ""
    if (
        _numeric(overhead_price) is not None
        and _numeric(fib_price) is not None
        and float(overhead_price) < float(fib_price)
    ):
        explanation = (
            "系统不是认为3浪只有 "
            f"{_format_percent(overhead_upside)} 空间；3浪的结构投射目标为 "
            f"{_format_price(fib_price)}（距参考价 {_format_percent(fib_upside)}），"
            f"但当前价格上方 {_format_percent(overhead_upside)} 存在已确认历史阻力；"
            "现有最近优先规则仍把它作为当前保守第一障碍。"
        )
    return {
        "target_projection": dict(projection),
        "has_target_projection": bool(projection),
        "effective_t1": _format_price(effective_t1),
        "effective_t1_source": _display(effective_source),
        "effective_t1_source_label": _target_source_label(effective_source),
        "nearest_overhead_confirmed_swing_high": _format_price(overhead_price),
        "overhead_resistance_upside_pct": _format_percent(overhead_upside),
        "nearest_wave3_fib_extension": _format_price(fib_price),
        "nearest_wave3_fib_extension_ratio": _format_number(fib_ratio, 3),
        "wave3_fib_upside_pct": _format_percent(fib_upside),
        "wave3_fib_extensions": "；".join(extension_labels) or "—",
        "target_boundary_explanation": explanation,
    }


def _format_human_price(value: Any, default: str = "未提供") -> str:
    """Format a compact price for the human-opportunity layer.

    The existing four-decimal plan formatting remains available in the audit
    and formal plan projections.  This two-decimal presentation keeps the
    first screen readable without changing any stored or calculated value.
    """

    if value is None or _raw_text(value) in {"", "—", "-"}:
        return default
    return _format_number(value, 2)


def _format_human_price_range(low: Any, high: Any) -> str:
    if low is None and high is None:
        return "未形成（缺少确认价或 ATR）"
    if low is not None and high is not None:
        return f"{_format_human_price(low)}–{_format_human_price(high)}"
    return _format_human_price(low if low is not None else high)


def _wave3_extension_rows(value: Any) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in _sequence(value):
        mapping = _mapping(item)
        if not mapping:
            continue
        ratio = _first_value(mapping.get("ratio"), mapping.get("ratio_label"))
        price = mapping.get("price")
        if ratio is None or _numeric(price) is None:
            continue
        rows.append({
            **dict(mapping),
            "ratio_label": _text(mapping.get("ratio_label")) or _extension_ratio_label(ratio),
        })
    return tuple(rows)


def _primary_wave3_extension(value: Any) -> Mapping[str, Any] | None:
    extensions = _wave3_extension_rows(value)
    if not extensions:
        return None
    return next(
        (item for item in extensions if _text(item.get("ratio_label")) == "1.618"),
        extensions[0],
    )


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
        or any("EVALUATION_FAILED" in _raw_text(reason)
               for reason in _sequence(result.get("reasons")))
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
        "SETUP_03": "平台突破",
        "SETUP_04": "极端恐慌反转",
    }
    return " / ".join(labels.get(item, "策略类型未确定") for item in setup.split(" / ") if item)


def _setup_display(setup: Any, default: str = "策略类型未确定") -> str:
    """Explain a retained setup identifier at its first user-facing use."""

    parts = [part.strip() for part in _raw_text(setup).split("/") if part.strip()]
    if not parts:
        return default
    return " / ".join(_SETUP_DISPLAY_LABELS.get(part, _setup_label(part)) for part in parts)


def _state_display(value: Any, default: str = "未提供") -> str:
    """Translate a setup/action state before it reaches the ordinary UI."""

    labels = {
        "NONE": "未形成",
        "WATCH": "观察中",
        "ARMED": "等待确认",
        "CONFIRMED": "已确认",
        "ACTIVE": "进行中",
        "FAILED": "已失效",
        "COMPLETED": "已完成",
        "NO_TRADE": "不交易",
        "ENTRY_ALLOWED": "允许入场",
        "DATA_BLOCKED": "数据异常",
        "WAIT_CONFIRMATION": "等待确认",
    }
    text = _raw_text(value).upper()
    return labels.get(text, _display(value, default))


def _humanize_user_text(value: Any, default: str = "") -> str:
    """Translate presentation prose without touching the stored contract."""

    text = _raw_text(value)
    if not text:
        return default
    replacements = (
        ("Wave3", "3浪"),
        ("Wave2", "2浪"),
        ("Wave1", "1浪"),
        ("Wave5", "5浪"),
        ("Fib", "斐波那契"),
        ("Decision", "正式判断"),
        ("ATR", "ATR14"),
        ("entry zone", "入场区"),
        ("target", "目标"),
        ("T+1", "下一交易日"),
        ("NO_TRADE", "不交易"),
        ("ABOVE_ENTRY_ZONE", "已超过允许入场区"),
        ("Synthetic Demo", "示例数据"),
        ("Paper Lifecycle Shadow", "模拟交易生命周期验证"),
        ("Dashboard", "日报页面"),
        ("artifact", "日报文件"),
    )
    for source, label in replacements:
        text = text.replace(source, label)
    text = text.replace("确认日 正式判断 为准", "确认日正式判断为准")
    text = re.sub(r"示例数据\s*/\s*示例数据", "示例数据", text)
    return text


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
            return "3浪结构策略跟踪持仓中"
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
            return "3浪结构策略跟踪持仓中"
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
    armed = _mapping(result.get("armed_opportunity"))
    value = _first_value(
        armed.get("structural_invalidation"),
        result.get("wave_invalidation"),
        result.get("structural_invalidation"),
        result.get("invalidation"),
        decision.get("structural_invalidation"),
        decision.get("wave_scenario_invalidation"),
    )
    if isinstance(value, (Mapping, list, tuple)):
        return _json_text(value)
    if _numeric(value) is not None:
        return _format_price(value, "未提供明确结构失效条件")
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
        ("T1_EXECUTION_DATA_REQUIRED", "等待补齐下一交易日执行数据"),
        ("PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED", "等待交易日历前置条件"),
        ("POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT", "等待补齐持仓来源记录"),
        ("PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED", "等待补齐持仓风险记录"),
        ("PORTFOLIO_PENDING_RESERVATION_UNRESOLVED", "等待处理未完成的组合风险预留"),
        ("PORTFOLIO_EXISTING_POSITION_CONFLICT", "等待解决现有持仓记录冲突"),
        ("QFQ_HISTORY_MUST_REACH_COMPLETED_SESSION_T", "等待历史行情覆盖到数据日期"),
        ("UPSTREAM_EVALUATION_FAILED", "等待上游结构分析恢复"),
        ("DECISION_EVALUATION_FAILED", "等待交易方案计算恢复"),
        ("ABOVE_ENTRY_ZONE", "已超过允许入场区"),
        ("TARGET_UPSIDE_BELOW_MINIMUM", "第一目标上涨空间不足5%"),
        ("RR_BELOW_MINIMUM", "第一目标盈亏比不足"),
        ("NO_VALID_TARGET", "没有有效第一目标"),
        ("INVALID_STRUCTURE", "交易结构未通过检查"),
        ("STALE_CONFIRMATION_GEOMETRY", "确认结构已过期"),
        ("ATR_UNAVAILABLE", "缺少 ATR14，暂时无法评估"),
        ("CURRENT_CLOSE_UNAVAILABLE", "缺少当前收盘价，暂时无法计算上涨空间"),
        ("ENTRY_ALLOWED", "允许入场"),
        ("NO_TRADE", "不交易"),
        ("WATCH", "观察中"),
        ("ARMED", "等待确认"),
        ("CONFIRMED", "已确认"),
        ("DATA_BLOCKED", "数据异常，无法评估"),
        ("SKIP_TARGET_UPSIDE_BELOW_MINIMUM", "下一交易日剩余第一目标空间不足5%，不追入"),
        ("等待新的 CONFIRMED event", "等待新的确认事件"),
        ("T 日没有新的 CONFIRMED event", "今天没有新的确认事件"),
    )
    for prefix, label in translations:
        if text == prefix or text.startswith(prefix + ":"):
            return label
    if text.startswith("DATA_QUALITY_"):
        return "等待数据质量恢复"
    if "QFQ" in text.upper() and ("BEFORE" in text.upper() or "日期" in text):
        return "复权行情日期早于数据日期"
    if "HISTORY_INSUFFICIENT" in text.upper():
        return "历史行情不足"
    if re.fullmatch(r"[A-Z][A-Z0-9_+\-.]{2,}", text):
        return "暂时无法评估（技术原因见开发者原始数据）"
    if re.search(r"[A-Za-z]+_[A-Za-z_]+", text):
        return "暂时无法评估（技术原因见开发者原始数据）"
    if re.search(r"[A-Za-z]{3,}", text):
        return "暂时无法评估（技术原因见开发者原始数据）"
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
    armed = _mapping(result.get("armed_opportunity"))
    return _first_value(
        armed.get("confirmation_level"),
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


def _confirmation_no_trade_summary(
    result: Mapping[str, Any], decision: Mapping[str, Any]
) -> str:
    """Summarise an existing confirmation-day rejection for the first layer.

    This is deliberately a formatter only.  All values come from the existing
    Daily Decision and opportunity-freshness payload; no entry, target, or RR
    geometry is recomputed here.
    """

    if (
        _text(result.get("final_status")).upper() != "NO_TRADE"
        or _decision_action(decision) != "NO_TRADE"
    ):
        return ""

    reason = _raw_text(decision.get("gate_reason")).upper()
    if not reason:
        return "今天出现确认，但当前入场条件没有通过。"

    freshness = _mapping(result.get("opportunity_freshness"))
    target_upside = _first_value(
        decision.get("target_upside_pct"), freshness.get("target_upside_pct")
    )
    minimum_upside = _first_value(
        decision.get("minimum_target_upside_pct"),
        freshness.get("minimum_target_upside_pct"),
    )
    entry_zone_distance = _first_value(
        decision.get("entry_zone_upper_distance_pct"),
        freshness.get("entry_zone_upper_distance_pct"),
    )
    rr = _mapping(decision.get("rr"))
    rr_ratios = _sequence(rr.get("rr_ratios"))
    first_rr = _first_value(rr_ratios[0] if rr_ratios else None, rr.get("rr"))

    fragments = ["确认成功"]
    distance = _numeric(entry_zone_distance)
    if reason == "ABOVE_ENTRY_ZONE":
        fragments.append("超过入场区")
    elif distance is not None:
        fragments.append("超过入场区" if distance > 0 else "仍在入场区")

    target_number = _numeric(target_upside)
    minimum_number = _numeric(minimum_upside)
    if reason == "TARGET_UPSIDE_BELOW_MINIMUM" and target_number is not None:
        target_text = f"第一目标空间 {_format_percent(target_number)}"
        if minimum_number is not None:
            target_text += f" < {_format_percent(minimum_number)}"
        fragments.append(target_text)
    elif target_number is not None:
        fragments.append(f"第一目标空间 {_format_percent(target_number)}")

    if reason == "RR_BELOW_MINIMUM" and _numeric(first_rr) is not None:
        fragments.append(f"R/R {_format_rr(first_rr)}")

    rejection_labels = {
        "ABOVE_ENTRY_ZONE": "超过入场区",
        "TARGET_UPSIDE_BELOW_MINIMUM": "T1空间不足",
        "RR_BELOW_MINIMUM": "R/R不足",
        "STALE_CONFIRMATION_GEOMETRY": "确认结构已过期",
        "NO_VALID_TARGET": "没有有效 T1 目标",
    }
    rejection = rejection_labels.get(reason)
    detail_is_present = (
        reason == "ABOVE_ENTRY_ZONE"
        or (
            reason == "TARGET_UPSIDE_BELOW_MINIMUM"
            and target_number is not None
            and minimum_number is not None
        )
    )
    if rejection and not detail_is_present and rejection not in fragments:
        fragments.append(rejection)
    if not rejection:
        return "今天出现确认，但当前入场条件没有通过。"
    fragments.append("→ 不交易")
    return "｜".join(fragments)


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
            no_trade_summary = _confirmation_no_trade_summary(result, decision)
            if no_trade_summary:
                return no_trade_summary
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
            "PROFIT_PROTECTION": "保护利润，按现有策略跟踪持仓管理规则推进。",
            "EXIT": "按现有策略跟踪持仓管理结果执行退出。",
        }.get(action, _reason_text(result) or "按现有策略跟踪持仓管理结果处理。")
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
        return f"当前等待“{primary_wave_label}”确认，仍需满足确认条件。"
    if stage == "CONFIRMED":
        return f"今天出现新的“{primary_wave_label}”确认信号。"
    if stage == "STRATEGY_PROPOSAL":
        if candidate_only:
            return "候选标的已经形成技术方案，但还没有进入正式策略池。"
        return "现有结构、入场区间和目标风险收益已经形成交易方案。"
    if stage == "ENTRY_ALLOWED":
        return "现有交易方案满足入场条件，仍需按下一交易日执行规则检查。"
    if stage == "POSITION_MANAGEMENT":
        return "该标的已经进入策略跟踪持仓，当前只评估持仓动作。"
    if stage == "FAILED":
        return "最终整体状态明确显示交易结构已经失效。"
    if stage == "DATA_BLOCKED":
        return "行情或生产前置数据没有达到可用要求。"
    if _has_persistent_confirmation(result):
        return "此前已经确认，但今天没有新的确认事件。"
    return _reason_text(result) or "当前没有满足入场条件的交易方案。"


def _today_conclusion(
    result: Mapping[str, Any], decision: Mapping[str, Any], stage: str
) -> str:
    if _decision_action(decision) == "NO_TRADE":
        reason_labels = {
            "TARGET_UPSIDE_BELOW_MINIMUM": "不交易：目标上涨空间不足",
            "RR_BELOW_MINIMUM": "不交易：收益风险比不足",
            "ABOVE_ENTRY_ZONE": "不追高：已经超过允许入场区",
        }
        reason = _raw_text(decision.get("gate_reason"))
        if reason in reason_labels:
            return reason_labels[reason]
    return STAGE_LABELS.get(stage, stage)


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


def _price_plan(
    decision: Mapping[str, Any],
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = freshness or {}
    target_values = _targets(decision)
    target_upside = _first_value(
        decision.get("target_upside_pct"), freshness.get("target_upside_pct")
    )
    target_band = _first_value(
        decision.get("target_upside_band"), freshness.get("target_upside_band")
    )
    minimum_upside = _first_value(
        decision.get("minimum_target_upside_pct"),
        freshness.get("minimum_target_upside_pct"),
    )
    entry_zone_distance = _first_value(
        decision.get("entry_zone_upper_distance_pct"),
        freshness.get("entry_zone_upper_distance_pct"),
    )
    confirmation_extension = _first_value(
        decision.get("confirmation_extension_pct"),
        freshness.get("confirmation_extension_pct"),
    )
    target_semantics = _target_projection_display(decision, target_values)
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
        "target_upside_pct": _format_percent(target_upside),
        "target_upside_band": _display(
            TARGET_UPSIDE_BAND_LABELS.get(_text(target_band), _text(target_band))
        ),
        "minimum_target_upside_pct": _format_percent(minimum_upside),
        "entry_zone_upper_distance_pct": _format_percent(
            entry_zone_distance, signed=True
        ),
        "confirmation_extension_pct": _format_percent(
            confirmation_extension, signed=True
        ),
        "t1_open": _format_price(freshness.get("t1_open")),
        "t1_gap_vs_planned_entry_pct": _format_percent(
            freshness.get("t1_gap_vs_planned_entry_pct"), signed=True
        ),
        "remaining_target_upside_pct": _format_percent(
            freshness.get("remaining_target_upside_pct")
        ),
        "has_decision": bool(decision),
        **target_semantics,
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
    freshness = dict(_mapping(result.get("opportunity_freshness")))
    armed_raw = dict(_mapping(result.get("armed_opportunity")))
    armed_opportunity = {
        **armed_raw,
        "current_close_display": _format_price(armed_raw.get("current_close")),
        "confirmation_level_display": _format_price(armed_raw.get("confirmation_level")),
        "distance_to_confirmation_display": _format_price(
            armed_raw.get("distance_to_confirmation")
        ),
        "distance_to_confirmation_pct_display": _format_percent(
            armed_raw.get("distance_to_confirmation_pct"), signed=True
        ),
        "structural_invalidation_display": _format_price(
            armed_raw.get("structural_invalidation")
        ),
        "atr14_display": _format_price(armed_raw.get("atr14")),
        "expected_entry_zone_low_display": _format_price(
            armed_raw.get("expected_entry_zone_low")
        ),
        "expected_entry_zone_high_display": _format_price(
            armed_raw.get("expected_entry_zone_high")
        ),
    }
    for key in (
        "t1_open",
        "t1_gap_vs_planned_entry_pct",
        "remaining_target_upside_pct",
    ):
        if key not in freshness and result.get(key) is not None:
            freshness[key] = result.get(key)
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
        "today_conclusion": _today_conclusion(result, decision, stage),
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
        "plan": _price_plan(decision, freshness),
        "position": _position_projection(result, universe, symbol, position_management),
        "opportunity_freshness": freshness,
        "armed_opportunity": armed_opportunity,
        "reference_target_diagnostics": dict(
            _mapping(result.get("reference_target_diagnostics"))
        ),
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


def _wave3_missing_text(values: Sequence[Any]) -> str:
    labels = {
        "WAVE1_ORIGIN_UNAVAILABLE": "缺少1浪起点，暂时无法计算3浪目标",
        "WAVE1_ORIGIN_PRICE_UNAVAILABLE": "缺少1浪起点价格，暂时无法计算3浪目标",
        "WAVE1_ORIGIN_NOT_CONFIRMED": "1浪起点尚未确认，暂时无法计算3浪目标",
        "WAVE1_PEAK_UNAVAILABLE": "缺少1浪高点，暂时无法计算3浪目标",
        "WAVE1_PEAK_PRICE_UNAVAILABLE": "缺少1浪高点价格，暂时无法计算3浪目标",
        "WAVE1_PEAK_NOT_CONFIRMED": "1浪高点尚未确认，暂时无法计算3浪目标",
        "WAVE2_LOW_UNAVAILABLE": "缺少2浪低点，暂时无法计算3浪目标",
        "WAVE2_LOW_PRICE_UNAVAILABLE": "缺少2浪低点价格，暂时无法计算3浪目标",
        "WAVE2_LOW_NOT_CONFIRMED": "2浪低点尚未确认，暂时无法计算3浪目标",
        "WAVE1_WAVE2_ANCHOR_ORDER_INVALID": "1浪与2浪锚点顺序无效，暂时无法计算3浪目标",
        "CONTINUATION_LOW0_UNAVAILABLE": "缺少延续结构起点，暂时无法计算3浪目标",
        "CONTINUATION_LOW0_PRICE_UNAVAILABLE": "缺少延续结构起点价格，暂时无法计算3浪目标",
        "CONTINUATION_LOW0_NOT_CONFIRMED": "延续结构起点尚未确认，暂时无法计算3浪目标",
        "CONTINUATION_LOW0_CONFIRMED_AFTER_AS_OF": "延续结构起点晚于当前日期，暂时无法计算3浪目标",
        "CONTINUATION_LOW1_UNAVAILABLE": "缺少延续结构高点，暂时无法计算3浪目标",
        "CONTINUATION_HIGH1_UNAVAILABLE": "缺少延续结构高点，暂时无法计算3浪目标",
        "CONTINUATION_HIGH1_PRICE_UNAVAILABLE": "缺少延续结构高点价格，暂时无法计算3浪目标",
        "CONTINUATION_HIGH1_NOT_CONFIRMED": "延续结构高点尚未确认，暂时无法计算3浪目标",
        "CONTINUATION_HIGH1_CONFIRMED_AFTER_AS_OF": "延续结构高点晚于当前日期，暂时无法计算3浪目标",
        "CONTINUATION_LOW2_UNAVAILABLE": "缺少延续结构回踩低点，暂时无法计算3浪目标",
        "CONTINUATION_LOW2_PRICE_UNAVAILABLE": "缺少延续结构回踩低点价格，暂时无法计算3浪目标",
        "CONTINUATION_LOW2_NOT_CONFIRMED": "延续结构回踩低点尚未确认，暂时无法计算3浪目标",
        "CONTINUATION_LOW2_CONFIRMED_AFTER_AS_OF": "延续结构回踩低点晚于当前日期，暂时无法计算3浪目标",
        "CONTINUATION_LOW0_CONTINUATION_LOW2_ANCHOR_ORDER_INVALID": "延续结构锚点顺序无效，暂时无法计算3浪目标",
        "SETUP_TYPE_HAS_NO_WAVE3_WAVE1_ANCHOR_CONTRACT": "缺少延续结构锚点，暂时无法计算3浪目标",
        "ABOVE_ENTRY_ZONE_FORMAL_DECISION_STOPPED_BEFORE_TARGET_GENERATION": "正式规则在目标计算前已判定不交易，因此正式 T1 未生成",
        "FORMAL_WAVE3_TARGET_PROJECTION_UNAVAILABLE": "缺少3浪目标投影所需结构信息，暂时无法计算3浪目标",
        "FORMAL_DECISION_UNAVAILABLE": "缺少正式判断，暂时无法确认目标",
    }
    rendered: list[str] = []
    for value in _sequence(values):
        key = _raw_text(value)
        label = labels.get(key, _translate_reason(key))
        if label and label not in rendered:
            rendered.append(label)
    return "；".join(rendered)


def _decision_wave3_anchor_mapping(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose already-produced Wave anchors to the canonical projection helper."""

    return {
        "wave1_origin": _first_value(
            decision.get("wave1_origin"),
            decision.get("continuation_low0"),
        ),
        "wave1_peak": _first_value(
            decision.get("wave1_peak"),
            decision.get("continuation_high1"),
            decision.get("confirmation_level"),
        ),
        "wave2_low": _first_value(
            decision.get("wave2_low"),
            decision.get("continuation_low2"),
            decision.get("structural_invalidation"),
        ),
    }


def _continuation_anchor_text(value: Any) -> str:
    anchors = _mapping(value)
    if not anchors:
        return "未提供"
    labels = (
        ("continuation_low0", "起点"),
        ("continuation_high1", "前一高点"),
        ("continuation_low2", "回踩低点"),
        ("continuation_high3", "确认高点"),
    )
    rendered = []
    for key, label in labels:
        anchor = _mapping(anchors.get(key))
        if not anchor:
            rendered.append(f"{label}未提供")
            continue
        rendered.append(f"{label} {_format_human_price(anchor.get('price'))}")
    return "；".join(rendered)


def _manual_opportunity_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project existing fields into the human-first detail layer.

    This function is presentation-only.  It selects already-produced target
    provenance and pre-confirmation projection values; it never derives a
    target, gate, ranking, or entry condition.
    """

    stage = _text(row.get("stage_key"))
    decision = _mapping(row.get("decision"))
    plan = _mapping(row.get("plan"))
    armed = _mapping(row.get("armed_opportunity"))
    has_decision = bool(decision)
    is_preconfirmation = stage in {"WATCH", "ARMED"}
    is_human_candidate = is_preconfirmation or has_decision
    if not is_human_candidate or row.get("data_blocked"):
        return {"available": False, "reason": "当前结果没有可展示的人工机会结构。"}

    if is_preconfirmation and not has_decision:
        reference_price = _numeric(armed.get("current_close"))
        reference_label = "当前价"
        confirmation = _numeric(armed.get("confirmation_level"))
        entry_low = _numeric(armed.get("expected_entry_zone_low"))
        entry_high = _numeric(armed.get("expected_entry_zone_high"))
        invalidation = _numeric(armed.get("structural_invalidation"))
        distance_pct = _numeric(armed.get("distance_to_confirmation_pct"))
        wave_extensions = _wave3_extension_rows(armed.get("wave3_fib_extensions"))
        wave_missing = tuple(_sequence(armed.get("wave3_missing_reasons")))
        if not wave_extensions and not wave_missing:
            if _text(armed.get("setup_type")) == "SETUP_01":
                wave_missing = (
                    "WAVE1_ORIGIN_UNAVAILABLE",
                    "WAVE1_PEAK_UNAVAILABLE",
                    "WAVE2_LOW_UNAVAILABLE",
                )
            else:
                wave_missing = (
                    "CONTINUATION_LOW0_UNAVAILABLE",
                    "CONTINUATION_HIGH1_UNAVAILABLE",
                    "CONTINUATION_LOW2_UNAVAILABLE",
                )
        system_conclusion = "尚未确认，当前不会放行；这不影响它作为人工观察机会展示。"
        confirmation_text = _format_human_price(confirmation)
        invalidation_text = _format_human_price(invalidation)
        next_action = (
            "打开图表检查量价和结构；若仍认可该结构，重点盯 "
            f"{confirmation_text} 附近的收盘确认。跌破 {invalidation_text} 则该观察逻辑失效。"
            if confirmation is not None and invalidation is not None
            else "打开图表检查量价和结构；当前缺少完整确认或失效字段，不能进一步假设。"
        )
        target_items = tuple(
            {
                "kind": "WAVE3_FIB_EXTENSION",
                "label": f"3浪斐波那契 {_text(item.get('ratio_label'), _format_number(item.get('ratio'), 3))}",
                "price": item.get("price"),
                "upside_pct": item.get("upside_pct"),
                "primary": _text(item.get("ratio_label")) in {"1.272", "1.618"},
            }
            for item in wave_extensions
        )
        return {
            "available": True,
            "stage": stage,
            "reference_label": reference_label,
            "reference_price": reference_price,
            "confirmation_level": confirmation,
            "distance_to_confirmation_pct": distance_pct,
            "entry_zone_low": entry_low,
            "entry_zone_high": entry_high,
            "structural_invalidation": invalidation,
            "structural_risk_pct": (
                relative_distance_pct(invalidation, reference_price)
                if invalidation is not None and reference_price not in {None, 0}
                else None
            ),
            "wave3_extensions": wave_extensions,
            "wave3_targets": target_items,
            "wave3_is_estimate": True,
            "wave3_missing_text": _wave3_missing_text(wave_missing),
            "wave3_missing_reasons": wave_missing,
            "system_conclusion": system_conclusion,
            "next_action": next_action,
            "formal_decision": False,
            "gate_reason": "",
            "target_upside_pct": None,
            "first_rr": None,
            "formal_t1": None,
            "formal_t1_upside_pct": None,
            "reference_target_diagnostics": {},
        }

    reference_price = _numeric(decision.get("planned_entry"))
    reference_label = "当前正式判断参考价"
    confirmation = _numeric(decision.get("confirmation_level"))
    entry_low = _numeric(decision.get("entry_zone_low"))
    entry_high = _numeric(decision.get("entry_zone_high"))
    invalidation = _numeric(decision.get("structural_invalidation"))
    freshness = _mapping(row.get("opportunity_freshness"))
    target_projection = _mapping(plan.get("target_projection"))
    wave_extensions = _wave3_extension_rows(target_projection.get("wave3_fib_extensions"))
    gate_reason = _text(decision.get("gate_reason"))
    reference_diagnostics = _mapping(row.get("reference_target_diagnostics"))
    wave3_presentation_only = False
    if not wave_extensions:
        fallback_projection = project_setup01_wave3_extensions(
            _decision_wave3_anchor_mapping(decision),
            current_close=reference_price,
            require_confirmed=False,
        ) if reference_price is not None else {}
        if _text(fallback_projection.get("wave3_projection_status")) == "AVAILABLE":
            wave_extensions = _wave3_extension_rows(
                fallback_projection.get("wave3_fib_extensions")
            )
            wave3_presentation_only = True
    wave_missing: tuple[Any, ...] = ()
    if not wave_extensions:
        if gate_reason == "ABOVE_ENTRY_ZONE":
            wave_missing = ("ABOVE_ENTRY_ZONE_FORMAL_DECISION_STOPPED_BEFORE_TARGET_GENERATION",)
        elif not has_decision:
            wave_missing = ("FORMAL_DECISION_UNAVAILABLE",)
        else:
            wave_missing = ("FORMAL_WAVE3_TARGET_PROJECTION_UNAVAILABLE",)

    formal_t1 = _numeric(
        _first_value(
            target_projection.get("current_effective_t1"),
            decision.get("T1"),
            (decision.get("targets") or [None])[0]
            if isinstance(decision.get("targets"), Sequence)
            and not isinstance(decision.get("targets"), (str, bytes, bytearray))
            else None,
        )
    )
    t1_upside = _first_value(
        target_projection.get("overhead_resistance_upside_pct"),
        decision.get("target_upside_pct"),
        freshness.get("target_upside_pct"),
    )
    rr = _mapping(decision.get("rr"))
    rr_values = _sequence(rr.get("rr_ratios"))
    first_rr = _numeric(rr_values[0] if rr_values else rr.get("rr"))
    target_items: list[dict[str, Any]] = []
    if formal_t1 is not None:
        target_items.append({
            "kind": "FORMAL_T1",
            "label": "第一障碍 / T1",
            "price": formal_t1,
            "upside_pct": t1_upside,
            "primary": False,
        })
    target_items.extend(
        {
            "kind": "WAVE3_FIB_EXTENSION",
            "label": (
                f"3浪结构目标 斐波那契 {_text(item.get('ratio_label'), _format_number(item.get('ratio'), 3))}"
                if wave3_presentation_only
                else f"3浪斐波那契 {_text(item.get('ratio_label'), _format_number(item.get('ratio'), 3))}"
            ),
            "price": item.get("price"),
            "upside_pct": item.get("upside_pct"),
            "primary": _text(item.get("ratio_label")) in {"1.272", "1.618"},
        }
        for item in wave_extensions
    )
    gate_reason = _text(decision.get("gate_reason"))
    if gate_reason == "ABOVE_ENTRY_ZONE":
        system_conclusion = "确认有效，但当前参考价已超过允许入场区上沿，因此本次不追高。"
        next_action = (
            "正式系统不追价；若继续人工观察，只观察后续结构演化，"
            "不要把普通回踩自动视为原确认机会重新有效。"
        )
    elif gate_reason == "TARGET_UPSIDE_BELOW_MINIMUM":
        system_conclusion = "第一目标剩余空间低于5%门槛"
        next_action = (
            "结合图表判断当前价格是否仍有可接受的结构空间；不要因为存在远端斐波那契目标而忽略"
            "正式入场区、结构失效与执行风险。"
        )
    elif gate_reason == "RR_BELOW_MINIMUM":
        system_conclusion = "第一目标 R/R 未达到系统最低要求"
        next_action = (
            "结合图表判断当前价格是否仍有可接受的结构空间；不要因为存在远端斐波那契目标而忽略"
            "正式入场区、结构失效与执行风险。"
        )
    elif _decision_action(decision) == "ENTRY_ALLOWED":
        system_conclusion = "正式条件满足；仍需遵循下一交易日、组合风控与人工批准边界。"
        next_action = "按正式系统的下一交易日与组合风控结果继续处理；本页只读，不自动下单。"
    else:
        system_conclusion = _text(
            _translate_reason(gate_reason),
            "正式系统尚未形成可执行交易方案。",
        )
        next_action = "先结合图表检查当前价格、结构失效与正式入场区，再决定是否继续人工跟踪。"

    return {
        "available": True,
        "stage": stage,
        "reference_label": reference_label,
        "reference_price": reference_price,
        "confirmation_level": confirmation,
        "distance_to_confirmation_pct": None,
        "entry_zone_low": entry_low,
        "entry_zone_high": entry_high,
        "structural_invalidation": invalidation,
        "structural_risk_pct": (
            relative_distance_pct(invalidation, reference_price)
            if invalidation is not None and reference_price not in {None, 0}
            else None
        ),
        "wave3_extensions": wave_extensions,
        "wave3_targets": tuple(target_items),
        "wave3_is_estimate": False,
        "wave3_presentation_only": wave3_presentation_only,
        "wave3_missing_text": _wave3_missing_text(wave_missing),
        "wave3_missing_reasons": wave_missing,
        "system_conclusion": system_conclusion,
        "next_action": next_action,
        "formal_decision": True,
        "gate_reason": gate_reason,
        "target_upside_pct": _numeric(t1_upside),
        "first_rr": first_rr,
        "formal_t1": formal_t1,
        "formal_t1_upside_pct": _numeric(t1_upside),
        "reference_target_diagnostics": dict(reference_diagnostics),
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
            result.append("策略跟踪持仓")
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


def _integer_count(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _diagnostic_by_market(
    payload: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    """Read existing Candidate/Funnel summaries without recomputing strategy state."""

    values: dict[str, dict[str, Any]] = {}
    direct = _mapping(payload.get(key))
    for market, value in direct.items():
        normalized = _normalised_market(market)
        if normalized:
            values[normalized] = dict(_mapping(value))
    for entry in entries:
        market = _normalised_market(entry.get("market"))
        value = _mapping(entry.get("candidate" if key == "candidate_markets" else "entry"))
        if key != "candidate_markets":
            value = _mapping(value.get("Funnel"))
        if market and value and market not in values:
            values[market] = dict(value)
    cloud = _mapping(payload.get("cloud_daily_report"))
    cloud_values = _mapping(cloud.get(key))
    if key == "candidate_markets" and not cloud_values:
        cloud_values = _mapping(cloud.get("candidate_diagnostics"))
    for market, value in cloud_values.items():
        normalized = _normalised_market(market)
        if normalized and normalized not in values:
            values[normalized] = dict(_mapping(value))
    return values


def _candidate_diagnostics(
    payload: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_by_market = _diagnostic_by_market(payload, entries, "candidate_markets")
    funnel_by_market = _diagnostic_by_market(payload, entries, "funnel")
    scope_by_market: dict[str, dict[str, Any]] = {}
    for entry in entries:
        market = _normalised_market(entry.get("market"))
        scope = _mapping(_mapping(entry.get("universe")).get("analysis_scope_counts"))
        if market and scope and market not in scope_by_market:
            scope_by_market[market] = dict(scope)
    markets = sorted(
        set(candidate_by_market)
        | set(funnel_by_market)
        | {row["market"] for row in rows if row.get("market") not in {"", "—"}}
    )
    numeric_keys = (
        "seed_count",
        "data_qualified_count",
        "included_count",
        "deep_requested_count",
        "deep_ready_count",
        "deep_analysis_count",
        "analysis_attempted_count",
        "strategy_analysis_count",
        "analysis_blocked_count",
        "formal_strategy_pool_count",
        "dynamic_candidate_count",
        "dynamic_candidate_only_count",
        "dynamic_candidate_analysis_count",
        "dynamic_candidate_only_analysis_count",
        "dynamic_candidate_blocked_count",
        "dynamic_candidate_only_blocked_count",
        "daily_result_count",
        "data_ok_count",
        "data_blocked_count",
        "watch_count",
        "armed_count",
        "new_confirmed_count",
        "strategy_proposal_count",
        "entry_allowed_count",
        "portfolio_allowed_count",
        "no_trade_count",
    )
    totals = {key: 0 for key in numeric_keys}
    aggregate_reasons: dict[str, int] = {}
    market_values: list[dict[str, Any]] = []
    for market in markets:
        candidate = candidate_by_market.get(market, {})
        funnel = funnel_by_market.get(market, {})
        scope = scope_by_market.get(market, {})
        market_rows = [row for row in rows if row.get("market") == market]
        included = _integer_count(candidate.get("candidate_included_count"))
        deep_analysis_value = candidate.get("strategy_analysis_count")
        if deep_analysis_value is None:
            deep_analysis_value = candidate.get("deep_analysis_count")
        if deep_analysis_value is None:
            deep_analysis_value = funnel.get("deep_analysis")
        deep_analysis = _integer_count(deep_analysis_value)
        attempted_value = candidate.get("deep_analysis_attempted_count")
        if attempted_value is None:
            attempted_value = scope.get("candidate_included_result_count")
        if attempted_value is None:
            attempted_value = deep_analysis
        analysis_blocked = _integer_count(
            candidate.get("analysis_blocked_count"),
            max(_integer_count(attempted_value) - deep_analysis, 0),
        )
        deep_requested = candidate.get("deep_history_requested_count")
        if deep_requested is None:
            deep_requested = deep_analysis
        deep_ready = candidate.get("deep_history_ready_count")
        if deep_ready is None:
            deep_ready = candidate.get("deep_history_ready_symbols", ())
            deep_ready = len(_sequence(deep_ready)) if not isinstance(deep_ready, (int, float)) else deep_ready
        reasons_value = candidate.get("candidate_exclusion_reason_counts")
        reason_counts = {
            _text(reason): _integer_count(count)
            for reason, count in _mapping(reasons_value).items()
            if _text(reason) and _integer_count(count)
        }
        if not reason_counts:
            for record in _sequence(candidate.get("candidate_records")):
                reason = _text(_mapping(record).get("exclusion_reason")) or "INCLUDED"
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        filter_reasons = [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
            if reason != "INCLUDED"
        ]
        for item in filter_reasons:
            aggregate_reasons[item["reason"]] = aggregate_reasons.get(item["reason"], 0) + item["count"]
        row_counts = {
            "daily_result_count": len(market_rows),
            "data_ok_count": sum(_text(row.get("raw_result", {}).get("data_status")).upper() == "DATA_OK" for row in market_rows),
            "data_blocked_count": sum(row.get("data_blocked", False) for row in market_rows),
            "watch_count": sum(row.get("stage_key") == "WATCH" for row in market_rows),
            "armed_count": sum(row.get("stage_key") == "ARMED" for row in market_rows),
            "new_confirmed_count": sum(bool(row.get("event_is_new")) for row in market_rows),
            "strategy_proposal_count": sum(row.get("stage_key") == "STRATEGY_PROPOSAL" for row in market_rows),
            "entry_allowed_count": sum(row.get("stage_key") == "ENTRY_ALLOWED" for row in market_rows),
            "portfolio_allowed_count": sum(_text(row.get("raw_result", {}).get("final_status")) == "PORTFOLIO_ALLOWED" for row in market_rows),
            "no_trade_count": sum(row.get("stage_key") == "NO_TRADE" for row in market_rows),
        }
        candidate_status = _text(candidate.get("status"))
        candidate_component_status = _text(
            candidate.get("candidate_status"),
            "UNAVAILABLE" if candidate_status in {"FAILED", "PROVIDER_GLOBAL_FAILURE"} else candidate_status,
        )
        selection_outcome = _text(candidate.get("candidate_selection_outcome"))
        if not selection_outcome:
            if candidate_status == "NO_CANDIDATES":
                selection_outcome = "NO_CANDIDATES"
            elif included:
                selection_outcome = "CANDIDATES_INCLUDED"
            elif candidate_status in {"FAILED", "PARTIAL_DATA_QUALITY"}:
                selection_outcome = "DISCOVERY_FAILED"
            elif candidate:
                selection_outcome = "NOT_REPORTED"
            else:
                selection_outcome = "NOT_REPORTED" if market_rows else "NOT_RUN"
        values = {
            "market": market,
            "label": MARKET_LABELS.get(market, market),
            "status": _text(
                candidate_status,
                "NOT_REPORTED" if market_rows and not candidate else "NOT_RUN",
            ),
            "candidate_status": candidate_component_status,
            "selection_outcome": selection_outcome,
            "stage_a_status": _text(
                _mapping(_mapping(candidate.get("stage_timings")).get("candidate_short_history")).get("status"),
                "NOT_REPORTED" if market_rows and not candidate else "NOT_RUN",
            ),
            "stage_b_status": _text(
                _mapping(_mapping(candidate.get("stage_timings")).get("deep_history")).get("status"),
                "NOT_REPORTED" if market_rows and not candidate else "NOT_RUN",
            ),
            "seed_count": _integer_count(candidate.get("seed_count")),
            "data_qualified_count": _integer_count(candidate.get("candidate_data_qualified_count")),
            "included_count": included,
            "deep_requested_count": _integer_count(deep_requested),
            "deep_ready_count": _integer_count(deep_ready),
            "deep_analysis_count": deep_analysis,
            "analysis_attempted_count": _integer_count(attempted_value),
            "strategy_analysis_count": deep_analysis,
            "analysis_blocked_count": analysis_blocked,
            "formal_strategy_pool_count": _integer_count(
                scope.get("formal_strategy_pool", scope.get("formal_strategy_pool_count"))
            ),
            "dynamic_candidate_count": _integer_count(
                scope.get("dynamic_candidate", scope.get("dynamic_candidate_count")),
                included,
            ),
            "dynamic_candidate_only_count": _integer_count(
                scope.get("dynamic_candidate_only", scope.get("dynamic_candidate_only_count"))
            ),
            "dynamic_candidate_analysis_count": _integer_count(
                scope.get("dynamic_candidate_strategy_analysis", scope.get("dynamic_candidate_analysis_count"))
            ),
            "dynamic_candidate_only_analysis_count": _integer_count(
                scope.get("dynamic_candidate_only_strategy_analysis", scope.get("dynamic_candidate_only_analysis_count"))
            ),
            "dynamic_candidate_blocked_count": _integer_count(
                scope.get("dynamic_candidate_data_blocked", scope.get("dynamic_candidate_blocked_count"))
            ),
            "dynamic_candidate_only_blocked_count": _integer_count(
                scope.get("dynamic_candidate_only_data_blocked", scope.get("dynamic_candidate_only_blocked_count"))
            ),
            "filter_reasons": filter_reasons,
            "candidate_errors": [
                _text(item) for item in _sequence(candidate.get("errors")) if _text(item)
            ],
            "funnel": dict(funnel),
            **row_counts,
        }
        values["coverage_status"] = (
            "DATA_ISSUE"
            if values["status"] in {"FAILED", "PARTIAL_DATA_QUALITY", "NOT_REPORTED"}
            or values["candidate_status"] == "UNAVAILABLE"
            or values["selection_outcome"] in {"DISCOVERY_FAILED", "NOT_REPORTED"}
            or values["candidate_errors"]
            or values["stage_a_status"] in {"FAILED", "PARTIAL_DATA_QUALITY", "NOT_REPORTED"}
            else "COVERAGE_INSUFFICIENT"
            if included and (
                deep_analysis < included
                or _integer_count(attempted_value) < included
            )
            else "NO_CANDIDATES"
            if values["selection_outcome"] == "NO_CANDIDATES"
            else "COVERAGE_COMPLETE"
        )
        for key in numeric_keys:
            totals[key] += values.get(key, 0)
        market_values.append(values)
    return {
        "markets": market_values,
        "totals": totals,
        "filter_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(aggregate_reasons.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _diagnostic_data_issues(
    payload: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    """Collect abnormal symbols from existing quality/provider error fields."""

    issues: dict[tuple[str, str, str], None] = {}

    def add(market: Any, symbol: Any, reason: Any) -> None:
        normalized_market = _normalised_market(market) or "—"
        normalized_symbol = _text(symbol) or "系统"
        normalized_reason = _text(reason) or "数据质量检查未通过"
        issues[(normalized_market, normalized_symbol, normalized_reason)] = None

    def add_error(value: Any, market: Any) -> None:
        text = _text(value)
        if not text:
            return
        left, separator, reason = text.partition(":")
        if "|" in left:
            error_market, symbol = left.split("|", 1)
            add(error_market, symbol, reason.strip() if separator else text)
        # Unscoped runtime/preflight text is intentionally kept in the status
        # banner and artifact metadata, not copied verbatim into the user mail.
        # Symbol-scoped provider errors remain visible above.

    cloud = _mapping(payload.get("cloud_daily_report"))
    market = _normalised_market(cloud.get("market"))
    quality = _mapping(cloud.get("data_quality"))
    for symbol in _sequence(quality.get("failed_symbols")):
        add(market, symbol, "数据质量未通过")
    for key in (
        "errors",
        "ephemeral_errors",
        "preflight_errors",
        "candidate_quality_errors",
    ):
        values = cloud.get(key) if key == "errors" else quality.get(key)
        for value in _sequence(values):
            add_error(value, market)
    runtime_errors = quality.get("candidate_runtime_errors")
    if isinstance(runtime_errors, Mapping):
        for candidate_market, value in runtime_errors.items():
            text = _text(value)
            if text:
                add(candidate_market, "候选链路", text)
    for value in _sequence(quality.get("candidate_quality_errors")):
        text = _text(value)
        if text:
            add(market, "候选链路", text)
    for symbol, provider in _mapping(cloud.get("provider_status")).items():
        provider = _mapping(provider)
        for value in _sequence(provider.get("errors")):
            add(market, symbol, value)
        for key in ("latest_status", "qfq"):
            value = _text(provider.get(key))
            if value and (
                value.upper().startswith(("FAILED", "ERROR", "DATA_"))
                or any(marker in value for marker in ("失败", "失效", "待复核", "单源"))
            ):
                add(market, symbol, f"{key}：{value}")
    for candidate in _mapping(payload.get("candidate_markets")).values():
        candidate = _mapping(candidate)
        candidate_market = _normalised_market(candidate.get("market")) or market
        for value in _sequence(candidate.get("errors")):
            if _text(value):
                add(candidate_market, "候选链路", value)
        deep_errors = _mapping(candidate.get("deep_history_errors"))
        for symbol, values in deep_errors.items():
            for value in _sequence(values) or (values,):
                add(candidate_market, symbol, value)
    if rows and not _mapping(payload.get("candidate_markets")) and not any(
        _mapping(entry.get("candidate")) for entry in _report_entries(payload)
    ):
        add(market, "候选链路", "候选阶段未报告，完整分析覆盖无法确认")
    for row in rows:
        if not row.get("data_blocked"):
            continue
        raw = _mapping(row.get("raw_result"))
        reasons = list(_sequence(raw.get("blocking_prerequisites")))
        reasons.extend(_sequence(raw.get("reasons")))
        if not reasons:
            reasons = [raw.get("data_status") or raw.get("final_status") or "数据质量未通过"]
        for reason in reasons:
            add(row.get("market"), row.get("symbol"), reason)
    cloud_status = _text(cloud.get("status")).upper()
    if cloud_status in {
        "FAILED", "INCOMPLETE_SESSION", "PARTIAL_DATA_QUALITY",
        "PROVIDER_GLOBAL_FAILURE", "COMPLETED_NO_USABLE_SYMBOLS",
    } and not issues:
        add(market, "系统", f"日报状态：{cloud_status}")
    return [
        {"market": market, "symbol": symbol, "reason": reason}
        for market, symbol, reason in sorted(issues)
    ]


def _diagnostics(
    payload: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate = _candidate_diagnostics(payload, entries, rows)
    data_issues = _diagnostic_data_issues(payload, rows)
    totals = candidate["totals"]
    has_candidate_summary = bool(candidate["markets"])
    signal_count = (
        totals["new_confirmed_count"]
        + totals["strategy_proposal_count"]
        + totals["entry_allowed_count"]
    )
    if data_issues:
        status = "DATA_ISSUE"
    elif has_candidate_summary and any(
        item["coverage_status"] == "COVERAGE_INSUFFICIENT"
        for item in candidate["markets"]
    ):
        status = "COVERAGE_INSUFFICIENT"
    elif signal_count == 0:
        status = "NORMAL_NO_SIGNAL"
    else:
        status = "SIGNAL_AVAILABLE"
    return {
        "status": status,
        "data_issues": data_issues,
        "candidate": candidate,
        "coverage": {
            **totals,
            "signal_count": signal_count,
        },
    }


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
        if cloud_status in {
            "FAILED", "INCOMPLETE_SESSION", "PARTIAL_DATA_QUALITY",
            "PROVIDER_GLOBAL_FAILURE", "COMPLETED_NO_USABLE_SYMBOLS",
        }:
            return {"status_key": "DATA_BLOCKED", "status_label": "数据异常"}
    candidate_markets = _mapping(payload.get("candidate_markets"))
    candidate = _mapping(candidate_markets.get(market))
    candidate_status = _text(candidate.get("status"))
    blocked = any(row["data_blocked"] for row in rows if row["market"] == market)
    blocked = blocked or candidate_status in {"FAILED", "PARTIAL_DATA_QUALITY"} or _preflight_market_status(payload, market)
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


def _freshness_funnel(
    payload: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    direct = _mapping(payload.get("freshness_funnel"))
    if direct:
        return dict(direct)
    numeric_keys = (
        "new_confirmed_total",
        "above_entry_zone_count",
        "target_upside_below_minimum_count",
        "rr_below_minimum_count",
        "other_no_trade_count",
        "entry_allowed_count",
        "t1_gap_skip_count",
        "t1_upside_decay_skip_count",
        "t1_gap_or_upside_skip_count",
    )
    totals = {key: 0 for key in numeric_keys}
    found = False
    conserved = True
    for entry in entries:
        funnel = _mapping(_mapping(entry.get("report")).get("freshness_funnel"))
        if not funnel:
            continue
        found = True
        for key in numeric_keys:
            try:
                totals[key] += int(funnel.get(key, 0) or 0)
            except (TypeError, ValueError):
                pass
        conserved = conserved and bool(funnel.get("confirmation_funnel_conserved", True))
    if not found:
        return {}
    return {**totals, "confirmation_funnel_conserved": conserved}


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
                projected["manual_opportunity"] = _manual_opportunity_projection(projected)
                rows.append(projected)
    presentation_order = DEFAULT_FOCUS_STAGES + tuple(
        stage for stage in STAGE_ORDER if stage not in DEFAULT_FOCUS_STAGES
    )
    stage_rank = {stage: index for index, stage in enumerate(presentation_order)}
    def presentation_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        armed = _mapping(row.get("armed_opportunity"))
        distance = _numeric(armed.get("distance_to_confirmation_pct"))
        armed_distance = abs(distance) if distance is not None else math.inf
        return (
            stage_rank.get(row["stage_key"], len(STAGE_ORDER)),
            armed_distance if row["stage_key"] == "ARMED" else 0.0,
            row["market"],
            row["symbol"],
            row["account_id"],
        )

    rows.sort(key=presentation_key)

    preflight = _mapping(payload.get("preflight"))
    cloud_daily = _mapping(payload.get("cloud_daily_report"))
    as_of_date = _first_value(payload.get("as_of_date"), preflight.get("T"))
    if as_of_date is None:
        as_of_date = next((row["raw_result"].get("as_of_date") for row in rows if row["raw_result"].get("as_of_date")), None)
    generated_at = _first_value(payload.get("generated_at"), next((row["raw_result"].get("generated_at") for row in rows if row["raw_result"].get("generated_at")), None))
    known_markets = {row["market"] for row in rows if row["market"] and row["market"] != "—"}
    known_markets.update(_normalised_market(item) for item in _mapping(payload.get("candidate_markets")))
    cloud_market = _normalised_market(cloud_daily.get("market"))
    if not cloud_market and entries:
        # Older saved Cloud artifacts carried the market at the payload root
        # before ``cloud_daily_report`` metadata was added.  Preserve their
        # one-market report presentation without changing any row semantics.
        root_market = _normalised_market(payload.get("market"))
        if root_market in {"CN", "US"}:
            cloud_market = root_market
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
        "analysis_count": len(rows),
        "completed_analysis_count": sum(
            _text(row["raw_result"].get("data_status")) == "DATA_OK"
            and not row["data_blocked"] for row in rows
        ),
        "watch_count": sum(row["stage_key"] == "WATCH" for row in rows),
        "armed_count": sum(row["stage_key"] == "ARMED" for row in rows),
        "new_confirmed_count": sum(row["event_is_new"] for row in rows),
        "strategy_proposal_count": sum(row["stage_key"] == "STRATEGY_PROPOSAL" for row in rows),
        "entry_allowed_count": sum(row["stage_key"] == "ENTRY_ALLOWED" for row in rows),
        "position_count": sum(row["is_position"] for row in rows),
        "data_blocked_count": sum(row["stage_key"] == "DATA_BLOCKED" for row in rows),
    }
    freshness_funnel = _freshness_funnel(payload, entries)
    diagnostics = _diagnostics(payload, entries, rows)
    sectors = sorted({row["sector"] for row in rows if row["sector"] != "—"}, key=str.casefold)
    paper = _paper_projection(payload, entries)
    rules = [
        {"question": question, "answer": answer}
        for question, answer in strategy_rules_for_dashboard()
    ]
    return {
        "title": "收盘交易决策日报" if cloud_daily else "每日交易决策工作台",
        "demo_label": _humanize_user_text(payload.get("demo_label")),
        "as_of_date": _display(as_of_date),
        "generated_at": _display(generated_at),
        "summary": summary,
        "freshness_funnel": freshness_funnel,
        "diagnostics": diagnostics,
        "markets": market_rows,
        "rows": rows,
        "sectors": sectors,
        "stage_order": STAGE_ORDER,
        "paper": paper,
        "strategy_rules": rules,
        "workspace_order": ("today", "paper", "performance", "rules", "diagnostics"),
        "cloud_daily_report": dict(cloud_daily),
        "prospective_observation": dict(_mapping(payload.get("prospective_observation"))),
        "opportunity_tracking": dict(_mapping(payload.get("opportunity_tracking"))),
    }


def _escape(value: Any) -> str:
    return html.escape(_display(value), quote=True)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


_USER_VISIBLE_RAW_ENUM_TOKENS = (
    "ABOVE_ENTRY_ZONE",
    "RR_BELOW_MINIMUM",
    "TARGET_UPSIDE_BELOW_MINIMUM",
    "NO_VALID_TARGET",
    "INVALID_STRUCTURE",
    "ATR_UNAVAILABLE",
    "NO_TRADE",
    "ENTRY_ALLOWED",
    "ARMED",
    "WATCH",
    "CONFIRMED",
    "DATA_BLOCKED",
    "SUCCESS",
    "FAILED",
    "PARTIAL_DATA_QUALITY",
    "SKIPPED_NON_SESSION",
    "STRATEGY_PROPOSAL",
    "POSITION_MANAGEMENT",
    "DATA_OK",
    "DATA_UNAVAILABLE",
    "DATA_STALE",
    "DATA_INVALID",
    "WAVE1_ORIGIN_UNAVAILABLE",
    "WAVE1_ORIGIN_PRICE_UNAVAILABLE",
    "WAVE1_ORIGIN_NOT_CONFIRMED",
    "WAVE1_PEAK_UNAVAILABLE",
    "WAVE1_PEAK_PRICE_UNAVAILABLE",
    "WAVE1_PEAK_NOT_CONFIRMED",
    "WAVE2_LOW_UNAVAILABLE",
    "WAVE2_LOW_PRICE_UNAVAILABLE",
    "WAVE2_LOW_NOT_CONFIRMED",
    "SETUP_TYPE_HAS_NO_WAVE3_WAVE1_ANCHOR_CONTRACT",
    "CURRENT_CLOSE_UNAVAILABLE",
    "REFERENCE_DIAGNOSTICS_UNAVAILABLE",
    "CONTINUATION_LOW0_UNAVAILABLE",
    "CONTINUATION_HIGH1_UNAVAILABLE",
    "CONTINUATION_LOW2_UNAVAILABLE",
)
_USER_VISIBLE_INTERNAL_FIELD_NAMES = (
    "planned_entry",
    "execution_stop",
    "entry_zone_low",
    "entry_zone_high",
    "target_candidates",
    "target_upside_pct",
    "minimum_target_upside_pct",
    "gate_reason",
    "current_close",
    "confirmation_level",
    "distance_to_confirmation_pct",
    "structural_invalidation",
    "wave3_fib_extensions",
    "wave3_projection_status",
    "reference_target",
    "reference_t1",
    "reference_t1_source",
    "reference_t1_upside_pct",
    "reference_t1_label",
    "reference_t1_upside_label",
    "reference_first_rr",
    "missing_reasons",
    "current_effective_t1",
    "effective_t1_source",
    "target_projection",
)
_USER_VISIBLE_UNNECESSARY_ENGLISH = (
    "Wave3",
    "Wave2",
    "Wave1",
    "Wave5",
    "Fib",
    "Setup",
    "Decision",
    "Gate",
    "Formal",
    "Reference",
    "Current",
    "Missing",
    "Target",
    "Projection",
    "Opportunity",
    "Freshness",
    "Above Entry Zone",
    "ratio",
    "Candidate",
    "included",
    "Seed",
    "Stage A",
    "Stage B",
    "Dashboard",
    "Synthetic Demo",
    "ticker",
    "Position Management",
    "Portfolio Risk",
    "raw JSON",
    "T+1",
    "RR",
)
_USER_VISIBLE_EXCLUDED_TAGS = frozenset({"head", "script", "style", "pre", "code"})
_HTML_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_USER_VISIBLE_EXCLUDED_CLASS_MARKERS = (
    "developer",
    "technical",
    "audit",
    "raw-data",
    "raw-evidence",
)


class _VisibleTextParser(HTMLParser):
    """Collect ordinary page text while skipping developer/audit evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[bool] = []

    @property
    def _excluded(self) -> bool:
        return any(self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set(_text(attributes.get("class")).split())
        excluded = (
            self._excluded
            or tag.lower() in _USER_VISIBLE_EXCLUDED_TAGS
            or any(
                marker in class_name.lower()
                for class_name in classes
                for marker in _USER_VISIBLE_EXCLUDED_CLASS_MARKERS
            )
        )
        if tag.lower() not in _HTML_VOID_TAGS:
            self._stack.append(excluded)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._excluded and data.strip():
            self.parts.append(data)


def _visible_html_text(value: str) -> tuple[str, ...]:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return tuple(part.strip() for part in parser.parts if part.strip())


def _count_visible_tokens(text: str, tokens: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    matches: list[str] = []
    for token in tokens:
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", re.IGNORECASE)
        matches.extend(pattern.findall(text))
    return len(matches), tuple(matches)


def user_visible_language_audit(value: str) -> dict[str, Any]:
    """Audit ordinary HTML copy without counting developer/audit evidence."""

    visible_parts = _visible_html_text(value)
    visible_text = " ".join(visible_parts)
    raw_enum_count, raw_enum_matches = _count_visible_tokens(
        visible_text, _USER_VISIBLE_RAW_ENUM_TOKENS
    )
    internal_field_count, internal_field_matches = _count_visible_tokens(
        visible_text, _USER_VISIBLE_INTERNAL_FIELD_NAMES
    )
    unnecessary_count, unnecessary_matches = _count_visible_tokens(
        visible_text, _USER_VISIBLE_UNNECESSARY_ENGLISH
    )
    mixed_language_count = sum(
        1
        for part in visible_parts
        if re.search(r"[\u4e00-\u9fff]", part)
        and _count_visible_tokens(part, _USER_VISIBLE_UNNECESSARY_ENGLISH)[0] > 0
    )
    allowed_counts = {
        token: _count_visible_tokens(visible_text, (token,))[0]
        for token in USER_VISIBLE_ALLOWED_ABBREVIATIONS
    }
    return {
        "audit_name": USER_VISIBLE_LANGUAGE_AUDIT,
        "user_visible_raw_enum_count": raw_enum_count,
        "user_visible_internal_field_count": internal_field_count,
        "user_visible_unnecessary_english_count": unnecessary_count,
        "user_visible_mixed_language_count": mixed_language_count,
        "user_visible_allowed_abbreviation_count": sum(allowed_counts.values()),
        "allowed_abbreviations": list(USER_VISIBLE_ALLOWED_ABBREVIATIONS),
        "user_visible_allowed_abbreviation_counts": allowed_counts,
        "raw_enum_matches": list(raw_enum_matches),
        "internal_field_matches": list(internal_field_matches),
        "unnecessary_english_matches": list(unnecessary_matches),
        "passed": not any((raw_enum_count, internal_field_count, unnecessary_count, mixed_language_count)),
    }


def html_consistency_audit(value: Any) -> dict[str, Any]:
    """Run the HTML consistency audit for a rendered page or dashboard payload."""

    rendered = value if isinstance(value, str) else render_dashboard_html(value)
    language = user_visible_language_audit(rendered)
    return {
        "audit_name": USER_VISIBLE_LANGUAGE_AUDIT,
        "USER_VISIBLE_LANGUAGE_AUDIT": language,
        **language,
    }


_CONSISTENCY_MATRIX_STAGES = (
    "WATCH",
    "ARMED",
    "CONFIRMED",
    "STRATEGY_PROPOSAL",
    "ENTRY_ALLOWED",
    "DATA_BLOCKED",
)
_CONSISTENCY_MATRIX_GATES = (
    "ABOVE_ENTRY_ZONE",
    "TARGET_UPSIDE_BELOW_MINIMUM",
    "RR_BELOW_MINIMUM",
    "NO_VALID_TARGET",
    "INVALID_STRUCTURE",
    "ATR_UNAVAILABLE",
    "ENTRY_ALLOWED",
)
_CONSISTENCY_MATRIX_METRICS = (
    "missing_current_price",
    "missing_confirmation",
    "missing_structural_risk",
    "missing_wave3_projection",
    "missing_reference_or_formal_t1",
    "missing_reference_or_formal_rr",
    "duplicate_summary",
    "raw_enum_leak",
    "unnecessary_english",
    "wrong_setup_missing_reason",
)


def daily_report_consistency_matrix(value: Any) -> dict[str, Any]:
    """Audit the rendered daily report by market/setup/stage/gate.

    This is a presentation regression gate.  It reads the already-produced
    result fields and never evaluates a setup or creates a target.
    """

    payload = _as_payload(value)
    projection = build_dashboard_projection(payload)
    rows = tuple(projection.get("rows", ()))
    rendered = render_dashboard_html(payload)
    language = user_visible_language_audit(rendered)
    cases: list[dict[str, Any]] = []

    def metrics_for(row: Mapping[str, Any], setup: str) -> dict[str, int]:
        stage = _text(row.get("stage_key"))
        decision = _mapping(row.get("decision"))
        manual = _mapping(row.get("manual_opportunity"))
        armed = _mapping(row.get("armed_opportunity"))
        diagnostics = _mapping(manual.get("reference_target_diagnostics"))
        wave_extensions = _sequence(manual.get("wave3_extensions"))
        wave_missing = _sequence(manual.get("wave3_missing_reasons"))
        formal_t1 = _numeric(manual.get("formal_t1"))
        formal_rr = _numeric(manual.get("first_rr"))
        gate = _text(decision.get("gate_reason"))
        if stage in {"WATCH", "ARMED"}:
            current_price = _numeric(armed.get("current_close"))
            confirmation = _numeric(armed.get("confirmation_level"))
            structural = _numeric(armed.get("structural_invalidation"))
            missing_wave = not wave_extensions and not wave_missing
        else:
            current_price = _numeric(manual.get("reference_price"))
            confirmation = _numeric(manual.get("confirmation_level"))
            structural = _numeric(manual.get("structural_invalidation"))
            missing_wave = (
                stage in {"CONFIRMED", "STRATEGY_PROPOSAL", "ENTRY_ALLOWED"}
                and setup in {"SETUP_01", "SETUP_02"}
                and not wave_extensions
                and not wave_missing
            )
        reference_t1 = _numeric(diagnostics.get("reference_t1"))
        reference_rr = _numeric(diagnostics.get("reference_first_rr"))
        expects_formal = gate in {
            "TARGET_UPSIDE_BELOW_MINIMUM",
            "RR_BELOW_MINIMUM",
            "ENTRY_ALLOWED",
        }
        expects_reference = gate == "ABOVE_ENTRY_ZONE"
        wrong_reason = (
            setup == "SETUP_02"
            and stage in {"WATCH", "ARMED"}
            and any(
                _text(reason) == "SETUP_TYPE_HAS_NO_WAVE3_WAVE1_ANCHOR_CONTRACT"
                for reason in wave_missing
            )
        )
        return {
            "missing_current_price": int(current_price is None and not row.get("data_blocked")),
            "missing_confirmation": int(confirmation is None and not row.get("data_blocked")),
            "missing_structural_risk": int(structural is None and not row.get("data_blocked")),
            "missing_wave3_projection": int(missing_wave),
            "missing_reference_or_formal_t1": int(
                (expects_reference and (reference_t1 is None or _text(diagnostics.get("status")) != "AVAILABLE"))
                or (expects_formal and formal_t1 is None)
            ),
            "missing_reference_or_formal_rr": int(
                (expects_reference and (reference_rr is None or _text(diagnostics.get("status")) != "AVAILABLE"))
                or (expects_formal and formal_rr is None)
            ),
            # A row must have either the legacy compact plan or the human
            # compact opportunity summary, never both.
            "duplicate_summary": int(
                bool(_compact_price(row)) and bool(_compact_human_opportunity(row))
            ),
            "raw_enum_leak": language["user_visible_raw_enum_count"],
            "unnecessary_english": language["user_visible_unnecessary_english_count"],
            "wrong_setup_missing_reason": int(wrong_reason),
        }

    for row in rows:
        setup_values = tuple(
            setup
            for setup in ("SETUP_01", "SETUP_02")
            if setup in _text(row.get("setup"))
            or setup in {
                _text(row.get("decision", {}).get("event_identity"))
                if isinstance(row.get("decision"), Mapping)
                else "",
            }
        )
        if not setup_values:
            continue
        stage = _text(row.get("stage_key"))
        if stage not in _CONSISTENCY_MATRIX_STAGES:
            continue
        decision = _mapping(row.get("decision"))
        gate = _text(decision.get("gate_reason")) or (
            "ENTRY_ALLOWED" if stage == "ENTRY_ALLOWED" else ""
        )
        if gate not in _CONSISTENCY_MATRIX_GATES:
            gate = "UNSPECIFIED"
        for setup in setup_values:
            metrics = metrics_for(row, setup)
            cases.append({
                "market": _normalised_market(row.get("market")) or "UNKNOWN",
                "setup": setup,
                "stage": stage,
                "gate": gate,
                "count": 1,
                **metrics,
            })

    totals = {metric: sum(item[metric] for item in cases) for metric in _CONSISTENCY_MATRIX_METRICS}
    totals["count"] = sum(item["count"] for item in cases)
    failures = [
        item for item in cases
        if any(item[metric] for metric in _CONSISTENCY_MATRIX_METRICS)
    ]
    return {
        "matrix_name": "DAILY_REPORT_CONSISTENCY_MATRIX_V1",
        "markets": ["CN", "US"],
        "setups": ["SETUP_01", "SETUP_02"],
        "stages": list(_CONSISTENCY_MATRIX_STAGES),
        "gates": list(_CONSISTENCY_MATRIX_GATES),
        "metrics": list(_CONSISTENCY_MATRIX_METRICS),
        "cases": cases,
        "totals": totals,
        "failed_case_count": len(failures),
        "passed": not failures,
        "language_audit": language,
    }


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
        ("第一目标 T1｜当前正式目标（保持规则与 R/R）", plan.get("effective_t1", plan.get("target_1"))),
        ("第一目标 T1 来源", plan.get("effective_t1_source_label")),
        ("第二目标 T2", plan.get("target_2")),
        ("第三目标 T3", plan.get("target_3")),
        ("保守第一障碍（最近已确认历史阻力）", plan.get("nearest_overhead_confirmed_swing_high")),
        ("保守第一障碍上涨空间", plan.get("overhead_resistance_upside_pct")),
        ("3浪结构目标（最近斐波那契投射）", plan.get("nearest_wave3_fib_extension")),
        ("3浪结构目标比例", plan.get("nearest_wave3_fib_extension_ratio")),
        ("3浪结构目标上涨空间", plan.get("wave3_fib_upside_pct")),
        ("后续3浪结构目标", plan.get("wave3_fib_extensions")),
        ("第一目标上涨空间", plan.get("target_upside_pct")),
        ("空间评价", plan.get("target_upside_band")),
        ("系统最低上涨要求", plan.get("minimum_target_upside_pct")),
        ("第一目标 R/R", _first_rr_text(plan.get("rr"))),
    )
    field_grid = _render_field_grid(fields, extra_class="plan-grid")
    if not field_grid:
        return ""
    return (
        '<section class="panel plan-panel"><h3>关键价格</h3>'
        + field_grid
        + (
            f'<p class="target-explanation">{_escape(plan.get("target_boundary_explanation"))}</p>'
            if _has_display_value(plan.get("target_boundary_explanation"))
            else ""
        )
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
                ("最高浮盈", "mfe_r"),
                ("最大不利", "mae_r"),
                ("最高浮盈回撤", "mfe_drawdown_r"),
                ("持有／退出原因", "management_reason"),
                ("现在要做什么", "action_label"),
            )
        )
    )
    if not field_grid:
        return ""
    return (
        '<section class="panel position-panel"><h3>策略跟踪持仓管理</h3>'
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
    if stage == "ARMED":
        armed = _mapping(row.get("armed_opportunity"))
        if armed.get("status") != "AVAILABLE":
            return "观察中 · 数据不足，不猜测"
        return (
            f"现价：{_display(armed.get('current_close_display'))} · "
            f"距确认：{_display(armed.get('distance_to_confirmation_pct_display'))}"
        )
    return ""


def _compact_position(row: Mapping[str, Any]) -> str:
    position = _mapping(row.get("position"))
    values = []
    for label, key in (("当前", "current_r"), ("最高浮盈", "mfe_r"), ("最大不利", "mae_r")):
        if _has_display_value(position.get(key)):
            values.append(f"{label} {_display(position.get(key))}")
    return "策略跟踪持仓管理：" + " · ".join(values) if values else "策略跟踪持仓中"


def _human_upside(value: Any, default: str = "未提供") -> str:
    if _numeric(value) is None:
        return default
    return _format_percent(value, default=default, signed=True)


def _render_human_glance(row: Mapping[str, Any]) -> str:
    manual = _mapping(row.get("manual_opportunity"))
    if not manual.get("available"):
        return ""
    stage = _text(manual.get("stage"))
    primary = _primary_wave3_extension(manual.get("wave3_extensions"))
    if stage in {"WATCH", "ARMED"}:
        wave_text = (
            f"{_format_human_price(primary.get('price'))} / {_human_upside(primary.get('upside_pct'))}"
            if primary
            else (_wave3_missing_text(manual.get("wave3_missing_reasons")) or "待补齐结构锚点")
        )
        metrics = (
            ("距确认", _human_upside(manual.get("distance_to_confirmation_pct"))),
            ("结构风险", _human_upside(manual.get("structural_risk_pct"))),
            ("预计入场区", _format_human_price_range(manual.get("entry_zone_low"), manual.get("entry_zone_high"))),
            ("3浪目标", wave_text),
        )
        chip = "等待确认" if stage == "ARMED" else "观察中"
        chip_class = "near" if stage == "ARMED" else ""
    else:
        metrics = (
            ("当前/参考价", _format_human_price(manual.get("reference_price"))),
            (
                "3浪1.618 / 上涨空间",
                f"{_format_human_price(primary.get('price'))} / {_human_upside(primary.get('upside_pct'))}"
                if primary
                else (_wave3_missing_text(manual.get("wave3_missing_reasons")) or "未生成"),
            ),
            ("结构风险", _human_upside(manual.get("structural_risk_pct"))),
            ("系统结论", _text(manual.get("system_conclusion"), "未形成")),
        )
        chip = "已确认"
        chip_class = "confirmed" if _decision_action(_mapping(row.get("decision"))) == "ENTRY_ALLOWED" else "blocked"
    return (
        '<div class="human-glance"><div class="human-glance-title">人工查看要点 '
        f'<span class="human-chip {chip_class}">{_escape(chip)}</span></div>'
        '<div class="human-metrics">'
        + "".join(
            f'<div class="human-metric"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
            for label, value in metrics
        )
        + "</div></div>"
    )


def _render_wave_target_cards(manual: Mapping[str, Any]) -> str:
    items = tuple(_mapping(item) for item in _sequence(manual.get("wave3_targets")))
    cards = []
    for item in items:
        price = item.get("price")
        ratio = _text(item.get("label"), "3浪目标")
        classes = "wave-target primary" if _bool(item.get("primary")) else "wave-target"
        cards.append(
            f'<div class="{classes}"><div class="ratio">{_escape(ratio)}</div>'
            f'<div class="price">{_escape(_format_human_price(price))}</div>'
            f'<div class="upside">较参考价 {_escape(_human_upside(item.get("upside_pct")))}</div></div>'
        )
    if not cards:
        missing = _text(manual.get("wave3_missing_text"), "正式结果未提供可消费的3浪目标投影")
        cards.append(
            '<div class="wave-target missing primary"><div class="ratio">3浪目标</div>'
            f'<div class="price">未生成：{_escape(missing)}</div>'
            '<div class="upside">不能在展示层重新推算</div></div>'
        )
    return '<div class="wave-target-grid">' + "".join(cards) + "</div>"


def _render_reference_target_diagnostics(manual: Mapping[str, Any]) -> str:
    diagnostics = _mapping(manual.get("reference_target_diagnostics"))
    if not diagnostics:
        return ""
    note = _text(
        diagnostics.get("note"),
        "正式系统已在超过允许入场区处判定不交易，以下数值仅供人工判断，不参与正式系统放行。",
    )
    if _text(diagnostics.get("status")) != "AVAILABLE":
        missing = _wave3_missing_text(diagnostics.get("missing_reasons")) or "参考目标诊断暂不可用"
        return (
            '<section class="reference-target-diagnostics">'
            '<h4>参考目标诊断（仅供人工判断）</h4>'
            f'<p>当前无法形成参考第一目标：{_escape(missing)}</p>'
            f'<p class="wave-target-note">{_escape(note)}</p>'
            '</section>'
        )
    source = _target_source_label(diagnostics.get("reference_t1_source"))
    fields = (
        ("参考第一目标 T1", _format_human_price(diagnostics.get("reference_t1"))),
        ("参考目标来源", source),
        ("参考上涨空间", _human_upside(diagnostics.get("reference_t1_upside_pct"))),
        ("参考第一目标盈亏比 R/R", _format_number(diagnostics.get("reference_first_rr"), 2)),
    )
    return (
        '<section class="reference-target-diagnostics">'
        '<h4>参考目标诊断（仅供人工判断）</h4>'
        '<div class="focus-grid">'
        + "".join(
            f'<div class="focus-field emphasis"><div class="focus-label">{_escape(label)}</div>'
            f'<div class="focus-value">{_escape(value)}</div></div>'
            for label, value in fields
        )
        + '</div>'
        f'<p class="wave-target-note">{_escape(note)}</p>'
        '</section>'
    )


def _render_manual_opportunity(row: Mapping[str, Any]) -> str:
    manual = _mapping(row.get("manual_opportunity"))
    if not manual.get("available"):
        return ""
    stage = _text(manual.get("stage"))
    is_estimate = _bool(manual.get("wave3_is_estimate"))
    wave3_presentation_only = _bool(manual.get("wave3_presentation_only"))
    reference_label = _text(manual.get("reference_label"), "当前价")
    reference_price = _format_human_price(manual.get("reference_price"))
    confirmation = _format_human_price(manual.get("confirmation_level"))
    entry_zone = _format_human_price_range(
        manual.get("entry_zone_low"), manual.get("entry_zone_high")
    )
    invalidation = _format_human_price(manual.get("structural_invalidation"))
    risk_pct = _human_upside(manual.get("structural_risk_pct"))
    if is_estimate:
        distance_pct = _human_upside(manual.get("distance_to_confirmation_pct"))
        lead = (
            f"离确认只差 {distance_pct}。先判断这只股票值不值得打开图表，而不是先看系统会不会自动放行。"
            if _numeric(manual.get("distance_to_confirmation_pct")) is not None
            else "先判断这只股票值不值得打开图表，而不是先看系统会不会自动放行。"
        )
        confirmation_sub = f"距确认 {distance_pct}"
        entry_sub = "按当前 ATR14，仅用于观察"
        heading = "预估3浪目标与上涨空间"
    else:
        lead = "先看潜在空间，再看正式规则为什么放行或拒绝。系统判定不交易，不代表这只股票没有人工观察价值。"
        confirmation_sub = ""
        entry_sub = "正式判断已生成"
        heading = (
            "3浪结构目标 / 人工机会空间"
            if wave3_presentation_only
            else "3浪目标与潜在上涨空间"
        )
    target_gap = _text(manual.get("wave3_missing_text"))
    gap_html = (
        f'<div class="prototype-data-gap">当前缺少：{_escape(target_gap)}；因此暂不能可靠计算3浪目标。'
        "展示层不会从价格倒推结构锚点。</div>"
        if target_gap and not manual.get("wave3_targets")
        else ""
    )
    return (
        '<section class="panel manual-opportunity-panel decision-focus">'
        '<h3>人工机会判断</h3>'
        f'<p class="lead"><b>{_escape(lead)}</b></p>'
        '<div class="manual-grid">'
        f'<div class="manual-cell"><div class="label">{_escape(reference_label)}</div>'
        f'<div class="value">{_escape(reference_price)}</div></div>'
        '<div class="manual-cell"><div class="label">确认价</div>'
        f'<div class="value">{_escape(confirmation)}</div>'
        + (f'<div class="sub">{_escape(confirmation_sub)}</div>' if confirmation_sub else "")
        + '</div>'
        '<div class="manual-cell"><div class="label">'
        + _escape("预计入场区" if is_estimate else "正式入场区")
        + '</div>'
        f'<div class="value">{_escape(entry_zone)}</div><div class="sub">{_escape(entry_sub)}</div></div>'
        '<div class="manual-cell"><div class="label">结构失效价</div>'
        f'<div class="value">{_escape(invalidation)}</div><div class="sub">较参考价 {_escape(risk_pct)}</div></div>'
        '</div>'
        '<div class="wave-target-section">'
        f'<h4>{_escape(heading)}</h4>'
        + (
            '<p class="wave-target-note">以下为人工机会空间，不等同正式第一至第三目标；正式系统仍按规则结论执行。</p>'
            if wave3_presentation_only
            else ""
        )
        + _render_wave_target_cards(manual)
        + gap_html
        + '</div>'
        + _render_reference_target_diagnostics(manual)
        + f'<div class="system-gate-line"><strong>正式系统结论：</strong>{_escape(manual.get("system_conclusion"))}</div>'
        + f'<div class="next-action-line"><b>人工下一步：</b>{_escape(manual.get("next_action"))}</div>'
        '</section>'
    )


def _formal_field_value(value: Any, reason: str) -> str:
    if _has_display_value(value):
        return _raw_text(value)
    return f"未生成；{reason}"


def _render_confirmed_decision(row: Mapping[str, Any]) -> str:
    manual = _mapping(row.get("manual_opportunity"))
    if not manual.get("available") or not manual.get("formal_decision"):
        return ""
    plan = _mapping(row.get("plan"))
    decision = _mapping(row.get("decision"))
    gate_reason = _text(manual.get("gate_reason"), "正式规则未通过")
    conclusion = (
        manual.get("system_conclusion")
        if gate_reason == "ABOVE_ENTRY_ZONE"
        else _text(row.get("waiting"), manual.get("system_conclusion"))
    )
    conclusion_class = "allowed" if _decision_action(decision) == "ENTRY_ALLOWED" else "blocked"
    label = {
        "ABOVE_ENTRY_ZONE": "超过允许入场区",
        "TARGET_UPSIDE_BELOW_MINIMUM": "第一目标上涨空间不足",
        "RR_BELOW_MINIMUM": "R/R 不足",
        "NO_VALID_TARGET": "没有有效第一目标",
        "ENTRY_ALLOWED": "正式条件满足",
    }.get(gate_reason, _translate_reason(gate_reason) or "正式规则未通过")
    target_1 = plan.get("target_1")
    if not _has_display_value(target_1):
        target_1 = f"未生成；{_translate_reason(gate_reason) or '正式第一目标未提供'}"
    fields = (
        ("策略", _setup_display(row.get("setup"))),
        ("确认价", plan.get("confirmation_level")),
        ("参考入场", plan.get("planned_entry")),
        ("允许入场区", _entry_zone_text(plan) or f"未生成；{_translate_reason(gate_reason) or '缺少正式入场区'}"),
        ("执行止损", plan.get("execution_stop")),
        ("第一目标 T1", target_1),
        ("T1 上涨空间", plan.get("target_upside_pct")),
        ("第一目标 R/R", _first_rr_text(plan.get("rr")) or f"未生成；{_translate_reason(gate_reason) or '缺少 R/R'}"),
        ("结构失效", plan.get("structural_invalidation") or _format_price(decision.get("structural_invalidation"))),
    )
    emphasis = {"确认价", "允许入场区", "第一目标 T1", "T1 上涨空间", "第一目标 R/R"}
    grid = ''.join(
        f'<div class="focus-field {"emphasis" if label_name in emphasis else ""}">'
        f'<div class="focus-label">{_escape(label_name)}</div>'
        f'<div class="focus-value">{_escape(_formal_field_value(value, _translate_reason(gate_reason) or "正式字段未提供"))}</div></div>'
        for label_name, value in fields
    )
    note = (
        "确认有效，但第一目标对应的 R/R 未达到系统最低要求，因此不交易。"
        if gate_reason == "RR_BELOW_MINIMUM"
        else "确认有效，但第一目标剩余上涨空间不足最低要求，因此不交易。"
        if gate_reason == "TARGET_UPSIDE_BELOW_MINIMUM"
        else manual.get("system_conclusion")
    )
    return (
        '<section class="panel decision-focus confirmed-focus"><h3>确认后的交易判断</h3>'
        f'<div class="focus-conclusion {conclusion_class}"><strong>{_escape(conclusion)}</strong>'
        f'<span>{_escape(label)}</span></div>'
        f'<div class="focus-grid">{grid}</div>'
        f'<p class="focus-note">{_escape(note)}</p></section>'
    )


def _render_logic_summary(row: Mapping[str, Any]) -> str:
    return (
        '<details class="logic-summary"><summary>结构与判断依据（展开）</summary><div class="logic-grid">'
        f'<section><h3>当前浪型</h3><p>{_escape(row.get("current_wave_label"))}</p></section>'
        f'<section><h3>所属策略</h3><p>{_escape(_setup_display(row.get("setup")))}</p></section>'
        f'<section><h3>已满足条件 / 现有依据</h3><p>{_escape(_satisfied_condition_text(row))}</p></section>'
        f'<section><h3>未满足条件 / 不交易原因</h3><p>{_escape(_unsatisfied_condition_text(row))}</p></section>'
        f'<section><h3>为什么</h3><p>{_escape(row.get("why"))}</p></section>'
        f'<section><h3>还差什么 / 现在要做什么</h3><p>{_escape(row.get("missing_condition"))}</p></section>'
        f'<section><h3>失效条件</h3><p>{_escape(row.get("invalidation"))}</p></section>'
        f'<section><h3>备选情景</h3><p>{_escape(row.get("alternate_wave_label"))}</p></section>'
        '</div></details>'
    )


def _render_opportunity_freshness(row: Mapping[str, Any]) -> str:
    """Render causal freshness facts in the human-readable detail view."""

    freshness = _mapping(row.get("opportunity_freshness"))
    if not freshness:
        return ""
    plan = _mapping(row.get("plan"))
    bullets: list[str] = []
    distance = _numeric(freshness.get("entry_zone_upper_distance_pct"))
    if distance is not None:
        if distance > 0:
            bullets.append(
                f"已超过允许入场区上沿 {_format_percent(abs(distance))}，本次机会已过度延伸，不追"
            )
        else:
            bullets.append("尚在允许入场区内")
    target_upside = _numeric(freshness.get("target_upside_pct"))
    minimum = _numeric(freshness.get("minimum_target_upside_pct"))
    band = _text(freshness.get("target_upside_band"))
    if target_upside is not None:
        if band == "BELOW_MINIMUM":
            bullets.append(
                "结构确认有效，但第一目标只剩 "
                f"{_format_percent(target_upside)}，低于 "
                f"{_format_percent(minimum)} 最低要求，目标空间不足，本次不交易"
            )
            bullets.append(
                f"参考价格：{_display(plan.get('planned_entry'))}；第一目标候选：{_display(plan.get('target_1'))}；"
                f"第一目标盈亏比 R/R：{_first_rr_text(plan.get('rr'))}"
            )
            if plan.get("has_target_projection"):
                bullets.append(
                    "当前正式 T1："
                    f"{_display(plan.get('effective_t1'))}；来源："
                    f"{_display(plan.get('effective_t1_source_label'))}"
                )
                if _has_display_value(plan.get("nearest_overhead_confirmed_swing_high")):
                    bullets.append(
                        "保守第一障碍（最近已确认历史阻力）："
                        f"{_display(plan.get('nearest_overhead_confirmed_swing_high'))}；"
                        f"上涨空间：{_display(plan.get('overhead_resistance_upside_pct'))}"
                    )
                if _has_display_value(plan.get("nearest_wave3_fib_extension")):
                    bullets.append(
                    "3浪结构目标（最近斐波那契投射）："
                        f"{_display(plan.get('nearest_wave3_fib_extension'))}；"
                        f"比例：{_display(plan.get('nearest_wave3_fib_extension_ratio'))}；"
                        f"上涨空间：{_display(plan.get('wave3_fib_upside_pct'))}"
                    )
                if _has_display_value(plan.get("wave3_fib_extensions")):
                    bullets.append(
                        "后续3浪结构目标："
                        f"{_display(plan.get('wave3_fib_extensions'))}"
                    )
            explanation = _text(plan.get("target_boundary_explanation"))
            if explanation:
                bullets.append(explanation + "；所以按现有保守规则不交易。")
            bullets.append("这些是 Decision gate 计算依据，不是买入/止盈建议")
        elif band == "LOW_UPSIDE":
            bullets.append(
                f"第一目标剩余空间：{_format_percent(target_upside)}；偏小，但达到最低交易门槛"
            )
        elif band == "PREFERRED_UPSIDE":
            bullets.append(
                f"第一目标剩余空间：{_format_percent(target_upside)}；空间较充足"
            )
        else:
            bullets.append(f"第一目标剩余空间：{_format_percent(target_upside)}")
    remaining = _numeric(freshness.get("remaining_target_upside_pct"))
    if remaining is not None:
        bullets.append(
            f"下一交易日实际开盘后第一目标剩余空间：{_format_percent(remaining)}"
        )
    outcome = _text(_mapping(row.get("raw_result")).get("execution_outcome"))
    if outcome == "SKIP_TARGET_UPSIDE_BELOW_MINIMUM":
        bullets.append("下一交易日剩余第一目标空间低于5%，已跳过，不追入")
    elif outcome in {
        "SKIP_GAP_BELOW_CONFIRMATION",
        "SKIP_GAP_ABOVE_ENTRY_ZONE",
    }:
        bullets.append("下一交易日开盘发生跳空，已按原有执行规则跳过")
    elif row.get("stage_key") in {"STRATEGY_PROPOSAL", "ENTRY_ALLOWED"}:
        bullets.append("下一交易日若高开，将重新检查剩余空间")
    if not bullets:
        return ""
    return (
        '<section class="panel opportunity-panel"><h3>机会新鲜度</h3>'
        "<ul>"
        + "".join(f"<li>{_escape(item)}</li>" for item in bullets)
        + "</ul></section>"
    )


def _render_armed_opportunity(row: Mapping[str, Any]) -> str:
    if row.get("stage_key") not in {"WATCH", "ARMED"}:
        return ""
    armed = _mapping(row.get("armed_opportunity"))
    title = "现在最重要的信息" if row.get("stage_key") == "ARMED" else "当前观察条件"
    if not armed:
        return (
            f'<section class="panel opportunity-panel"><h3>{_escape(title)}</h3>'
            '<p>观察中，不是买入信号。缺少 causal 机会投影，不能猜测价格条件。</p></section>'
        )
    if armed.get("status") != "AVAILABLE":
        reasons = _wave3_missing_text(armed.get("missing_reasons"))
        return (
            f'<section class="panel opportunity-panel"><h3>{_escape(title)}</h3>'
            '<p>当前结构尚未形成可量化机会；观察状态不代表可以买入。</p>'
            f'<p>缺少：{_escape(reasons or "机会投影字段不完整")}</p>'
            '<p>下一步：等待结构确认或补齐因果锚点。</p></section>'
        )
    entry_zone = (
        f"{armed.get('expected_entry_zone_low_display')} – "
        f"{armed.get('expected_entry_zone_high_display')}"
    )
    return (
        f'<section class="panel opportunity-panel"><h3>{_escape(title)}</h3>'
        '<p><strong>观察中，不是买入信号</strong></p>'
        + _render_field_grid(
            (
                ("阶段", _state_display(armed.get("state"), STAGE_LABELS.get(row.get("stage_key"), "未提供"))),
                ("策略类型", _setup_display(armed.get("setup_type"))),
                ("当前收盘价", armed.get("current_close_display")),
                ("确认价", armed.get("confirmation_level_display")),
                ("距确认价", armed.get("distance_to_confirmation_display")),
                ("距确认百分比", armed.get("distance_to_confirmation_pct_display")),
                ("当前 ATR14", armed.get("atr14_display")),
                ("预计入场区（按当前 ATR14，仅供观察）", entry_zone),
                ("结构失效价", armed.get("structural_invalidation_display")),
                *(
                    (("延续结构锚点", _continuation_anchor_text(armed.get("continuation_anchors"))),)
                    if _text(armed.get("setup_type")) == "SETUP_02"
                    else ()
                ),
            ),
            extra_class="plan-grid",
        )
        + (
            '<p class="prototype-data-gap">当前缺少：'
            + _escape(_wave3_missing_text(armed.get("wave3_missing_reasons")))
            + '；因此不能在观察层可靠计算3浪目标。</p>'
            if _text(armed.get("wave3_projection_status")) == "DATA_UNAVAILABLE"
            else ""
        )
        + f'<p>{_escape(_humanize_user_text(armed.get("guidance"), "继续观察，等待结构确认。"))}</p></section>'
    )


def _dashboard_search_text(row: Mapping[str, Any]) -> str:
    return f'{_raw_text(row.get("symbol"))} {_raw_text(row.get("name"))}'


def dashboard_search_matches(row: Mapping[str, Any], query: Any) -> bool:
    """Return whether a UI search query matches a ticker or company name."""

    needle = _raw_text(query).casefold()
    if not needle:
        return True
    haystack = _dashboard_search_text(row).casefold()
    return needle in haystack


def _condition_values(values: Sequence[Any]) -> str:
    rendered: list[str] = []
    for value in values:
        if isinstance(value, (Mapping, list, tuple)):
            text = _json_text(value)
        else:
            text = _translate_reason(value)
        if text and text not in rendered:
            rendered.append(text)
    return "；".join(rendered)


def _satisfied_condition_text(row: Mapping[str, Any]) -> str:
    result = _mapping(row.get("raw_result"))
    decision = _mapping(row.get("decision"))
    direct_values: list[Any] = []
    for source in (result, decision):
        for key in (
            "satisfied_conditions",
            "met_conditions",
            "passed_conditions",
            "conditions_met",
        ):
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                direct_values.extend(value)
            elif value not in (None, ""):
                direct_values.append(value)
    text = _condition_values(direct_values)
    if text:
        return text
    if str(result.get("data_status") or "").upper() != "DATA_OK":
        return f"数据状态：{_display(result.get('data_status'))}；未完成正式策略计算。"
    facts = []
    wave = _display(row.get("current_wave_label"))
    if wave != "—":
        facts.append(f"当前浪型：{wave}")
    for label, key in (("SETUP_01", "setup01_state"), ("SETUP_02", "setup02_state")):
        state = _text(row.get(key))
        if state and state.upper() not in {"NONE", "—"}:
            facts.append(f"{_setup_display(label)}：{_state_display(state)}")
    if row.get("event_is_new"):
        facts.append("T 日产生新的确认事件")
    why = _text(row.get("why"))
    if why and why not in facts:
        facts.append(f"分析依据：{why}")
    return "；".join(facts) or "本次结果未提供可单列的已满足条件。"


def _unsatisfied_condition_text(row: Mapping[str, Any]) -> str:
    result = _mapping(row.get("raw_result"))
    decision = _mapping(row.get("decision"))
    values: list[Any] = []
    for source in (result, decision):
        for key in (
            "unsatisfied_conditions",
            "missing_conditions",
            "unmet_conditions",
            "blocking_prerequisites",
        ):
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                values.extend(value)
            elif value not in (None, ""):
                values.append(value)
    missing = _text(row.get("missing_condition"))
    if missing and missing not in {"—", "尚未形成"}:
        values.append(missing)
    for value in _sequence(result.get("reasons")):
        values.append(value)
    gate_reason = decision.get("gate_reason")
    if gate_reason:
        values.append(gate_reason)
    text = _condition_values(values)
    if text:
        return text
    if _text(row.get("stage_key")) in {"NO_TRADE", "FAILED", "DATA_BLOCKED"}:
        return "本次结果未提供可单列的不交易原因。"
    return "当前没有额外未满足条件记录。"


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
        + _render_manual_opportunity(row)
        + (
            _render_confirmed_decision(row)
            if row.get("stage_key") == "CONFIRMED"
            else _render_plan(row)
        )
        + _render_armed_opportunity(row)
        + _render_opportunity_freshness(row)
        + (_render_position({**row, "position": position}) if row.get("is_position") else "")
        + _render_logic_summary(row)
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
        '<section><h4>策略跟踪持仓管理（Position Management）</h4>'
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


def _compact_human_opportunity(row: Mapping[str, Any]) -> str:
    manual = _mapping(row.get("manual_opportunity"))
    if not manual.get("available"):
        return ""
    primary = _primary_wave3_extension(manual.get("wave3_extensions"))
    risk = _human_upside(manual.get("structural_risk_pct"))
    if _text(manual.get("stage")) in {"WATCH", "ARMED"}:
        current = _format_human_price(manual.get("reference_price"))
        distance = _human_upside(manual.get("distance_to_confirmation_pct"))
        target = (
            f"3浪1.618 {_format_human_price(primary.get('price'))}（{_human_upside(primary.get('upside_pct'))}）"
            if primary
            else "3浪目标待补结构锚点"
        )
        return f"现价 {current} · 距确认 {distance} · 结构风险 {risk} · {target}"
    reference = _format_human_price(manual.get("reference_price"))
    target = (
        f"3浪1.618 {_format_human_price(primary.get('price'))}（{_human_upside(primary.get('upside_pct'))}）"
        if primary
        else "3浪目标待补结构锚点"
    )
    return f"参考价 {reference} · {target} · 结构风险 {risk}"


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
    human_compact = _compact_human_opportunity(row)
    price_block = (
        f'<span class="row-price">{_escape(compact_plan)}</span>'
        if not human_compact
        else ""
    )
    human_price_block = (
        f'<span class="v3-price row-price">{_escape(human_compact)}</span>'
        if human_compact
        else ""
    )
    return (
        '<article class="stock-row" '
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
        + human_price_block
        + _render_human_glance(row)
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


def _render_opportunity_tracking(projection: Mapping[str, Any]) -> str:
    tracking = _mapping(projection.get("opportunity_tracking"))
    if not tracking:
        return ""
    if tracking.get("status") != "SUCCESS":
        status_label = {
            "FAILED": "数据异常",
            "NOT_RUN": "未运行",
            "SUCCESS": "已完成",
        }.get(_text(tracking.get("status")), "状态未确定")
        return ('<section class="diagnostic-card" aria-label="机会跟踪"><h2>机会跟踪</h2>'
                f'<p>账本状态：{_escape(status_label)}；'
                f'{_escape(_translate_reason(tracking.get("error")) or "诊断报告不写入正式前瞻账本")}</p></section>')
    reasons = '；'.join(f'{_escape(_translate_reason(reason))}：{count}'
                       for reason, count in tracking.get("today_original_reasons", {}).items())
    stats = ''.join(
        '<li>' + _escape(_translate_reason(row["original_reason"]))
        + f'：成熟 {row["matured_count"]}，完整 {row["complete_count"]}，缺口 {row["coverage_gap_count"]}；'
        + f'10日收盘变化均值 {_format_percent(row.get("mean_close_return"), signed=True)}，'
        + f'中位数 {_format_percent(row.get("median_close_return"), signed=True)}；'
        + f'最大有利变化均值 {_format_percent(row.get("mean_max_favorable_move"), signed=True)}，'
        + f'最大不利变化均值 {_format_percent(row.get("mean_max_adverse_move"), signed=True)}；'
        + f'T1触及 {row["T1_touched_count"]}，止损触及 {row["stop_touched_count"]}'
        + ('；样本不足' if row["sample_insufficient"] else '') + '</li>'
        for row in tracking.get("matured_by_original_reason", ()))
    return ('<section class="diagnostic-card" aria-label="机会跟踪"><h2>机会跟踪</h2>'
            f'<p>今日新增观察 {tracking["new_observation_count"]}；{reasons or "无新增"}</p>'
            f'<p>仍在跟踪 {tracking["active_tracking_count"]}；今日完成10个交易日观察 {tracking["completed_today_count"]}；'
            f'今日数据缺口 {tracking.get("coverage_gaps_today", 0)}</p>'
            + ('<p>样本不足，仅作描述统计，不评价参数优劣。</p>' if tracking["sample_insufficient"] else '')
            + '<ul>' + stats + '</ul><p>' + _escape(tracking["description"]) + '</p></section>')


def _render_prospective_observation(projection: Mapping[str, Any]) -> str:
    observation = _mapping(projection.get("prospective_observation"))
    if not observation:
        return ""
    return (
        '<details class="diagnostic-card audit-card" aria-label="前瞻只读观察" data-protocol="'
        + _escape(observation.get("protocol_version")) + '">'
        + '<summary>前瞻只读观察（展开数据审计）</summary><p>'
        + f'正式池 {_escape(observation.get("formal_symbols"))}；动态候选 {_escape(observation.get("dynamic_symbols"))}；'
        + f'重叠 {_escape(observation.get("overlap_symbols"))}；并集 {_escape(observation.get("union_symbols"))}；'
        + f'DATA_OK {_escape(observation.get("data_ok_symbols"))}；DATA_BLOCKED {_escape(observation.get("data_blocked_symbols"))}；'
        + f'首次确认 {_escape(observation.get("first_event_count"))}；Decision {_escape(observation.get("decision_count"))}'
        + '</p></details>'
    )


def _render_diagnostics(projection: Mapping[str, Any]) -> str:
    diagnostics = _mapping(projection.get("diagnostics"))
    status = _text(diagnostics.get("status"), "—")
    status_labels = {
        "DATA_ISSUE": "部分标的无法评估，请分别查看已完成结果与异常",
        "COVERAGE_INSUFFICIENT": "候选覆盖不足，不能据此判断没有机会",
        "NORMAL_NO_SIGNAL": "覆盖已完成，今天没有交易信号",
        "SIGNAL_AVAILABLE": "已完成覆盖，存在已计算信号",
    }
    issues = tuple(_mapping(item) for item in _sequence(diagnostics.get("data_issues")))
    issue_html = "".join(
        f'<li><strong>{_escape(item.get("market"))} · {_escape(item.get("symbol"))}</strong>：{_escape(_translate_reason(item.get("reason")) or "数据异常")}</li>'
        for item in issues
    )
    candidate = _mapping(diagnostics.get("candidate"))
    coverage = _mapping(diagnostics.get("coverage"))
    market_html = []
    for item in _sequence(candidate.get("markets")):
        item = _mapping(item)
        reasons = "；".join(
            f'{_escape(_mapping(reason).get("reason"))}：{_escape(_mapping(reason).get("count"))}'
            for reason in _sequence(item.get("filter_reasons"))
        )
        reason_line = (
            f'<div class="diagnostic-reasons">筛选原因：{reasons}</div>'
            if reasons else ""
        )
        outcome_labels = {
            "CANDIDATES_INCLUDED": "已有候选进入后续分析",
            "NO_CANDIDATES": "Stage A 数据完整，按既有规则筛选后确实没有候选",
            "DISCOVERY_FAILED": "候选发现失败，覆盖不完整",
            "NOT_REPORTED": "候选链路未报告，覆盖不完整",
            "NOT_RUN": "候选链路未运行",
        }
        outcome = _text(item.get("selection_outcome"), "NOT_REPORTED")
        candidate_errors = "；".join(
            _text(error) for error in _sequence(item.get("candidate_errors")) if _text(error)
        )
        scope_line = (
            f'正式策略池 {_escape(item.get("formal_strategy_pool_count"))}；'
            f'动态候选 {_escape(item.get("dynamic_candidate_count"))}（仅动态 {_escape(item.get("dynamic_candidate_only_count"))}）；'
            f'动态候选完成策略分析 {_escape(item.get("dynamic_candidate_analysis_count"))}（仅动态 {_escape(item.get("dynamic_candidate_only_analysis_count"))}）'
        )
        analysis_line = (
            f'策略分析尝试 {_escape(item.get("analysis_attempted_count"))}；'
            f'完成 {_escape(item.get("strategy_analysis_count"))}；'
            f'因数据阻断 {_escape(item.get("analysis_blocked_count"))}'
        )
        market_html.append(
            '<div class="diagnostic-market">'
            f'<strong>{_escape(item.get("label"))}</strong>'
            f'<span>CANDIDATE_STATUS：{_escape(item.get("candidate_status"))}</span>'
            f'<span>候选结论：{_escape(outcome_labels.get(outcome, outcome))}</span>'
            f'<span>Seed {_escape(item.get("seed_count"))} → 数据合格 {_escape(item.get("data_qualified_count"))} → included {_escape(item.get("included_count"))} → 深度分析 {_escape(item.get("deep_analysis_count"))}</span>'
            f'<span>{scope_line}</span>'
            f'<span>{analysis_line}；Stage A {_escape(item.get("stage_a_status"))}；Stage B {_escape(item.get("stage_b_status"))}</span>'
            f'<span>实际日报结果 {_escape(item.get("daily_result_count"))}；DATA_OK {_escape(item.get("data_ok_count"))}；NO_TRADE {_escape(item.get("no_trade_count"))}；数据异常 {_escape(item.get("data_blocked_count"))}</span>'
            f'{reason_line}'
            + (f'<div class="diagnostic-reasons">候选链路异常：{_escape(candidate_errors)}</div>' if candidate_errors else "")
            + '</div>'
        )
    if not market_html:
        market_html.append(
            f'<div class="diagnostic-market">实际日报结果 {_escape(coverage.get("daily_result_count"))}；DATA_OK {_escape(coverage.get("data_ok_count"))}；NO_TRADE {_escape(coverage.get("no_trade_count"))}</div>'
        )
    issue_block = (
        '<details class="diagnostic-issues"><summary>异常标的及原因（展开原始诊断）</summary><ul>'
        + issue_html
        + "</ul></details>"
        if issues else ""
    )
    return (
        f'<section class="diagnostic-panel {"diagnostic-danger" if issues else ""}" aria-label="日报诊断">'
        f'<div class="diagnostic-heading"><h2>覆盖与日报诊断</h2><span>{_escape(status_labels.get(status, "状态未确定"))}</span></div>'
        f'<div class="diagnostic-coverage">候选种子 {_escape(coverage.get("seed_count"))} → 数据合格 {_escape(coverage.get("data_qualified_count"))} → 纳入候选 {_escape(coverage.get("included_count"))}；成功分析 {_escape(projection["summary"]["completed_analysis_count"])}；无法评估 {_escape(projection["summary"]["data_blocked_count"])}</div>'
        + issue_block
        + '<details class="diagnostic-technical"><summary>查看完整覆盖与筛选诊断</summary><div class="diagnostic-markets">'
        + "".join(market_html)
        + "</div></details></section>"
    )


_PAPER_STATUS_LABELS = {
    "PENDING_T1": "等待下一交易日执行",
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
    labels = [f"第{index}目标 T{index}：{_format_price(value)}" for index, value in enumerate(values, start=1)]
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
            ("第一目标上涨空间", _paper_percent(trade.get("target_upside_pct"))),
            ("空间评价", TARGET_UPSIDE_BAND_LABELS.get(_text(trade.get("target_upside_band")), _text(trade.get("target_upside_band")))),
            ("第一目标计划 R/R", _format_rr(trade.get("initial_rr"))),
            ("目标价", targets),
            ("目标规则", "目标价只记录状态，不自动止盈。"),
        )
        next_text = "等待下一交易日开盘，暂不把计划当成已成交。"
    elif status == "OPEN":
        fill_text = (
            f"{_display(trade.get('execution_date'))} 开盘 {_format_price(trade.get('actual_entry'))}，"
            f"已通过下一交易日执行检查；实际第一目标 R/R 为 {actual_rr}，模拟成交已成立。"
        )
        state_fields = (
            ("实际买入价", _format_price(trade.get("actual_entry"))),
            ("当前价格", _format_price(trade.get("current_price"))),
            ("当前收益", _paper_percent(trade.get("current_return_pct"), signed=True)),
            ("当前 R", _format_r(trade.get("current_r"))),
            ("最高浮盈 / 最大不利", f"{_format_r(trade.get('current_mfe'))} / {_format_r(trade.get('current_mae'))}"),
            ("当前保护止损", _format_price(trade.get("current_stop"))),
            ("第一目标上涨空间", _paper_percent(trade.get("target_upside_pct"))),
            ("下一交易日剩余第一目标空间", _paper_percent(trade.get("remaining_target_upside_pct"))),
            ("目标价", targets),
            ("目标状态", _paper_target_status_label(target_status)),
            ("目标规则", "目标价只记录状态，不自动止盈。"),
        )
        next_text = _paper_action_text(trade)
    elif status == "SKIPPED":
        fill_text = f"下一交易日开盘 {_format_price(trade.get('t1_open'))}，没有模拟成交；{_paper_human_text(trade.get('why_execution') or trade.get('skip_reason'))}"
        state_fields = (
            ("计划入场", _format_price(trade.get("planned_entry"))),
            ("下一交易日开盘", _format_price(trade.get("t1_open"))),
            ("下一交易日剩余第一目标空间", _paper_percent(trade.get("remaining_target_upside_pct"))),
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
        next_text = "等待完整的下一交易日或持仓管理记录。"
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
        "target_upside_pct": trade.get("target_upside_pct"),
        "target_upside_band": trade.get("target_upside_band"),
        "minimum_target_upside_pct": trade.get("minimum_target_upside_pct"),
        "entry_zone_upper_distance_pct": trade.get("entry_zone_upper_distance_pct"),
        "confirmation_extension_pct": trade.get("confirmation_extension_pct"),
        "t1_gap_vs_planned_entry_pct": trade.get("t1_gap_vs_planned_entry_pct"),
        "remaining_target_upside_pct": trade.get("remaining_target_upside_pct"),
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
            '<p>未启用前瞻模拟账本。只有显式运行相应模拟跟踪命令才会写入策略模拟账本。</p></div>'
            '</section>'
        )
    performance = _mapping(paper.get("performance"))
    status_counts = _mapping(paper.get("status_counts"))
    metrics = (
        ("计划数", performance.get("plans", status_counts.get("PENDING_T1", 0))),
        ("已执行", performance.get("executed", 0)),
        ("等待下一交易日", status_counts.get("PENDING_T1", 0)),
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
        '<p>前瞻、逐事件、只读生产决策输入；不使用组合盈亏，不产生生产批准或券商订单。</p></div>'
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
        '<h2>今日模拟交易重点</h2><span>等待下一交易日、模拟持仓与今日结束记录</span></div>'
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
        ("模拟持仓", performance.get("open", 0)),
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
    for dimension, label in (("setup", "策略类型"), ("market", "市场"), ("provenance", "来源")):
        buckets = _mapping(grouped.get(dimension))
        cards = []
        for key, stats_value in buckets.items():
            stats = _mapping(stats_value)
            group_label = (
                _paper_source_label(key)
                if dimension == "provenance"
                else _setup_display(key)
                if dimension == "setup"
                else key
            )
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
        '<p>只统计已经结束的模拟交易；未成交方案和模拟持仓不进入胜率分母。</p></div>'
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
        '<p>本页只解释当前已实现的波浪 → 策略类型 → 正式判断 → 下一交易日 → 策略跟踪持仓管理规则。</p></div>'
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
        ("ARMED", "机会观察", summary["armed_count"]),
        ("WATCH", "观察中", summary["watch_count"]),
        ("confirmed", "新确认", summary["new_confirmed_count"]),
        ("STRATEGY_PROPOSAL", "交易方案", summary["strategy_proposal_count"]),
        ("ENTRY_ALLOWED", "可入场", summary["entry_allowed_count"]),
        ("POSITION_MANAGEMENT", "策略跟踪持仓", summary["position_count"]),
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
        "PARTIAL_DATA_QUALITY": "部分标的无法评估；已完成分析的结果仍可查看，异常标的不得用于交易",
        "FAILED": "报告存在核心评估异常；以下已完成结果仅供复核，本次运行未通过验收",
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
.summary-primary {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; margin:12px 0 7px; }} .summary-secondary {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 9px; }}
.metric {{ appearance:none; background:var(--card); border:1px solid var(--line); border-radius:11px; padding:10px 12px; min-height:66px; color:var(--ink); text-align:left; }} .metric-link {{ cursor:pointer; font:inherit; }} .metric-link:hover {{ border-color:#8ca9c2; box-shadow:0 3px 10px #18324b12; }}
.metric-label,.field-label {{ color:var(--muted); font-size:12px; }} .metric-value {{ display:block; margin-top:3px; font-size:23px; line-height:1.1; font-weight:750; }} .summary-primary .metric:nth-child(1) .metric-value,.summary-primary .metric:nth-child(2) .metric-value {{ color:var(--teal); }} .summary-primary .metric:nth-child(6) .metric-value {{ color:var(--red); }}
.summary-secondary .metric {{ min-height:48px; padding:8px 12px; display:flex; align-items:center; gap:10px; }} .summary-secondary .metric-value {{ margin:0; font-size:20px; }}
.diagnostic-issues > summary,.diagnostic-technical > summary,.diagnostic-card > summary {{ cursor:pointer; min-height:44px; padding:10px 0; font-size:13px; color:var(--blue); font-weight:700; }}
.market-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-bottom:8px; }} .market-card {{ background:#fff; border:1px solid var(--line); border-radius:11px; padding:8px 13px; display:flex; justify-content:space-between; align-items:center; }} .diagnostic-panel {{ background:#fff; border:1px solid var(--line); border-radius:11px; padding:11px 13px; margin:0 0 10px; }} .diagnostic-danger {{ border-color:#efb4b4; background:#fffafa; }} .diagnostic-heading {{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; }} .diagnostic-heading h2 {{ margin:0; font-size:16px; }} .diagnostic-heading span {{ color:var(--muted); font-size:12px; }} .diagnostic-coverage {{ margin-top:5px; color:#53687b; font-size:13px; }} .diagnostic-issues {{ margin-top:8px; color:var(--red); font-size:13px; }} .diagnostic-issues ul {{ margin:4px 0 0; padding-left:20px; }} .diagnostic-markets {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; margin-top:9px; }} .diagnostic-market {{ display:flex; flex-direction:column; gap:2px; background:#f8fafc; border-radius:8px; padding:8px 10px; color:#53687b; font-size:12px; overflow-wrap:anywhere; }} .diagnostic-market strong {{ color:var(--ink); font-size:13px; }} .diagnostic-reasons {{ color:var(--amber); }}
.market-name {{ font-weight:750; margin-right:8px; }} .market-label {{ color:var(--muted); font-size:12px; }} .data-status {{ border-radius:999px; padding:3px 9px; font-weight:700; font-size:12px; }} .status-DATA_OK {{ background:var(--teal-soft); color:var(--teal); }} .status-DATA_BLOCKED {{ background:var(--red-soft); color:var(--red); }} .status-NOT_RUN {{ background:#edf1f6; color:var(--muted); }}
.stage-nav {{ position:sticky; top:0; z-index:20; display:flex; flex-wrap:wrap; gap:4px; margin:8px 0 9px; padding:7px 8px; align-items:center; background:#f5f7fbeF; border:1px solid var(--line); border-radius:11px; box-shadow:0 4px 14px #18324b12; backdrop-filter:blur(8px); }} .stage-nav-label {{ color:var(--muted); font-weight:700; margin-right:2px; white-space:nowrap; }} .stage-link {{ min-height:44px; border:1px solid transparent; border-radius:8px; background:transparent; color:var(--blue); font:inherit; font-size:13px; font-weight:700; cursor:pointer; padding:6px 8px; white-space:nowrap; }} .stage-link:hover,.stage-link[aria-pressed="true"] {{ color:var(--teal); background:#e8f5f2; border-color:#b9ddd5; }} .nav-count {{ color:var(--muted); font-weight:650; }}
.filters {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; background:#eaf0f6; border:1px solid var(--line); border-radius:11px; padding:9px 10px; margin-bottom:10px; }} .filters label {{ display:flex; align-items:center; gap:6px; color:var(--muted); font-size:13px; }} .search-field {{ flex:1 1 250px; }} select,input[type="search"] {{ min-height:44px; border:1px solid #cbd6e2; border-radius:8px; background:#fff; color:var(--ink); padding:6px 9px; font:inherit; min-width:100px; }} input[type="search"] {{ width:100%; min-width:200px; }}
.results-heading {{ display:flex; align-items:baseline; gap:10px; margin:13px 2px 7px; }} .results-heading h2 {{ margin:0; font-size:20px; }} .results-heading span {{ color:var(--muted); font-size:12px; }} .cards {{ display:flex; flex-direction:column; gap:7px; }} .stock-row {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 13px; box-shadow:0 3px 12px #18324b08; }} .stock-row[hidden] {{ display:none; }}
.row-top {{ display:flex; justify-content:space-between; align-items:center; gap:10px; min-width:0; }} .row-identity {{ display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 9px; min-width:0; }} .ticker {{ font-size:16px; font-weight:800; letter-spacing:.02em; }} .company {{ font-weight:750; }} .sector {{ color:var(--muted); font-size:13px; }} .market-chip {{ color:var(--muted); font-size:12px; border-left:1px solid var(--line); padding-left:9px; }} .stage {{ white-space:nowrap; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:750; }} .stage-watch,.stage-armed {{ background:var(--amber-soft); color:var(--amber); }} .stage-confirmed,.stage-strategy-proposal,.stage-entry-allowed {{ background:var(--blue-soft); color:var(--blue); }} .stage-position-management {{ background:var(--teal-soft); color:var(--teal); }} .stage-failed,.stage-data-blocked {{ background:var(--red-soft); color:var(--red); }} .stage-no-trade {{ background:#edf1f6; color:var(--muted); }}
.row-bottom {{ display:flex; flex-wrap:wrap; align-items:center; gap:5px 12px; margin-top:5px; }} .row-signals {{ display:flex; flex:1 1 420px; flex-wrap:wrap; align-items:center; gap:4px 11px; min-width:0; }} .row-signals > span {{ font-size:13px; }} .row-why {{ color:#53687b; font-weight:650; overflow-wrap:anywhere; }} .row-wave {{ color:var(--blue); font-weight:750; }} .row-setup {{ color:#53687b; font:12px Consolas,monospace; }} .row-next {{ color:var(--muted); overflow-wrap:anywhere; }} .row-price {{ color:var(--teal); font-weight:700; }} .row-actions {{ display:flex; flex:0 0 auto; align-items:center; gap:8px; margin-left:auto; }} .identity-row {{ display:flex; flex-wrap:wrap; gap:4px; margin:0; }} .badge {{ border:1px solid #c8d6e2; border-radius:999px; padding:2px 6px; color:#486074; font-size:11px; background:#f7fafc; white-space:nowrap; }} .badge.warning {{ color:var(--amber); border-color:#f2ca8c; background:var(--amber-soft); }} .badge.positive {{ color:var(--teal); border-color:#9ed7ca; background:var(--teal-soft); }}
.details {{ flex:0 0 auto; margin:0; border:0; padding:0; }} .details[open] {{ flex-basis:100%; }} .details summary {{ min-height:44px; display:inline-flex; align-items:center; cursor:pointer; color:var(--blue); font-size:13px; font-weight:750; white-space:nowrap; list-style:none; padding:8px 0; }} .details summary::-webkit-details-marker {{ display:none; }} .details summary::before {{ content:"＋ "; }} .details[open] summary::before {{ content:"− "; }} .detail-body {{ border-top:1px solid var(--line); margin-top:8px; padding-top:10px; }} .field-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }} .field {{ min-width:0; }} .field-value {{ margin-top:2px; font-weight:650; overflow-wrap:anywhere; }} .panel {{ border-top:1px solid var(--line); padding-top:11px; margin-top:11px; }} .panel h3 {{ margin:0 0 8px; font-size:14px; }} .plan-panel h3 {{ color:var(--blue); }} .position-panel h3 {{ color:var(--teal); }} .detail-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:10px; }} .detail-grid section {{ background:#f8fafc; border-radius:9px; padding:9px 11px; }} .detail-grid h4,.details h4 {{ margin:0 0 4px; font-size:13px; }} .detail-grid p {{ margin:3px 0; font-size:13px; overflow-wrap:anywhere; }} code {{ color:#5c6d80; font-size:11px; }} pre {{ max-height:300px; overflow:auto; white-space:pre-wrap; background:#111d2a; color:#dce9f4; border-radius:9px; padding:11px; font:12px/1.5 Consolas,monospace; }}
.workspace-nav {{ display:flex; flex-wrap:wrap; gap:5px; margin:10px 0 8px; padding:6px; background:#e8eef5; border:1px solid var(--line); border-radius:12px; }} .workspace-link {{ min-height:44px; border:1px solid transparent; border-radius:9px; background:transparent; color:var(--blue); font:inherit; font-weight:750; padding:8px 12px; cursor:pointer; white-space:nowrap; }} .workspace-link:hover,.workspace-link[aria-pressed="true"] {{ color:#fff; background:var(--blue); border-color:var(--blue); }} .workspace-panel {{ margin-top:10px; }} .workspace-panel[hidden] {{ display:none; }} .workspace-heading {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px; margin:13px 2px 8px; }} .workspace-heading h2 {{ margin:0; font-size:21px; }} .workspace-heading p {{ margin:0; color:var(--muted); font-size:13px; }} .workspace-subheading {{ margin:17px 2px 7px; font-size:16px; }} .paper-summary {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; }} .paper-summary .metric {{ min-height:61px; }} .paper-trades {{ display:flex; flex-direction:column; gap:9px; }} .paper-trade {{ background:#fff; border:1px solid var(--line); border-left:4px solid #8ca9c2; border-radius:12px; padding:12px 14px; }} .paper-status-OPEN {{ border-left-color:var(--teal); }} .paper-status-CLOSED {{ border-left-color:var(--blue); }} .paper-status-SKIPPED {{ border-left-color:var(--muted); }} .paper-status-PENDING_T1 {{ border-left-color:var(--amber); }} .paper-trade-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }} .paper-trade-meta {{ display:flex; flex-wrap:wrap; gap:4px 10px; color:var(--muted); font-size:12px; margin-top:3px; }} .paper-status {{ background:#edf1f6; color:#506276; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:750; white-space:nowrap; }} .paper-human-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:11px; }} .paper-human-grid > section {{ background:#f8fafc; border-radius:9px; padding:10px 12px; }} .paper-human-grid h4 {{ margin:0 0 5px; font-size:13px; color:var(--blue); }} .paper-human-grid p {{ margin:0; font-size:13px; overflow-wrap:anywhere; }} .paper-technical-details {{ margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }} .paper-technical-details summary {{ cursor:pointer; color:var(--blue); font-size:12px; font-weight:750; }} .paper-technical-fields {{ margin-top:8px; }} .paper-technical-details pre {{ margin-top:8px; }} .paper-stat-note {{ color:var(--muted); font-size:12px; margin:12px 2px 0; }} .paper-warning {{ background:var(--amber-soft); color:#7a4300; border:1px solid #f2ca8c; border-radius:9px; padding:8px 10px; margin:8px 0; font-size:13px; }} .coverage-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }} .coverage-card {{ display:flex; flex-direction:column; gap:2px; background:#fff; border:1px solid var(--line); border-radius:9px; padding:9px 11px; font-size:13px; }} .coverage-card span {{ color:var(--muted); }} .coverage-CONTINUOUS {{ color:var(--teal) !important; font-weight:750; }} .coverage-GAP_DETECTED {{ color:var(--amber) !important; font-weight:750; }} .performance-summary-grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); margin-bottom:13px; }} .performance-table {{ margin-top:12px; }} .performance-table h3 {{ margin:0 0 5px; font-size:15px; }} .performance-groups {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }} .performance-group {{ background:#fff; border:1px solid var(--line); border-radius:9px; padding:9px 11px; }} .performance-group h4 {{ margin:0 0 7px; font-size:14px; color:var(--blue); }} .performance-group-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; }} .rules-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }} .rule-card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:11px 13px; }} .rule-card h3 {{ margin:0 0 4px; font-size:14px; color:var(--blue); }} .rule-card p {{ margin:0; font-size:13px; }} .empty {{ color:var(--muted); text-align:center; padding:30px; background:#fff; border:1px dashed #c5d1df; border-radius:12px; }} .footer {{ color:var(--muted); font-size:12px; margin-top:18px; }}
.decision-focus {{ margin:0 0 10px !important; border:1px solid #a9c7df !important; background:#f7fbff !important; border-radius:12px !important; padding:12px 14px !important; }} .decision-focus > h3 {{ margin:0 0 8px; font-size:16px; }} .focus-conclusion {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 10px; padding:8px 10px; border-radius:9px; background:#e9f3fb; }} .focus-conclusion strong {{ font-size:15px; color:#163d5c; }} .focus-conclusion span {{ font-size:12px; font-weight:750; color:#47677f; }} .focus-conclusion.blocked {{ background:#fff0f0; }} .focus-conclusion.blocked strong {{ color:#9b3030; }} .focus-conclusion.allowed {{ background:#e8f5f2; }} .focus-conclusion.allowed strong {{ color:#166a5a; }} .focus-grid {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:7px; }} .focus-field {{ min-width:0; padding:8px 9px; border:1px solid #d8e4ee; border-radius:9px; background:#fff; }} .focus-field.emphasis {{ border-color:#9bbbd4; background:#f2f8fc; }} .focus-label {{ font-size:11px; color:#63798b; margin-bottom:3px; }} .focus-value {{ font-size:15px; font-weight:760; color:#102b42; overflow-wrap:anywhere; }} .focus-note {{ margin:9px 0 0 !important; color:#526a7d; font-size:13px; line-height:1.55; }} .human-glance {{ margin:8px 0 2px; padding:10px 12px; border-radius:10px; background:#f6f9fc; border:1px solid #dde6ee; }} .human-glance-title {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-weight:800; margin-bottom:7px; }} .human-chip {{ display:inline-block; padding:2px 7px; border-radius:999px; font-size:11px; border:1px solid #c7d5e1; background:#fff; }} .human-chip.near {{ border-color:#d6b36b; background:#fffaf0; }} .human-chip.confirmed {{ border-color:#8bb9a8; background:#f2fbf7; }} .human-chip.blocked {{ border-color:#d3a0a0; background:#fff6f6; }} .human-metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }} .human-metric {{ min-width:0; }} .human-metric span {{ display:block; font-size:11px; color:#758899; margin-bottom:2px; }} .human-metric strong {{ display:block; font-size:14px; line-height:1.35; overflow-wrap:anywhere; }} .manual-opportunity-panel {{ border:1px solid #b9ccdc; background:#fbfdff; }} .manual-opportunity-panel h3 {{ margin:0 0 5px; font-size:18px; }} .manual-opportunity-panel .lead {{ margin:0 0 11px; color:#445e72; line-height:1.55; }} .manual-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:10px 0; }} .manual-cell {{ padding:10px; border:1px solid #dbe5ed; border-radius:10px; background:#fff; }} .manual-cell .label {{ font-size:11px; color:#728596; margin-bottom:4px; }} .manual-cell .value {{ font-size:18px; font-weight:800; line-height:1.25; overflow-wrap:anywhere; }} .manual-cell .sub {{ font-size:12px; color:#607485; margin-top:3px; line-height:1.35; }} .wave-target-section {{ margin-top:12px; }} .wave-target-section h4 {{ margin:0 0 7px; font-size:14px; }} .wave-target-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }} .wave-target {{ padding:10px; border-radius:10px; border:1px solid #d9e5ef; background:#fff; }} .wave-target .ratio {{ font-size:11px; color:#718598; }} .wave-target .price {{ font-size:19px; font-weight:850; margin-top:4px; overflow-wrap:anywhere; }} .wave-target .upside {{ font-size:14px; font-weight:750; margin-top:2px; overflow-wrap:anywhere; }} .wave-target.primary {{ border-width:2px; }} .wave-target.missing {{ border-style:dashed; background:#fafafa; }} .wave-target.missing .price {{ font-size:13px; font-weight:700; color:#71808d; }} .system-gate-line {{ margin-top:12px; padding:9px 10px; border-radius:9px; background:#f6f6f6; font-size:13px; line-height:1.5; }} .system-gate-line strong {{ margin-right:5px; }} .next-action-line {{ margin-top:8px; font-size:14px; line-height:1.55; }} .v3-price {{ font-weight:700; }} .prototype-data-gap {{ font-size:12px; color:#6d7e8c; margin-top:9px; padding-top:8px; border-top:1px dashed #d2dde6; }} .logic-summary {{ margin:8px 0 10px; border:1px solid #dbe4ec; border-radius:10px; background:#fff; }} .logic-summary > summary {{ cursor:pointer; padding:10px 12px; color:#35617f; font-size:13px; font-weight:750; }} .logic-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:0 12px 12px; }} .logic-grid > section {{ padding:8px 10px; border-radius:8px; background:#f8fafc; }} .logic-grid h3 {{ margin:0 0 4px; font-size:13px; }} .logic-grid p {{ margin:0; font-size:12px; line-height:1.5; color:#526a7d; }}
@media (max-width:1050px) {{ .summary-primary {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }} @media (max-width:620px) {{ .shell {{ width:min(100% - 20px,1440px); padding-top:10px; }} .hero {{ padding:18px 20px; border-radius:15px; }} .summary-primary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .summary-secondary {{ flex-direction:column; }} .market-grid,.diagnostic-markets {{ grid-template-columns:1fr; }} .row-top {{ align-items:flex-start; }} .stage {{ margin-top:1px; }} .row-signals {{ flex-basis:100%; }} .row-actions {{ width:100%; justify-content:space-between; margin-left:0; }} .detail-grid {{ grid-template-columns:1fr; }} .field-grid {{ gap:7px; }} .ticker {{ font-size:15px; }} }}
.today-paper-focus {{ margin-bottom:12px; }} .paper-focus-cards {{ display:flex; flex-direction:column; gap:7px; }} .paper-focus-card {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:3px 10px; align-items:center; background:#fff; border:1px solid var(--line); border-left:4px solid var(--teal); border-radius:10px; padding:9px 12px; }} .paper-focus-card span {{ color:var(--muted); font-size:13px; }} .paper-focus-meta {{ display:block; font-size:12px !important; }} .paper-focus-values {{ grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:4px 14px; }}
@media (max-width:1050px) {{ .paper-summary {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} .performance-summary-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media (max-width:620px) {{ .paper-summary,.performance-summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .paper-grid,.paper-human-grid,.rules-grid,.performance-groups {{ grid-template-columns:1fr; }} .coverage-grid {{ grid-template-columns:1fr; }} }}
@media (max-width:900px) {{ .focus-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .logic-grid {{ grid-template-columns:1fr; }} }} @media (max-width:760px) {{ .human-metrics,.manual-grid,.wave-target-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }} @media (max-width:560px) {{ .focus-grid {{ grid-template-columns:1fr; }} .decision-focus {{ padding:10px !important; }} }}
</style>
</head>
<body>
<main class="shell">
<header class="hero"><div class="eyebrow">每日收盘报告 · 只读</div>{demo_banner}{cloud_banner}<h1>{_escape(projection['title'])}</h1><div class="hero-meta"><span>数据日期：{_escape(projection['as_of_date'])}</span><span>生成时间：{_escape(projection['generated_at'])}</span></div><div class="readonly-note">先看今日确认和等待确认，再查看无法评估的标的。观察状态不代表可以买入；点击股票展开交易依据。本报告只读，不自动下单。</div></header>
<section class="summary-primary" aria-label="今日重点摘要">
{_metric('可入场', summary['entry_allowed_count'], 'positive')}
{_metric('已形成交易方案', summary['strategy_proposal_count'])}
{_metric('今日确认', summary['new_confirmed_count'], 'positive')}
{_metric('等待确认', summary['armed_count'])}
{_metric('策略跟踪持仓', summary['position_count'])}
{_metric('数据异常', summary['data_blocked_count'], 'danger')}
</section>
<section class="summary-secondary" aria-label="次级摘要">
{_metric_link('观察中', summary['watch_count'], 'WATCH')}
{_metric('候选总数', summary['candidate_total'])}
{_metric('报告覆盖标的', summary['analysis_count'])}
{_metric('成功分析', summary['completed_analysis_count'])}
</section>
<section class="market-grid" aria-label="市场数据状态">{_render_market_cards(projection['markets'])}</section>
 {_render_diagnostics(projection)}
 {_render_opportunity_tracking(projection)}
 {_render_prospective_observation(projection)}
<nav class="workspace-nav" aria-label="工作台导航">{workspace_nav}</nav>
{_render_paper_workspace(paper)}
{_render_performance_workspace(paper)}
{_render_rules_workspace(projection.get('strategy_rules', ( )))}
<section id="decision-workspace" class="workspace-panel">
{_render_today_paper_focus(paper, projection.get('as_of_date'))}
<nav class="stage-nav" aria-label="阶段导航"><span class="stage-nav-label">阶段查看：</span>{stage_nav}</nav>
<section class="filters" aria-label="股票筛选"><label class="search-field">搜索<input id="search-filter" type="search" placeholder="代码或公司名称" autocomplete="off"></label><label>市场<select id="market-filter"><option value="">全部</option><option value="CN">中国市场（CN）</option><option value="US">美国市场（US）</option></select></label><label>当前阶段<select id="stage-filter"><option value="">全部</option>{stage_options}</select></label><label>浪型策略<select id="setup-filter"><option value="">全部</option><option value="SETUP_01">2浪→3浪</option><option value="SETUP_02">3浪延续</option></select></label><label>行业／板块<select id="sector-filter"><option value="">全部</option>{sector_options}</select></label><span id="visible-count" class="stage-nav-label"></span></section>
<div class="results-heading"><h2 id="results-title">今日重点</h2><span id="results-description">先查看确认、等待确认与异常；全部结果保留在“全部/诊断”</span></div>
<section id="cards" class="cards" aria-live="polite">{cards}</section><div id="empty" class="empty" hidden>没有符合当前筛选条件的股票。</div>
</section>
<div class="footer">默认优先查看今日重点；全部结果可从“全部/诊断”查看，筛选不会删除日报结果。点击“查看交易依据”查看当日状态、条件、原因、价格计划和失效条件；原始诊断默认收起。页面不替代用户最终交易决定。</div>
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
    focus: '先处理可入场、方案、确认、等待确认、策略跟踪持仓与异常',
    ARMED: '只看等待确认的股票',
    WATCH: '只看观察中的股票',
    confirmed: '只看今天新确认的事件',
    STRATEGY_PROPOSAL: '只看已经形成交易方案的股票',
    ENTRY_ALLOWED: '只看可以入场的股票',
    POSITION_MANAGEMENT: '只看策略跟踪持仓',
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
    const viewLabel = activeView === 'focus' ? '今日重点' : activeView === 'all' ? '全部/诊断' : activeView === 'confirmed' ? '今日确认' : ({{ARMED:'等待确认', WATCH:'观察中', STRATEGY_PROPOSAL:'交易方案', ENTRY_ALLOWED:'可入场', POSITION_MANAGEMENT:'策略跟踪持仓'}}[activeView] || activeView);
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
    "USER_VISIBLE_ALLOWED_ABBREVIATIONS",
    "USER_VISIBLE_LANGUAGE_AUDIT",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STATUS_LABELS",
    "WAVE_LABELS",
    "WAVE_SHORT_LABELS",
    "dashboard_universe_metadata",
    "dashboard_search_matches",
    "build_dashboard_projection",
    "daily_report_consistency_matrix",
    "html_consistency_audit",
    "load_dashboard_json",
    "render_daily_report_email_html",
    "render_dashboard_html",
    "user_visible_language_audit",
    "write_dashboard_html",
]
