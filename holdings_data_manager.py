"""Deterministic single-symbol holdings lifecycle orchestration.

This module owns lifecycle intent, identity normalization, history coverage and
audit orchestration.  It deliberately delegates provider calls and Sheet writes
to the existing production adapters; it is not a second market-data pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from core import (
    Quote,
    quote_sanity_issue,
)
from latest_snapshot import (
    LatestSnapshot,
    evaluate_latest_snapshot,
    project_latest_row,
    project_validation_row,
    quote_row,
)
from providers import QFQ_HISTORY_SOURCES as QFQ_SOURCES
from sheets_client import LOG_HEADERS, VALIDATION_HEADERS


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
SUPPORTED_MARKETS = frozenset({"CN", "HK", "US", "JP", "SE"})

# Coverage is based on observed provider session dates, not a weekday calendar.
# These conservative bounds reject obviously truncated/sparse annual payloads
# while allowing normal exchange holiday clusters without inventing sessions.
MIN_ONE_YEAR_BARS = 180
MAX_NORMAL_SESSION_GAP_DAYS = 14
MAX_COVERAGE_BOUNDARY_LAG_DAYS = 7


def beijing_now() -> datetime:
    """Return the lifecycle timestamp in the spreadsheet's canonical zone."""
    return datetime.now(BEIJING_TIMEZONE)


def _ratio(value, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    return float(text[:-1].strip()) / 100 if text.endswith("%") else float(text)


class HoldingsDataManagerError(ValueError):
    """A fail-closed input, identity, provider or quality error."""


class Operation(str, Enum):
    ADD = "ADD"
    REENTER = "REENTER"
    CLOSE = "CLOSE"
    SYNC = "SYNC"


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    IDEMPOTENT = "IDEMPOTENT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class NormalizedHolding:
    symbol: str
    market: str
    name: str
    currency: str
    timezone: str
    close_time: str
    primary_source: str
    verifier_source: str
    historical_source: str
    yfinance_symbol: str
    baostock_symbol: str

    def watch_row(self, enabled: bool = False) -> dict:
        return {
            "启用": enabled,
            "市场": self.market,
            "主数据源": self.primary_source,
            "校验数据源": self.verifier_source,
            "历史数据源": self.historical_source,
            "时区": self.timezone,
            "收盘时间": self.close_time,
            "统一代码": self.symbol,
            "名称": self.name,
            "币种": self.currency,
            "BaoStock代码": self.baostock_symbol,
            "yfinance代码": self.yfinance_symbol,
            "AKShare代码": "",
        }


@dataclass(frozen=True)
class ParsedRequest:
    operation: Operation
    symbol: str
    market: str | None


@dataclass(frozen=True)
class OperationResult:
    operation: str
    symbol: str
    market: str
    status: str
    enabled: bool | None
    history_rows_written: int
    message: str

    @property
    def ok(self) -> bool:
        return self.status in {ResultStatus.SUCCESS.value, ResultStatus.IDEMPOTENT.value}


_MARKET_ALIASES = {
    "CN": "CN", "A股": "CN", "沪深": "CN", "上交所": "CN", "深交所": "CN",
    "HK": "HK", "港股": "HK", "香港": "HK",
    "US": "US", "美股": "US", "美国": "US",
    "JP": "JP", "日股": "JP", "日本": "JP",
    "SE": "SE", "瑞典股": "SE", "瑞典": "SE",
}
_SUFFIX_MARKETS = {"SH": "CN", "SS": "CN", "SZ": "CN", "HK": "HK", "T": "JP", "ST": "SE"}
_DEFAULTS = {
    "CN": ("CNY", "Asia/Shanghai", "15:00", "yfinance", "BaoStock", "yfinance"),
    "HK": ("HKD", "Asia/Hong_Kong", "16:00", "yfinance", "Tencent", "yfinance"),
    "US": ("USD", "America/New_York", "16:00", "yfinance", "Tencent", "yfinance"),
    "JP": ("JPY", "Asia/Tokyo", "15:00", "yfinance", "", "yfinance"),
    "SE": ("SEK", "Europe/Stockholm", "17:30", "yfinance", "", "yfinance"),
}
_SYMBOL_TOKEN = re.compile(r"(?<![A-Za-z0-9])\$?[A-Za-z]{1,10}(?:[.-][A-Za-z0-9]{1,8})?|(?<!\d)\d{4,6}(?:\.(?:SH|SS|SZ|HK|T|ST))?(?!\d)", re.IGNORECASE)
_INTENT_WORDS = {
    "ADD", "REENTER", "CLOSE", "SYNC", "I", "BUY", "BOUGHT", "ADD", "REENTER", "CLOSE", "SYNC",
}


def _canonical_market(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().upper()
    return _MARKET_ALIASES.get(text) or _MARKET_ALIASES.get(str(value).strip())


def _infer_market(symbol: str) -> str:
    upper = symbol.upper()
    if re.fullmatch(r"\d{6}(?:\.(?:SH|SS|SZ))?", upper):
        return "CN"
    suffix = upper.rsplit(".", 1)[-1] if "." in upper else ""
    if suffix in _SUFFIX_MARKETS:
        return _SUFFIX_MARKETS[suffix]
    if re.fullmatch(r"\d{4,5}\.HK", upper):
        return "HK"
    if re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}", upper):
        # Supported non-CN/HK exchanges require an explicit exchange suffix.
        # A bare alphabetic token therefore has one deterministic interpretation.
        return "US"
    raise HoldingsDataManagerError(f"无法确定标的市场：{symbol}")


def _cn_exchange(code: str) -> str:
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("60", "68", "5", "9")):
        return "SH"
    return "SZ"


