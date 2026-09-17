"""Static, email-safe presentation for the Cloud Daily Report.

This module deliberately consumes the existing dashboard projection instead of
re-evaluating any Wave, Setup, Decision, Risk, or Position Management logic.
The output is a compact Chinese summary for mail clients; the standalone
interactive dashboard remains the browser artifact.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import html
from typing import Any

from trading.daily_dashboard import build_dashboard_projection


EMAIL_MAX_HIGHLIGHTS = 20

_PRIORITY_LABELS = {
    "data": "数据异常",
    "position": "持仓",
    "plan": "已形成交易计划",
    "no_trade": "今日不交易",
    "confirmed": "今日新确认",
    "armed": "接近确认",
}
_STATUS_LABELS = {
    "SUCCESS": "数据正常",
    "SKIPPED_NON_SESSION": "非交易日，已跳过",
    "INCOMPLETE_SESSION": "尚未收盘，本次未生成交易信号",
    "PARTIAL_DATA_QUALITY": "部分数据异常",
    "FAILED": "数据异常",
}
_MARKET_LABELS = {"CN": "A股", "US": "美股"}
_PLAN_STAGES = frozenset(("ENTRY_ALLOWED", "STRATEGY_PROPOSAL"))
_MINIMUM_RR_TEXT = "2.00R"
_EXECUTION_COPY = {
    "EXECUTED": "T+1 开盘已通过执行检查并记录模拟成交",
    "SKIP_TARGET_UPSIDE_BELOW_MINIMUM": "T+1 剩余第一目标空间低于5%，已跳过，不追入",
    "SKIP_GAP_BELOW_CONFIRMATION": "T+1 低开回到确认价下方，已按原规则跳过",
    "SKIP_GAP_ABOVE_ENTRY_ZONE": "T+1 高开超过允许入场区，已按原规则跳过",
}
_NO_TRADE_COPY = {
    "RR_BELOW_MINIMUM": ("不交易", "收益风险比不足"),
    "TARGET_UPSIDE_BELOW_MINIMUM": ("不交易", "目标上涨空间不足"),
    "ABOVE_ENTRY_ZONE": ("不追高", "已经高于允许入场区上沿"),
    "NO_VALID_TARGET": ("不交易", "没有高于参考价格的有效第一目标"),
    "ATR_UNAVAILABLE": ("不交易", "波动率数据不足"),
    "STALE_CONFIRMATION_GEOMETRY": ("不交易", "确认结构已过期"),
    "INVALID_STRUCTURE": ("不交易", "交易结构未通过检查"),
}
_TECHNICAL_MARKERS = (
    "SETUP_01",
    "SETUP_02",
    "SETUP_03",
    "SETUP_04",
    "WATCH",
    "ARMED",
    "CONFIRMED",
    "event_identity",
    "provenance",
    "raw JSON",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _escape(value: Any, default: str = "—") -> str:
    return html.escape(_text(value, default), quote=True)


def _human(value: Any, default: str) -> str:
    """Keep unexpected machine tokens out of the default mail view."""

    text = _text(value)
    if not text or text in {"—", "None", "null"}:
        return default
    if any(marker in text for marker in _TECHNICAL_MARKERS):
        return default
    return text


def _integer(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _decision_action(row: Mapping[str, Any]) -> str:
    return _text(_mapping(row.get("decision")).get("action")).upper()


def _decision_gate_reason(row: Mapping[str, Any]) -> str:
    decision_reason = _text(_mapping(row.get("decision")).get("gate_reason")).upper()
    if decision_reason:
        return decision_reason
    for value in _sequence(row.get("reasons")):
        reason = _text(value).upper()
        if reason in _NO_TRADE_COPY:
            return reason
    return ""


def _is_plan(row: Mapping[str, Any]) -> bool:
    """Only a production-meaningful allowed/proposal row is a trade plan.

    A projected ``plan.has_decision`` only means that an individual Decision
    object exists.  It is intentionally not sufficient: a rejected Decision
    can still retain all of its calculation fields for diagnostics.
    """

    return (
        not bool(row.get("data_blocked"))
        and _text(row.get("stage_key")).upper() in _PLAN_STAGES
        and _decision_action(row) == "ENTRY_ALLOWED"
    )


def _is_no_trade_decision(row: Mapping[str, Any]) -> bool:
    return (
        not bool(row.get("data_blocked"))
        and not bool(row.get("is_position"))
        and _decision_action(row) == "NO_TRADE"
    )


def _no_trade_copy(row: Mapping[str, Any]) -> tuple[str, str]:
    return _NO_TRADE_COPY.get(
        _decision_gate_reason(row),
        ("不交易", "当前入场条件未通过"),
    )


def _priority(row: Mapping[str, Any]) -> str | None:
    if row.get("data_blocked"):
        return "data"
    if row.get("is_position"):
        return "position"
    if _is_plan(row):
        return "plan"
    if _is_no_trade_decision(row):
        return "no_trade"
    if row.get("event_is_new"):
        return "confirmed"
    if _text(row.get("stage_key")) == "ARMED":
        return "armed"
    return None


def _target_market(projection: Mapping[str, Any]) -> str:
    cloud = _mapping(projection.get("cloud_daily_report"))
    return _text(cloud.get("market")).upper()


def _rows_for_mail(projection: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    target_market = _target_market(projection)
    rows: list[dict[str, Any]] = []
    for value in _sequence(projection.get("rows")):
        row = dict(_mapping(value))
        if not row:
            continue
        if target_market and _text(row.get("market")).upper() != target_market:
            continue
        if _priority(row) is not None:
            rows.append(row)
    rank = {key: index for index, key in enumerate(_PRIORITY_LABELS)}
    def armed_distance(row: Mapping[str, Any]) -> float:
        if _priority(row) != "armed":
            return 0.0
        value = _mapping(row.get("armed_opportunity")).get(
            "distance_to_confirmation_pct"
        )
        try:
            return abs(float(value))
        except (TypeError, ValueError):
            return float("inf")

    rows.sort(
        key=lambda row: (
            rank.get(_priority(row) or "", len(rank)),
            armed_distance(row),
            _text(row.get("market")),
            _text(row.get("symbol")).casefold(),
            _text(row.get("name")).casefold(),
        )
    )
    return tuple(rows)


def _all_rows_for_mail(projection: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    target_market = _target_market(projection)
    rows: list[Mapping[str, Any]] = []
    for value in _sequence(projection.get("rows")):
        row = _mapping(value)
        if not row:
            continue
        if target_market and _text(row.get("market")).upper() != target_market:
            continue
        rows.append(row)
    return tuple(rows)


def _status(projection: Mapping[str, Any]) -> str:
    cloud = _mapping(projection.get("cloud_daily_report"))
    cloud_status = _text(cloud.get("status")).upper()
    if cloud_status:
        return _STATUS_LABELS.get(cloud_status, "数据异常")
    markets = [
        _text(_mapping(value).get("status_label"), "未运行")
        for value in _sequence(projection.get("markets"))
        if _mapping(value)
    ]
    return "；".join(markets) or "未运行"


def _market_text(projection: Mapping[str, Any]) -> str:
    cloud = _mapping(projection.get("cloud_daily_report"))
    market = _target_market(projection)
    if market:
        return _text(cloud.get("market_label"), _MARKET_LABELS.get(market, market))
    labels = [
        _text(_mapping(value).get("label"))
        for value in _sequence(projection.get("markets"))
        if _text(_mapping(value).get("label"))
    ]
    return "、".join(dict.fromkeys(labels)) or "—"


def _data_issue_count(projection: Mapping[str, Any]) -> int:
    count = sum(
        bool(row.get("data_blocked"))
        for row in _all_rows_for_mail(projection)
    )
    cloud = _mapping(projection.get("cloud_daily_report"))
    quality = _mapping(cloud.get("data_quality"))
    failed_symbols = {
        _text(value)
        for value in _sequence(quality.get("failed_symbols"))
        if _text(value)
    }
    count = max(count, len(failed_symbols))
    quality_counts = _mapping(quality.get("counts"))
    count = max(
        count,
        sum(
            _integer(value)
            for key, value in quality_counts.items()
            if _text(key).upper() != "DATA_OK"
        ),
    )
    cloud_status = _text(cloud.get("status")).upper()
    if cloud_status and cloud_status not in {"SUCCESS", "SKIPPED_NON_SESSION"}:
        count = max(count, 1)
    if not cloud_status and any(
        _text(_mapping(value).get("status_key")).upper() == "DATA_BLOCKED"
        for value in _sequence(projection.get("markets"))
    ):
        count = max(count, 1)
    return count


def _summary(projection: Mapping[str, Any]) -> dict[str, int]:
    mail_rows = _all_rows_for_mail(projection)
    plan_count = sum(1 for row in mail_rows if _is_plan(row))
    return {
        "new_confirmed": sum(bool(row.get("event_is_new")) for row in mail_rows),
        "armed": sum(_text(row.get("stage_key")) == "ARMED" for row in mail_rows),
        "plans": plan_count,
        "positions": sum(bool(row.get("is_position")) for row in mail_rows),
        "data_issues": _data_issue_count(projection),
    }


def _section_header(label: str, count: int) -> str:
    return (
        '<tr><td style="padding:16px 0 8px 0;">'
        f'<h2 style="margin:0;color:#172033;font-size:18px;line-height:1.35;">{html.escape(label)}（{count}）</h2>'
        "</td></tr>"
    )


def _next_step(row: Mapping[str, Any], category: str) -> str:
    value = _text(row.get("missing_condition")) or _text(row.get("next_step"))
    defaults = {
        "data": "等待数据恢复，本日不生成交易信号。",
        "position": "按现有持仓管理结果处理。",
        "plan": "交易方案已经形成，按现有流程继续。",
        "no_trade": "本次不形成交易计划，等待下一次满足入场条件的机会。",
        "confirmed": "等待入场条件评估。",
        "armed": "等待确认条件。",
    }
    return _human(value, defaults[category])


def _today_text(row: Mapping[str, Any], category: str) -> str:
    if category == "no_trade":
        conclusion, reason = _no_trade_copy(row)
        return f"{conclusion}；原因：{reason}"
    defaults = {
        "data": "行情或生产前置数据没有达到可用要求。",
        "position": "该标的已经进入持仓管理。",
        "plan": "现有结构、入场区间和目标风险收益已经形成交易方案。",
        "confirmed": "今天出现新的确认信号。",
        "armed": "当前接近确认，仍需满足确认条件。",
    }
    conclusion = _human(row.get("today_conclusion"), _PRIORITY_LABELS[category])
    why = _human(row.get("why"), defaults[category])
    if conclusion and conclusion not in why:
        return f"{conclusion}；{why}"
    return why


def _first_rr_text(plan: Mapping[str, Any]) -> str:
    text = _text(plan.get("rr"))
    if not text:
        return "—"
    first = text.split("/", 1)[0].strip()
    if not first or first in {"—", "-"}:
        return "—"
    return first if first.upper().endswith("R") else f"{first}R"


def _target_semantics_html(
    plan: Mapping[str, Any],
    *,
    no_trade: bool = False,
) -> str:
    """Render the shared target projection without calculating target geometry."""

    if not bool(plan.get("has_target_projection")):
        return ""
    fields = (
        ("当前正式 T1（保持 gate/RR）", plan.get("effective_t1")),
        ("T1 来源", plan.get("effective_t1_source_label")),
        ("保守第一障碍（最近已确认历史阻力）", plan.get("nearest_overhead_confirmed_swing_high")),
        ("保守第一障碍上涨空间", plan.get("overhead_resistance_upside_pct")),
        ("Wave3 结构目标（最近 Fib 投射）", plan.get("nearest_wave3_fib_extension")),
        ("Wave3 结构目标 ratio", plan.get("nearest_wave3_fib_extension_ratio")),
        ("Wave3 结构目标上涨空间", plan.get("wave3_fib_upside_pct")),
        ("后续 Wave3 结构目标", plan.get("wave3_fib_extensions")),
    )
    rendered = "".join(
        f'<div style="margin:2px 0;">{html.escape(label)}：{_escape(value)}</div>'
        for label, value in fields
        if _text(value) not in {"", "—", "-"}
    )
    explanation = _text(plan.get("target_boundary_explanation"))
    if explanation:
        if no_trade:
            explanation += "；所以按现有保守规则不交易。"
        rendered += (
            '<div style="margin:7px 0 0 0;color:#687386;">'
            f"{_escape(explanation)}"
            "</div>"
        )
    return rendered


def _no_trade_html(row: Mapping[str, Any]) -> str:
    if not _is_no_trade_decision(row):
        return ""
    plan = _mapping(row.get("plan"))
    reason = _decision_gate_reason(row)
    if reason == "TARGET_UPSIDE_BELOW_MINIMUM":
        return (
            '<div style="margin-top:10px;padding:10px;background-color:#fff8ed;border-left:3px solid #d98b20;">'
            '<div style="margin:0 0 5px 0;color:#8a5510;font-weight:700;">Decision 计算依据</div>'
            f'<div style="margin:2px 0;">参考价格：{_escape(plan.get("planned_entry"))}</div>'
            f'<div style="margin:2px 0;">结构止损：{_escape(plan.get("execution_stop"))}</div>'
            f'<div style="margin:2px 0;">第一目标候选：{_escape(plan.get("target_1"))}</div>'
            f'<div style="margin:2px 0;">目标上涨空间：{_escape(plan.get("target_upside_pct"))}</div>'
            f'<div style="margin:2px 0;">系统最低要求：{_escape(plan.get("minimum_target_upside_pct"))}</div>'
            f'<div style="margin:2px 0;">对应 RR：{_escape(_first_rr_text(plan))}</div>'
            f'<div style="margin:2px 0;">最低 RR 要求：{_MINIMUM_RR_TEXT}</div>'
            + _target_semantics_html(plan, no_trade=True)
            + '<div style="margin:7px 0 0 0;color:#687386;">说明：目标空间不足；这些是本次 Decision gate 的计算依据，不是买入/止盈建议。</div>'
            + '</div>'
        )
    if reason == "RR_BELOW_MINIMUM":
        return (
            '<div style="margin-top:10px;padding:10px;background-color:#fff8ed;border-left:3px solid #d98b20;">'
            '<div style="margin:0 0 5px 0;color:#8a5510;font-weight:700;">Decision 计算依据</div>'
            f'<div style="margin:2px 0;">参考价格：{_escape(plan.get("planned_entry"))}</div>'
            f'<div style="margin:2px 0;">结构止损：{_escape(plan.get("execution_stop"))}</div>'
            f'<div style="margin:2px 0;">第一目标候选：{_escape(plan.get("target_1"))}</div>'
            f'<div style="margin:2px 0;">目标上涨空间：{_escape(plan.get("target_upside_pct"))}</div>'
            f'<div style="margin:2px 0;">系统最低要求：{_escape(plan.get("minimum_target_upside_pct"))}</div>'
            f'<div style="margin:2px 0;">对应 RR：{_escape(_first_rr_text(plan))}</div>'
            f'<div style="margin:2px 0;">最低 RR 要求：{_MINIMUM_RR_TEXT}</div>'
            + _target_semantics_html(plan)
            + '<div style="margin:7px 0 0 0;color:#687386;">这些是本次 Decision gate 的计算依据，不是买入/止盈建议。</div>'
            + '</div>'
        )
    if reason == "ABOVE_ENTRY_ZONE":
        return (
            '<div style="margin-top:10px;padding:10px;background-color:#fff8ed;border-left:3px solid #d98b20;">'
            '<div style="margin:0 0 5px 0;color:#8a5510;font-weight:700;">Decision 计算依据</div>'
            f'<div style="margin:2px 0;">允许入场区：{_escape(plan.get("entry_zone_low"))}～{_escape(plan.get("entry_zone_high"))}</div>'
            f'<div style="margin:2px 0;">当前价格：{_escape(plan.get("planned_entry"))}</div>'
            '<div style="margin:2px 0;">原因：已经高于允许入场区上沿</div>'
            '<div style="margin:7px 0 0 0;color:#687386;">这些是本次 Decision gate 的计算依据，不是买入/止盈建议。</div>'
            '</div>'
        )
    return (
        '<div style="margin-top:10px;padding:10px;background-color:#fff8ed;border-left:3px solid #d98b20;">'
        '<div style="margin:0 0 5px 0;color:#8a5510;font-weight:700;">Decision 计算依据</div>'
        '<div style="margin:7px 0 0 0;color:#687386;">这些是本次 Decision gate 的计算依据，不是买入/止盈建议。</div>'
        '</div>'
    )


def _plan_html(row: Mapping[str, Any]) -> str:
    if not _is_plan(row):
        return ""
    plan = _mapping(row.get("plan"))
    targets = "；".join(
        f"T{index}：{_escape(plan.get(key))}"
        for index, key in enumerate(("target_1", "target_2", "target_3"), start=1)
    )
    optional_lines = []
    for label, key in (
        ("目标上涨空间", "target_upside_pct"),
        ("空间评价", "target_upside_band"),
        ("T+1 gap", "t1_gap_vs_planned_entry_pct"),
        ("T+1 剩余第一目标空间", "remaining_target_upside_pct"),
    ):
        value = _text(plan.get(key))
        if value and value not in {"—", "-"}:
            optional_lines.append(
                f'<div style="margin:2px 0;">{label}：{_escape(value)}</div>'
            )
    outcome = _text(_mapping(row.get("raw_result")).get("execution_outcome"))
    if outcome in _EXECUTION_COPY:
        optional_lines.append(
            f'<div style="margin:2px 0;">T+1 结果：{_escape(_EXECUTION_COPY[outcome])}</div>'
        )
    return (
        '<div style="margin-top:10px;padding:10px;background-color:#f4f8ff;border-left:3px solid #356ae6;">'
        '<div style="margin:0 0 5px 0;color:#244a9b;font-weight:700;">交易计划（来自真实 Decision）</div>'
        f'<div style="margin:2px 0;">入场（Entry）：{_escape(plan.get("planned_entry"))}</div>'
        f'<div style="margin:2px 0;">止损（Stop）：{_escape(plan.get("execution_stop"))}</div>'
        f'<div style="margin:2px 0;">目标（Targets）：{targets}</div>'
        + _target_semantics_html(plan)
        + "".join(optional_lines)
        + f'<div style="margin:2px 0;">风险收益比（RR）：{_escape(plan.get("rr"))}</div>'
        "</div>"
    )


def _armed_html(row: Mapping[str, Any]) -> str:
    if _priority(row) != "armed":
        return ""
    armed = _mapping(row.get("armed_opportunity"))
    if armed.get("status") != "AVAILABLE":
        reasons = "、".join(
            _text(value) for value in _sequence(armed.get("missing_reasons")) if _text(value)
        )
        return (
            '<div style="margin-top:10px;padding:10px;background-color:#fff8ed;border-left:3px solid #d98b20;">'
            '<div style="font-weight:700;">机会观察｜不是买入信号</div>'
            '<div>数据不足，不能猜测。</div>'
            f'<div>缺失原因：{_escape(reasons, "机会投影字段不完整")}</div></div>'
        )
    low = _escape(armed.get("expected_entry_zone_low_display"))
    high = _escape(armed.get("expected_entry_zone_high_display"))
    return (
        '<div style="margin-top:10px;padding:10px;background-color:#f4f8ff;border-left:3px solid #356ae6;">'
        '<div style="font-weight:700;">机会观察｜不是买入信号</div>'
        f'<div>当前收盘价：{_escape(armed.get("current_close_display"))}</div>'
        f'<div>确认价：{_escape(armed.get("confirmation_level_display"))}</div>'
        f'<div>距确认：{_escape(armed.get("distance_to_confirmation_display"))}（{_escape(armed.get("distance_to_confirmation_pct_display"))}）</div>'
        f'<div>确认后预期观察入场区：{low}～{high}</div>'
        f'<div>结构失效价：{_escape(armed.get("structural_invalidation_display"))}</div>'
        f'<div style="margin-top:6px;color:#687386;">{_escape(armed.get("guidance"))}</div></div>'
    )


def _row_html(category: str, row: Mapping[str, Any]) -> str:
    name = _escape(row.get("name"), "未命名标的")
    symbol = _escape(row.get("symbol"), "未知代码")
    wave = _escape(row.get("current_wave_label"), "当前浪型暂不可判断")
    today = html.escape(_today_text(row, category), quote=True)
    next_step = html.escape(_next_step(row, category), quote=True)
    has_plan = "是" if _is_plan(row) else "否"
    today_label = "今日结论" if category == "no_trade" else "今天发生什么"
    market = _text(row.get("market")).upper()
    market_suffix = f" · {_MARKET_LABELS.get(market, market)}" if market else ""
    return (
        '<tr><td style="padding:6px 0;">'
        '<div style="padding:12px;border:1px solid #d9dee8;border-radius:8px;background-color:#ffffff;">'
        f'<h3 style="margin:0 0 9px 0;color:#172033;font-size:16px;line-height:1.4;">{name}（{symbol}）{html.escape(market_suffix)}</h3>'
        f'<div style="margin:5px 0;"><span style="color:#687386;">当前浪型：</span>{wave}</div>'
        f'<div style="margin:5px 0;"><span style="color:#687386;">{today_label}：</span>{today}</div>'
        f'<div style="margin:5px 0;"><span style="color:#687386;">还差什么 / 下一步：</span>{next_step}</div>'
        f'<div style="margin:5px 0;"><span style="color:#687386;">是否已有交易计划：</span>{has_plan}</div>'
        + _plan_html(row)
        + _armed_html(row)
        + _no_trade_html(row)
        + "</div></td></tr>"
    )


def _alert_html(projection: Mapping[str, Any], issue_count: int) -> str:
    cloud = _mapping(projection.get("cloud_daily_report"))
    status = _text(cloud.get("status")).upper()
    quality = _mapping(cloud.get("data_quality"))
    failed = [
        _escape(value)
        for value in _sequence(quality.get("failed_symbols"))
        if _text(value)
    ]
    if issue_count:
        detail = f"异常标的：{'、'.join(failed)}。" if failed else "本次日报未通过数据质量或收盘前置检查。"
        if status == "INCOMPLETE_SESSION":
            detail = "当前交易日尚未完成收盘检查，本日不生成新的交易信号。"
        return (
            '<tr><td style="padding:10px 0 2px 0;">'
            '<div style="padding:11px;border:1px solid #efb4b4;border-radius:8px;background-color:#fff5f5;color:#8d2020;">'
            f'<strong>数据异常</strong>：{detail}'
            "</div></td></tr>"
        )
    if status == "SKIPPED_NON_SESSION":
        return (
            '<tr><td style="padding:10px 0 2px 0;">'
            '<div style="padding:11px;border:1px solid #d9dee8;border-radius:8px;background-color:#f8fafc;color:#4d5b70;">'
            "今天是非交易日，日报已跳过，不使用上一交易日替代。"
            "</div></td></tr>"
        )
    return ""


def _run_link_html(projection: Mapping[str, Any]) -> str:
    url = _text(_mapping(projection.get("cloud_daily_report")).get("github_run_url"))
    if not (url.startswith("https://") or url.startswith("http://")):
        return ""
    return (
        '<tr><td style="padding:14px 0 0 0;text-align:center;">'
        f'<a href="{html.escape(url, quote=True)}" style="color:#356ae6;font-size:13px;">查看本次 GitHub 运行</a>'
        "</td></tr>"
    )


def render_daily_report_email_html(payload: Mapping[str, Any]) -> str:
    """Render a static, single-column HTML email from an existing report payload."""

    projection = build_dashboard_projection(payload)
    all_rows = _all_rows_for_mail(projection)
    focus_rows = _rows_for_mail(projection)
    displayed_rows = focus_rows[:EMAIL_MAX_HIGHLIGHTS]
    summary = _summary(projection)
    market = _market_text(projection)
    trade_date = _escape(projection.get("as_of_date"))
    status = _escape(_status(projection))
    title = _escape(projection.get("title"), "收盘交易决策日报")

    groups: list[str] = []
    for category, label in _PRIORITY_LABELS.items():
        values = [row for row in displayed_rows if _priority(row) == category]
        if not values:
            continue
        groups.append(_section_header(label, len(values)))
        groups.extend(_row_html(category, row) for row in values)

    if not groups:
        groups.append(
            '<tr><td style="padding:16px 0;color:#536176;">'
            "今天没有数据异常、持仓、交易方案、新确认或接近确认的重点标的。"
            "</td></tr>"
        )

    remaining = max(len(all_rows) - len(displayed_rows), 0)
    if len(all_rows) > EMAIL_MAX_HIGHLIGHTS and remaining:
        groups.append(
            '<tr><td style="padding:12px 0;color:#536176;font-size:13px;">'
            f"其余 {remaining} 只观察标的未展开。"
            "</td></tr>"
        )

    return (
        '<!doctype html><html lang="zh-CN"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title></head>"
        '<body style="margin:0;padding:0;background-color:#f2f4f7;color:#263246;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,Arial,sans-serif;font-size:15px;line-height:1.55;">'
        '<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;background-color:#f2f4f7;">'
        '<tr><td align="center" style="padding:12px 8px 24px 8px;">'
        '<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="width:100%;max-width:390px;border-collapse:collapse;">'
        '<tr><td style="padding:8px 0 12px 0;">'
        f'<h1 style="margin:0;color:#172033;font-size:22px;line-height:1.3;">{title}</h1>'
        f'<p style="margin:5px 0 0 0;color:#687386;">市场：{html.escape(market, quote=True)} · T：{trade_date}</p>'
        "</td></tr>"
        '<tr><td style="padding:12px;border:1px solid #d9dee8;border-radius:8px;background-color:#ffffff;">'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>市场</strong>：{html.escape(market, quote=True)}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>T</strong>：{trade_date}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>数据状态</strong>：{status}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>新确认数量</strong>：{summary["new_confirmed"]}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>接近确认数量</strong>：{summary["armed"]}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>交易方案数量</strong>：{summary["plans"]}</div>'
        f'<div style="padding:4px 0;border-bottom:1px solid #edf0f4;"><strong>持仓数量</strong>：{summary["positions"]}</div>'
        f'<div style="padding:4px 0;"><strong>数据异常数量</strong>：{summary["data_issues"]}</div>'
        "</td></tr>"
        + _alert_html(projection, summary["data_issues"])
        + "".join(groups)
        + _run_link_html(projection)
        + '<tr><td style="padding:18px 0 0 0;color:#8a94a6;font-size:12px;text-align:center;">'
        "本邮件为静态阅读摘要；完整交互 Dashboard 仍保留在日报 HTML artifact。"
        "</td></tr>"
        "</table></td></tr></table></body></html>"
    )


__all__ = ["EMAIL_MAX_HIGHLIGHTS", "render_daily_report_email_html"]
