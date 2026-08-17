from __future__ import annotations

import time
from datetime import date, timedelta
from functools import lru_cache
from typing import Callable, Iterable

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
    frame = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=adjust == "qfq",
        actions=False,
        repair=False,
    )
    if frame.empty:
        return []
    frame = frame.reset_index().rename(columns={"Date": "日期"})
    return _records_to_quotes(frame, watch, "yfinance")


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
