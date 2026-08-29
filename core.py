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

    if date_match and close_pass and volume_pass:
        return ValidationResult("已验证", True, True, True, close_diff, volume_diff, "日期、收盘价和成交量均通过校验")

    if not date_match:
        if primary.trade_date < verifier.trade_date:
            note = "主源日期滞后，已采用更新来源；最新交易日仅单源可用"
        else:
            note = "校验源日期滞后，已采用更新来源；最新交易日仅单源可用"
        return ValidationResult(
            "待复核", False, False, False, close_diff, volume_diff, note
        )

    reasons = []
    if date_match and not close_pass:
        reasons.append("收盘价差异超限")
    if date_match and not volume_pass:
        reasons.append("成交量差异超限或缺失")
    return ValidationResult("待复核", date_match, close_pass, volume_pass, close_diff, volume_diff, "；".join(reasons))


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
    """Return a legacy wall-clock expectation or an evidence-based session.

    Callers that have source observations should pass them and use the
    evidence-based result.  The no-observation form is retained for research
    and compatibility callers; production latest-data orchestration must not
    use it as a freshness guard because a delayed run can cross a weekend.
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


def latest_completed_market_session(
    timezone_name: str,
    close_time_text: str,
    fetched_at: datetime,
    observed_quotes: Iterable[Quote],
    buffer_minutes: int = 20,
) -> Optional[date]:
    """Return the latest completed session supported by valid source evidence.

    This deliberately does not manufacture exchange holidays or infer a
    weekday's session from wall-clock time.  A quote dated today is accepted
    only after that market's close buffer; on weekends and delayed runs the
    newest valid observed source date remains the freshness target.
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
    """Prefer a valid newer date before provider priority or same-day quality."""
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

    if primary_issue and not verifier_issue:
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
