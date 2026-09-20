"""Shared latest-quote evaluation and Sheet row projections.

The scheduled ``main.run(mode='latest')`` path and the single-symbol holdings
lifecycle both need the same source-date, freshness, validation and quote
selection semantics.  This module is intentionally limited to that contract;
provider orchestration and lifecycle writes remain owned by their callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from core import (
    Quote,
    ValidationResult,
    fresher_quote,
    latest_completed_market_session,
    latest_quote,
    market_close_confirmed,
    ordinary_calendar_freshness_guard,
    quote_sanity_issue,
    validate_quotes,
)


LATEST_UNAVAILABLE_STATUS = "数据不可用"


@dataclass(frozen=True)
class LatestSnapshot:
    """The bounded result of evaluating two latest-source payloads."""

    primary: Quote | None
    verifier: Quote | None
    chosen: Quote | None
    validation: ValidationResult
    completed_trade_date: date | None
    calendar_guard: date
    displayed_status: str | None
    confirmed: bool
    actual_primary_source: str
    actual_verifier_source: str
    future_dates: tuple[date, ...]
    future_note: str
    stale_note: str
    calendar_stale_note: str
    sanity_note: str
    source_selection_note: str
    fallback_notes: tuple[str, ...]
    errors: tuple[str, ...]
    identity_errors: tuple[str, ...]
    stale_sources_rejected: int

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(
            item
            for item in (
                self.validation.note,
                self.stale_note,
                self.calendar_stale_note,
                self.sanity_note,
                self.future_note,
                self.source_selection_note,
                "；".join(self.fallback_notes),
            )
            if item
        )

    @property
    def validation_notes(self) -> tuple[str, ...]:
        """Notes written to ``校验记录`` by the existing latest pipeline."""
        return tuple(
            item
            for item in (
                self.validation.note,
                self.stale_note,
                self.calendar_stale_note,
                self.sanity_note,
                self.future_note,
                self.source_selection_note,
            )
            if item
        )

    @property
    def publishable(self) -> bool:
        """Whether this snapshot is safe for a lifecycle publish boundary."""
        return (
            self.completed_trade_date is not None
            and self.chosen is not None
            and not self.identity_errors
            and self.chosen.trade_date == self.completed_trade_date
            and quote_sanity_issue(self.chosen) is None
            and not self.calendar_stale_note
        )

    @property
    def blocking_reason(self) -> str:
        if self.identity_errors:
            return self.identity_errors[0]
        if self.completed_trade_date is None:
            return "无法根据有效来源确定最新已完成市场交易日"
        if self.chosen is None:
            return "无法形成最新行情快照：主源和校验源均不可用"
        if self.chosen.trade_date != self.completed_trade_date:
            return (
                "最新行情选中日期落后于最近已完成市场交易日："
                f"{self.chosen.trade_date.isoformat()}<"
                f"{self.completed_trade_date.isoformat()}"
            )
        if self.sanity_note:
            return f"最新行情 sanity 校验失败：{self.sanity_note}"
        if self.calendar_stale_note:
            return self.calendar_stale_note
        return "最新行情快照不可发布"


def _identity_errors(
    quotes: Iterable[Quote],
    expected_symbol: str | None,
    expected_market: str | None,
) -> tuple[str, ...]:
    if expected_symbol is None and expected_market is None:
        return ()
    symbol = str(expected_symbol or "").strip().upper()
    market = str(expected_market or "").strip().upper()
    errors: list[str] = []
    for quote in quotes:
        if quote.symbol.strip().upper() != symbol:
            errors.append("latest provider 返回了不同标的")
        elif quote.market.strip().upper() != market:
            errors.append("latest provider 返回了不同市场")
    return tuple(dict.fromkeys(errors))


def evaluate_latest_snapshot(
    primary_quotes: Iterable[Quote],
    verifier_quotes: Iterable[Quote],
    *,
    fetched_at: datetime,
    timezone_name: str,
    close_time_text: str,
    close_tolerance: float,
    volume_tolerance: float,
    primary_source: str = "",
    verifier_source: str = "",
    errors: Iterable[str] = (),
    expected_symbol: str | None = None,
    expected_market: str | None = None,
    apply_calendar_freshness: bool = True,
) -> LatestSnapshot:
    """Evaluate latest evidence using the production ``core`` semantics.

    ``apply_calendar_freshness`` is true for scheduled latest and holdings
    lifecycle operations.  Full mode passes false because its historical path
    retains the existing full-mode behavior.
    """
    primary_payload = list(primary_quotes)
    verifier_payload = list(verifier_quotes)
    all_quotes = (*primary_payload, *verifier_payload)
    local_today = fetched_at.astimezone(ZoneInfo(timezone_name)).date()
    future_quotes = tuple(
        quote for quote in all_quotes if quote.trade_date > local_today
    )
    future_dates = tuple(sorted({quote.trade_date for quote in future_quotes}))
    future_note = ""
    if future_dates:
        future_note = (
            "未来交易日行情已拒绝："
            + ",".join(item.isoformat() for item in future_dates)
        )

    completed = latest_completed_market_session(
        timezone_name, close_time_text, fetched_at, all_quotes
    )
    calendar_guard = ordinary_calendar_freshness_guard(
        timezone_name, close_time_text, fetched_at
    )

    primary = latest_quote(primary_payload, max_trade_date=completed) if completed else None
    verifier = latest_quote(verifier_payload, max_trade_date=completed) if completed else None
    validation = validate_quotes(primary, verifier, close_tolerance, volume_tolerance)
    chosen = fresher_quote(primary, verifier)

    stale_note = ""
    if chosen is not None and completed is not None and chosen.trade_date != completed:
        stale_note = (
            f"选中行情日期{chosen.trade_date.isoformat()}"
            f"早于最新已完成市场交易日{completed.isoformat()}"
        )

    calendar_stale_note = ""
    if (
        apply_calendar_freshness
        and completed is not None
        and completed < calendar_guard
    ):
        calendar_stale_note = (
            f"有效来源最新日期{completed.isoformat()}"
            f"早于普通日历freshness guard{calendar_guard.isoformat()}；"
            "不推断交易所节假日，行情仅保留显示并待复核"
        )

    sanity_note = quote_sanity_issue(chosen) if chosen is not None else ""
    displayed_status = validation.status if chosen is not None else None
    if chosen is not None:
        if stale_note or sanity_note or future_note or calendar_stale_note:
            displayed_status = "待复核"

    source_selection_note = ""
    primary_sanity_issue = quote_sanity_issue(primary) if primary is not None else None
    verifier_sanity_issue = quote_sanity_issue(verifier) if verifier is not None else None
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

    fallback_notes = tuple(
        item
        for item in (
            f"主数据源{primary_source}回退至{primary.source}"
            if primary is not None and primary.source != primary_source
            else "",
            f"校验数据源{verifier_source}回退至{verifier.source}"
            if verifier is not None and verifier.source != verifier_source
            else "",
        )
        if item
    )
    actual_primary_source = primary.source if primary is not None else primary_source
    actual_verifier_source = verifier.source if verifier is not None else verifier_source
    all_errors = list(errors)
    if future_note:
        all_errors.append(future_note)
    stale_rejected = len({quote.source for quote in future_quotes})
    if primary is not None and verifier is not None and primary.trade_date != verifier.trade_date:
        stale_rejected += 1

    confirmed = bool(
        chosen is not None
        and displayed_status == "已验证"
        and market_close_confirmed(
            chosen.trade_date, timezone_name, close_time_text, fetched_at
        )
    )
    return LatestSnapshot(
        primary=primary,
        verifier=verifier,
        chosen=chosen,
        validation=validation,
        completed_trade_date=completed,
        calendar_guard=calendar_guard,
        displayed_status=displayed_status,
        confirmed=confirmed,
        actual_primary_source=actual_primary_source,
        actual_verifier_source=actual_verifier_source,
        future_dates=future_dates,
        future_note=future_note,
        stale_note=stale_note,
        calendar_stale_note=calendar_stale_note,
        sanity_note=sanity_note,
        source_selection_note=source_selection_note,
        fallback_notes=fallback_notes,
        errors=tuple(all_errors),
        identity_errors=_identity_errors(all_quotes, expected_symbol, expected_market),
        stale_sources_rejected=stale_rejected,
    )


def quote_row(quote: Quote, fetched_at: datetime, adjustment: str) -> dict:
    """Project a quote into the existing raw/qfq history schema."""
    return {
        "统一代码": quote.symbol,
        "名称": quote.name,
        "市场": quote.market,
        "交易日期": quote.trade_date,
        "复权方式": adjustment,
        "数据源": quote.source,
        "开盘": quote.open,
        "最高": quote.high,
        "最低": quote.low,
        "收盘": quote.close,
        "昨收": quote.preclose,
        "涨跌幅": quote.pct_change,
        "成交量": quote.volume,
        "成交额": quote.amount,
        "换手率": quote.turnover_rate,
        "币种": quote.currency,
        "抓取时间": fetched_at,
    }


def project_latest_row(snapshot: LatestSnapshot, fetched_at: datetime) -> dict:
    if snapshot.chosen is None:
        raise ValueError("不可为没有 chosen quote 的 snapshot 投影最新行情")
    quote = snapshot.chosen
    return {
        "统一代码": quote.symbol,
        "名称": quote.name,
        "市场": quote.market,
        "交易日期": quote.trade_date,
        "抓取时间": fetched_at,
        "正式收盘": snapshot.confirmed,
        "校验状态": snapshot.displayed_status,
        "主数据源": snapshot.actual_primary_source,
        "校验数据源": snapshot.actual_verifier_source,
        "开盘": quote.open,
        "最高": quote.high,
        "最低": quote.low,
        "收盘": quote.close,
        "昨收": quote.preclose,
        "涨跌幅": quote.pct_change,
        "成交量": quote.volume,
        "成交额": quote.amount,
        "换手率": quote.turnover_rate,
        "收盘价差异": snapshot.validation.close_diff,
        "成交量差异": snapshot.validation.volume_diff,
        "币种": quote.currency,
        "备注": "；".join((*snapshot.notes, *snapshot.errors)),
    }


def project_latest_failure_row(
    watch: dict,
    existing: dict | None,
    fetched_at: datetime,
    reason: str,
) -> dict:
    """Mark a failed latest refresh without presenting the prior quote as fresh.

    The legacy Sheet is also an input to external monitoring.  Removing a
    symbol from the upsert on provider failure would leave its previous row
    looking valid to consumers that only read ``最新行情``.  Preserve the
    last observed values for audit/display, but stamp the current attempt as
    unavailable and make the stale-input rule explicit.
    """

    row = dict(existing or {})
    symbol = str(watch.get("统一代码") or row.get("统一代码") or "").strip()
    market = str(watch.get("市场") or row.get("市场") or "").strip()
    name = str(watch.get("名称") or row.get("名称") or symbol).strip()
    currency = str(watch.get("币种") or row.get("币种") or "").strip()
    primary_source = str(watch.get("主数据源") or row.get("主数据源") or "").strip()
    verifier_source = str(watch.get("校验数据源") or row.get("校验数据源") or "").strip()
    prior_date = row.get("交易日期")
    prior_date_text = str(prior_date or "").strip() or "未知"
    safe_reason = str(reason or "未提供失败原因").strip()
    return {
        **row,
        "统一代码": symbol,
        "名称": name,
        "市场": market,
        "抓取时间": fetched_at,
        "正式收盘": False,
        "校验状态": LATEST_UNAVAILABLE_STATUS,
        "主数据源": primary_source,
        "校验数据源": verifier_source,
        "币种": currency,
        "备注": (
            f"本次行情更新失败：{safe_reason}；"
            f"保留最后行情日期{prior_date_text}仅供审计，禁止下游监控当作当前新鲜数据"
        ),
    }


def latest_row_is_monitorable(
    row: dict,
    expected_trade_date: date,
    *,
    require_verified: bool = False,
) -> bool:
    """Return whether a Sheet latest row is safe for a freshness-gated reader.

    Consumers must supply the expected completed session from their own market
    calendar.  A row stamped ``数据不可用`` or dated before that session is
    never accepted, even if its OHLCV values are still present for audit.
    """

    if not isinstance(expected_trade_date, date):
        return False
    status = str(row.get("校验状态") or "").strip()
    accepted_statuses = {"已验证"} if require_verified else {"已验证", "单源可用"}
    if status not in accepted_statuses:
        return False
    if not _sheet_bool(row.get("正式收盘")):
        return False
    value = row.get("交易日期")
    if isinstance(value, datetime):
        value = value.date()
    elif not isinstance(value, date):
        text = str(value or "").strip()
        try:
            value = date.fromisoformat(text[:10])
        except (TypeError, ValueError):
            return False
    return value == expected_trade_date


def _sheet_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def project_validation_row(snapshot: LatestSnapshot, fetched_at: datetime) -> dict:
    if snapshot.chosen is None:
        raise ValueError("不可为没有 chosen quote 的 snapshot 投影校验记录")
    quote = snapshot.chosen
    return {
        "抓取时间": fetched_at,
        "统一代码": quote.symbol,
        "交易日期": quote.trade_date,
        "主数据源": snapshot.actual_primary_source,
        "校验数据源": snapshot.actual_verifier_source,
        "主源收盘": snapshot.primary.close if snapshot.primary else None,
        "校验源收盘": snapshot.verifier.close if snapshot.verifier else None,
        "收盘价差异": snapshot.validation.close_diff,
        "主源成交量": snapshot.primary.volume if snapshot.primary else None,
        "校验源成交量": snapshot.verifier.volume if snapshot.verifier else None,
        "成交量差异": snapshot.validation.volume_diff,
        "日期一致": snapshot.validation.date_match,
        "价格通过": snapshot.validation.close_pass,
        "成交量通过": snapshot.validation.volume_pass,
        "校验状态": snapshot.displayed_status,
        "说明": "；".join(snapshot.validation_notes),
    }