def normalize_holding(
    symbol: str,
    market: str | None = None,
    name: str | None = None,
    source_overrides: Mapping[str, str] | None = None,
) -> NormalizedHolding:
    raw = str(symbol or "").strip().replace("$", "")
    if not raw or any(char.isspace() for char in raw) or "/" in raw:
        raise HoldingsDataManagerError(f"标的身份格式不明确：{symbol}")
    upper = raw.upper()
    inferred = _infer_market(upper)
    explicit = _canonical_market(market)
    if market is not None and explicit is None:
        raise HoldingsDataManagerError(f"无法确定市场：{market}")
    if explicit and explicit != inferred:
        raise HoldingsDataManagerError(
            f"标的与市场冲突：{upper}推断为{inferred}，输入市场为{explicit}"
        )
    normalized_market = explicit or inferred
    if normalized_market not in SUPPORTED_MARKETS:
        raise HoldingsDataManagerError(f"不支持的市场：{normalized_market}")

    if normalized_market == "CN":
        code = upper.split(".", 1)[0]
        if not re.fullmatch(r"\d{6}", code):
            raise HoldingsDataManagerError(f"A股代码必须为6位数字：{symbol}")
        exchange = _cn_exchange(code)
        if exchange == "BJ":
            raise HoldingsDataManagerError(f"北交所代码暂未在现有市场映射中注册：{symbol}")
        canonical_symbol = f"{code}.{exchange}"
        yf_symbol = f"{code}.SS" if exchange == "SH" else f"{code}.SZ"
        baostock = f"{exchange.lower()}.{code}"
    elif normalized_market == "HK":
        match = re.fullmatch(r"(\d{4,5})(?:\.HK)?", upper)
        if not match:
            raise HoldingsDataManagerError(f"港股代码必须为4至5位数字并带HK：{symbol}")
        code = match.group(1).zfill(5)
        canonical_symbol = f"{code}.HK"
        yf_symbol = f"{int(code)}.HK"
        baostock = ""
    elif normalized_market == "US":
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}(?:\.[A-Z0-9-]{1,8})?", upper):
            raise HoldingsDataManagerError(f"美股代码格式不明确：{symbol}")
        canonical_symbol = upper
        yf_symbol = upper
        baostock = ""
    elif normalized_market == "JP":
        match = re.fullmatch(r"([A-Z0-9-]{1,10})\.T", upper)
        if not match:
            raise HoldingsDataManagerError(f"日股代码必须带.T交易所后缀：{symbol}")
        canonical_symbol = upper
        yf_symbol = upper
        baostock = ""
    else:
        match = re.fullmatch(r"([A-Z0-9-]{1,10})\.ST", upper)
        if not match:
            raise HoldingsDataManagerError(f"瑞典股代码必须带.ST交易所后缀：{symbol}")
        canonical_symbol = upper
        yf_symbol = upper
        baostock = ""

    currency, timezone_name, close_time, primary, verifier, history = _DEFAULTS[normalized_market]
    overrides = {str(key): str(value).strip() for key, value in (source_overrides or {}).items()}
    primary = overrides.get("主数据源", overrides.get("primary_source", primary))
    verifier = overrides.get("校验数据源", overrides.get("verifier_source", verifier))
    history = overrides.get("历史数据源", overrides.get("historical_source", history))
    if not primary:
        raise HoldingsDataManagerError("主数据源不能为空")
    if history not in QFQ_SOURCES:
        raise HoldingsDataManagerError(f"历史数据源不支持前复权：{history}")
    try:
        from providers import PROVIDERS
    except ImportError as exc:  # pragma: no cover - repository import failure
        raise HoldingsDataManagerError("现有行情 provider 不可用") from exc
    if primary not in PROVIDERS or (verifier and verifier not in PROVIDERS):
        raise HoldingsDataManagerError("主／校验数据源未注册")
    return NormalizedHolding(
        canonical_symbol,
        normalized_market,
        str(name or canonical_symbol).strip() or canonical_symbol,
        currency,
        timezone_name,
        close_time,
        primary,
        verifier,
        history,
        yf_symbol,
        baostock,
    )


