from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core import (
    Quote,
    expected_latest_trade_date,
    fresher_quote,
    latest_quote,
    latest_completed_market_session,
    market_close_confirmed,
    ordinary_calendar_freshness_guard,
    quote_sanity_issue,
    validate_quotes,
)
from trading.events import (
    DecisionEventKey,
    evaluate_setup03_event,
    setup03_decision_key,
)
from trading.models import Decision, Setup, SetupState


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    """Return the pipeline timestamp in the spreadsheet's canonical timezone."""
    return datetime.now(BEIJING_TIMEZONE)


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def as_ratio(value, default: float) -> float:
    """Parse a decimal ratio or a percentage string from Google Sheets."""
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    if text.endswith("%"):
        return float(text[:-1].strip()) / 100
    return float(text)


def required_config(config: dict, key: str):
    """Return an explicitly configured value; Decision parameters never default."""
    value = config.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"参数设置缺少必填参数：{key}")
    return value


def trading_parameters(config: dict) -> tuple[dict, dict, float]:
    """Parse every SETUP_03/Decision argument from 参数设置."""
    setup_parameters = {
        "swing_lookback": int(float(required_config(config, "setup_swing_lookback"))),
        "platform_window": int(float(required_config(config, "setup_platform_window"))),
        "platform_tolerance_pct": as_ratio(
            required_config(config, "setup_platform_tolerance_pct"), 0.0
        ),
        "arm_proximity_pct": as_ratio(
            required_config(config, "setup_arm_proximity_pct"), 0.0
        ),
    }
    decision_parameters = {
        "swing_lookback": int(
            float(required_config(config, "decision_swing_lookback"))
        ),
        "atr_period": int(float(required_config(config, "decision_atr_period"))),
        "atr_buffer": float(required_config(config, "decision_atr_buffer")),
        "max_chase_atr": float(required_config(config, "decision_max_chase_atr")),
    }
    risk_capital = float(required_config(config, "decision_risk_capital"))
    return setup_parameters, decision_parameters, risk_capital


def wanted_markets_for_group(group: str) -> set[str]:
    """Map scheduled job groups to every supported exchange market."""
    markets = {
        "asia": {"CN", "HK", "JP"},
        "us": {"US", "SE"},
    }
    return markets.get(group, {"CN", "HK", "JP", "US", "SE"})


def quote_row(quote: Quote, fetched_at: datetime, adjustment: str) -> dict:
    return {
        "统一代码": quote.symbol, "名称": quote.name, "市场": quote.market,
        "交易日期": quote.trade_date, "复权方式": adjustment, "数据源": quote.source,
        "开盘": quote.open, "最高": quote.high, "最低": quote.low, "收盘": quote.close,
        "昨收": quote.preclose, "涨跌幅": quote.pct_change, "成交量": quote.volume,
        "成交额": quote.amount, "换手率": quote.turnover_rate, "币种": quote.currency,
        "抓取时间": fetched_at,
    }


def decision_row(
    quote: Quote,
    setup: Setup,
    decision: Decision,
    fetched_at: datetime,
    confirmed_date: date | None,
    risk_capital: float,
    data_source: str,
) -> dict:
    """Project an existing Trading Core Decision into display-only Sheet fields."""
    entry = decision.entry_plan
    rr = decision.rr
    position = decision.position_size
    targets = decision.targets
    ratios = rr.rr_ratios if rr is not None else ()
    return {
        "统一代码": quote.symbol,
        "交易日期": quote.trade_date,
        "Setup类型": setup.setup_type,
        "名称": quote.name,
        "市场": quote.market,
        "币种": quote.currency,
        "决策时间": fetched_at,
        "Setup状态": setup.state.value,
        "确认日期": confirmed_date,
        "决策动作": decision.action.value,
        "计划入场": entry.planned_entry if entry else None,
        "入场区间下沿": entry.entry_zone_low if entry else None,
        "入场区间上沿": entry.entry_zone_high if entry else None,
        "试探入场": entry.probe_entry if entry else None,
        "确认入场": entry.confirmation_entry if entry else None,
        "确认条件": entry.confirmation_conditions if entry else None,
        "结构失效价": decision.structural_invalidation,
        "执行止损": decision.execution_stop,
        "每股风险": rr.risk_per_share if rr else None,
        "T1": targets[0] if len(targets) > 0 else None,
        "T2": targets[1] if len(targets) > 1 else None,
        "T3": targets[2] if len(targets) > 2 else None,
        "T1_RR": ratios[0] if ratios else None,
        "RR质量": rr.quality if rr else None,
        "风险资本": risk_capital,
        "理论数量": position.theoretical_quantity if position else None,
        "最大损失": position.max_loss if position else None,
        "数据源": data_source,
        "数据序列": "前复权",
        "写入时间": fetched_at,
    }


