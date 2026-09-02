from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    market: str
    trade_date: date
    source: str
    open: float
    high: float
    low: float
    close: float
    preclose: Optional[float]
    pct_change: Optional[float]
    volume: Optional[float]
    amount: Optional[float]
    turnover_rate: Optional[float]
    currency: str


@dataclass(frozen=True)
class ValidationResult:
    status: str
    date_match: bool
    close_pass: bool
    volume_pass: bool
    close_diff: Optional[float]
    volume_diff: Optional[float]
    note: str


def relative_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    denominator = max(abs(float(a)), abs(float(b)), 1e-12)
    return abs(float(a) - float(b)) / denominator


def validate_quotes(
    primary: Optional[Quote],
    verifier: Optional[Quote],
    close_tolerance: float,
    volume_tolerance: float,
) -> ValidationResult:
    if primary is None and verifier is None:
        return ValidationResult("抓取失败", False, False, False, None, None, "两个来源均不可用")
    if primary is None or verifier is None:
        return ValidationResult("单源可用", False, False, False, None, None, "仅一个来源返回数据")
    if primary.source == verifier.source:
        return ValidationResult(
            "单源可用", False, False, False, None, None,
            f"主源和校验源均回退至同一数据源：{primary.source}",
        )

    date_match = primary.trade_date == verifier.trade_date
    close_diff = relative_diff(primary.close, verifier.close)
    volume_diff = relative_diff(primary.volume, verifier.volume)
    close_pass = date_match and close_diff is not None and close_diff <= close_tolerance
    volume_pass = date_match and volume_diff is not None and volume_diff <= volume_tolerance

    if not date_match:
        if primary.trade_date < verifier.trade_date:
            note = "主源日期滞后，已采用更新来源；最新交易日仅单源可用"
        else:
            note = "校验源日期滞后，已采用更新来源；最新交易日仅单源可用"
        return ValidationResult(
            "待复核", False, False, False, close_diff, volume_diff, note
        )

    if close_pass and volume_pass:
        return ValidationResult("已验证", True, True, True, close_diff, volume_diff, "日期、收盘价和成交量均通过校验")
    if close_pass:
        return ValidationResult(
            "已验证",
            True,
            True,
            False,
            close_diff,
            volume_diff,
            "日期、收盘价通过校验；成交量差异超限或缺失（仅提示，不影响行情可用性）",
        )
    return ValidationResult("待复核", True, False, volume_pass, close_diff, volume_diff, "收盘价差异超限")


def market_close_confirmed(
    trade_date: date,
    timezone_name: str,
    close_time_text: str,
    fetched_at: datetime,
    buffer_minutes: int = 20,
) -> bool:
    zone = ZoneInfo(timezone_name)
    local_now = fetched_at.astimezone(zone)
    hour, minute = (int(part) for part in close_time_text.split(":", 1))
    close_at = datetime.combine(trade_date, time(hour, minute), zone) + timedelta(minutes=buffer_minutes)
    return local_now >= close_at


def expected_latest_trade_date(
    timezone_name: str,
    close_time_text: str,
    fetched_at: datetime,
    buffer_minutes: int = 20,
    observed_quotes: Iterable[Quote] | None = None,
) -> Optional[date]:
    """Return a compatibility wall-clock expectation or source-evidence date.

    Production latest mode passes observed quotes and uses the evidence-based
    result.  The no-observation form remains for compatibility callers only;
    it is not a sufficient production freshness guard on delayed runs.
    """
    if observed_quotes is not None:
        return latest_completed_market_session(
            timezone_name,
            close_time_text,
            fetched_at,
            observed_quotes,
            buffer_minutes,
        )

    zone = ZoneInfo(timezone_name)
    local_now = fetched_at.astimezone(zone)
    if local_now.weekday() >= 5:
        return None
    hour, minute = (int(part) for part in close_time_text.split(":", 1))
    close_at = datetime.combine(local_now.date(), time(hour, minute), zone) + timedelta(minutes=buffer_minutes)
    return local_now.date() if local_now >= close_at else None


def ordinary_calendar_freshness_guard(
    timezone_name: str,
    close_time_text: str,
    fetched_at: datetime,
    buffer_minutes: int = 20,
) -> date:
    """Return a deterministic ordinary-weekday freshness lower bound.

    This is only a freshness guard.  It deliberately does not assert that
    the market was open on the returned weekday and does not use an exchange
    holiday calendar.
    """
    zone = ZoneInfo(timezone_name)
    local_now = fetched_at.astimezone(zone)
    guard_date = local_now.date()
    if local_now.weekday() >= 5:
        while guard_date.weekday() >= 5:
            guard_date -= timedelta(days=1)
        return guard_date

    hour, minute = (int(part) for part in close_time_text.split(":", 1))
    close_at = datetime.combine(
        guard_date, time(hour, minute), zone
    ) + timedelta(minutes=buffer_minutes)
    if local_now >= close_at:
        return guard_date

    guard_date -= timedelta(days=1)
    while guard_date.weekday() >= 5:
        guard_date -= timedelta(days=1)
    return guard_date


def latest_completed_market_session(
    timezone_name: str,
    close_time_text: str,
    fetched_at: datetime,
    observed_quotes: Iterable[Quote],
    buffer_minutes: int = 20,
) -> Optional[date]:
    """Return the latest completed session supported by sane source quotes.

    A quote dated today is accepted only after that market's close buffer.
    Weekend and delayed runs retain the newest valid observed session.  Dates
    after the market-local current date and internally invalid OHLCV quotes
    are excluded; the caller can report those exclusions explicitly.
    """
    zone = ZoneInfo(timezone_name)
    local_now = fetched_at.astimezone(zone)
    hour, minute = (int(part) for part in close_time_text.split(":", 1))
    close_at = datetime.combine(
        local_now.date(), time(hour, minute), zone
    ) + timedelta(minutes=buffer_minutes)
    completed_dates = {
        quote.trade_date
        for quote in observed_quotes
        if quote.trade_date <= local_now.date()
        and (quote.trade_date < local_now.date() or local_now >= close_at)
        and quote_sanity_issue(quote) is None
    }
    return max(completed_dates, default=None)


def latest_quote(
    quotes: list[Quote], max_trade_date: date | None = None
) -> Optional[Quote]:
    if not quotes:
        return None
    candidates = [
        quote for quote in quotes
        if max_trade_date is None or quote.trade_date <= max_trade_date
    ]
    return max(candidates, key=lambda item: item.trade_date) if candidates else None


def fresher_quote(primary: Optional[Quote], verifier: Optional[Quote]) -> Optional[Quote]:
    """Prefer a sane newer quote, then provider priority for equal dates."""
    if primary is None:
        return verifier
    if verifier is None:
        return primary

    primary_issue = quote_sanity_issue(primary)
    verifier_issue = quote_sanity_issue(verifier)
    if primary_issue and not verifier_issue:
        return verifier
    if verifier_issue and not primary_issue:
        return primary
    if primary.trade_date > verifier.trade_date:
        return primary
    if verifier.trade_date > primary.trade_date:
        return verifier
    return primary


def quote_sanity_issue(quote: Quote) -> Optional[str]:
    """Return a reason when an OHLCV quote is internally inconsistent."""
    if quote.low > quote.high:
        return "行情字段异常：最低价高于最高价"
    if not quote.low <= quote.open <= quote.high:
        return "行情字段异常：开盘价不在最低价和最高价之间"
    if not quote.low <= quote.close <= quote.high:
        return "行情字段异常：收盘价不在最低价和最高价之间"
    if quote.volume is not None and quote.volume < 0:
        return "行情字段异常：成交量为负数"
    return None