def parse_natural_language(text: str) -> ParsedRequest:
    request = str(text or "").strip()
    if not request:
        raise HoldingsDataManagerError("自然语言请求为空")
    operation_hits: list[Operation] = []
    if re.search(r"重新买回|重新入场|重新入持|再买回|再入场|REENTER", request, re.IGNORECASE):
        operation_hits.append(Operation.REENTER)
    if re.search(r"清仓|卖出|退出持仓|不再持有|CLOSE", request, re.IGNORECASE):
        operation_hits.append(Operation.CLOSE)
    if re.search(r"同步|补齐|更新历史|刷新历史|SYNC", request, re.IGNORECASE):
        operation_hits.append(Operation.SYNC)
    if re.search(r"添加|新增|买了|买入|持有|ADD|BUY|BOUGHT", request, re.IGNORECASE):
        operation_hits.append(Operation.ADD)
    if len(set(operation_hits)) != 1:
        raise HoldingsDataManagerError("无法唯一确定持仓操作")
    symbols = []
    for match in _SYMBOL_TOKEN.finditer(request):
        token = match.group(0).lstrip("$").upper()
        if token not in _INTENT_WORDS and token not in {"US", "CN", "HK", "JP", "SE"}:
            symbols.append(token)
    if len(symbols) != 1:
        raise HoldingsDataManagerError("无法唯一确定标的身份")
    explicit_market = None
    for text_key, canonical in _MARKET_ALIASES.items():
        if text_key in request or re.search(rf"(?<![A-Z]){canonical}(?![A-Z])", request, re.IGNORECASE):
            if explicit_market and explicit_market != canonical:
                raise HoldingsDataManagerError("自然语言请求包含多个市场")
            explicit_market = canonical
    return ParsedRequest(next(iter(set(operation_hits))), symbols[0], explicit_market)


