from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone

from core import (
    Quote,
    expected_latest_trade_date,
    fresher_quote,
    latest_quote,
    market_close_confirmed,
    quote_sanity_issue,
    validate_quotes,
)


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


def wanted_markets_for_group(group: str) -> set[str]:
    """Map scheduled job groups to every supported exchange market."""
    markets = {
        "asia": {"CN", "HK"},
        "us": {"US", "SE"},
    }
    return markets.get(group, {"CN", "HK", "US", "SE"})


def quote_row(quote: Quote, fetched_at: datetime, adjustment: str) -> dict:
    return {
        "统一代码": quote.symbol, "名称": quote.name, "市场": quote.market,
        "交易日期": quote.trade_date, "复权方式": adjustment, "数据源": quote.source,
        "开盘": quote.open, "最高": quote.high, "最低": quote.low, "收盘": quote.close,
        "昨收": quote.preclose, "涨跌幅": quote.pct_change, "成交量": quote.volume,
        "成交额": quote.amount, "换手率": quote.turnover_rate, "币种": quote.currency,
        "抓取时间": fetched_at,
    }


def fixture() -> None:
    first = Quote("000725.SZ", "京东方A", "CN", date(2026, 8, 14), "AKShare", 4.1, 4.2, 4.0, 4.15, 4.08, 1.72, 100_000_000, 415_000_000, 1.2, "CNY")
    second = Quote("000725.SZ", "京东方A", "CN", date(2026, 8, 14), "BaoStock", 4.1, 4.2, 4.0, 4.1505, 4.08, 1.73, 99_500_000, 413_000_000, 1.2, "CNY")
    print(json.dumps(validate_quotes(first, second, 0.0005, 0.02).__dict__, ensure_ascii=False, indent=2))


def run(group: str) -> None:
    from providers import fetch_with_retry
    from sheets_client import HISTORY_HEADERS, LOG_HEADERS, VALIDATION_HEADERS, SheetsClient

    client = SheetsClient()
    config = client.config()
    history_days = int(float(config.get("history_days", 1000)))
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    close_tolerance = as_ratio(config.get("close_tolerance_pct"), 0.0005)
    volume_tolerance = as_ratio(config.get("volume_tolerance_pct"), 0.02)
    write_adjusted = as_bool(config.get("write_adjusted", True))
    fetched_at = datetime.now(timezone.utc)
    end = fetched_at.date()
    start = end - timedelta(days=max(history_days * 2, 365))
    wanted_markets = wanted_markets_for_group(group)

    latest_rows, raw_rows, adjusted_rows, validation_rows, log_rows = [], [], [], [], []
    for watch in client.records("自选清单"):
        if not as_bool(watch.get("启用")) or str(watch.get("市场")) not in wanted_markets:
            continue
        primary_source = str(watch.get("主数据源") or "").strip()
        verifier_source = str(watch.get("校验数据源") or "").strip()
        primary_quotes = []
        verifier_quotes = []
        errors = []
        for source, target in ((primary_source, primary_quotes), (verifier_source, verifier_quotes)):
            if not source:
                continue
            try:
                target.extend(fetch_with_retry(source, watch, "raw", start, end, retry_count, retry_wait))
            except Exception as exc:
                errors.append(str(exc))

        primary = latest_quote(primary_quotes)
        verifier = latest_quote(verifier_quotes)
        result = validate_quotes(primary, verifier, close_tolerance, volume_tolerance)
        chosen = fresher_quote(primary, verifier)
        if chosen is None:
            log_rows.append({"运行时间": fetched_at, "任务组": group, "市场": watch["市场"], "统一代码": watch["统一代码"], "执行状态": "失败", "新增／更新行数": 0, "消息": "；".join(errors)})
            continue

        expected_date = expected_latest_trade_date(
            str(watch["时区"]), str(watch["收盘时间"]), fetched_at
        )
        stale_note = ""
        sanity_note = quote_sanity_issue(chosen) or ""
        displayed_status = result.status
        if expected_date is not None and chosen.trade_date < expected_date:
            displayed_status = "待复核"
            stale_note = f"收盘后数据仍停留在{chosen.trade_date.isoformat()}，期望日期为{expected_date.isoformat()}"
        if sanity_note:
            displayed_status = "待复核"

        confirmed = displayed_status == "已验证" and market_close_confirmed(
            chosen.trade_date, str(watch["时区"]), str(watch["收盘时间"]), fetched_at
        )
        notes = [item for item in (result.note, stale_note, sanity_note, "；".join(errors)) if item]
        latest_rows.append({
            "统一代码": chosen.symbol, "名称": chosen.name, "市场": chosen.market,
            "交易日期": chosen.trade_date, "抓取时间": fetched_at, "正式收盘": confirmed,
            "校验状态": displayed_status, "主数据源": primary_source, "校验数据源": verifier_source,
            "开盘": chosen.open, "最高": chosen.high, "最低": chosen.low, "收盘": chosen.close,
            "昨收": chosen.preclose, "涨跌幅": chosen.pct_change, "成交量": chosen.volume,
            "成交额": chosen.amount, "换手率": chosen.turnover_rate,
            "收盘价差异": result.close_diff, "成交量差异": result.volume_diff,
            "币种": chosen.currency, "备注": "；".join(notes),
        })
        validation_rows.append({
            "抓取时间": fetched_at, "统一代码": chosen.symbol, "交易日期": chosen.trade_date,
            "主数据源": primary_source, "校验数据源": verifier_source,
            "主源收盘": primary.close if primary else None, "校验源收盘": verifier.close if verifier else None,
            "收盘价差异": result.close_diff, "主源成交量": primary.volume if primary else None,
            "校验源成交量": verifier.volume if verifier else None, "成交量差异": result.volume_diff,
            "日期一致": result.date_match, "价格通过": result.close_pass, "成交量通过": result.volume_pass,
            "校验状态": displayed_status, "说明": "；".join(item for item in (result.note, stale_note, sanity_note) if item),
        })
        if verifier is not None and (primary is None or verifier.trade_date > primary.trade_date):
            history_source, history_quotes = verifier_source, verifier_quotes
        else:
            history_source, history_quotes = primary_source, primary_quotes
        raw_for_symbol = [quote_row(item, fetched_at, "未复权") for item in history_quotes[-history_days:]]
        adjusted_for_symbol = []
        raw_rows.extend(raw_for_symbol)
        if write_adjusted:
            try:
                adjusted = fetch_with_retry(history_source, watch, "qfq", start, end, retry_count, retry_wait)
                adjusted_for_symbol = [quote_row(item, fetched_at, "前复权") for item in adjusted[-history_days:]]
                adjusted_rows.extend(adjusted_for_symbol)
            except Exception as exc:
                errors.append(f"前复权失败：{exc}")
        log_rows.append({"运行时间": fetched_at, "任务组": group, "市场": watch["市场"], "统一代码": watch["统一代码"], "执行状态": displayed_status, "新增／更新行数": len(raw_for_symbol) + len(adjusted_for_symbol), "消息": "；".join(notes)})

    changed = client.upsert_latest(latest_rows)
    changed += client.upsert_history("历史行情_未复权", raw_rows)
    if write_adjusted:
        changed += client.upsert_history("历史行情_前复权", adjusted_rows)
    client.append_rows("校验记录", VALIDATION_HEADERS, validation_rows)
    client.append_rows("运行日志", LOG_HEADERS, log_rows)
    print(f"完成：最新行情{len(latest_rows)}个，写入／更新{changed}行。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["asia", "us", "all"], default="all")
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    fixture() if args.fixture else run(args.group)
