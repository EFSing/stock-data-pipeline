from __future__ import annotations

import time
import json
import re
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Callable, Iterable
from urllib.parse import quote as urlquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from core import Quote


RAW_SNAPSHOT_FALLBACKS: dict[str, dict[str, tuple[str, ...]]] = {
    # Opposite orders preserve independent validation whenever both public
    # snapshot endpoints are healthy.
    "CN": {
        "yfinance": ("Tencent", "Sina"),
        "BaoStock": ("Sina", "Tencent"),
        "Tencent": ("Sina",),
        "Sina": ("Tencent",),
    },
    "HK": {
        "yfinance": ("Tencent", "Sina"),
        "Tencent": ("Sina",),
        "Sina": ("Tencent",),
    },
    "US": {
        "yfinance": ("Tencent", "Sina"),
        "Tencent": ("Sina",),
        "Sina": ("Tencent",),
    },
}


def _number(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _row_number(row, *keys):
    """Read one numeric field without substituting another OHLC value."""
    for key in keys:
        if key in row:
            return _number(row[key])
    return None


def _row_ohlc_is_complete(row) -> bool:
    return all(
        _row_number(row, chinese, english) is not None
        for chinese, english in (
            ("开盘", "Open"),
            ("最高", "High"),
            ("最低", "Low"),
            ("收盘", "Close"),
        )
    )


def _as_date(value, timezone_name: str | None = None) -> date:
    """Normalize a provider timestamp to the market's local session date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("行情日期为空")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return date.fromisoformat(text[:10])
    if parsed.tzinfo is not None and timezone_name:
        parsed = parsed.astimezone(ZoneInfo(timezone_name))
    return parsed.date()


def _records_to_quotes(frame, watch: dict, source: str, volume_multiplier: float = 1.0) -> list[Quote]:
    quotes: list[Quote] = []
    previous_close = None
    for row in frame.to_dict("records"):
        if not _row_ohlc_is_complete(row):
            continue
        opening = _row_number(row, "开盘", "Open")
        high = _row_number(row, "最高", "High")
        low = _row_number(row, "最低", "Low")
        close = _row_number(row, "收盘", "Close")
        volume = _row_number(row, "成交量", "Volume")
        preclose = _row_number(row, "昨收", "Preclose")
        if preclose is None:
            preclose = previous_close
        pct_change = _row_number(row, "涨跌幅", "PctChange")
        if pct_change is None and preclose not in (None, 0):
            pct_change = (close / preclose - 1) * 100
        quotes.append(
            Quote(
                symbol=str(watch["统一代码"]),
                name=str(watch["名称"]),
                market=str(watch["市场"]),
                trade_date=_as_date(
                    row.get("日期", row.get("Date")),
                    str(watch.get("时区") or "UTC"),
                ),
                source=source,
                open=opening,
                high=high,
                low=low,
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


def _cn_exchange_symbol(watch: dict) -> str:
    """Return the Tencent/Sina market-prefixed A-share symbol."""
    code = str(watch.get("统一代码") or watch.get("AKShare代码") or "").split(".", 1)[0]
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"无法转换A股代码：{code}")
    if code.startswith(("4", "8")):
        prefix = "bj"
    elif code.startswith(("60", "68", "5", "9")):
        prefix = "sh"
    else:
        prefix = "sz"
    return prefix + code


def _plain_symbol(watch: dict) -> str:
    return str(watch.get("yfinance代码") or watch.get("统一代码") or "").split(".", 1)[0]


def _tencent_symbol(watch: dict) -> str:
    market = str(watch["市场"])
    if market == "CN":
        return _cn_exchange_symbol(watch)
    if market == "HK":
        code = _plain_symbol(watch).zfill(5)
        if not re.fullmatch(r"\d{5}", code):
            raise ValueError(f"无法转换港股代码：{code}")
        return "r_hk" + code
    if market == "US":
        code = _plain_symbol(watch).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", code):
            raise ValueError(f"无法转换美股代码：{code}")
        return "us" + code
    raise ValueError(f"腾讯快照不支持市场：{market}")


def _sina_symbol(watch: dict) -> str:
    market = str(watch["市场"])
    if market == "CN":
        return _cn_exchange_symbol(watch)
    if market == "HK":
        code = _plain_symbol(watch).zfill(5)
        if not re.fullmatch(r"\d{5}", code):
            raise ValueError(f"无法转换港股代码：{code}")
        return "hk" + code
    if market == "US":
        code = _plain_symbol(watch).lower()
        if not re.fullmatch(r"[a-z][a-z0-9.-]*", code):
            raise ValueError(f"无法转换美股代码：{code}")
        return "gb_" + code
    raise ValueError(f"新浪快照不支持市场：{market}")


def _read_public_quote(url: str, headers: dict[str, str] | None = None) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*", **(headers or {})},
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("gb18030", errors="replace")


def _snapshot_quote(
    watch: dict,
    source: str,
    trade_date: date,
    open_price,
    high,
    low,
    close,
    preclose,
    volume,
    amount,
    turnover_rate,
    start: date,
    end: date,
) -> list[Quote]:
    close_number = _number(close)
    if close_number is None or close_number <= 0 or not start <= trade_date <= end:
        return []
    preclose_number = _number(preclose)
    pct_change = None
    if preclose_number not in (None, 0):
        pct_change = (close_number / preclose_number - 1) * 100
    return [Quote(
        symbol=str(watch["统一代码"]),
        name=str(watch["名称"]),
        market=str(watch["市场"]),
        trade_date=trade_date,
        source=source,
        open=_number(open_price) or close_number,
        high=_number(high) or close_number,
        low=_number(low) or close_number,
        close=close_number,
        preclose=preclose_number,
        pct_change=pct_change,
        volume=_number(volume),
        amount=_number(amount),
        turnover_rate=_number(turnover_rate),
        currency=str(watch["币种"]),
    )]


def fetch_tencent(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    """Fetch the latest regular-session snapshot from Tencent."""
    if adjust != "raw":
        raise ValueError("腾讯快照不提供前复权历史行情")
    market = str(watch["市场"])
    symbol = _tencent_symbol(watch)
    text = _read_public_quote(f"https://qt.gtimg.cn/q={symbol}")
    match = re.search(r'="(.*)"', text)
    if not match:
        raise RuntimeError("腾讯返回格式异常")
    fields = match.group(1).split("~")
    if len(fields) < 39 or not fields[30]:
        raise RuntimeError("腾讯返回字段不足")
    if market == "CN":
        trade_date = datetime.strptime(fields[30][:8], "%Y%m%d").date()
        deal = fields[35].split("/") if len(fields) > 35 else []
        volume_lots = _number(fields[36])
        volume = volume_lots * 100 if volume_lots is not None else None
        amount = deal[2] if len(deal) > 2 else None
    else:
        trade_date = datetime.strptime(fields[30][:10].replace("/", "-"), "%Y-%m-%d").date()
        volume = fields[36]
        amount = fields[37] if len(fields) > 37 else None
    return _snapshot_quote(
        watch, "Tencent", trade_date,
        fields[5], fields[33], fields[34], fields[3], fields[4],
        volume, amount, fields[38], start, end,
    )


def fetch_sina(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    """Fetch the latest regular-session snapshot from Sina."""
    if adjust != "raw":
        raise ValueError("新浪快照不提供前复权历史行情")
    market = str(watch["市场"])
    symbol = _sina_symbol(watch)
    text = _read_public_quote(
        f"https://hq.sinajs.cn/list={symbol}",
        {"Referer": "https://finance.sina.com.cn/"},
    )
    match = re.search(r'="(.*)"', text)
    if not match:
        raise RuntimeError("新浪返回格式异常")
    fields = match.group(1).split(",")
    if market == "CN":
        if len(fields) < 32 or not fields[30]:
            raise RuntimeError("新浪返回字段不足")
        values = (
            date.fromisoformat(fields[30]), fields[1], fields[4], fields[5],
            fields[3], fields[2], fields[8], fields[9],
        )
    elif market == "HK":
        if len(fields) < 19 or not fields[17]:
            raise RuntimeError("新浪返回字段不足")
        values = (
            datetime.strptime(fields[17], "%Y/%m/%d").date(), fields[2], fields[4],
            fields[5], fields[6], fields[3], fields[12], fields[11],
        )
    else:
        if len(fields) < 28 or not fields[25]:
            raise RuntimeError("新浪返回字段不足")
        update_date = date.fromisoformat(fields[3][:10])
        match_date = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})", fields[25])
        if not match_date:
            raise RuntimeError("新浪美股正式交易日期格式异常")
        regular_month = datetime.strptime(match_date.group(1), "%b").month
        regular_year = update_date.year - 1 if regular_month == 12 and update_date.month == 1 else update_date.year
        regular_date = date(regular_year, regular_month, int(match_date.group(2)))
        values = (
            regular_date, fields[5], fields[6], fields[7], fields[1], fields[26],
            fields[10], fields[30] if len(fields) > 30 else None,
        )
    return _snapshot_quote(
        watch, "Sina", values[0],
        values[1], values[2], values[3], values[4], values[5],
        values[6], values[7], None, start, end,
    )


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
            frame = frame.sort_index().reset_index().rename(columns={"Date": "日期"})
            records = frame.to_dict("records")
            if records and _row_ohlc_is_complete(records[-1]):
                quotes = _records_to_quotes(frame, watch, "yfinance")
                if quotes:
                    return quotes
                yfinance_error = RuntimeError("yfinance历史行情没有完整OHLC行")
            else:
                yfinance_error = RuntimeError("yfinance历史行情最新观察行OHLC不完整")
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


def fetch_baostock_latest(watch: dict, end: date) -> list[Quote]:
    """Fetch a bounded recent window for latest-only operation."""
    return fetch_baostock(watch, "raw", end - timedelta(days=7), end)


def fetch_yfinance_latest(watch: dict, end: date) -> list[Quote]:
    """Fetch only a small recent window for the latest quote path."""
    import yfinance as yf

    symbol = str(watch["yfinance代码"])
    yfinance_error: Exception | None = None
    yfinance_rows: list[Quote] = []
    try:
        frame = yf.Ticker(symbol).history(
            start=(end - timedelta(days=7)).isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
            repair=False,
        )
        if not frame.empty:
            frame = frame.sort_index().reset_index().rename(columns={"Date": "日期"})
            records = frame.to_dict("records")
            if records and _row_ohlc_is_complete(records[-1]):
                yfinance_rows = _records_to_quotes(frame, watch, "yfinance")
                if yfinance_rows:
                    return yfinance_rows
            else:
                yfinance_error = RuntimeError("yfinance最新行情最新观察行OHLC不完整")
                yfinance_rows = []
    except Exception as exc:
        yfinance_error = exc

    try:
        chart_rows = _fetch_yahoo_chart_latest(watch, end)
        return chart_rows or yfinance_rows
    except Exception as chart_error:
        if yfinance_rows:
            return yfinance_rows
        if yfinance_error is None:
            raise
        raise RuntimeError(
            f"yfinance最新行情失败：{yfinance_error}；"
            f"Yahoo Chart回退失败：{chart_error}"
        ) from chart_error


def _fetch_yahoo_chart_latest(watch: dict, end: date) -> list[Quote]:
    """Fetch the newest sane Yahoo Chart session from a bounded daily probe.

    Some Yahoo range responses expose an incomplete newest row while a
    bounded request contains the completed OHLCV bar.  Probe only the recent
    seven calendar days, newest first, and include a bounded lookback in each
    successful probe so ``_records_to_quotes`` can retain the prior close for
    the selected session.  Never fill a missing close from another field.
    """
    errors: list[str] = []
    for offset in range(8):
        day = end - timedelta(days=offset)
        try:
            rows = _fetch_yahoo_chart(
                watch, "raw", day - timedelta(days=7), day
            )
        except Exception as exc:
            errors.append(f"{day.isoformat()}: {exc}")
            continue
        if rows:
            return rows
    if errors:
        raise RuntimeError("；".join(errors))
    return []


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
        open_price = _indexed(price.get("open"), index, None)
        high_price = _indexed(price.get("high"), index, None)
        low_price = _indexed(price.get("low"), index, None)
        adjusted_close = adjusted[index] if index < len(adjusted) else None
        if raw_close is None or any(
            value is None for value in (open_price, high_price, low_price)
        ):
            continue
        factor = 1.0
        if adjust == "qfq":
            if adjusted_close is None or not raw_close:
                continue
            factor = adjusted_close / raw_close
        row = {
            "日期": datetime.fromtimestamp(timestamp, exchange_timezone).date(),
            "Open": open_price * factor,
            "High": high_price * factor,
            "Low": low_price * factor,
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
    "BaoStock": fetch_baostock,
    "Tencent": fetch_tencent,
    "Sina": fetch_sina,
    "yfinance": fetch_yfinance,
}

LATEST_PROVIDERS: dict[str, Callable[[dict, date], list[Quote]]] = {
    "BaoStock": fetch_baostock_latest,
    "Tencent": lambda watch, end: fetch_tencent(
        watch, "raw", end - timedelta(days=7), end
    ),
    "Sina": lambda watch, end: fetch_sina(
        watch, "raw", end - timedelta(days=7), end
    ),
    "yfinance": fetch_yfinance_latest,
}

# Only these configured sources provide historical qfq bars. YahooChart remains
# an internal qfq-capable fallback behind the yfinance provider.
QFQ_HISTORY_SOURCES = frozenset({"BaoStock", "yfinance"})


def _configured_source_candidates(source: str, market: str, adjust: str) -> list[str]:
    # Existing Sheets may still name AKShare. Treat it only as a deprecated
    # configuration alias; no AKShare import or network request is performed.
    if source == "AKShare":
        source = "Tencent" if adjust == "raw" and market in {"HK", "US"} else "yfinance"
    candidates = [source]
    if adjust == "raw":
        candidates.extend(RAW_SNAPSHOT_FALLBACKS.get(market, {}).get(source, ()))
    return list(dict.fromkeys(candidates))


def fetch_with_retry(
    source: str,
    watch: dict,
    adjust: str,
    start: date,
    end: date,
    retry_count: int,
    retry_wait_seconds: float,
    target_trade_date: date | None = None,
    preserve_source_order: bool = False,
) -> list[Quote]:
    market = str(watch.get("市场"))
    candidates = _configured_source_candidates(source, market, adjust)
    unknown = [candidate for candidate in candidates if candidate not in PROVIDERS]
    if unknown:
        raise ValueError(f"未知数据源：{unknown[0]}")

    errors: list[str] = []
    last_error: Exception | None = None
    attempts = max(1, retry_count)
    for candidate in candidates:
        stale_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                quotes = PROVIDERS[candidate](watch, adjust, start, end)
                if not quotes:
                    raise LookupError("返回空数据")
                sorted_quotes = sorted(quotes, key=lambda item: item.trade_date)
                latest_date = sorted_quotes[-1].trade_date
                if target_trade_date is not None and latest_date < target_trade_date:
                    stale_error = LookupError(
                        f"返回数据日期{latest_date.isoformat()}落后于目标交易日"
                        f"{target_trade_date.isoformat()}"
                    )
                    last_error = stale_error
                    break
                return list(quotes) if preserve_source_order else sorted_quotes
            except Exception as exc:  # 上游站点错误需要重试并写入日志。
                last_error = exc
                if attempt < attempts:
                    time.sleep(max(0, retry_wait_seconds))
        if stale_error is not None:
            errors.append(f"{candidate}数据失效：{stale_error}")
        else:
            errors.append(f"{candidate}连续{attempts}次抓取失败：{last_error}")
    raise RuntimeError("；".join(errors)) from last_error


def fetch_latest_with_retry(
    source: str,
    watch: dict,
    end: date,
    retry_count: int,
    retry_wait_seconds: float,
    target_trade_date: date | None = None,
) -> list[Quote]:
    """Fetch recent quote evidence without entering full-history fetch.

    ``target_trade_date`` is optional to preserve the existing latest-mode
    behavior.  Cloud reports pass the exact completed session so a stale
    configured source can use the existing raw-snapshot fallback chain before
    two-source validation, matching ``fetch_with_retry`` semantics.
    """
    market = str(watch.get("市场"))
    candidates = _configured_source_candidates(source, market, "raw")
    unknown = [candidate for candidate in candidates if candidate not in LATEST_PROVIDERS]
    if unknown:
        raise ValueError(f"未知数据源：{unknown[0]}")

    errors: list[str] = []
    last_error: Exception | None = None
    attempts = max(1, retry_count)
    for candidate in candidates:
        stale_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                quotes = LATEST_PROVIDERS[candidate](watch, end)
                if not quotes:
                    raise LookupError("返回空数据")
                sorted_quotes = sorted(quotes, key=lambda item: item.trade_date)
                if target_trade_date is not None and sorted_quotes[-1].trade_date < target_trade_date:
                    stale_error = LookupError(
                        f"返回数据日期{sorted_quotes[-1].trade_date.isoformat()}落后于目标交易日"
                        f"{target_trade_date.isoformat()}"
                    )
                    last_error = stale_error
                    break
                return sorted_quotes
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(max(0, retry_wait_seconds))
        if stale_error is not None:
            errors.append(f"{candidate}最新行情失效：{stale_error}")
        else:
            errors.append(f"{candidate}最新行情连续{attempts}次抓取失败：{last_error}")
    raise RuntimeError("；".join(errors)) from last_error