def _date_from_sheet(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise HoldingsDataManagerError("历史行缺少交易日期")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise HoldingsDataManagerError(f"历史行交易日期无法解析：{text}") from exc


def _calendar_year_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


@dataclass(frozen=True)
class HistoryCoverageReport:
    """Deterministic, provider-session-based history coverage/QC result."""

    ok: bool
    raw_bar_count: int
    adjusted_bar_count: int
    raw_duplicate_count: int
    adjusted_duplicate_count: int
    raw_first_trade_date: date | None
    raw_last_trade_date: date | None
    adjusted_first_trade_date: date | None
    adjusted_last_trade_date: date | None
    raw_only_dates: tuple[date, ...]
    adjusted_only_dates: tuple[date, ...]
    suspicious_gaps: tuple[tuple[date, date], ...]
    reason: str


def _suspicious_gaps(dates: set[date]) -> list[tuple[date, date]]:
    ordered = sorted(dates)
    return [
        (left, right)
        for left, right in zip(ordered, ordered[1:])
        if (right - left).days > MAX_NORMAL_SESSION_GAP_DAYS
    ]


def history_coverage_report(
    raw_dates: Iterable[date],
    adjusted_dates: Iterable[date],
    start: date,
    end: date,
) -> HistoryCoverageReport:
    """Check annual raw/qfq coverage using only provider-observed sessions.

    Weekdays are never treated as expected sessions.  A normal holiday gap is
    therefore accepted; a gap longer than the bounded session-date threshold
    is treated as suspicious and must be fetched or fail closed.
    """
    raw_list = list(raw_dates)
    adjusted_list = list(adjusted_dates)
    raw_set = set(raw_list)
    adjusted_set = set(adjusted_list)
    raw_first = min(raw_set) if raw_set else None
    raw_last = max(raw_set) if raw_set else None
    adjusted_first = min(adjusted_set) if adjusted_set else None
    adjusted_last = max(adjusted_set) if adjusted_set else None
    raw_only = tuple(sorted(raw_set - adjusted_set))
    adjusted_only = tuple(sorted(adjusted_set - raw_set))
    suspicious = tuple(sorted(set(_suspicious_gaps(raw_set) + _suspicious_gaps(adjusted_set))))
    raw_duplicates = len(raw_list) - len(raw_set)
    adjusted_duplicates = len(adjusted_list) - len(adjusted_set)

    reasons: list[str] = []
    if start > end:
        reasons.append("历史目标区间无效")
    if raw_duplicates or adjusted_duplicates:
        reasons.append("历史日期重复")
    if raw_only or adjusted_only:
        reasons.append("未复权与前复权 session-date 集合不一致")
    if not raw_set or not adjusted_set:
        reasons.append("raw/qfq 历史为空")
    if raw_set and (min(raw_set) < start or max(raw_set) > end):
        reasons.append("未复权日期越界")
    if adjusted_set and (min(adjusted_set) < start or max(adjusted_set) > end):
        reasons.append("前复权日期越界")
    if raw_last is None or raw_last < end:
        reasons.append("未复权历史未到达目标末日")
    if adjusted_last is None or adjusted_last < end:
        reasons.append("前复权历史未到达目标末日")
    if raw_first is None or (raw_first - start).days > MAX_COVERAGE_BOUNDARY_LAG_DAYS:
        reasons.append("未复权历史起点明显截断")
    if adjusted_first is None or (adjusted_first - start).days > MAX_COVERAGE_BOUNDARY_LAG_DAYS:
        reasons.append("前复权历史起点明显截断")
    if len(raw_set) < MIN_ONE_YEAR_BARS:
        reasons.append("未复权历史过于稀疏")
    if len(adjusted_set) < MIN_ONE_YEAR_BARS:
        reasons.append("前复权历史过于稀疏")
    if suspicious:
        reasons.append("历史中段存在异常长 session-date gap")

    return HistoryCoverageReport(
        ok=not reasons,
        raw_bar_count=len(raw_list),
        adjusted_bar_count=len(adjusted_list),
        raw_duplicate_count=raw_duplicates,
        adjusted_duplicate_count=adjusted_duplicates,
        raw_first_trade_date=raw_first,
        raw_last_trade_date=raw_last,
        adjusted_first_trade_date=adjusted_first,
        adjusted_last_trade_date=adjusted_last,
        raw_only_dates=raw_only,
        adjusted_only_dates=adjusted_only,
        suspicious_gaps=suspicious,
        reason="；".join(reasons) or "coverage/QC通过",
    )


def _merge_intervals(intervals: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    ordered = sorted((left, right) for left, right in intervals if left <= right)
    merged: list[list[date]] = []
    for left, right in ordered:
        if merged and left <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return [(left, right) for left, right in merged]


def _coverage_gaps(dates: set[date], start: date, end: date) -> list[tuple[date, date]]:
    """Return bounded ranges to ask the provider about, without weekday math."""
    if start > end:
        return []
    if not dates:
        return [(start, end)]
    ordered = sorted(value for value in dates if start <= value <= end)
    if not ordered:
        return [(start, end)]
    intervals: list[tuple[date, date]] = []
    if (ordered[0] - start).days > MAX_COVERAGE_BOUNDARY_LAG_DAYS:
        intervals.append((start, ordered[0] - timedelta(days=1)))
    if ordered[-1] < end:
        intervals.append((ordered[-1] + timedelta(days=1), end))
    for left, right in _suspicious_gaps(set(ordered)):
        intervals.append((left + timedelta(days=1), right - timedelta(days=1)))
    return _merge_intervals(intervals)


def _has_one_year_coverage(dates: set[date], start: date, end: date) -> bool:
    """Compatibility helper backed by the full raw/qfq coverage contract."""
    return history_coverage_report(dates, dates, start, end).ok


def _history_dates(rows: Iterable[dict], identity: tuple[str, str]) -> set[date]:
    dates: set[date] = set()
    for row in rows:
        row_identity = (
            str(row.get("统一代码") or "").strip().upper(),
            str(row.get("市场") or "").strip().upper(),
        )
        if row_identity != identity:
            continue
        trade_date = _date_from_sheet(row.get("交易日期"))
        if trade_date in dates:
            raise HoldingsDataManagerError(
                f"历史行情存在重复日期：{identity[1]}|{identity[0]}|{trade_date.isoformat()}"
            )
        dates.add(trade_date)
    return dates


def _validate_fetched_quotes(
    quotes: Iterable[Quote],
    watch: dict,
    start: date,
    end: date,
) -> list[Quote]:
    result = list(quotes)
    if not result:
        raise HoldingsDataManagerError("历史 provider 返回空数据")
    dates: set[date] = set()
    for quote in result:
        if quote.symbol.strip().upper() != str(watch["统一代码"]).strip().upper():
            raise HoldingsDataManagerError("provider 返回了不同标的")
        if quote.market.strip().upper() != str(watch["市场"]).strip().upper():
            raise HoldingsDataManagerError("provider 返回了不同市场")
        if not start <= quote.trade_date <= end:
            raise HoldingsDataManagerError("provider 返回了请求范围外日期")
        if quote.trade_date in dates:
            raise HoldingsDataManagerError(
                f"provider 返回重复日期：{quote.trade_date.isoformat()}"
            )
        dates.add(quote.trade_date)
        issue = quote_sanity_issue(quote)
        if issue:
            raise HoldingsDataManagerError(issue)
    return sorted(result, key=lambda item: item.trade_date)


def _identity_matches(row: dict, identity: tuple[str, str]) -> bool:
    return (
        str(row.get("统一代码") or "").strip().upper(),
        str(row.get("市场") or "").strip().upper(),
    ) == identity


class HoldingsDataManager:
    """Execute one deterministic ADD/REENTER/CLOSE/SYNC operation."""

    def __init__(
        self,
        client=None,
        fetch_history: Callable | None = None,
        fetch_latest: Callable | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ):
        if client is None:
            from sheets_client import SheetsClient

            client = SheetsClient()
        if fetch_history is None or fetch_latest is None:
            from providers import fetch_latest_with_retry, fetch_with_retry

            fetch_history = fetch_history or fetch_with_retry
            fetch_latest = fetch_latest or fetch_latest_with_retry
        self.client = client
        self.fetch_history = fetch_history
        self.fetch_latest = fetch_latest
        self.now_fn = now_fn or beijing_now

    def execute_text(self, text: str) -> OperationResult:
        parsed = parse_natural_language(text)
        return self.execute(parsed.operation, parsed.symbol, parsed.market)

    def execute(
        self,
        operation: Operation | str,
        symbol: str,
        market: str | None = None,
        *,
        name: str | None = None,
        source_overrides: Mapping[str, str] | None = None,
    ) -> OperationResult:
        rows_written = 0
        try:
            action = operation if isinstance(operation, Operation) else Operation(str(operation).upper())
            normalized = normalize_holding(symbol, market, name, source_overrides)
            watchlist = list(self.client.records("自选清单"))
            matches = [
                row for row in watchlist
                if _identity_matches(row, (normalized.symbol, normalized.market))
            ]
            if len(matches) > 1:
                raise HoldingsDataManagerError(
                    f"自选清单存在重复身份：{normalized.market}|{normalized.symbol}"
                )
            existing = matches[0] if matches else None
            if action is Operation.CLOSE:
                return self._close(normalized, existing)
            if action is Operation.REENTER and existing is None:
                raise HoldingsDataManagerError("REENTER要求自选清单中已有历史身份，请先ADD")
            if action is Operation.SYNC and existing is None:
                raise HoldingsDataManagerError("SYNC要求自选清单中已有历史身份")

            watch = self._watch_for_operation(normalized, existing)
            operation_at = self._operation_timestamp()
            if action is Operation.SYNC:
                target = self._latest_completed_date(watch, operation_at)
                rows_written = self._sync_history(normalized, watch, target, operation_at)
                return self._audit_result(
                    normalized, action, ResultStatus.SUCCESS,
                    self._enabled(existing), rows_written,
                    f"SYNC成功：历史缺口补齐，写入/更新{rows_written}行",
                )

            snapshot = self._latest_snapshot(normalized, watch, operation_at)
            target = snapshot.completed_trade_date
            assert target is not None
            start = _calendar_year_before(target)
            existing_report = self._existing_history_report(normalized, start, target)
            history_complete = existing_report.ok
            latest_complete = self._latest_row_is_current(normalized, snapshot)
            validation_complete = self._validation_row_is_current(normalized, target)

            # Enabled identities are idempotent only after all state has been
            # reconciled.  A missing latest or validation row must be repaired.
            if (
                existing is not None
                and self._enabled(existing)
                and history_complete
                and latest_complete
                and validation_complete
            ):
                return self._audit_result(
                    normalized, action, ResultStatus.IDEMPOTENT, True, 0,
                    f"{action.value}幂等：latest、校验记录和历史 coverage 均完整",
                )

            # Reconcile each durable component independently.  A previous
            # attempt may have persisted history/latest/validation before its
            # final watchlist write failed; retrying must preserve those
            # complete components and only repair what is still missing.
            if not history_complete:
                # History QC is the first write boundary.  No latest or
                # validation publication happens until history is complete.
                rows_written = self._sync_history(
                    normalized, watch, target, operation_at,
                )
            if not latest_complete:
                self.client.upsert_latest([project_latest_row(snapshot, operation_at)])
            if not validation_complete:
                self.client.append_rows(
                    "校验记录",
                    VALIDATION_HEADERS,
                    [project_validation_row(snapshot, operation_at)],
                )

            # Enable only after latest and validation writes both succeed.
            if existing is None or not self._enabled(existing):
                if existing is None:
                    watchlist_row = normalized.watch_row(enabled=True)
                else:
                    watchlist_row = dict(existing)
                    watchlist_row["启用"] = True
                self.client.upsert_watchlist(watchlist_row)
            action_message = (
                f"{action.value}成功（按REENTER语义）"
                if action is Operation.ADD and existing is not None and not self._enabled(existing)
                else f"{action.value}成功"
            )
            message = (
                f"{action_message}：以同一已完成交易日{target.isoformat()}"
                f"完成历史、最新行情和校验记录，历史写入/更新{rows_written}行"
            )
            return self._audit_result(
                normalized, action, ResultStatus.SUCCESS, True, rows_written, message
            )
        except Exception as exc:
            try:
                normalized_for_audit = normalize_holding(symbol, market, name, source_overrides)
            except Exception:
                normalized_for_audit = None
            if normalized_for_audit is not None:
                try:
                    return self._audit_result(
                        normalized_for_audit,
                        operation if isinstance(operation, Operation) else Operation(str(operation).upper()),
                        ResultStatus.FAILED,
                        None,
                        rows_written,
                        str(exc),
                    )
                except Exception as audit_exc:
                    raise HoldingsDataManagerError(
                        f"{exc}；持仓生命周期审计写入失败：{audit_exc}"
                    ) from exc
            raise HoldingsDataManagerError(str(exc)) from exc

    @staticmethod
    def _enabled(row: dict | None) -> bool:
        if row is None:
            return False
        return str(row.get("启用") or "").strip().lower() in {"true", "1", "yes", "是"}

    def _watch_for_operation(
        self, normalized: NormalizedHolding, existing: dict | None
    ) -> dict:
        if existing is None:
            return normalized.watch_row(enabled=False)
        watch = dict(existing)
        if not str(watch.get("历史数据源") or "").strip():
            raise HoldingsDataManagerError("自选清单缺少历史数据源，拒绝猜测 provider")
        if str(watch.get("市场") or "").strip().upper() != normalized.market:
            raise HoldingsDataManagerError("自选清单市场与规范化身份不一致")
        watch["统一代码"] = normalized.symbol
        watch["市场"] = normalized.market
        watch.setdefault("名称", normalized.name)
        watch.setdefault("币种", normalized.currency)
        watch.setdefault("时区", normalized.timezone)
        watch.setdefault("收盘时间", normalized.close_time)
        watch.setdefault("yfinance代码", normalized.yfinance_symbol)
        watch.setdefault("BaoStock代码", normalized.baostock_symbol)
        if not str(watch.get("主数据源") or "").strip():
            raise HoldingsDataManagerError("自选清单缺少主数据源，拒绝猜测 provider")
        if str(watch.get("历史数据源")).strip() not in QFQ_SOURCES:
            raise HoldingsDataManagerError("自选清单历史数据源不支持前复权")
        return watch

    def _operation_timestamp(self) -> datetime:
        operation_at = self.now_fn()
        if operation_at.tzinfo is None:
            operation_at = operation_at.replace(tzinfo=BEIJING_TIMEZONE)
        return operation_at.astimezone(BEIJING_TIMEZONE)

    def _validation_tolerances(self) -> tuple[float, float]:
        config_reader = getattr(self.client, "config", None)
        config = config_reader() if callable(config_reader) else {}
        return (
            _ratio(config.get("close_tolerance_pct"), 0.0005),
            _ratio(config.get("volume_tolerance_pct"), 0.02),
        )

    def _latest_snapshot(
        self,
        normalized: NormalizedHolding,
        watch: dict,
        operation_at: datetime,
    ) -> LatestSnapshot:
        local_end = operation_at.astimezone(ZoneInfo(str(watch["时区"]))).date()
        retry_count = max(1, int(float(watch.get("重试次数") or 1)))
        retry_wait = max(0.0, float(watch.get("重试等待秒") or 0.0))
        primary_quotes: list[Quote] = []
        verifier_quotes: list[Quote] = []
        errors: list[str] = []
        for source, target in (
            (str(watch["主数据源"]).strip(), primary_quotes),
            (str(watch.get("校验数据源") or "").strip(), verifier_quotes),
        ):
            if not source:
                continue
            try:
                target.extend(
                    self.fetch_latest(source, watch, local_end, retry_count, retry_wait)
                )
            except Exception as exc:
                errors.append(str(exc))

        close_tolerance, volume_tolerance = self._validation_tolerances()
        snapshot = evaluate_latest_snapshot(
            primary_quotes,
            verifier_quotes,
            fetched_at=operation_at,
            timezone_name=str(watch["时区"]),
            close_time_text=str(watch["收盘时间"]),
            close_tolerance=close_tolerance,
            volume_tolerance=volume_tolerance,
            primary_source=str(watch["主数据源"]).strip(),
            verifier_source=str(watch.get("校验数据源") or "").strip(),
            errors=errors,
            expected_symbol=normalized.symbol,
            expected_market=normalized.market,
        )
        if not snapshot.publishable:
            raise HoldingsDataManagerError(
                f"最新行情不可发布：{snapshot.blocking_reason}"
            )
        return snapshot

    def _latest_completed_date(self, watch: dict, operation_at: datetime) -> date:
        normalized = normalize_holding(
            str(watch["统一代码"]),
            str(watch["市场"]),
            str(watch.get("名称") or ""),
            {
                "主数据源": str(watch.get("主数据源") or ""),
                "校验数据源": str(watch.get("校验数据源") or ""),
                "历史数据源": str(watch.get("历史数据源") or ""),
            },
        )
        snapshot = self._latest_snapshot(normalized, watch, operation_at)
        assert snapshot.completed_trade_date is not None
        return snapshot.completed_trade_date

    def _existing_history_report(
        self, normalized: NormalizedHolding, start: date, target: date
    ) -> HistoryCoverageReport:
        identity = (normalized.symbol, normalized.market)
        raw_existing = [
            row for row in self.client.records("历史行情_未复权")
            if _identity_matches(row, identity)
        ]
        adjusted_existing = [
            row for row in self.client.records("历史行情_前复权")
            if _identity_matches(row, identity)
        ]
        raw_dates = _history_dates(raw_existing, identity)
        adjusted_dates = _history_dates(adjusted_existing, identity)
        if any(trade_date > target for trade_date in raw_dates | adjusted_dates):
            raise HoldingsDataManagerError("历史行情包含未来交易日期")
        return history_coverage_report(
            sorted(raw_dates), sorted(adjusted_dates), start, target
        )

    def _latest_row_is_current(
        self, normalized: NormalizedHolding, snapshot: LatestSnapshot
    ) -> bool:
        target = snapshot.completed_trade_date
        if target is None:
            return False
        rows = [
            row for row in self.client.records("最新行情")
            if _identity_matches(row, (normalized.symbol, normalized.market))
        ]
        if len(rows) > 1:
            raise HoldingsDataManagerError(
                f"最新行情存在重复身份：{normalized.market}|{normalized.symbol}"
            )
        if not rows:
            return False
        try:
            row_date = _date_from_sheet(rows[0].get("交易日期"))
        except HoldingsDataManagerError:
            return False
        return (
            row_date == target
            and str(rows[0].get("校验状态") or "").strip()
            in {"已验证", "单源可用", "待复核"}
        )

    def _validation_row_is_current(
        self, normalized: NormalizedHolding, target: date
    ) -> bool:
        for row in self.client.records("校验记录"):
            # The existing validation schema has no 市场 column; normalized
            # symbols are canonical (for example ``512400.SH``), so the
            # unified code remains the existing validation identity key.
            if str(row.get("统一代码") or "").strip().upper() != normalized.symbol:
                continue
            try:
                if _date_from_sheet(row.get("交易日期")) == target:
                    return True
            except HoldingsDataManagerError:
                continue
        return False

    def _close(
        self, normalized: NormalizedHolding, existing: dict | None
    ) -> OperationResult:
        if existing is None or not self._enabled(existing):
            return self._audit_result(
                normalized, Operation.CLOSE, ResultStatus.IDEMPOTENT,
                False, 0, "CLOSE幂等：标的不在当前启用持仓集合；历史数据未删除",
            )
        updated = dict(existing)
        updated["启用"] = False
        self.client.upsert_watchlist(updated)
        return self._audit_result(
            normalized, Operation.CLOSE, ResultStatus.SUCCESS,
            False, 0, "CLOSE成功：仅停用当前持仓；历史数据未删除",
        )

    def _sync_history(
        self,
        normalized: NormalizedHolding,
        watch: dict,
        target: date,
        operation_at: datetime,
    ) -> int:
        start = _calendar_year_before(target)
        identity = (normalized.symbol, normalized.market)
        raw_existing = [
            row for row in self.client.records("历史行情_未复权")
            if _identity_matches(row, identity)
        ]
        adjusted_existing = [
            row for row in self.client.records("历史行情_前复权")
            if _identity_matches(row, identity)
        ]
        raw_dates = _history_dates(raw_existing, identity)
        adjusted_dates = _history_dates(adjusted_existing, identity)
        if any(trade_date > target for trade_date in raw_dates | adjusted_dates):
            raise HoldingsDataManagerError("历史行情包含未来交易日期")

        retry_count = max(1, int(float(watch.get("重试次数") or 1)))
        retry_wait = max(0.0, float(watch.get("重试等待秒") or 0.0))
        raw_quotes: list[Quote] = []
        adjusted_quotes: list[Quote] = []
        for fetch_start, fetch_end in _coverage_gaps(raw_dates, start, target):
            raw_quotes.extend(self._fetch_interval(
                watch, "raw", str(watch["主数据源"]), fetch_start, fetch_end,
                target, retry_count, retry_wait,
            ))
        for fetch_start, fetch_end in _coverage_gaps(adjusted_dates, start, target):
            adjusted_quotes.extend(self._fetch_interval(
                watch, "qfq", str(watch["历史数据源"]), fetch_start, fetch_end,
                target, retry_count, retry_wait,
            ))
        raw_quotes = _validate_fetched_quotes(raw_quotes, watch, start, target) if raw_quotes else []
        adjusted_quotes = _validate_fetched_quotes(adjusted_quotes, watch, start, target) if adjusted_quotes else []
        coverage = history_coverage_report(
            sorted(raw_dates) + [quote.trade_date for quote in raw_quotes],
            sorted(adjusted_dates) + [quote.trade_date for quote in adjusted_quotes],
            start,
            target,
        )
        if not coverage.ok:
            raise HoldingsDataManagerError(f"历史 coverage/QC 未通过：{coverage.reason}")

        raw_rows = [quote_row(quote, operation_at, "未复权") for quote in raw_quotes]
        adjusted_rows = [quote_row(quote, operation_at, "前复权") for quote in adjusted_quotes]
        written = 0
        if raw_rows:
            written += self.client.upsert_history("历史行情_未复权", raw_rows)
        if adjusted_rows:
            written += self.client.upsert_history("历史行情_前复权", adjusted_rows)
        return written

    def _fetch_interval(
        self,
        watch: dict,
        adjustment: str,
        source: str,
        start: date,
        end: date,
        target: date,
        retry_count: int,
        retry_wait: float,
    ) -> list[Quote]:
        try:
            quotes = self.fetch_history(
                source,
                watch,
                adjustment,
                start,
                end,
                retry_count,
                retry_wait,
                target_trade_date=target if end >= target else None,
            )
        except Exception as exc:
            raise HoldingsDataManagerError(
                f"{adjustment}历史抓取失败：{exc}"
            ) from exc
        return _validate_fetched_quotes(quotes, watch, start, end)

    def _audit_result(
        self,
        normalized: NormalizedHolding,
        operation: Operation,
        status: ResultStatus,
        enabled: bool | None,
        rows_written: int,
        message: str,
    ) -> OperationResult:
        operation_at = self.now_fn()
        if operation_at.tzinfo is None:
            operation_at = operation_at.replace(tzinfo=BEIJING_TIMEZONE)
        operation_at = operation_at.astimezone(BEIJING_TIMEZONE)
        audit_message = f"action={operation.value}; result={status.value}; {message}"
        self.client.append_rows("运行日志", LOG_HEADERS, [{
            "运行时间": operation_at,
            "任务组": "holdings-data-manager",
            "市场": normalized.market,
            "统一代码": normalized.symbol,
            "执行状态": status.value,
            "新增／更新行数": rows_written,
            "消息": audit_message,
        }])
        return OperationResult(
            operation.value,
            normalized.symbol,
            normalized.market,
            status.value,
            enabled,
            rows_written,
            message,
        )
