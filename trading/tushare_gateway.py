"""Temporary, read-only Tushare gateway for the candidate shadow probe.

The gateway intentionally has one local configuration source.  It is not part
of the production provider fallback chain and it never writes Sheets, state,
orders, or logs containing credentials.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

from core import Quote


TUSHARE_LOCAL_CONFIG_REQUIRED = "TUSHARE_LOCAL_CONFIG_REQUIRED"
TUSHARE_PYTHON_PACKAGE_REQUIRED = "TUSHARE_PYTHON_PACKAGE_REQUIRED"


class TushareGatewayError(RuntimeError):
    """A safe, non-secret gateway error suitable for probe output."""


def _load_local_config() -> tuple[str, str]:
    """Load the required project-local configuration without environment fallback."""

    try:
        from local_tushare_config import TUSHARE_API_URL, TUSHARE_TOKEN
    except ModuleNotFoundError as exc:
        if exc.name == "local_tushare_config":
            raise TushareGatewayError(TUSHARE_LOCAL_CONFIG_REQUIRED) from None
        raise

    token = str(TUSHARE_TOKEN or "").strip()
    api_url = str(TUSHARE_API_URL or "").strip().rstrip("/")
    if not token or token == "YOUR_TOKEN_HERE" or not api_url:
        raise TushareGatewayError(TUSHARE_LOCAL_CONFIG_REQUIRED)
    return token, api_url


def create_tushare_pro(ts_module: Any | None = None) -> Any:
    """Create the vendor client using the required local gateway settings."""

    token, api_url = _load_local_config()
    if ts_module is None:
        try:
            import tushare as ts
        except ModuleNotFoundError:
            raise TushareGatewayError(TUSHARE_PYTHON_PACKAGE_REQUIRED) from None
    else:
        ts = ts_module

    # These assignments are required by the temporary gateway vendor contract.
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = api_url
    return pro


class TushareGateway:
    """Lazy Tushare client wrapper with no production side effects."""

    def __init__(self, ts_module: Any | None = None):
        self._ts_module = ts_module
        self._pro: Any | None = None

    @property
    def pro(self) -> Any:
        if self._pro is None:
            self._pro = create_tushare_pro(self._ts_module)
        return self._pro

    def daily(
        self,
        *,
        ts_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        trade_date: date | None = None,
    ) -> Any:
        """Call the standard Tushare daily endpoint with bounded inputs."""

        if trade_date is not None:
            params = {"trade_date": trade_date.strftime("%Y%m%d")}
        else:
            if not ts_code or start_date is None or end_date is None:
                raise TushareGatewayError("TUSHARE_DAILY_REQUEST_ARGUMENTS_REQUIRED")
            params = {
                "ts_code": str(ts_code),
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            }
        try:
            return self.pro.daily(**params)
        except TushareGatewayError:
            raise
        except Exception:
            # Do not expose vendor exception text: it may contain request data.
            raise TushareGatewayError("TUSHARE_DAILY_REQUEST_FAILED") from None

    def daily_multi_symbol(
        self,
        symbols: Iterable[str],
        *,
        start_date: date,
        end_date: date,
    ) -> Any:
        """Call daily once with the official comma-separated ``ts_code`` shape."""

        values = tuple(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
        if not values:
            raise TushareGatewayError("TUSHARE_DAILY_SYMBOLS_REQUIRED")
        return self.daily(
            ts_code=",".join(values),
            start_date=start_date,
            end_date=end_date,
        )

    def daily_trade_date(self, trade_date: date) -> Any:
        """Call daily once for one completed market date."""

        return self.daily(trade_date=trade_date)

    def adj_factor_multi_symbol(
        self,
        symbols: Iterable[str],
        *,
        start_date: date,
        end_date: date,
    ) -> Any:
        """Call the official multi-symbol adjustment-factor contract."""

        values = tuple(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
        if not values:
            raise TushareGatewayError("TUSHARE_ADJ_FACTOR_SYMBOLS_REQUIRED")
        try:
            return self.pro.adj_factor(
                ts_code=",".join(values),
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception:
            raise TushareGatewayError("TUSHARE_ADJ_FACTOR_REQUEST_FAILED") from None

    def pro_bar_qfq(
        self,
        symbol: str,
        *,
        start_date: date,
        end_date: date,
    ) -> Any:
        """Call the optional vendor pro_bar qfq contract without raw errors."""

        try:
            return self.pro.pro_bar(
                ts_code=str(symbol).strip().upper(),
                adj="qfq",
                freq="D",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception:
            raise TushareGatewayError("TUSHARE_PRO_BAR_QFQ_UNAVAILABLE") from None


def _records(result: Any) -> list[Mapping[str, Any]]:
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return list(result.to_dict("records"))
    if isinstance(result, Mapping):
        return [result]
    return [dict(row) for row in result]


def tushare_result_records(result: Any) -> list[Mapping[str, Any]]:
    """Expose normalized response rows for bounded probe accounting."""

    return _records(result)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _daily_rows_to_quotes(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[Quote]:
    quotes: list[Quote] = []
    for row in rows:
        trade_date = _trade_date(row.get("trade_date"))
        opening = _number(row.get("open"))
        high = _number(row.get("high"))
        low = _number(row.get("low"))
        close = _number(row.get("close"))
        if (
            trade_date is None
            or not start_date <= trade_date <= end_date
            or None in (opening, high, low, close)
        ):
            continue

        # Tushare's daily contract reports vol in hands and amount in thousand
        # CNY; Quote stores base shares and base currency units.
        volume = _number(row.get("vol"))
        amount = _number(row.get("amount"))
        quotes.append(
            Quote(
                symbol=symbol,
                name=symbol,
                market="CN",
                trade_date=trade_date,
                source="TushareGateway",
                open=float(opening),
                high=float(high),
                low=float(low),
                close=float(close),
                preclose=_number(row.get("pre_close")),
                pct_change=_number(row.get("pct_chg")),
                volume=volume * 100.0 if volume is not None else None,
                amount=amount * 1000.0 if amount is not None else None,
                turnover_rate=_number(row.get("turnover_rate")),
                currency="CNY",
            )
        )
    return sorted(quotes, key=lambda quote: quote.trade_date)


def parse_tushare_daily_rows(
    rows: Iterable[Mapping[str, Any]],
    symbols: Iterable[str],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, list[Quote]]:
    """Group a bulk daily response into requested CN symbol histories."""

    requested = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    grouped: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in requested}
    for row in rows:
        symbol = str(row.get("ts_code") or "").strip().upper()
        if symbol in grouped:
            grouped[symbol].append(row)
    return {
        symbol: _daily_rows_to_quotes(
            symbol_rows,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        for symbol, symbol_rows in grouped.items()
    }


def fetch_tushare_daily_history(
    gateway: TushareGateway,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[Quote]:
    """Fetch one CN daily history series for the read-only runtime probe."""

    rows = gateway.daily(ts_code=symbol, start_date=start_date, end_date=end_date)
    return _daily_rows_to_quotes(
        _records(rows),
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_tushare_daily_history_bulk(
    gateway: TushareGateway,
    symbols: Iterable[str],
    start_date: date,
    end_date: date,
) -> dict[str, list[Quote]]:
    """Fetch one comma-separated multi-symbol daily batch."""

    values = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    result = gateway.daily_multi_symbol(values, start_date=start_date, end_date=end_date)
    return parse_tushare_daily_rows(
        _records(result), values, start_date=start_date, end_date=end_date
    )


def fetch_tushare_daily_history_by_trade_date(
    gateway: TushareGateway,
    symbols: Iterable[str],
    trade_dates: Iterable[date],
) -> dict[str, list[Quote]]:
    """Fetch one date-major batch per completed session and filter symbols."""

    values = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    grouped: dict[str, list[Quote]] = {symbol: [] for symbol in values}
    for trade_date in trade_dates:
        result = gateway.daily_trade_date(trade_date)
        day_histories = parse_tushare_daily_rows(
            _records(result),
            values,
            start_date=trade_date,
            end_date=trade_date,
        )
        for symbol, quotes in day_histories.items():
            grouped[symbol].extend(quotes)
    return {
        symbol: sorted(quotes, key=lambda quote: quote.trade_date)
        for symbol, quotes in grouped.items()
    }


__all__ = [
    "TUSHARE_LOCAL_CONFIG_REQUIRED",
    "TUSHARE_PYTHON_PACKAGE_REQUIRED",
    "TushareGateway",
    "TushareGatewayError",
    "create_tushare_pro",
    "fetch_tushare_daily_history",
    "fetch_tushare_daily_history_bulk",
    "fetch_tushare_daily_history_by_trade_date",
    "parse_tushare_daily_rows",
    "tushare_result_records",
]
