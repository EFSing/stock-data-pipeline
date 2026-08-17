from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
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

    date_match = primary.trade_date == verifier.trade_date
    close_diff = relative_diff(primary.close, verifier.close)
    volume_diff = relative_diff(primary.volume, verifier.volume)
    close_pass = date_match and close_diff is not None and close_diff <= close_tolerance
    volume_pass = date_match and volume_diff is not None and volume_diff <= volume_tolerance

    if date_match and close_pass and volume_pass:
        return ValidationResult("已验证", True, True, True, close_diff, volume_diff, "日期、收盘价和成交量均通过校验")

    reasons = []
    if not date_match:
        reasons.append("交易日期不一致")
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


def latest_quote(quotes: list[Quote]) -> Optional[Quote]:
    if not quotes:
        return None
    return max(quotes, key=lambda item: item.trade_date)