def published_setup03_decision_keys(rows: list[dict]) -> set[DecisionEventKey]:
    """Read the production event-stream keys used to make reruns idempotent."""
    return {
        setup03_decision_key(
            str(row.get("统一代码") or "").strip(),
            str(row.get("交易日期") or "").strip(),
            str(row.get("Setup类型") or "").strip(),
        )
        for row in rows
        if str(row.get("统一代码") or "").strip()
        and str(row.get("交易日期") or "").strip()
        and str(row.get("Setup类型") or "").strip() == "SETUP_03"
    }


def evaluate_set03_decision(
    qfq_quotes: list[Quote],
    chosen_trade_date: date,
    confirmed: bool,
    risk_capital: float,
    setup_parameters: dict,
    decision_parameters: dict,
    published_decision_keys: set[DecisionEventKey] | None = None,
) -> tuple[tuple[Setup, Decision, date | None] | None, str]:
    """Return only a new, unpublished CONFIRMED Decision event."""
    if not confirmed:
        return None, "SETUP_03 Decision跳过：尚非正式收盘"
    if not qfq_quotes:
        return None, "SETUP_03 Decision跳过：前复权历史为空"
    if qfq_quotes[-1].trade_date != chosen_trade_date:
        return None, (
            "SETUP_03 Decision跳过：前复权末日"
            f"{qfq_quotes[-1].trade_date.isoformat()}与行情日"
            f"{chosen_trade_date.isoformat()}不一致"
        )

    evaluation = evaluate_setup03_event(
        qfq_quotes,
        risk_capital,
        setup_parameters,
        decision_parameters,
        published_decision_keys or (),
    )
    if evaluation.event_type is not SetupState.CONFIRMED:
        return None, (
            "SETUP_03 Decision跳过：当前最后一根K线无新CONFIRMED事件"
            f"（Setup状态={evaluation.setup.state.value}）"
        )
    if evaluation.duplicate:
        return None, "SETUP_03 Decision跳过：该CONFIRMED事件已发布"
    assert evaluation.decision is not None
    return (
        evaluation.setup,
        evaluation.decision,
        evaluation.confirmed_date,
    ), ""


def select_history_series(
    primary_source: str,
    primary_quotes: list[Quote],
    verifier_source: str,
    verifier_quotes: list[Quote],
    chosen: Quote,
    max_trade_date: date | None = None,
) -> tuple[str, list[Quote]]:
    """Prefer a real historical series over a one-row snapshot response."""
    options = []
    for source, quotes in (
        (primary_source, primary_quotes),
        (verifier_source, verifier_quotes),
    ):
        bounded = [
            quote for quote in quotes
            if max_trade_date is None or quote.trade_date <= max_trade_date
        ]
        if source and bounded:
            options.append((source, bounded))
    if not options:
        return "yfinance", [chosen]
    history_source, history_quotes = max(options, key=lambda item: len(item[1]))
    history_quotes = sorted(history_quotes, key=lambda item: item.trade_date)
    if history_quotes[-1].trade_date < chosen.trade_date:
        history_quotes.append(chosen)
    elif history_quotes[-1].trade_date == chosen.trade_date:
        # Keep the published raw history consistent with the sanity-aware
        # quote selected for 最新行情.
        history_quotes[-1] = chosen
    return history_source, history_quotes


def fixture() -> None:
    first = Quote("000725.SZ", "京东方A", "CN", date(2026, 8, 14), "yfinance", 4.1, 4.2, 4.0, 4.15, 4.08, 1.72, 100_000_000, 415_000_000, 1.2, "CNY")
    second = Quote("000725.SZ", "京东方A", "CN", date(2026, 8, 14), "BaoStock", 4.1, 4.2, 4.0, 4.1505, 4.08, 1.73, 99_500_000, 413_000_000, 1.2, "CNY")
    print(json.dumps(validate_quotes(first, second, 0.0005, 0.02).__dict__, ensure_ascii=False, indent=2))


