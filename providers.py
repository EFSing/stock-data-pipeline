from __future__ import annotations

import time
import json
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from functools import lru_cache
from typing import Callable, Iterable
from urllib.parse import quote as urlquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from core import Quote


def _number(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _as_date(value) -> date:
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _records_to_quotes(frame, watch: dict, source: str, volume_multiplier: float = 1.0) -> list[Quote]:
    quotes: list[Quote] = []
    previous_close = None
    for row in frame.to_dict("records"):
        close = _number(row.get("收盘", row.get("Close")))
        if close is None:
            continue
        volume = _number(row.get("成交量", row.get("Volume")))
        preclose = _number(row.get("昨收", row.get("Preclose")))
        if preclose is None:
            preclose = previous_close
        pct_change = _number(row.get("涨跌幅", row.get("PctChange")))
        if pct_change is None and preclose not in (None, 0):
            pct_change = (close / preclose - 1) * 100
        quotes.append(
            Quote(
                symbol=str(watch["统一代码"]),
                name=str(watch["名称"]),
                market=str(watch["市场"]),
                trade_date=_as_date(row.get("日期", row.get("Date"))),
                source=source,
                open=_number(row.get("开盘", row.get("Open"))) or close,
                high=_number(row.get("最高", row.get("High"))) or close,
                low=_number(row.get("最低", row.get("Low"))) or close,
                close=close,
                preclose=preclose,
                pct_change=pct_change,
                volume=volume * volume_multiplier if volume is not None else None,
                amount=_number(row.get("成交额", row.get("Amount"))),
                turnover_rate=_number(row.get("换手率", row.get("TurnoverRate"))),
                currency=str(watch["币种"]),
            )
        )
        previous_close = close
    return quotes


@lru_cache(maxsize=1)
def _akshare_us_symbol_map() -> dict[str, str]:
    import akshare as ak

    frame = ak.stock_us_spot_em()
    result: dict[str, str] = {}
    for provider_code in frame["代码"].astype(str):
        ticker = provider_code.rsplit(".", 1)[-1].upper()
        result.setdefault(ticker, provider_code)
    return result


def fetch_akshare(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    import akshare as ak

    market = str(watch["市场"])
    code = str(watch.get("AKShare代码", ""))
    adjustment = "qfq" if adjust == "qfq" else ""
    kwargs = {
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "adjust": adjustment,
    }
    if market == "CN":
        frame = ak.stock_zh_a_hist(symbol=code, period="daily", **kwargs)
        return _records_to_quotes(frame, watch, "AKShare")
    if market == "HK":
        frame = ak.stock_hk_hist(symbol=code, period="daily", **kwargs)
        return _records_to_quotes(frame, watch, "AKShare")
    if market == "US":
        if not code or code.upper() == "AUTO":
            code = _akshare_us_symbol_map().get(str(watch["统一代码"]).upper(), "")
        if not code:
            raise LookupError(f"AKShare未找到美股代码映射：{watch['统一代码']}")
        frame = ak.stock_us_hist(symbol=code, period="daily", **kwargs)
        return _records_to_quotes(frame, watch, "AKShare")
    raise ValueError(f"AKShare不支持市场：{market}")


def fetch_baostock(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    import baostock as bs
    import pandas as pd

    if str(watch["市场"]) != "CN":
        raise ValueError("BaoStock仅用于A股")
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock登录失败：{login.error_msg}")
    try:
        result = bs.query_history_k_data_plus(
            str(watch["BaoStock代码"]),
            "date,open,high,low,close,preclose,volume,amount,turn,pctChg",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="2" if adjust == "qfq" else "3",
        )
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock查询失败：{result.error_msg}")
        rows = []
        while result.next():
            rows.append(result.get_row_data())
        frame = pd.DataFrame(rows, columns=result.fields).rename(
            columns={
                "date": "日期", "open": "开盘", "high": "最高", "low": "最低",
                "close": "收盘", "preclose": "昨收", "volume": "成交量",
                "amount": "成交额", "turn": "换手率", "pctChg": "涨跌幅",
            }
        )
        return _records_to_quotes(frame, watch, "BaoStock")
    finally:
        bs.logout()


def fetch_yfinance(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    import yfinance as yf

    symbol = str(watch["yfinance代码"])
    yfinance_error: Exception | None = None
    try:
        frame = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=adjust == "qfq",
            actions=False,
            repair=False,
        )
        if not frame.empty:
            frame = frame.reset_index().rename(columns={"Date": "日期"})
            return _records_to_quotes(frame, watch, "yfinance")
    except Exception as exc:
        yfinance_error = exc

    try:
        return _fetch_yahoo_chart(watch, adjust, start, end)
    except Exception as chart_error:
        if yfinance_error is None:
            raise
        raise RuntimeError(
            f"yfinance失败：{yfinance_error}；Yahoo Chart回退失败：{chart_error}"
        ) from chart_error


def _fetch_yahoo_chart(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    """Fetch daily bars from Yahoo's keyless chart endpoint.

    This endpoint does not need the cookie/crumb session used by yfinance, so it
    remains useful when that session is rate-limited.  Two public hosts are tried
    because Yahoo occasionally throttles them independently.
    """
    symbol = str(watch["yfinance代码"])
    period1 = int(datetime.combine(start, datetime_time.min, timezone.utc).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=1), datetime_time.min, timezone.utc).timestamp())
    errors: list[str] = []
    payload = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = (
            f"https://{host}/v8/finance/chart/{urlquote(symbol, safe='')}"
            f"?period1={period1}&period2={period2}&interval=1d&events=history"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            chart_error = payload.get("chart", {}).get("error")
            if chart_error:
                raise RuntimeError(str(chart_error))
            break
        except Exception as exc:
            errors.append(f"{host}: {exc}")
    if payload is None:
        raise RuntimeError("；".join(errors))

    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    price = (indicators.get("quote") or [{}])[0]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    timezone_name = (result.get("meta") or {}).get("exchangeTimezoneName") or "UTC"
    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except Exception:
        exchange_timezone = timezone.utc

    rows = []
    for index, timestamp in enumerate(timestamps):
        raw_close = (price.get("close") or [None] * len(timestamps))[index]
        if raw_close is None:
            continue
        factor = 1.0
        if adjust == "qfq" and index < len(adjusted) and adjusted[index] is not None and raw_close:
            factor = adjusted[index] / raw_close
        row = {
            "日期": datetime.fromtimestamp(timestamp, exchange_timezone).date(),
            "Open": _indexed(price.get("open"), index, raw_close) * factor,
            "High": _indexed(price.get("high"), index, raw_close) * factor,
            "Low": _indexed(price.get("low"), index, raw_close) * factor,
            "Close": raw_close * factor,
            "Volume": _indexed(price.get("volume"), index, None),
        }
        rows.append(row)

    import pandas as pd

    return _records_to_quotes(pd.DataFrame(rows), watch, "YahooChart")


def _indexed(values, index: int, default):
    if not values or index >= len(values) or values[index] is None:
        return default
    return values[index]


PROVIDERS: dict[str, Callable[[dict, str, date, date], list[Quote]]] = {
    "AKShare": fetch_akshare,
    "BaoStock": fetch_baostock,
    "yfinance": fetch_yfinance,
}


def fetch_with_retry(
    source: str,
    watch: dict,
    adjust: str,
    start: date,
    end: date,
    retry_count: int,
    retry_wait_seconds: float,
) -> list[Quote]:
    if source not in PROVIDERS:
        raise ValueError(f"未知数据源：{source}")
    last_error: Exception | None = None
    for attempt in range(1, max(1, retry_count) + 1):
        try:
            quotes = PROVIDERS[source](watch, adjust, start, end)
            return sorted(quotes, key=lambda item: item.trade_date)
        except Exception as exc:  # 上游站点错误需要重试并写入日志。
            last_error = exc
            if attempt < max(1, retry_count):
                time.sleep(max(0, retry_wait_seconds))
    raise RuntimeError(f"{source}连续{retry_count}次抓取失败：{last_error}") from last_error
