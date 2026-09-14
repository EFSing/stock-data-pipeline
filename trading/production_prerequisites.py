"""Production prerequisite contracts and read-only construction adapters.

This module is the narrow boundary between the existing frozen Daily Decision
Chain and manually maintained Google Sheets facts. It validates and adapts
records; it does not write strategy rows, use account NAV for a strategy
proposal, infer entry/risk metadata, or call a broker.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import json
import math
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from core import Quote
from trading.daily_decision_chain import (
    DATA_BAD,
    DATA_OK,
    DATA_STALE,
    DATA_UNAVAILABLE,
    CompletedSessionIdentity,
    DailyDecisionResult,
    DailyPositionManagementResult,
    DailyPortfolioResult,
    DailySymbolInput,
    DecisionStateStore,
    InMemoryDecisionStateStore,
    OpenPositionState,
    PendingT1Decision,
    SettlementRecord,
)
from trading.models import (
    DecisionAction,
    EntryPlan,
    PositionSize,
    RiskReward,
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
)
from trading.portfolio_risk import (
    OpenPortfolioPosition,
    PortfolioCandidate,
    PortfolioReservation,
    PortfolioReservationStatus,
    PortfolioSettlement,
    UNKNOWN_RISK_GROUP,
    normalize_risk_group,
)
from trading.position_management import (
    PositionAction,
    PositionAnchor,
    PositionExitReason,
    PositionOrigin,
    PositionTarget,
    TargetReachStatus,
)
from trading.setup01_decision import (
    Setup01Decision,
    Setup01Execution,
    Setup01TargetCandidate,
    Setup01TargetProvenance,
)
from trading.setup01_replay import Setup01ReplayEvent
from trading.setup02_decision import (
    Setup02Decision,
    Setup02Execution,
    Setup02TargetCandidate,
    Setup02TargetProvenance,
)
from trading.setup02 import Setup02Evaluation
from trading.setup02_replay import Setup02ReplayEvent


STRATEGY_ACCOUNT_SHEET = "策略账户"
STRATEGY_UNIVERSE_SHEET = "策略股票池"
RISK_GROUP_SHEET = "策略风险分组"
STRATEGY_POSITION_SHEET = "策略持仓"
DECISION_STATE_SHEET = "策略决策状态"
LATEST_SHEET = "最新行情"
QFQ_HISTORY_SHEET = "历史行情_前复权"

STRATEGY_ACCOUNT_HEADERS = ("账户ID", "启用", "市场", "币种", "参考净值", "净值日期", "备注")
STRATEGY_UNIVERSE_HEADERS = ("启用", "账户ID", "市场", "统一代码", "名称", "备注")
RISK_GROUP_HEADERS = ("市场", "统一代码", "风险组", "备注")
STRATEGY_POSITION_HEADERS = (
    "启用", "账户ID", "市场", "统一代码", "数量", "实际入场价",
    "当前保护止损", "入场日期", "来源事件ID", "更新时间", "备注",
)
DECISION_STATE_HEADERS = (
    "记录类型", "主键", "账户ID", "市场", "统一代码", "交易日期", "状态",
    "PayloadJSON", "更新时间",
)
LATEST_REQUIRED_HEADERS = (
    "统一代码", "市场", "交易日期", "正式收盘", "校验状态",
    "开盘", "最高", "最低", "收盘", "币种",
)
QFQ_HISTORY_REQUIRED_HEADERS = (
    "统一代码", "市场", "交易日期", "复权方式", "开盘", "最高", "最低", "收盘", "币种",
)

PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH = (
    "PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH"
)
STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS = "STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS"
PAPER_SYMBOL_MULTIPLE_ACCOUNTS = "PAPER_SYMBOL_MULTIPLE_ACCOUNTS"
PAPER_ACCOUNT_ROUTING_REQUIRED = "PAPER_ACCOUNT_ROUTING_REQUIRED"
PRODUCTION_ACCOUNT_REQUIRED = "PRODUCTION_ACCOUNT_REQUIRED"
PRODUCTION_SCHEMA_REQUIRED = "PRODUCTION_SCHEMA_REQUIRED"
PRODUCTION_DATA_QUALITY_REQUIRED = "PRODUCTION_DATA_QUALITY_REQUIRED"
PRODUCTION_STATE_STORE_REQUIRED = "PRODUCTION_STATE_STORE_REQUIRED"
PRODUCTION_STATE_ACCOUNT_REQUIRED = "PRODUCTION_STATE_ACCOUNT_REQUIRED"
PRODUCTION_ACCOUNT_STRATEGY_UNIVERSE_REQUIRED = "PRODUCTION_ACCOUNT_STRATEGY_UNIVERSE_REQUIRED"
PENDING_T1_SYMBOL_OUTSIDE_STRATEGY_UNIVERSE = "PENDING_T1_SYMBOL_OUTSIDE_STRATEGY_UNIVERSE"
PERSISTED_STATE_INCOMPLETE = "PERSISTED_STATE_INCOMPLETE"
STATE_STORE_READ_ONLY = "STATE_STORE_READ_ONLY"

PUBLISHED_EVENT = "PUBLISHED_EVENT"
PENDING_T1 = "PENDING_T1"
SETTLEMENT = "SETTLEMENT"
POSITION_ORIGIN_RECORD = "POSITION_ORIGIN"
DAILY_RESULT = "DAILY_RESULT"
_STATE_RECORD_TYPES = {
    PUBLISHED_EVENT, PENDING_T1, SETTLEMENT, POSITION_ORIGIN_RECORD, DAILY_RESULT
}
_QFQ_NAMES = {"qfq", "前复权", "前复权历史", "forward_adjusted"}
EXPECTED_CURRENCY_BY_MARKET = {"CN": "CNY", "US": "USD"}


class ProductionPrerequisiteError(ValueError):
    """A production fact or contract cannot be accepted safely."""


class SheetsRecordsClient(Protocol):
    def records(self, sheet_name: str) -> list[dict]: ...


@dataclass(frozen=True)
class StrategyAccount:
    account_id: str
    enabled: bool
    market: str
    currency: str
    reference_nav: float | None
    nav_date: date | None
    note: str = ""


@dataclass(frozen=True)
class StrategyUniverseEntry:
    enabled: bool
    account_id: str
    market: str
    symbol: str
    name: str = ""
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.market.upper(), self.symbol.upper()


@dataclass(frozen=True)
class StrategyRiskGroup:
    market: str
    symbol: str
    risk_group: str
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.market.upper(), self.symbol.upper()


@dataclass(frozen=True)
class StrategyPositionFact:
    enabled: bool
    account_id: str
    market: str
    symbol: str
    quantity: float | None
    actual_entry: float | None
    protective_stop: float | None
    entry_date: date | None
    source_event_id: str | None
    updated_at: datetime | date | None
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.market.upper(), self.symbol.upper()


@dataclass(frozen=True)
class ProductionAccountRun:
    account: StrategyAccount
    inputs: tuple[DailySymbolInput, ...]
    existing_positions: tuple[OpenPortfolioPosition, ...]
    state_store: DecisionStateStore | None = None
    # These are reporting/provenance facts only.  They do not change the
    # Daily Chain transaction semantics or create a second universe source.
    formal_strategy_pool: tuple[str, ...] = ()
    active_strategy_positions: tuple[str, ...] = ()
    paper_tracked_symbols: tuple[str, ...] = ()

    @property
    def reference_nav(self) -> float | None:
        return self.account.reference_nav


@dataclass(frozen=True)
class AccountPreflightSummary:
    account_id: str
    market: str
    currency: str
    trade_date: date
    nav_status: str
    strategy_symbol_count: int
    position_count: int
    data_ok_count: int
    data_bad_stale_unavailable_count: int
    missing_risk_groups: tuple[str, ...]
    missing_position_origins: tuple[str, ...]
    calendar_status: str
    state_store_status: str
    production_readiness: str
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "账户ID": self.account_id,
            "市场": self.market,
            "币种": self.currency,
            "T": self.trade_date.isoformat(),
            "NAV状态": self.nav_status,
            "策略股票数": self.strategy_symbol_count,
            "持仓数": self.position_count,
            "DATA_OK数": self.data_ok_count,
            "DATA_BAD/STALE/UNAVAILABLE数": self.data_bad_stale_unavailable_count,
            "缺风险组": list(self.missing_risk_groups),
            "缺PositionOrigin": list(self.missing_position_origins),
            "calendar status": self.calendar_status,
            "state-store status": self.state_store_status,
            "production readiness": self.production_readiness,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ProductionPreflightReport:
    trade_date: date
    accounts: tuple[AccountPreflightSummary, ...]
    errors: tuple[str, ...]
    state_store_status: str
    writes_performed: bool = False

    @property
    def ready(self) -> bool:
        return not self.errors and bool(self.accounts) and all(
            item.production_readiness == "READY" for item in self.accounts
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "T": self.trade_date.isoformat(),
            "accounts": [item.to_dict() for item in self.accounts],
            "errors": list(self.errors),
            "state-store status": self.state_store_status,
            "read behavior": "READ_ONLY",
            "NO STATE WRITE": not self.writes_performed,
            "NO Sheets mutation": not self.writes_performed,
            "production readiness": "READY" if self.ready else "NOT_READY",
        }

    def to_markdown(self) -> str:
        lines = [
            "# Production Prerequisites V1 Preflight", "",
            f"- T：{self.trade_date.isoformat()}",
            f"- state-store status：{self.state_store_status}",
            f"- read behavior：READ_ONLY；NO STATE WRITE：{'是' if not self.writes_performed else '否'}",
            f"- production readiness：{'READY' if self.ready else 'NOT_READY'}", "",
        ]
        for account in self.accounts:
            lines.extend([
                f"## {account.account_id}（{account.market}/{account.currency}）", "",
                f"- NAV状态：{account.nav_status}；策略股票数：{account.strategy_symbol_count}；持仓数：{account.position_count}",
                f"- DATA_OK数：{account.data_ok_count}；DATA_BAD/STALE/UNAVAILABLE数：{account.data_bad_stale_unavailable_count}",
                f"- 缺风险组：{'、'.join(account.missing_risk_groups) or '无'}",
                f"- 缺PositionOrigin：{'、'.join(account.missing_position_origins) or '无'}",
                f"- calendar status：{account.calendar_status}；state-store status：{account.state_store_status}",
                f"- production readiness：{account.production_readiness}",
            ])
            if account.errors:
                lines.append(f"- errors：{'；'.join(account.errors)}")
            lines.append("")
        if self.errors:
            lines.extend(["## errors", "", *[f"- {item}" for item in self.errors], ""])
        return "\n".join(lines)


@dataclass(frozen=True)
class ProductionSnapshot:
    preflight: ProductionPreflightReport
    account_runs: tuple[ProductionAccountRun, ...]


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key, "")
    return str(value).strip() if value is not None else ""


def _market_rows(rows: Sequence[Mapping[str, Any]], market: str | None) -> list[dict]:
    """Keep only one market's records before parsing their business fields.

    Sheets is a shared configuration store, but a cloud run is deliberately
    scoped to one exchange.  Filtering before parsing prevents malformed rows
    belonging to the other exchange from blocking an otherwise independent
    report.  Blank rows are ignored by the scoped path just like the existing
    parsers ignore blank rows.
    """

    if not market:
        return list(rows)
    wanted = str(market).strip().upper()
    return [row for row in rows if _text(row, "市场").upper() == wanted]


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "启用"}


def _as_float(value: Any, *, field_name: str, required: bool = True) -> float | None:
    if value is None or str(value).strip() == "":
        if required:
            raise ProductionPrerequisiteError(f"{field_name} required")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionPrerequisiteError(f"{field_name} malformed") from exc
    if not math.isfinite(number):
        raise ProductionPrerequisiteError(f"{field_name} must be finite")
    return number


def parse_sheet_date(value: Any, *, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
        except (OverflowError, ValueError) as exc:
            raise ProductionPrerequisiteError(f"{field_name} malformed") from exc
    text = str(value).strip()
    if not text:
        raise ProductionPrerequisiteError(f"{field_name} required")
    try:
        return date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError as exc:
        raise ProductionPrerequisiteError(f"{field_name} malformed") from exc


def parse_sheet_datetime(value: Any, *, field_name: str) -> datetime | date:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ProductionPrerequisiteError(f"{field_name} required")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return parse_sheet_date(value, field_name=field_name)


def _key(market: str, symbol: str) -> tuple[str, str]:
    return str(market).strip().upper(), str(symbol).strip().upper()


def _headers_for(client: Any, sheet_name: str, rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    if hasattr(client, "headers"):
        values = client.headers(sheet_name)
        if values:
            return tuple(str(item).strip() for item in values if str(item).strip())
    book = getattr(client, "book", None)
    if book is not None:
        worksheet = book.worksheet(sheet_name)
        if hasattr(worksheet, "row_values"):
            values = worksheet.row_values(1)
            if values:
                return tuple(str(item).strip() for item in values if str(item).strip())
    values: list[str] = []
    for row in rows:
        for name in row:
            if str(name) not in values:
                values.append(str(name))
    return tuple(values)


def validate_sheet_schema(
    client: SheetsRecordsClient,
    sheet_name: str,
    required_headers: Sequence[str],
) -> tuple[str, ...]:
    """Validate a Sheet through the existing ``records`` boundary."""
    try:
        rows = list(client.records(sheet_name))
        return _validate_headers(client, sheet_name, rows, required_headers)
    except Exception as exc:
        return (f"{PRODUCTION_SCHEMA_REQUIRED}:{sheet_name}:{exc}",)


def _validate_headers(
    client: Any,
    sheet_name: str,
    rows: Sequence[Mapping[str, Any]],
    required_headers: Sequence[str],
) -> tuple[str, ...]:
    headers = _headers_for(client, sheet_name, rows)
    missing = tuple(header for header in required_headers if header not in headers)
    return tuple(f"{PRODUCTION_SCHEMA_REQUIRED}:{sheet_name}:缺少{header}" for header in missing)


def parse_strategy_accounts(rows: Iterable[Mapping[str, Any]], *, as_of_date: date | None = None) -> tuple[StrategyAccount, ...]:
    result: list[StrategyAccount] = []
    seen: set[str] = set()
    for row in rows:
        account_id = _text(row, "账户ID")
        if not account_id:
            if any(_text(row, header) for header in STRATEGY_ACCOUNT_HEADERS):
                raise ProductionPrerequisiteError(f"{PRODUCTION_ACCOUNT_REQUIRED}:账户ID")
            continue
        if account_id in seen:
            raise ProductionPrerequisiteError(f"{PRODUCTION_ACCOUNT_REQUIRED}:duplicate:{account_id}")
        seen.add(account_id)
        enabled = _as_bool(row.get("启用"))
        market = _text(row, "市场").upper()
        currency = _text(row, "币种").upper()
        # These legacy Sheet fields remain readable for compatibility, but are
        # optional allocation facts rather than strategy prerequisites.
        try:
            nav = _as_float(row.get("参考净值"), field_name="参考净值", required=False)
        except ProductionPrerequisiteError:
            nav = None
        nav_date = None
        raw_nav_date = row.get("净值日期")
        if raw_nav_date is not None and str(raw_nav_date).strip():
            try:
                nav_date = parse_sheet_date(raw_nav_date, field_name="净值日期")
            except ProductionPrerequisiteError:
                nav_date = None
        if enabled:
            if not market or not currency:
                raise ProductionPrerequisiteError(f"{PRODUCTION_ACCOUNT_REQUIRED}:{account_id}")
            expected_currency = EXPECTED_CURRENCY_BY_MARKET.get(market)
            if expected_currency and currency != expected_currency:
                raise ProductionPrerequisiteError(
                    f"{PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH}:{account_id}"
                )
        result.append(StrategyAccount(account_id, enabled, market, currency, nav, nav_date, _text(row, "备注")))
    return tuple(result)


def parse_strategy_universe(rows: Iterable[Mapping[str, Any]]) -> tuple[StrategyUniverseEntry, ...]:
    result: list[StrategyUniverseEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if not _as_bool(row.get("启用")):
            continue
        item = StrategyUniverseEntry(
            True, _text(row, "账户ID"), _text(row, "市场").upper(),
            _text(row, "统一代码").upper(), _text(row, "名称"), _text(row, "备注"),
        )
        if not item.account_id or not item.market or not item.symbol:
            raise ProductionPrerequisiteError("PRODUCTION_STRATEGY_UNIVERSE_REQUIRED")
        identity = (item.account_id, *item.key)
        if identity in seen:
            raise ProductionPrerequisiteError(f"PRODUCTION_STRATEGY_UNIVERSE_DUPLICATE:{'|'.join(identity)}")
        seen.add(identity)
        result.append(item)
    return tuple(result)


def parse_risk_groups(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], StrategyRiskGroup]:
    result: dict[tuple[str, str], StrategyRiskGroup] = {}
    for row in rows:
        market, symbol = _key(_text(row, "市场"), _text(row, "统一代码"))
        group = _text(row, "风险组")
        if not market and not symbol and not group:
            continue
        if not market or not symbol or not group:
            raise ProductionPrerequisiteError("PRODUCTION_RISK_GROUP_REQUIRED")
        key = (market, symbol)
        if key in result:
            raise ProductionPrerequisiteError(f"PRODUCTION_RISK_GROUP_DUPLICATE:{market}|{symbol}")
        result[key] = StrategyRiskGroup(market, symbol, normalize_risk_group(group), _text(row, "备注"))
    return result


def parse_strategy_positions(rows: Iterable[Mapping[str, Any]]) -> tuple[StrategyPositionFact, ...]:
    result: list[StrategyPositionFact] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if not _as_bool(row.get("启用")):
            continue
        account_id = _text(row, "账户ID")
        market = _text(row, "市场").upper()
        symbol = _text(row, "统一代码").upper()
        if not account_id or not market or not symbol:
            raise ProductionPrerequisiteError("PRODUCTION_OPEN_POSITION_REQUIRED")
        identity = (account_id, market, symbol)
        if identity in seen:
            raise ProductionPrerequisiteError(f"PRODUCTION_OPEN_POSITION_DUPLICATE:{'|'.join(identity)}")
        seen.add(identity)
        quantity = _as_float(row.get("数量"), field_name="数量")
        actual_entry = _as_float(row.get("实际入场价"), field_name="实际入场价")
        protective_stop = _as_float(row.get("当前保护止损"), field_name="当前保护止损")
        if quantity is None or quantity <= 0 or actual_entry is None or protective_stop is None:
            raise ProductionPrerequisiteError(f"PRODUCTION_OPEN_POSITION_INVALID:{'|'.join(identity)}")
        entry_date = parse_sheet_date(row.get("入场日期"), field_name="入场日期")
        source_event = _text(row, "来源事件ID") or None
        updated_at = None
        if _text(row, "更新时间"):
            updated_at = parse_sheet_datetime(row.get("更新时间"), field_name="更新时间")
        result.append(StrategyPositionFact(
            True, account_id, market, symbol, quantity, actual_entry,
            protective_stop, entry_date, source_event, updated_at, _text(row, "备注"),
        ))
    return tuple(result)


def _number_from_row(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        if name in row and str(row.get(name)).strip() != "":
            return _as_float(row.get(name), field_name=name)
    return None


def _quote_from_row(
    row: Mapping[str, Any], *, symbol: str, market: str, name: str, currency: str,
) -> Quote:
    trade_date = parse_sheet_date(row.get("交易日期"), field_name="交易日期")
    values = {
        field: _number_from_row(row, chinese, english)
        for field, chinese, english in (
            ("open", "开盘", "Open"), ("high", "最高", "High"),
            ("low", "最低", "Low"), ("close", "收盘", "Close"),
        )
    }
    if any(value is None for value in values.values()):
        raise ProductionPrerequisiteError("行情OHLC字段不完整")
    row_currency = _text(row, "币种")
    if not row_currency:
        raise ProductionPrerequisiteError("行情币种 required")
    return Quote(
        symbol=symbol, name=name or _text(row, "名称"), market=market,
        trade_date=trade_date, source=_text(row, "数据源") or _text(row, "主数据源") or "Sheets",
        open=float(values["open"]), high=float(values["high"]), low=float(values["low"]), close=float(values["close"]),
        preclose=_number_from_row(row, "昨收", "Preclose"),
        pct_change=_number_from_row(row, "涨跌幅", "PctChange"),
        volume=_number_from_row(row, "成交量", "Volume"),
        amount=_number_from_row(row, "成交额", "Amount"),
        turnover_rate=_number_from_row(row, "换手率", "TurnoverRate"),
        currency=row_currency,
    )


def _same_identity(row: Mapping[str, Any], item: StrategyUniverseEntry) -> bool:
    return _key(_text(row, "市场"), _text(row, "统一代码")) == item.key


def _data_for_symbol(
    item: StrategyUniverseEntry,
    *,
    as_of_date: date,
    account_currency: str,
    latest_rows: Sequence[Mapping[str, Any]],
    history_rows: Sequence[Mapping[str, Any]],
    calendar_identity: CompletedSessionIdentity,
) -> tuple[DailySymbolInput, str, str | None]:
    matching_latest = [row for row in latest_rows if _same_identity(row, item)]
    matching_history = [
        row for row in history_rows
        if _same_identity(row, item)
        and (not _text(row, "复权方式") or _text(row, "复权方式").lower() in _QFQ_NAMES)
    ]
    status = DATA_OK
    detail: str | None = None
    latest_quote: Quote | None = None
    history: tuple[Quote, ...] = ()
    if not matching_latest:
        status, detail = DATA_UNAVAILABLE, "latest missing"
    elif len(matching_latest) != 1:
        status, detail = DATA_BAD, "latest identity duplicate"
    else:
        row = matching_latest[0]
        try:
            latest_quote = _quote_from_row(row, symbol=item.symbol, market=item.market, name=item.name, currency=account_currency)
            if latest_quote.currency.upper() != account_currency.upper():
                raise ProductionPrerequisiteError(PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH)
            if latest_quote.trade_date < as_of_date:
                status, detail = DATA_STALE, "latest date < T"
            elif latest_quote.trade_date > as_of_date:
                status, detail = DATA_BAD, "latest date > T"
            elif not _as_bool(row.get("正式收盘")):
                status, detail = DATA_BAD, "latest not formally closed"
            elif _text(row, "校验状态") != "已验证":
                status, detail = DATA_BAD, "latest validation not verified"
        except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
            status, detail = DATA_BAD, str(exc)
    if not matching_history:
        if status == DATA_OK:
            status, detail = DATA_UNAVAILABLE, "qfq missing"
    else:
        try:
            parsed_history = [
                _quote_from_row(row, symbol=item.symbol, market=item.market, name=item.name, currency=account_currency)
                for row in matching_history
            ]
            dates = [quote.trade_date for quote in parsed_history]
            if len(set(dates)) != len(dates):
                raise ProductionPrerequisiteError("qfq duplicate date")
            if any(quote.currency.upper() != account_currency.upper() for quote in parsed_history):
                raise ProductionPrerequisiteError(PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH)
            history = tuple(sorted(parsed_history, key=lambda quote: quote.trade_date))
            if history[-1].trade_date < as_of_date:
                status, detail = DATA_STALE, "qfq last date < T"
            elif history[-1].trade_date > as_of_date:
                status, detail = DATA_BAD, "qfq last date > T"
        except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
            status, detail = DATA_BAD, str(exc)
            history = ()
    if status == DATA_OK and (latest_quote is None or not history or history[-1].trade_date != as_of_date):
        status, detail = DATA_BAD, "latest/qfq T coverage incomplete"
    return DailySymbolInput(
        symbol=item.symbol, market=item.market, as_of_date=as_of_date,
        qfq_history=history, data_quality_status=status,
        completed_session_identity=calendar_identity,
    ), status, detail


class ExactExchangeCalendarProvider:
    """Exact production session identity backed by ``exchange_calendars``."""

    MARKET_CALENDAR_MAP = {"CN": "XSHG", "US": "XNYS"}

    def __init__(self, mapping: Mapping[str, str] | None = None) -> None:
        self.mapping = {str(k).upper(): str(v) for k, v in (mapping or self.MARKET_CALENDAR_MAP).items()}

    def calendar_name(self, market: str) -> str:
        name = self.mapping.get(str(market).upper())
        if not name:
            raise ProductionPrerequisiteError("PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED")
        return name

    def is_session(self, market: str, trade_date: date) -> bool:
        """Return whether ``trade_date`` is an exact exchange session."""

        try:
            import exchange_calendars as xc
            import pandas as pd
            calendar = xc.get_calendar(self.calendar_name(market))
            return bool(calendar.is_session(pd.Timestamp(trade_date)))
        except (ImportError, KeyError, TypeError, ValueError) as exc:
            raise ProductionPrerequisiteError(
                "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED"
            ) from exc

    def completed_session(
        self, market: str, trade_date: date, *, now: datetime | None = None
    ) -> CompletedSessionIdentity:
        try:
            import exchange_calendars as xc
            import pandas as pd
            name = self.calendar_name(market)
            session = pd.Timestamp(trade_date)
            calendar = xc.get_calendar(name)
            if not calendar.is_session(session):
                raise ProductionPrerequisiteError(
                    "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED"
                )
            if now is not None:
                if now.tzinfo is None or now.utcoffset() is None:
                    raise ProductionPrerequisiteError("COMPLETED_SESSION_REQUIRED")
                current = pd.Timestamp(now)
                if current < calendar.session_close(session):
                    raise ProductionPrerequisiteError("COMPLETED_SESSION_REQUIRED")
            next_session = calendar.next_session(session).date()
        except ProductionPrerequisiteError:
            raise
        except (ImportError, KeyError, TypeError, ValueError) as exc:
            raise ProductionPrerequisiteError(
                "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED"
            ) from exc
        return CompletedSessionIdentity(
            market=str(market).upper(), trade_date=trade_date,
            identity=f"exchange_calendars:{name}:{trade_date.isoformat()}",
            exact_exchange_calendar=True,
            next_session_date=next_session,
            session_dates=(trade_date, next_session),
        )

    def get_completed_session(self, market: str, trade_date: date, *, now: datetime | None = None) -> CompletedSessionIdentity:
        return self.completed_session(market, trade_date, now=now)

    def next_session(self, market: str, trade_date: date) -> date:
        next_date = self.completed_session(market, trade_date).next_session_date
        if next_date is None:
            raise ProductionPrerequisiteError(
                "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED"
            )
        return next_date

    def session_identity(self, market: str, trade_date: date) -> str:
        return self.completed_session(market, trade_date).identity


def _state_type_registry() -> dict[str, type]:
    classes = (
        CompletedSessionIdentity, DailyDecisionResult, DailyPortfolioResult,
        DailyPositionManagementResult, PendingT1Decision, SettlementRecord,
        Setup01Decision, Setup01Execution, Setup01TargetCandidate, Setup01TargetProvenance,
        Setup02Decision, Setup02Execution, Setup02TargetCandidate, Setup02TargetProvenance,
        Setup01ReplayEvent, Setup02ReplayEvent, Setup01Evaluation, Setup02Evaluation,
        SwingPoint, PositionSize, RiskReward, EntryPlan, PortfolioCandidate,
        PortfolioReservation, PortfolioSettlement, OpenPortfolioPosition,
        PositionOrigin, PositionTarget, PositionAnchor,
    )
    enum_classes = (
        DecisionAction, SetupState, SwingKind, Trend, PositionAction,
        PositionExitReason, TargetReachStatus, PortfolioReservationStatus,
    )
    values = {cls.__module__ + "." + cls.__qualname__: cls for cls in (*classes, *enum_classes)}
    from trading.daily_decision_chain import T1ExecutionPhase
    values[T1ExecutionPhase.__module__ + "." + T1ExecutionPhase.__qualname__] = T1ExecutionPhase
    return values


def _encode_state(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"__kind__": "enum", "type": value.__class__.__module__ + "." + value.__class__.__qualname__, "value": value.value}
    if isinstance(value, datetime):
        return {"__kind__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__kind__": "date", "value": value.isoformat()}
    if is_dataclass(value):
        return {
            "__kind__": "dataclass",
            "type": value.__class__.__module__ + "." + value.__class__.__qualname__,
            "fields": {
                field.name: _encode_state(getattr(value, field.name))
                for field in fields(value)
                if field.name != "selected_event"
            },
        }
    if isinstance(value, tuple):
        return {"__kind__": "tuple", "items": [_encode_state(item) for item in value]}
    if isinstance(value, list):
        return {"__kind__": "list", "items": [_encode_state(item) for item in value]}
    if isinstance(value, dict):
        return {"__kind__": "dict", "items": [[_encode_state(key), _encode_state(item)] for key, item in value.items()]}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported state payload value: {type(value).__name__}")


def _decode_state(value: Any) -> Any:
    if not isinstance(value, dict) or "__kind__" not in value:
        if isinstance(value, list):
            return [_decode_state(item) for item in value]
        return value
    kind = value.get("__kind__")
    if kind == "date":
        return date.fromisoformat(str(value["value"]))
    if kind == "datetime":
        return datetime.fromisoformat(str(value["value"]))
    if kind == "enum":
        cls = _state_type_registry().get(str(value["type"]))
        if cls is None or not issubclass(cls, Enum):
            raise ValueError("unknown persisted enum type")
        return cls(value["value"])
    if kind == "tuple":
        return tuple(_decode_state(item) for item in value["items"])
    if kind == "list":
        return [_decode_state(item) for item in value["items"]]
    if kind == "dict":
        return {_decode_state(pair[0]): _decode_state(pair[1]) for pair in value["items"]}
    if kind == "dataclass":
        cls = _state_type_registry().get(str(value["type"]))
        if cls is None or not is_dataclass(cls):
            raise ValueError("unknown persisted dataclass type")
        data = value.get("fields")
        if not isinstance(data, dict):
            raise ValueError("persisted dataclass fields malformed")
        return cls(**{name: _decode_state(item) for name, item in data.items()})
    raise ValueError("unknown persisted payload kind")


def encode_payload(value: Any) -> str:
    return json.dumps(_encode_state(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_payload(payload: str) -> Any:
    parsed = json.loads(payload)
    return _decode_state(parsed)


class SheetsDecisionStateStore:
    """Persistent ``DecisionStateStore`` using one injected Sheets client.

    The default is read-only.  A caller must explicitly pass ``write_enabled``
    to use the normal stateful path; preflight never does so.
    """

    def __init__(
        self,
        client: SheetsRecordsClient,
        *,
        write_enabled: bool = False,
        account_id: str | None = None,
        known_account_ids: Iterable[str] | None = None,
        sheet_name: str = DECISION_STATE_SHEET,
        market: str | None = None,
    ) -> None:
        self.client = client
        self.write_enabled = write_enabled
        self.account_id = str(account_id or "").strip()
        if not self.account_id:
            raise ProductionPrerequisiteError(PRODUCTION_STATE_ACCOUNT_REQUIRED)
        self.known_account_ids = frozenset(
            str(value).strip() for value in (known_account_ids or ()) if str(value).strip()
        )
        if self.known_account_ids and self.account_id not in self.known_account_ids:
            raise ProductionPrerequisiteError(f"unknown persisted account: {self.account_id}")
        self.sheet_name = sheet_name
        normalized_market = str(market or "").strip().upper()
        if normalized_market and normalized_market not in {"CN", "US"}:
            raise ProductionPrerequisiteError(f"unsupported market: {normalized_market}")
        self.market = normalized_market or None
        self._records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.published_events: dict[str, DailyDecisionResult] = {}
        self.pending: dict[str, PendingT1Decision] = {}
        self.settled: dict[str, SettlementRecord] = {}
        self.position_origins: dict[str, PositionOrigin] = {}
        self.daily_history: list[DailyDecisionResult] = []
        loaded: dict[tuple[str, str], Any] = {}
        rows = list(client.records(sheet_name))
        for row in rows:
            if self.market and _text(row, "市场").upper() != self.market:
                continue
            row_account_id = _text(row, "账户ID")
            if not row_account_id:
                raise ProductionPrerequisiteError("corrupted persisted state: account")
            if self.known_account_ids and row_account_id not in self.known_account_ids:
                raise ProductionPrerequisiteError(f"unknown persisted account: {row_account_id}")
            if row_account_id != self.account_id:
                if not self.known_account_ids:
                    raise ProductionPrerequisiteError(
                        f"account-mismatched persisted state: {row_account_id}"
                    )
                continue
            record_type = _text(row, "记录类型")
            primary_key = _text(row, "主键")
            if record_type not in _STATE_RECORD_TYPES or not primary_key:
                raise ProductionPrerequisiteError("corrupted persisted state: identity")
            identity = (row_account_id, record_type, primary_key)
            if identity in self._records:
                raise ProductionPrerequisiteError(f"duplicate persisted primary key: {record_type}|{primary_key}")
            payload = row.get("PayloadJSON")
            if not isinstance(payload, str) or not payload.strip():
                raise ProductionPrerequisiteError("corrupted persisted state: PayloadJSON")
            try:
                value = decode_payload(payload)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise ProductionPrerequisiteError("corrupted persisted state: PayloadJSON") from exc
            self._records[identity] = dict(row)
            loaded[(record_type, primary_key)] = value
        self._load_values(loaded)

    def _load_values(self, loaded: Mapping[tuple[str, str], Any]) -> None:
        for (record_type, primary_key), value in loaded.items():
            if record_type == PUBLISHED_EVENT:
                if not isinstance(value, DailyDecisionResult):
                    raise ProductionPrerequisiteError("corrupted published event payload")
                self.published_events[primary_key] = value
            elif record_type == PENDING_T1:
                if not isinstance(value, PendingT1Decision):
                    raise ProductionPrerequisiteError("corrupted pending payload")
                event = getattr(value, "event", None)
                if not isinstance(event, (Setup01ReplayEvent, Setup02ReplayEvent)):
                    raise ProductionPrerequisiteError("corrupted pending event payload")
                if event.event_identity != primary_key:
                    raise ProductionPrerequisiteError(f"corrupted pending lineage: {primary_key}")
                self.pending[primary_key] = value
            elif record_type == SETTLEMENT:
                if not isinstance(value, SettlementRecord):
                    raise ProductionPrerequisiteError("corrupted settlement payload")
                settlement_pending = getattr(value, "pending", None)
                if not isinstance(settlement_pending, PendingT1Decision):
                    raise ProductionPrerequisiteError("corrupted settlement pending payload")
                if getattr(settlement_pending.event, "event_identity", None) != primary_key:
                    raise ProductionPrerequisiteError(f"corrupted settlement lineage: {primary_key}")
                self.settled[primary_key] = value
            elif record_type == POSITION_ORIGIN_RECORD:
                if not isinstance(value, PositionOrigin):
                    raise ProductionPrerequisiteError("corrupted position origin payload")
                if getattr(value, "source_event_identity", None) != primary_key:
                    raise ProductionPrerequisiteError(f"corrupted position origin lineage: {primary_key}")
                self.position_origins[primary_key] = value
            elif record_type == DAILY_RESULT:
                if not isinstance(value, DailyDecisionResult):
                    raise ProductionPrerequisiteError("corrupted daily result payload")
                self.daily_history.append(value)

        for identity, pending in self.pending.items():
            if identity not in self.published_events:
                raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:pending_without_published:{identity}")
        for identity, settlement in self.settled.items():
            pending = self.pending.get(identity)
            if identity not in self.published_events or pending is None or pending != settlement.pending:
                raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:settlement_lineage:{identity}")
        for identity in self.position_origins:
            if identity not in self.settled:
                raise ProductionPrerequisiteError(
                    f"{PERSISTED_STATE_INCOMPLETE}:origin_without_settlement:{identity}"
                )
        for identity in self.settled:
            self.pending.pop(identity, None)
        for identity, result in self.published_events.items():
            portfolio = getattr(result, "portfolio_result", None)
            execution_phase = getattr(
                getattr(result, "execution_phase", None),
                "value",
                getattr(result, "execution_phase", None),
            )
            if (
                portfolio is not None
                and portfolio.status == "PORTFOLIO_ALLOWED"
                and execution_phase == "PENDING_T1_EXECUTION_CHECK"
                and identity not in self.pending
                and identity not in self.settled
            ):
                raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:published_without_t1_state:{identity}")
            event_identities = getattr(result, "new_confirmed_event_identities", ()) or ()
            if not isinstance(event_identities, (tuple, list)):
                raise ProductionPrerequisiteError("corrupted published event identity payload")
            published_identities = set(event_identities)
            if getattr(result, "new_confirmed_event_identity", None):
                published_identities.add(result.new_confirmed_event_identity)
            if getattr(result, "event_was_new", False):
                published_identities.add(identity)
            if published_identities and not any(
                identity in set(item.new_confirmed_event_identities)
                or identity == item.new_confirmed_event_identity
                for item in self.daily_history
            ):
                raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:published_without_daily_result:{identity}")
        for result in self.daily_history:
            event_identities = getattr(result, "new_confirmed_event_identities", ()) or ()
            if not isinstance(event_identities, (tuple, list)):
                raise ProductionPrerequisiteError("corrupted daily result identity payload")
            daily_identities = set(event_identities)
            if getattr(result, "new_confirmed_event_identity", None):
                daily_identities.add(result.new_confirmed_event_identity)
            if getattr(result, "event_was_new", False):
                daily_identities.add(getattr(result, "new_confirmed_event_identity", None) or "")
            if any(identity not in self.published_events for identity in daily_identities if identity):
                raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:daily_without_published")

    def _load_value(self, record_type: str, primary_key: str, value: Any) -> None:
        """Compatibility helper for callers that used the old private hook."""
        self._load_values({(record_type, primary_key): value})

    def _append(self, record_type: str, primary_key: str, value: Any, *, status: str, item: Any = None) -> None:
        identity = (self.account_id, record_type, primary_key)
        if identity in self._records:
            raise ProductionPrerequisiteError(f"duplicate persisted primary key: {record_type}|{primary_key}")
        if not self.write_enabled:
            raise ProductionPrerequisiteError(STATE_STORE_READ_ONLY)
        if not hasattr(self.client, "append_rows"):
            raise ProductionPrerequisiteError("state client lacks append_rows")
        trade_date = (
            getattr(item, "as_of_date", None)
            or getattr(item, "trade_date", None)
            or getattr(item, "entry_date", None)
        )
        symbol = getattr(item, "symbol", "")
        market = getattr(item, "market", "")
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "记录类型": record_type, "主键": primary_key, "账户ID": self.account_id,
            "市场": market, "统一代码": symbol,
            "交易日期": trade_date.isoformat() if isinstance(trade_date, date) else "",
            "状态": status, "PayloadJSON": encode_payload(value), "更新时间": now,
        }
        self.client.append_rows(self.sheet_name, list(DECISION_STATE_HEADERS), [row])
        self._records[identity] = row

    def get_published_event(self, identity: str) -> DailyDecisionResult | None:
        return self.published_events.get(identity)

    def record_published_event(self, identity: str, result: DailyDecisionResult) -> None:
        self._append(PUBLISHED_EVENT, identity, result, status="PUBLISHED", item=result)
        self.published_events[identity] = result

    def pending_for_symbol(self, symbol: str) -> tuple[PendingT1Decision, ...]:
        return tuple(item for identity, item in self.pending.items() if identity not in self.settled and item.event.symbol.upper() == symbol.upper())

    def save_pending(self, pending: PendingT1Decision) -> None:
        identity = pending.event.event_identity
        if identity not in self.published_events:
            raise ProductionPrerequisiteError(f"{PERSISTED_STATE_INCOMPLETE}:pending_without_published:{identity}")
        if identity in self.pending or identity in self.settled:
            raise ProductionPrerequisiteError(f"T+1 decision already persisted: {identity}")
        self._append(PENDING_T1, identity, pending, status="PENDING", item=pending.event)
        self.pending[identity] = pending

    def settle_pending(self, identity: str, record: SettlementRecord) -> None:
        if identity in self.settled:
            raise ProductionPrerequisiteError(f"T+1 settlement already exists: {identity}")
        pending = self.pending.get(identity)
        if pending is None or pending != record.pending:
            raise ProductionPrerequisiteError(f"pending T+1 decision not found: {identity}")
        self._append(SETTLEMENT, identity, record, status="SETTLED", item=record.pending.event)
        self.pending.pop(identity, None)
        self.settled[identity] = record

    def get_settlement(self, identity: str) -> SettlementRecord | None:
        return self.settled.get(identity)

    def save_position_origin(self, origin: PositionOrigin) -> None:
        identity = origin.source_event_identity
        if identity in self.position_origins:
            raise ProductionPrerequisiteError(f"position origin already exists: {identity}")
        self._append(POSITION_ORIGIN_RECORD, identity, origin, status="ACTIVE", item=origin)
        self.position_origins[identity] = origin

    def get_position_origin(self, identity: str) -> PositionOrigin | None:
        return self.position_origins.get(identity)

    def record_daily_result(self, result: DailyDecisionResult) -> None:
        identity = f"{result.market.upper()}|{result.symbol.upper()}|{result.as_of_date.isoformat()}|{result.generated_at.isoformat()}"
        self._append(DAILY_RESULT, identity, result, status="RECORDED", item=result)
        self.daily_history.append(result)


class ProductionInputAdapter:
    """Compose one isolated run per enabled strategy account."""

    def __init__(
        self,
        client: SheetsRecordsClient,
        *,
        as_of_date: date,
        calendar_provider: ExactExchangeCalendarProvider | None = None,
        state_store: DecisionStateStore | None = None,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
        paper_active_symbols: Mapping[str, Sequence[str]] | None = None,
        market: str | None = None,
        ephemeral_latest_rows: Sequence[Mapping[str, Any]] | None = None,
        ephemeral_qfq_rows: Sequence[Mapping[str, Any]] | None = None,
        ephemeral_errors: Mapping[Any, Any] | None = None,
    ) -> None:
        self.client = client
        self.as_of_date = as_of_date
        self.calendar_provider = calendar_provider or ExactExchangeCalendarProvider()
        self.state_store = state_store
        normalized_market = str(market or "").strip().upper()
        if normalized_market and normalized_market not in {"CN", "US"}:
            raise ProductionPrerequisiteError(f"unsupported market: {normalized_market}")
        self.market = normalized_market or None
        self.now = now
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.paper_active_symbols = {
            str(market).upper(): frozenset(
                str(symbol).strip().upper()
                for symbol in symbols
                if str(symbol).strip()
            )
            for market, symbols in (paper_active_symbols or {}).items()
        }
        # ``None`` means use the legacy Sheet-backed path.  An explicit empty
        # sequence is meaningful for the cloud path: it must not silently fall
        # back to yesterday's persisted行情.
        self.ephemeral_latest_rows = (
            None if ephemeral_latest_rows is None else tuple(ephemeral_latest_rows)
        )
        self.ephemeral_qfq_rows = (
            None if ephemeral_qfq_rows is None else tuple(ephemeral_qfq_rows)
        )
        self.ephemeral_errors = dict(ephemeral_errors or {})
        self._snapshot: ProductionSnapshot | None = None

    def _current_now(self) -> datetime:
        value = self.now if self.now is not None else self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ProductionPrerequisiteError("COMPLETED_SESSION_REQUIRED")
        return value

    def _read_all(self) -> tuple[dict[str, list[dict]], list[str]]:
        contracts = {
            STRATEGY_ACCOUNT_SHEET: STRATEGY_ACCOUNT_HEADERS,
            STRATEGY_UNIVERSE_SHEET: STRATEGY_UNIVERSE_HEADERS,
            RISK_GROUP_SHEET: RISK_GROUP_HEADERS,
            STRATEGY_POSITION_SHEET: STRATEGY_POSITION_HEADERS,
            DECISION_STATE_SHEET: DECISION_STATE_HEADERS,
        }
        # Cloud runs inject today's latest/QFQ rows from the ephemeral
        # provider boundary.  Do not even read the legacy market-data sheets
        # on that path; they remain available to the old Sheet-backed/manual
        # runner when the arguments are omitted.
        if self.ephemeral_latest_rows is None:
            contracts[LATEST_SHEET] = LATEST_REQUIRED_HEADERS
        if self.ephemeral_qfq_rows is None:
            contracts[QFQ_HISTORY_SHEET] = QFQ_HISTORY_REQUIRED_HEADERS
        records: dict[str, list[dict]] = {}
        errors: list[str] = []
        for sheet_name, headers in contracts.items():
            try:
                rows = list(self.client.records(sheet_name))
                if headers:
                    errors.extend(_validate_headers(self.client, sheet_name, rows, headers))
                records[sheet_name] = _market_rows(rows, self.market)
            except Exception as exc:
                errors.append(f"{PRODUCTION_SCHEMA_REQUIRED}:{sheet_name}:{exc}")
                records[sheet_name] = []
        return records, list(dict.fromkeys(errors))

    def snapshot(self) -> ProductionSnapshot:
        if self._snapshot is not None:
            return self._snapshot
        records, errors = self._read_all()
        state_status = "OK"
        try:
            accounts = parse_strategy_accounts(records.get(STRATEGY_ACCOUNT_SHEET, []), as_of_date=self.as_of_date)
            universe = parse_strategy_universe(records.get(STRATEGY_UNIVERSE_SHEET, []))
            risk_groups = parse_risk_groups(records.get(RISK_GROUP_SHEET, []))
            positions = parse_strategy_positions(records.get(STRATEGY_POSITION_SHEET, []))
        except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
            errors.append(str(exc))
            accounts, universe, risk_groups, positions = (), (), {}, ()
        enabled_accounts = {item.account_id: item for item in accounts if item.enabled}
        state_stores: dict[str, DecisionStateStore] = {}
        known_account_ids = tuple(item.account_id for item in accounts)
        if self.state_store is not None:
            injected_account_id = str(getattr(self.state_store, "account_id", "") or "").strip()
            if injected_account_id:
                if injected_account_id in enabled_accounts:
                    state_stores[injected_account_id] = self.state_store
                else:
                    state_status = f"ERROR:unknown persisted account: {injected_account_id}"
                    errors.append(PRODUCTION_STATE_STORE_REQUIRED)
            elif len(enabled_accounts) == 1:
                state_stores[next(iter(enabled_accounts))] = self.state_store
            else:
                state_status = f"ERROR:{PRODUCTION_STATE_ACCOUNT_REQUIRED}"
                errors.append(PRODUCTION_STATE_STORE_REQUIRED)
        else:
            try:
                for account_id in known_account_ids:
                    store = SheetsDecisionStateStore(
                        self.client,
                        write_enabled=False,
                        account_id=account_id,
                        known_account_ids=known_account_ids,
                        market=self.market,
                    )
                    if account_id in enabled_accounts:
                        state_stores[account_id] = store
            except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
                state_status = f"ERROR:{exc}"
                errors.append(PRODUCTION_STATE_STORE_REQUIRED)
        missing_scoped_accounts = tuple(sorted(set(enabled_accounts) - set(state_stores)))
        if missing_scoped_accounts:
            state_status = f"ERROR:{PRODUCTION_STATE_ACCOUNT_REQUIRED}:{','.join(missing_scoped_accounts)}"
            errors.append(PRODUCTION_STATE_STORE_REQUIRED)
        if not universe:
            errors.append("PRODUCTION_STRATEGY_UNIVERSE_REQUIRED")
        by_symbol_accounts: dict[tuple[str, str], set[str]] = {}
        for item in universe:
            by_symbol_accounts.setdefault(item.key, set()).add(item.account_id)
        for identity, account_ids in by_symbol_accounts.items():
            if len(account_ids) > 1:
                errors.append(f"{STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS}:{identity[0]}|{identity[1]}")
        for item in universe:
            account = enabled_accounts.get(item.account_id)
            if account is None:
                errors.append(f"{PRODUCTION_ACCOUNT_REQUIRED}:{item.account_id}")
            elif item.market != account.market.upper():
                errors.append(f"{PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH}:{item.account_id}:{item.symbol}")
        for position in positions:
            account = enabled_accounts.get(position.account_id)
            if account is None:
                errors.append(f"{PRODUCTION_ACCOUNT_REQUIRED}:{position.account_id}")
            elif position.market != account.market.upper():
                errors.append(
                    f"{PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH}:{position.account_id}:{position.symbol}"
                )
        for account in enabled_accounts.values():
            expected_currency = EXPECTED_CURRENCY_BY_MARKET.get(account.market.upper())
            if expected_currency and account.currency.upper() != expected_currency:
                errors.append(f"{PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH}:{account.account_id}")
        runs: list[ProductionAccountRun] = []
        summaries: list[AccountPreflightSummary] = []
        for account in enabled_accounts.values():
            account_errors: list[str] = []
            account_universe = tuple(item for item in universe if item.account_id == account.account_id)
            account_positions = tuple(item for item in positions if item.account_id == account.account_id)
            if not account_universe:
                account_errors.append(PRODUCTION_ACCOUNT_STRATEGY_UNIVERSE_REQUIRED)
            formal_keys = {item.key for item in account_universe}
            # An active position is an independent management input.  It is
            # still validated against the same latest/QFQ and PositionOrigin
            # contracts, but it must not disappear merely because its symbol
            # is absent from today's formal pool or Candidate set.
            position_only_entries = tuple(
                StrategyUniverseEntry(
                    True,
                    account.account_id,
                    position.market,
                    position.symbol,
                    position.symbol,
                    "ACTIVE_POSITION_OUTSIDE_FORMAL_POOL",
                )
                for position in account_positions
                if position.key not in formal_keys
            )
            paper_entries = tuple(
                StrategyUniverseEntry(
                    True,
                    account.account_id,
                    account.market.upper(),
                    symbol,
                    symbol,
                    "PAPER_TRACKED",
                )
                for symbol in sorted(self.paper_active_symbols.get(account.market.upper(), ()))
                if (account.market.upper(), symbol) not in formal_keys
                and (account.market.upper(), symbol)
                not in {entry.key for entry in position_only_entries}
            )
            analysis_entries = account_universe + position_only_entries + paper_entries
            nav_status = "NOT_REQUIRED_FOR_STRATEGY_PROPOSAL"
            try:
                current_now = self._current_now()
                calendar_identity = self.calendar_provider.completed_session(
                    account.market, self.as_of_date, now=current_now
                )
                calendar_status = f"OK:{calendar_identity.identity}->{calendar_identity.next_session_date.isoformat()}"
            except ProductionPrerequisiteError as exc:
                calendar_identity = None
                calendar_status = f"ERROR:{exc}"
                account_errors.append(str(exc))
            latest_rows = (
                records.get(LATEST_SHEET, [])
                if self.ephemeral_latest_rows is None
                else list(self.ephemeral_latest_rows)
            )
            history_rows = (
                records.get(QFQ_HISTORY_SHEET, [])
                if self.ephemeral_qfq_rows is None
                else list(self.ephemeral_qfq_rows)
            )
            inputs: list[DailySymbolInput] = []
            existing_positions: list[OpenPortfolioPosition] = []
            statuses: list[str] = []
            missing_groups: list[str] = []
            missing_origins: list[str] = []
            position_by_key = {item.key: item for item in account_positions}
            for item in analysis_entries:
                group = risk_groups.get(item.key)
                if item.note != "PAPER_TRACKED" and (
                    group is None or group.risk_group == UNKNOWN_RISK_GROUP
                ):
                    missing_groups.append(item.symbol)
                try:
                    if calendar_identity is None:
                        continue
                    symbol_input, status, detail = _data_for_symbol(
                        item, as_of_date=self.as_of_date, account_currency=account.currency,
                        latest_rows=latest_rows, history_rows=history_rows,
                        calendar_identity=calendar_identity,
                    )
                    extra_detail = self.ephemeral_errors.get(
                        f"{item.market.upper()}|{item.symbol.upper()}"
                    )
                    if extra_detail and status != DATA_OK:
                        detail = str(extra_detail)
                    symbol_input = replace(
                        symbol_input,
                        risk_group=group.risk_group if group else None,
                        paper_tracked=item.note == "PAPER_TRACKED",
                    )
                    if status != DATA_OK:
                        account_errors.append(f"{PRODUCTION_DATA_QUALITY_REQUIRED}:{item.symbol}:{status}:{detail}")
                    statuses.append(status)
                    inputs.append(symbol_input)
                    position_fact = position_by_key.get(item.key)
                    if position_fact is not None:
                        origin = None
                        if position_fact.source_event_id:
                            origin = _position_origin_from_store(
                                state_stores.get(account.account_id), position_fact.source_event_id
                            )
                            if origin is None:
                                missing_origins.append(item.symbol)
                        else:
                            missing_origins.append(item.symbol)
                        if origin is not None and (
                            origin.source_event_identity != position_fact.source_event_id
                            or origin.symbol.upper() != item.symbol.upper()
                            or origin.market.upper() != item.market.upper()
                            or origin.entry_date > self.as_of_date
                        ):
                            account_errors.append(f"POSITION_ORIGIN_IDENTITY_MISMATCH:{item.symbol}")
                            origin = None
                        latest_quote = _latest_quote_for_input(symbol_input, latest_rows, item, account.currency)
                        portfolio_position = None
                        if latest_quote is not None and status == DATA_OK:
                            portfolio_position = OpenPortfolioPosition(
                                source_event_identity=position_fact.source_event_id or f"MANUAL_POSITION|{account.account_id}|{item.market}|{item.symbol}",
                                source_setup="MANUAL_STRATEGY_POSITION",
                                symbol=item.symbol, market=item.market,
                                entry_date=position_fact.entry_date or self.as_of_date,
                                quantity=float(position_fact.quantity), current_price=float(latest_quote.close),
                                active_protective_stop=float(position_fact.protective_stop),
                                risk_group=group.risk_group if group else UNKNOWN_RISK_GROUP,
                                actual_entry=float(position_fact.actual_entry),
                            )
                            existing_positions.append(portfolio_position)
                        inputs[-1] = DailySymbolInput(
                            symbol=symbol_input.symbol, market=symbol_input.market, as_of_date=symbol_input.as_of_date,
                            qfq_history=symbol_input.qfq_history, data_quality_status=symbol_input.data_quality_status,
                            completed_session_identity=symbol_input.completed_session_identity,
                            risk_group=group.risk_group if group else None,
                            open_position_state=OpenPositionState(item.symbol, item.market, origin=origin, portfolio_position=portfolio_position),
                            paper_tracked=False,
                        )
                except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
                    account_errors.append(f"{PRODUCTION_DATA_QUALITY_REQUIRED}:{item.symbol}:{exc}")
            scoped_store = state_stores.get(account.account_id)
            pending_values = tuple(getattr(scoped_store, "pending", {}).values())
            universe_keys = formal_keys
            for pending in pending_values:
                pending_key = (
                    str(getattr(pending.event, "market", "")).upper(),
                    str(getattr(pending.event, "symbol", "")).upper(),
                )
                if pending_key not in universe_keys:
                    account_errors.append(
                        f"{PENDING_T1_SYMBOL_OUTSIDE_STRATEGY_UNIVERSE}:{pending.event.symbol}"
                    )
            data_ok = sum(status == DATA_OK for status in statuses)
            data_bad = len(statuses) - data_ok
            readiness = "READY"
            if account_errors or state_status != "OK":
                readiness = "NOT_READY"
            store_for_run = scoped_store
            if store_for_run is None:
                readiness = "NOT_READY"
            if calendar_identity is not None and analysis_entries and store_for_run is not None:
                runs.append(ProductionAccountRun(
                    account,
                    tuple(inputs),
                    tuple(existing_positions),
                    store_for_run,
                    tuple(item.symbol for item in account_universe),
                    tuple(item.symbol for item in account_positions),
                    tuple(item.symbol for item in paper_entries),
                ))
            summaries.append(AccountPreflightSummary(
                account_id=account.account_id, market=account.market, currency=account.currency,
                trade_date=self.as_of_date, nav_status=nav_status,
                strategy_symbol_count=len(account_universe), position_count=len(account_positions),
                data_ok_count=data_ok, data_bad_stale_unavailable_count=data_bad,
                missing_risk_groups=tuple(sorted(set(missing_groups))),
                missing_position_origins=tuple(sorted(set(missing_origins))),
                calendar_status=calendar_status, state_store_status=state_status,
                production_readiness=readiness, errors=tuple(dict.fromkeys(account_errors)),
            ))
        if not enabled_accounts:
            errors.append(PRODUCTION_ACCOUNT_REQUIRED)
        report = ProductionPreflightReport(
            self.as_of_date, tuple(summaries), tuple(dict.fromkeys(errors)), state_status, writes_performed=False
        )
        self._snapshot = ProductionSnapshot(report, tuple(runs))
        return self._snapshot

    def preflight(self) -> ProductionPreflightReport:
        return self.snapshot().preflight

    def account_runs(self) -> tuple[ProductionAccountRun, ...]:
        return self.snapshot().account_runs


def _latest_quote_for_input(
    symbol_input: DailySymbolInput,
    latest_rows: Sequence[Mapping[str, Any]],
    item: StrategyUniverseEntry,
    currency: str,
) -> Quote | None:
    matches = [row for row in latest_rows if _same_identity(row, item)]
    if len(matches) != 1:
        return None
    try:
        return _quote_from_row(matches[0], symbol=item.symbol, market=item.market, name=item.name, currency=currency)
    except (TypeError, ValueError, ProductionPrerequisiteError):
        return None


def _position_origin_from_store(store: DecisionStateStore | None, identity: str) -> PositionOrigin | None:
    if store is None:
        return None
    getter = getattr(store, "get_position_origin", None)
    if getter is not None:
        return getter(identity)
    return getattr(store, "position_origins", {}).get(identity)


def build_production_snapshot(
    client: SheetsRecordsClient,
    *,
    as_of_date: date,
    calendar_provider: ExactExchangeCalendarProvider | None = None,
    state_store: DecisionStateStore | None = None,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    paper_active_symbols: Mapping[str, Sequence[str]] | None = None,
    market: str | None = None,
    ephemeral_latest_rows: Sequence[Mapping[str, Any]] | None = None,
    ephemeral_qfq_rows: Sequence[Mapping[str, Any]] | None = None,
    ephemeral_errors: Mapping[Any, Any] | None = None,
) -> ProductionSnapshot:
    return ProductionInputAdapter(
        client, as_of_date=as_of_date,
        calendar_provider=calendar_provider, state_store=state_store,
        now=now, clock=clock, paper_active_symbols=paper_active_symbols,
        market=market, ephemeral_latest_rows=ephemeral_latest_rows,
        ephemeral_qfq_rows=ephemeral_qfq_rows, ephemeral_errors=ephemeral_errors,
    ).snapshot()


__all__ = [
    "AccountPreflightSummary", "DECISION_STATE_HEADERS", "DECISION_STATE_SHEET",
    "DATA_BAD", "DATA_OK", "DATA_STALE", "DATA_UNAVAILABLE",
    "ExactExchangeCalendarProvider", "ProductionAccountRun", "ProductionInputAdapter",
    "ProductionPreflightReport", "ProductionPrerequisiteError", "ProductionSnapshot",
    "PRODUCTION_ACCOUNT_STRATEGY_UNIVERSE_REQUIRED", "PENDING_T1_SYMBOL_OUTSIDE_STRATEGY_UNIVERSE",
    "PERSISTED_STATE_INCOMPLETE", "PRODUCTION_STATE_ACCOUNT_REQUIRED",
    "PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH", "STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS",
    "PAPER_SYMBOL_MULTIPLE_ACCOUNTS",
    "PAPER_ACCOUNT_ROUTING_REQUIRED",
    "LATEST_REQUIRED_HEADERS", "QFQ_HISTORY_REQUIRED_HEADERS",
    "SheetsDecisionStateStore", "StrategyAccount", "StrategyPositionFact",
    "StrategyRiskGroup", "StrategyUniverseEntry", "build_production_snapshot",
    "decode_payload", "encode_payload", "parse_risk_groups", "parse_sheet_date",
    "parse_strategy_accounts", "parse_strategy_positions", "parse_strategy_universe",
    "validate_sheet_schema",
]