def run(group: str, mode: str = "full") -> dict:
    if mode not in {"latest", "full"}:
        raise ValueError(f"未知执行模式：{mode}，仅支持 latest 或 full")

    from providers import (
        QFQ_HISTORY_SOURCES,
        fetch_latest_with_retry,
        fetch_with_retry,
    )
    from sheets_client import HISTORY_HEADERS, LOG_HEADERS, VALIDATION_HEADERS, SheetsClient

    client = SheetsClient()
    config = client.config()
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    close_tolerance = as_ratio(config.get("close_tolerance_pct"), 0.0005)
    volume_tolerance = as_ratio(config.get("volume_tolerance_pct"), 0.02)
    if mode == "full":
        history_days = int(float(config.get("history_days", 1000)))
        write_adjusted = as_bool(config.get("write_adjusted", True))
        setup_parameters, decision_parameters, risk_capital = trading_parameters(config)
    fetched_at = beijing_now()
    end = fetched_at.date()
    start = (
        end - timedelta(days=max(history_days * 2, 365))
        if mode == "full"
        else None
    )
    wanted_markets = wanted_markets_for_group(group)

    watchlist = client.records("自选清单")
    requested_symbols = [
        watch for watch in watchlist
        if as_bool(watch.get("启用")) and str(watch.get("市场")) in wanted_markets
    ]
    published_decision_keys = (
        published_setup03_decision_keys(client.records("交易决策"))
        if mode == "full"
        else set()
    )
    latest_rows, raw_rows, adjusted_rows = [], [], []
    validation_rows, decision_rows, log_rows = [], [], []
    verified_count = 0
    single_source_current_count = 0
    pending_review_count = 0
    stale_sources_rejected = 0
    failed_symbols: list[str] = []
    for watch in watchlist:
        if not as_bool(watch.get("启用")) or str(watch.get("市场")) not in wanted_markets:
            continue
        primary_source = str(watch.get("主数据源") or "").strip()
        verifier_source = str(watch.get("校验数据源") or "").strip()
        historical_source = str(watch.get("历史数据源") or "").strip() if mode == "full" else ""
        primary_quotes = []
        verifier_quotes = []
        errors = []
        for source, target in ((primary_source, primary_quotes), (verifier_source, verifier_quotes)):
            if not source:
                continue
            try:
                if mode == "latest":
                    target.extend(
                        fetch_latest_with_retry(
                            source, watch, end, retry_count, retry_wait
                        )
                    )
                else:
                    target.extend(
                        fetch_with_retry(
                            source, watch, "raw", start, end, retry_count, retry_wait,
                        )
                    )
            except Exception as exc:
                errors.append(str(exc))

        local_today = fetched_at.astimezone(ZoneInfo(str(watch["时区"]))).date()
        future_quotes = [
            quote for quote in (*primary_quotes, *verifier_quotes)
            if quote.trade_date > local_today
        ]
        future_note = ""
        if future_quotes:
            future_dates = ",".join(
                sorted({quote.trade_date.isoformat() for quote in future_quotes})
            )
            future_note = f"未来交易日行情已拒绝：{future_dates}"
            errors.append(future_note)
            stale_sources_rejected += len({quote.source for quote in future_quotes})
        completed_date = latest_completed_market_session(
            str(watch["时区"]),
            str(watch["收盘时间"]),
            fetched_at,
            (*primary_quotes, *verifier_quotes),
        )
        if completed_date is None:
            failed_symbols.append(str(watch.get("统一代码") or ""))
            errors.append("无法根据有效来源确定最新已完成市场交易日，已拒绝发布")
            log_rows.append({
                "运行时间": fetched_at, "任务组": group, "市场": watch["市场"],
                "统一代码": watch["统一代码"], "执行状态": "失败",
                "新增／更新行数": 0, "消息": "；".join(errors),
            })
            continue

        calendar_stale_note = ""
        if mode == "latest":
            calendar_guard = ordinary_calendar_freshness_guard(
                str(watch["时区"]),
                str(watch["收盘时间"]),
                fetched_at,
            )
            if completed_date < calendar_guard:
                calendar_stale_note = (
                    f"有效来源最新日期{completed_date.isoformat()}"
                    f"早于普通日历freshness guard{calendar_guard.isoformat()}；"
                    "不推断交易所节假日，行情仅保留显示并待复核"
                )

        primary = latest_quote(primary_quotes, max_trade_date=completed_date)
        verifier = latest_quote(verifier_quotes, max_trade_date=completed_date)
        if primary is not None and verifier is not None and primary.trade_date != verifier.trade_date:
            stale_sources_rejected += 1
        primary_sanity_issue = quote_sanity_issue(primary) if primary is not None else None
        verifier_sanity_issue = quote_sanity_issue(verifier) if verifier is not None else None
        result = validate_quotes(primary, verifier, close_tolerance, volume_tolerance)
        chosen = fresher_quote(primary, verifier)
        source_selection_note = ""
        if (
            chosen is verifier
            and primary is not None
            and verifier is not None
            and primary.trade_date == verifier.trade_date
            and primary_sanity_issue
            and not verifier_sanity_issue
        ):
            issue = primary_sanity_issue.removeprefix("行情字段异常：")
            source_selection_note = (
                f"主数据源{primary.source}字段异常（{issue}），"
                f"最终行情采用{verifier.source}"
            )
        if chosen is None:
            failed_symbols.append(str(watch.get("统一代码") or ""))
            log_rows.append({"运行时间": fetched_at, "任务组": group, "市场": watch["市场"], "统一代码": watch["统一代码"], "执行状态": "失败", "新增／更新行数": 0, "消息": "；".join(errors)})
            continue

        stale_note = ""
        sanity_note = quote_sanity_issue(chosen) or ""
        displayed_status = result.status
        if chosen.trade_date != completed_date:
            displayed_status = "待复核"
            stale_note = (
                f"选中行情日期{chosen.trade_date.isoformat()}"
                f"早于最新已完成市场交易日{completed_date.isoformat()}"
            )
        if sanity_note:
            displayed_status = "待复核"
        if future_note:
            displayed_status = "待复核"
        if calendar_stale_note:
            displayed_status = "待复核"

        freshness_single_source = "最新交易日仅单源可用" in result.note
        if displayed_status == "已验证":
            verified_count += 1
        if result.status == "单源可用" or freshness_single_source:
            single_source_current_count += 1
        if displayed_status != "已验证":
            pending_review_count += 1

        confirmed = displayed_status == "已验证" and market_close_confirmed(
            chosen.trade_date, str(watch["时区"]), str(watch["收盘时间"]), fetched_at
        )
        fallback_notes = []
        if primary is not None and primary.source != primary_source:
            fallback_notes.append(f"主数据源{primary_source}回退至{primary.source}")
        if verifier is not None and verifier.source != verifier_source:
            fallback_notes.append(f"校验数据源{verifier_source}回退至{verifier.source}")
        actual_primary_source = primary.source if primary is not None else primary_source
        actual_verifier_source = verifier.source if verifier is not None else verifier_source
        notes = [
            item for item in
            (
                result.note,
                stale_note,
                calendar_stale_note,
                sanity_note,
                future_note,
                source_selection_note,
                "；".join(fallback_notes),
            )
            if item
        ]
        latest_rows.append({
            "统一代码": chosen.symbol, "名称": chosen.name, "市场": chosen.market,
            "交易日期": chosen.trade_date, "抓取时间": fetched_at, "正式收盘": confirmed,
            "校验状态": displayed_status, "主数据源": actual_primary_source,
            "校验数据源": actual_verifier_source,
            "开盘": chosen.open, "最高": chosen.high, "最低": chosen.low, "收盘": chosen.close,
            "昨收": chosen.preclose, "涨跌幅": chosen.pct_change, "成交量": chosen.volume,
            "成交额": chosen.amount, "换手率": chosen.turnover_rate,
            "收盘价差异": result.close_diff, "成交量差异": result.volume_diff,
            "币种": chosen.currency, "备注": "；".join((*notes, *errors)),
        })
        validation_rows.append({
            "抓取时间": fetched_at, "统一代码": chosen.symbol, "交易日期": chosen.trade_date,
            "主数据源": actual_primary_source, "校验数据源": actual_verifier_source,
            "主源收盘": primary.close if primary else None, "校验源收盘": verifier.close if verifier else None,
            "收盘价差异": result.close_diff, "主源成交量": primary.volume if primary else None,
            "校验源成交量": verifier.volume if verifier else None, "成交量差异": result.volume_diff,
            "日期一致": result.date_match, "价格通过": result.close_pass, "成交量通过": result.volume_pass,
            "校验状态": displayed_status,
            "说明": "；".join(
                item
                for item in (
                    result.note,
                    stale_note,
                    calendar_stale_note,
                    sanity_note,
                    future_note,
                    source_selection_note,
                )
                if item
            ),
        })
        raw_for_symbol = []
        adjusted_for_symbol = []
        adjusted = []
        if mode == "full":
            _, history_quotes = select_history_series(
                primary_source, primary_quotes, verifier_source, verifier_quotes,
                chosen, max_trade_date=completed_date,
            )
            raw_for_symbol = [
                quote_row(item, fetched_at, "未复权")
                for item in history_quotes[-history_days:]
            ]
            raw_rows.extend(raw_for_symbol)
            if write_adjusted or confirmed:
                if not historical_source:
                    errors.append("前复权失败：自选清单缺少历史数据源")
                elif historical_source not in QFQ_HISTORY_SOURCES:
                    errors.append(f"前复权失败：历史数据源{historical_source}不支持qfq")
                else:
                    try:
                        adjusted = fetch_with_retry(
                            historical_source,
                            watch,
                            "qfq",
                            start,
                            end,
                            retry_count,
                            retry_wait,
                            target_trade_date=chosen.trade_date,
                        )
                    except Exception as exc:
                        errors.append(f"前复权失败：{exc}")
            if write_adjusted and adjusted:
                adjusted_for_symbol = [
                    quote_row(item, fetched_at, "前复权")
                    for item in adjusted[-history_days:]
                ]
                adjusted_rows.extend(adjusted_for_symbol)

            try:
                decision_result, decision_note = evaluate_set03_decision(
                    adjusted,
                    chosen.trade_date,
                    confirmed,
                    risk_capital,
                    setup_parameters,
                    decision_parameters,
                    published_decision_keys,
                )
            except Exception as exc:
                errors.append(f"SETUP_03 Decision失败：{exc}")
            else:
                if decision_result is None:
                    errors.append(decision_note)
                else:
                    setup, decision, confirmed_date = decision_result
                    decision_rows.append(
                        decision_row(
                            adjusted[-1],
                            setup,
                            decision,
                            fetched_at,
                            confirmed_date,
                            risk_capital,
                            adjusted[-1].source,
                        )
                    )
                    published_decision_keys.add(
                        setup03_decision_key(
                            adjusted[-1].symbol,
                            adjusted[-1].trade_date,
                            setup.setup_type,
                        )
                    )
        log_rows.append({"运行时间": fetched_at, "任务组": group, "市场": watch["市场"], "统一代码": watch["统一代码"], "执行状态": displayed_status, "新增／更新行数": len(raw_for_symbol) + len(adjusted_for_symbol), "消息": "；".join(item for item in (*notes, *errors) if item)})

    changed = client.upsert_latest(latest_rows)
    if mode == "full":
        changed += client.upsert_history("历史行情_未复权", raw_rows)
        if write_adjusted:
            changed += client.upsert_history("历史行情_前复权", adjusted_rows)
        changed += client.upsert_decisions(decision_rows)
    client.append_rows("校验记录", VALIDATION_HEADERS, validation_rows)
    client.append_rows("运行日志", LOG_HEADERS, log_rows)
    summary = {
        "mode": mode,
        "symbols_requested": len(requested_symbols),
        "freshest_rows_written": len(latest_rows),
        "verified": verified_count,
        "single_source_current": single_source_current_count,
        "pending_review": pending_review_count,
        "stale_sources_rejected": stale_sources_rejected,
        "failed_symbols": len(failed_symbols),
        "failed_symbol_list": failed_symbols,
        "history_rows_written": len(raw_rows) + len(adjusted_rows),
        "decision_rows_written": len(decision_rows),
        "status": "SUCCESS" if pending_review_count == 0 and not failed_symbols else "PARTIAL_DATA_QUALITY",
    }
    print("RUN_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["asia", "us", "all"], default="all")
    parser.add_argument("--mode", choices=["latest", "full"], default="full")
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    fixture() if args.fixture else run(args.group, args.mode)
