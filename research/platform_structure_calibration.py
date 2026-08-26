"""Phase 5H SETUP_03 platform-structure calibration (research only).

The fixed tolerance sequence is evaluated through the production replay path.
This module aggregates structure and market heterogeneity only: it does not
consume forward returns, execution outcomes, or P&L and cannot select a
production parameter.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
from statistics import median

from core import Quote
from research.frozen_validation import validate_phase5e_baseline
from research.replay_input import ReplayInputManifest
from trading.indicators import atr
from trading.models import SetupState
from trading.replay import SymbolReplayReport, replay_setup03_history


CALIBRATION_TOLERANCES = (0.025, 0.03, 0.035, 0.04, 0.045, 0.05, 0.055, 0.075, 0.10)
PRIMARY_TOLERANCES = frozenset(CALIBRATION_TOLERANCES[:7])
VOLATILITY_WINDOW = 20


@dataclass(frozen=True)
class PlatformStructureArtifacts:
    market_rows: tuple[dict, ...]
    stability_rows: tuple[dict, ...]
    event_change_rows: tuple[dict, ...]
    concentration_rows: tuple[dict, ...]


def platform_structure_calibration_artifacts(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    production_setup_parameters: dict,
    decision_parameters: dict,
    manifest: ReplayInputManifest,
    parameter_version: str,
    tolerances: tuple[float, ...] = CALIBRATION_TOLERANCES,
) -> PlatformStructureArtifacts:
    """Run the fixed structure grid without ranking or parameter selection."""
    validate_phase5e_baseline(manifest, parameter_version)
    if tuple(tolerances) != CALIBRATION_TOLERANCES:
        raise ValueError("Phase 5H tolerance sequence is frozen")
    if not symbol_quotes or set(symbol_quotes) != {row.symbol for row in manifest.symbols}:
        raise ValueError("Phase 5H requires complete frozen dataset coverage")

    atr_period = int(decision_parameters.get("atr_period", 14))
    market_bars = Counter(q.market for quotes in symbol_quotes.values() for q in quotes)
    all_bars = sum(market_bars.values())
    if all_bars != manifest.total_bar_count:
        raise ValueError("Phase 5H bar conservation failed")

    normalizers = {
        symbol: _normalizers(quotes, atr_period)
        for symbol, quotes in symbol_quotes.items()
    }
    market_rows: list[dict] = []
    concentration_rows: list[dict] = []
    reports_by_tolerance: dict[float, dict[str, SymbolReplayReport]] = {}

    for tolerance in tolerances:
        setup_parameters = dict(production_setup_parameters)
        setup_parameters["platform_tolerance_pct"] = tolerance
        reports = {
            symbol: replay_setup03_history(
                quotes, risk_capital, setup_parameters, decision_parameters
            )
            for symbol, quotes in sorted(symbol_quotes.items())
        }
        reports_by_tolerance[tolerance] = reports
        if sum(len(report.days) for report in reports.values()) != all_bars:
            raise ValueError("Phase 5H replay-day conservation failed")

        markets = ("ALL", *sorted(market_bars))
        tolerance_rows = []
        for market in markets:
            selected = [
                report for report in reports.values()
                if market == "ALL" or report.market == market
            ]
            bars = all_bars if market == "ALL" else market_bars[market]
            tolerance_rows.append(
                _market_summary(tolerance, market, bars, selected, normalizers)
            )
        all_row = tolerance_rows[0]
        market_only = tolerance_rows[1:]
        for field in ("bars", "platform_identified", "WATCH", "ARMED", "CONFIRMED"):
            if sum(row[field] for row in market_only) != all_row[field]:
                raise ValueError(f"Phase 5H market conservation failed: {field}")
        market_rows.extend(tolerance_rows)
        concentration_rows.extend(_concentration_rows(tolerance, reports))

    stability_rows: list[dict] = []
    change_rows: list[dict] = []
    for previous, current in zip(tolerances, tolerances[1:]):
        summary, changes = _adjacent_stability(
            previous,
            current,
            reports_by_tolerance[previous],
            reports_by_tolerance[current],
        )
        stability_rows.extend(summary)
        change_rows.extend(changes)

    return PlatformStructureArtifacts(
        tuple(market_rows), tuple(stability_rows), tuple(change_rows),
        tuple(concentration_rows)
    )


def render_platform_structure_report(
    artifacts: PlatformStructureArtifacts, dataset_hash: str
) -> str:
    lines = [
        "# Phase 5H SETUP_03 Platform Structure Calibration",
        "",
        "> 只研究平台结构与市场异质性；不按收益优化，不选择 production tolerance，不启动 OOS。",
        "",
        f"- Frozen dataset：`{dataset_hash}`",
        "- 主研究区：`2.5%、3%、3.5%、4%、4.5%、5%、5.5%`",
        "- 压力测试边界：`7.5%、10%`",
        "- 标准化仅使用信号当日及以前数据：Wilder ATR 与 20 日 close-to-close 实现波动率。",
        "",
        "## 全样本与市场标准化结构",
        "",
        "| tolerance | 市场 | bars | 平台/千bar | CONFIRMED/千bar | high span median/P90 | low span median/P90 | 宽度/ATR median | 宽度/波动率价格 median |",
        "|---:|---|---:|---:|---:|---|---|---:|---:|",
    ]
    for row in artifacts.market_rows:
        lines.append(
            f"| {row['platform_tolerance_pct']:.1%} | {row['市场']} | {row['bars']} | "
            f"{row['platform_per_1000_bars']:.2f} | {row['confirmed_per_1000_bars']:.2f} | "
            f"{_pair(row['high_span_median'], row['high_span_P90'])} | "
            f"{_pair(row['low_span_median'], row['low_span_P90'])} | "
            f"{_number(row['platform_width_ATR_median'])} | "
            f"{_number(row['platform_width_realized_vol_median'])} |"
        )
    lines.extend((
        "", "## 相邻 tolerance 稳定性", "",
        "| 前档→后档 | 市场 | Jaccard | retention | 新增 | 消失 | 同标的匹配数 | 日期漂移 median/P90 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ))
    for row in artifacts.stability_rows:
        lines.append(
            f"| {row['前一tolerance']:.1%}→{row['当前tolerance']:.1%} | {row['市场']} | "
            f"{row['CONFIRMED_Jaccard']:.2%} | {row['retention']:.2%} | "
            f"{row['新增事件']} | {row['消失事件']} | {row['日期匹配事件']} | "
            f"{_days(row['日期漂移_median_days'])}/{_days(row['日期漂移_P90_days'])} |"
        )
    lines.extend((
        "", "## 解释边界", "",
        "市场统计同时给出绝对计数与每千 bar 发生率；集中度 CSV 另列 market/year/symbol 的最大份额与 HHI。",
        "事件稳定性使用 symbol+CONFIRMED date 的精确集合计算 Jaccard/retention；日期漂移则在同一标的内按最近日期一对一匹配，完整新增/消失明细另列 CSV。",
        "ATR/波动率标准化描述平台整体宽度，不改变 production Setup 的 percentage tolerance 判定。",
        "若观察到市场差异，只能作为下一阶段设计问题；本阶段禁止实施 market-specific 参数。", ""
    ))
    return "\n".join(lines)


def _market_summary(tolerance, market, bars, reports, normalizers):
    days = [day for report in reports for day in report.days]
    detected = [
        day for day in days
        if day.setup_diagnostics and day.setup_diagnostics.platform_detected_this_bar
    ]
    events = [
        event for report in reports for event in report.events
        if event.event_type is SetupState.CONFIRMED
    ]
    states = Counter(day.setup_state for day in days)
    high_spans = [d.setup_diagnostics.high_span for d in detected]
    low_spans = [d.setup_diagnostics.low_span for d in detected]
    high_counts = [d.setup_diagnostics.high_count for d in detected]
    low_counts = [d.setup_diagnostics.low_count for d in detected]
    asymmetry = [abs(h - l) for h, l in zip(high_spans, low_spans)]
    terminal_events = [event for report in reports for event in report.events]
    durations = [
        event.setup.confirmed_index - event.setup.detected_index + 1
        for event in terminal_events
        if event.setup.confirmed_index is not None and event.setup.detected_index is not None
    ] + [
        event.setup.state_entered_index - event.setup.detected_index + 1
        for event in terminal_events
        if event.event_type is SetupState.FAILED
        and event.setup.state_entered_index is not None
        and event.setup.detected_index is not None
    ]
    atr_widths = []
    rv_widths = []
    width_pcts = []
    for day in detected:
        diag = day.setup_diagnostics
        width = diag.breakout_price - diag.structural_invalidation
        close = diag.close
        if close and close > 0:
            width_pcts.append(width / close)
        index = diag.index
        atr_value, rv_value = normalizers[day.symbol][index]
        if atr_value and atr_value > 0:
            atr_widths.append(width / atr_value)
        if rv_value and close and rv_value > 0 and close > 0:
            rv_widths.append(width / (close * rv_value))
    return {
        "platform_tolerance_pct": tolerance,
        "研究区类型": "PRIMARY" if tolerance in PRIMARY_TOLERANCES else "STRESS_BOUNDARY",
        "市场": market,
        "bars": bars,
        "platform_identified": len(detected),
        "WATCH": states[SetupState.WATCH],
        "ARMED": states[SetupState.ARMED],
        "CONFIRMED": len(events),
        "platform_per_1000_bars": 1000 * len(detected) / bars,
        "confirmed_per_1000_bars": 1000 * len(events) / bars,
        "high_span_median": _quantile(high_spans, .5),
        "high_span_P75": _quantile(high_spans, .75),
        "high_span_P90": _quantile(high_spans, .9),
        "low_span_median": _quantile(low_spans, .5),
        "low_span_P75": _quantile(low_spans, .75),
        "low_span_P90": _quantile(low_spans, .9),
        "platform_duration_bars_median": _quantile(durations, .5),
        "platform_duration_sample_n": len(durations),
        "platform_duration_bars_P75": _quantile(durations, .75),
        "platform_duration_bars_P90": _quantile(durations, .9),
        "swing_high_count_median": _quantile(high_counts, .5),
        "swing_high_count_P90": _quantile(high_counts, .9),
        "swing_low_count_median": _quantile(low_counts, .5),
        "swing_low_count_P90": _quantile(low_counts, .9),
        "span_asymmetry_median": _quantile(asymmetry, .5),
        "span_asymmetry_P90": _quantile(asymmetry, .9),
        "platform_width_pct_median": _quantile(width_pcts, .5),
        "platform_width_pct_P90": _quantile(width_pcts, .9),
        "platform_width_ATR_n": len(atr_widths),
        "platform_width_ATR_median": _quantile(atr_widths, .5),
        "platform_width_ATR_P90": _quantile(atr_widths, .9),
        "platform_width_realized_vol_n": len(rv_widths),
        "platform_width_realized_vol_median": _quantile(rv_widths, .5),
        "platform_width_realized_vol_P90": _quantile(rv_widths, .9),
    }


def _normalizers(quotes, atr_period):
    atrs = atr(quotes, atr_period)
    returns = [None]
    for previous, current in zip(quotes, quotes[1:]):
        returns.append(float(current.close) / float(previous.close) - 1)
    result = []
    for i in range(len(quotes)):
        window = [v for v in returns[max(1, i - VOLATILITY_WINDOW + 1):i + 1] if v is not None]
        rv = None
        if len(window) >= VOLATILITY_WINDOW:
            mean = sum(window) / len(window)
            rv = sqrt(sum((v - mean) ** 2 for v in window) / (len(window) - 1))
        result.append((atrs[i], rv))
    return tuple(result)


def _event_map(reports, market):
    return {
        (event.symbol, event.confirmed_date or event.trade_date): event
        for report in reports.values()
        if market == "ALL" or report.market == market
        for event in report.events
        if event.event_type is SetupState.CONFIRMED
    }


def _adjacent_stability(previous, current, previous_reports, current_reports):
    markets = ("ALL", *sorted({r.market for r in previous_reports.values()} | {r.market for r in current_reports.values()}))
    summaries = []
    changes = []
    for market in markets:
        old = _event_map(previous_reports, market)
        new = _event_map(current_reports, market)
        old_keys, new_keys = set(old), set(new)
        retained = old_keys & new_keys
        union = old_keys | new_keys
        added, disappeared = new_keys - old_keys, old_keys - new_keys
        matches = _nearest_date_matches(disappeared, added)
        drifts = [abs((new_date - old_date).days) for _, old_date, new_date in matches]
        summaries.append({
            "前一tolerance": previous, "当前tolerance": current, "市场": market,
            "前一CONFIRMED": len(old_keys), "当前CONFIRMED": len(new_keys),
            "精确保留事件": len(retained),
            "CONFIRMED_Jaccard": len(retained) / len(union) if union else 1.0,
            "retention": len(retained) / len(old_keys) if old_keys else (1.0 if not new_keys else 0.0),
            "新增事件": len(added), "消失事件": len(disappeared),
            "日期匹配事件": len(matches),
            "日期漂移_median_days": _quantile(drifts, .5),
            "日期漂移_P90_days": _quantile(drifts, .9),
            "日期无漂移比例": sum(v == 0 for v in drifts) / len(drifts) if drifts else None,
        })
        if market == "ALL":
            matched_old = {(symbol, old_date) for symbol, old_date, _ in matches}
            matched_new = {(symbol, new_date) for symbol, _, new_date in matches}
            for symbol, event_date in sorted(retained):
                changes.append(_change(previous, current, symbol, event_date, event_date, "RETAINED"))
            for symbol, old_date, new_date in matches:
                changes.append(_change(previous, current, symbol, old_date, new_date, "DATE_DRIFT"))
            for symbol, event_date in sorted(disappeared - matched_old):
                changes.append(_change(previous, current, symbol, event_date, None, "DISAPPEARED"))
            for symbol, event_date in sorted(added - matched_new):
                changes.append(_change(previous, current, symbol, None, event_date, "ADDED"))
    return summaries, changes


def _nearest_date_matches(disappeared, added):
    candidates = sorted(
        (abs((new_date - old_date).days), symbol, old_date, new_date)
        for symbol, old_date in disappeared
        for new_symbol, new_date in added
        if symbol == new_symbol
    )
    used_old, used_new, matches = set(), set(), []
    for _, symbol, old_date, new_date in candidates:
        old_key, new_key = (symbol, old_date), (symbol, new_date)
        if old_key not in used_old and new_key not in used_new:
            used_old.add(old_key); used_new.add(new_key)
            matches.append((symbol, old_date, new_date))
    return matches


def _change(previous, current, symbol, old_date, new_date, status):
    return {
        "前一tolerance": previous, "当前tolerance": current, "symbol": symbol,
        "前一CONFIRMED日期": old_date.isoformat() if old_date else "",
        "当前CONFIRMED日期": new_date.isoformat() if new_date else "",
        "状态": status,
        "日期漂移_days": (new_date - old_date).days if old_date and new_date else None,
    }


def _concentration_rows(tolerance, reports):
    events = [
        (report.market, event.symbol, (event.confirmed_date or event.trade_date).year)
        for report in reports.values() for event in report.events
        if event.event_type is SetupState.CONFIRMED
    ]
    rows = []
    for scope in ("ALL", *sorted({report.market for report in reports.values()})):
        selected = [event for event in events if scope == "ALL" or event[0] == scope]
        total = len(selected)
        dimensions = (("market", 0), ("symbol", 1), ("year", 2)) if scope == "ALL" else (("symbol", 1), ("year", 2))
        for dimension, index in dimensions:
            counts = Counter(event[index] for event in selected)
            shares = [count / total for count in counts.values()] if total else []
            rows.append({
                "platform_tolerance_pct": tolerance, "范围": scope, "维度": dimension,
                "CONFIRMED": total, "分组数": len(counts),
                "最大分组": str(max(counts, key=counts.get)) if counts else "",
                "最大份额": max(shares, default=None),
                "HHI": sum(share * share for share in shares) if shares else None,
            })
    return rows


def _quantile(values, q):
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    position = (len(clean) - 1) * q
    lower = int(position); upper = min(lower + 1, len(clean) - 1)
    weight = position - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _pair(a, b):
    return "—" if a is None else f"{a:.2%}/{b:.2%}"


def _number(value):
    return "—" if value is None else f"{value:.2f}"


def _days(value):
    return "—" if value is None else f"{value:.1f}d"
