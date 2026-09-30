from __future__ import annotations

import time
import json
import hashlib
import os
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote as urlquote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from core import Quote
from market_data_contract import (
    AdjustmentUnverifiedError,
    CN_ADJUSTMENT_ENGINE_VERSION,
    CN_ETF_ADJUSTMENT_ENGINE_VERSION,
    CN_SINGLE_SOURCE_PROVIDER,
    ProviderGlobalFailure,
    ProviderSymbolError,
    US_ADJUSTMENT_ENGINE_VERSION,
    US_SINGLE_SOURCE_PROVIDER,
    canonical_provider_for_market,
    source_provenance,
)


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


@dataclass(frozen=True)
class SingleSourceFetchResult:
    """One canonical provider response plus its adjustment provenance."""

    quotes: tuple[Quote, ...]
    provider: str
    provenance: dict[str, object]
    api_requests: int = 1


HITHINK_BASE_URL = "https://fuyao.aicubes.cn"
HITHINK_API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
HITHINK_ASSET_TYPE_FIELD = "HITHINK资产类型"
HITHINK_ASSET_TYPE_SOURCE = (
    "HITHINK_FINANCIAL_API:/api/meta/tickers/search"
)
HITHINK_STOCK_ASSET_TYPE = "a-share"
HITHINK_ETF_ASSET_TYPE = "fund-etf"


def _normalise_hithink_asset_type(value: object) -> str:
    """Map explicit asset metadata to HiThink's canonical enum."""

    normalized = str(value or "").strip().lower()
    aliases = {
        "a-share": HITHINK_STOCK_ASSET_TYPE,
        "stock": HITHINK_STOCK_ASSET_TYPE,
        "equity": HITHINK_STOCK_ASSET_TYPE,
        "股票": HITHINK_STOCK_ASSET_TYPE,
        "fund-etf": HITHINK_ETF_ASSET_TYPE,
        "etf": HITHINK_ETF_ASSET_TYPE,
        "基金": HITHINK_ETF_ASSET_TYPE,
        "基金/ETF": HITHINK_ETF_ASSET_TYPE,
    }
    return aliases.get(normalized, normalized)


def _hithink_asset_type(watch: dict) -> tuple[str, int]:
    """Resolve asset type from explicit metadata or the same-vendor directory.

    The symbol code is never used as an asset classifier.  A caller may carry
    a previously resolved ``HITHINK资产类型`` value; otherwise the provider's
    metadata endpoint is queried and the exact thscode match is required.
    """

    explicit_values = (
        watch.get(HITHINK_ASSET_TYPE_FIELD),
        watch.get("asset_type"),
        watch.get("资产类型"),
        watch.get("证券类型"),
        watch.get("asset_class"),
    )
    for value in explicit_values:
        normalized = _normalise_hithink_asset_type(value)
        if normalized:
            if normalized not in {HITHINK_STOCK_ASSET_TYPE, HITHINK_ETF_ASSET_TYPE}:
                raise ProviderSymbolError(
                    f"HITHINK_ASSET_TYPE_UNSUPPORTED:{normalized}"
                )
            return normalized, 0

    symbol = _hithink_symbol(watch)
    payload = _hithink_json(
        "/api/meta/tickers/search",
        {"q": symbol, "limit": 50},
    )
    items = _hithink_items(payload)
    exact = [
        item
        for item in items
        if str(item.get("thscode") or "").strip().upper() == symbol
    ]
    if not exact:
        raise ProviderSymbolError("HITHINK_SYMBOL_METADATA_NOT_FOUND")
    asset_type = _normalise_hithink_asset_type(exact[0].get("asset_type"))
    if asset_type not in {HITHINK_STOCK_ASSET_TYPE, HITHINK_ETF_ASSET_TYPE}:
        raise ProviderSymbolError(f"HITHINK_ASSET_TYPE_UNSUPPORTED:{asset_type or 'missing'}")
    watch[HITHINK_ASSET_TYPE_FIELD] = asset_type
    watch["HITHINK资产类型来源"] = HITHINK_ASSET_TYPE_SOURCE
    return asset_type, 1


def _hithink_symbol(watch: dict) -> str:
    value = str(
        watch.get("HITHINK代码")
        or watch.get("统一代码")
        or ""
    ).strip().upper()
    if not value:
        raise ProviderSymbolError("HITHINK_SYMBOL_MISSING")
    return value


def _hithink_epoch_ms(value: date) -> int:
    local = datetime.combine(value, datetime_time.min, ZoneInfo("Asia/Shanghai"))
    return int(local.timestamp() * 1000)


def _hithink_json(path: str, params: dict[str, object]) -> dict:
    api_key = os.environ.get(HITHINK_API_KEY_ENV, "").strip()
    if not api_key:
        raise ProviderGlobalFailure("HITHINK_PROVIDER_AUTH_MISSING")
    url = f"{HITHINK_BASE_URL}{path}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "stock-data-pipeline/SINGLE_SOURCE_MARKET_DATA_V1",
            "Accept": "application/json",
            "X-api-key": api_key,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) in {401, 403, 429} or int(getattr(exc, "code", 0) or 0) >= 500:
            raise ProviderGlobalFailure(f"HITHINK_PROVIDER_HTTP_{getattr(exc, 'code', 'UNKNOWN')}") from exc
        raise ProviderSymbolError(f"HITHINK_SYMBOL_HTTP_{getattr(exc, 'code', 'UNKNOWN')}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderGlobalFailure(f"HITHINK_PROVIDER_NETWORK:{type(exc).__name__}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID") from exc
    if not isinstance(payload, dict):
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    code = payload.get("code")
    if code not in (None, 0, "0", "200", 200):
        if str(code) in {"2001", "2003", "4001", "401", "403"}:
            raise ProviderGlobalFailure(f"HITHINK_PROVIDER_ERROR:{code}")
        raise ProviderSymbolError(f"HITHINK_SYMBOL_ERROR:{code}")
    return payload


def _hithink_items(payload: dict) -> list[dict]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    items = data.get("item")
    if items is None:
        items = data.get("items")
    if items is None:
        return []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    return [dict(item) for item in items]


def _hithink_item_date(item: dict) -> date:
    value = item.get("date_ms", item.get("date"))
    if value is None:
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value) / 1000, ZoneInfo("Asia/Shanghai")).date()
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError, OSError) as exc:
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID") from exc


def _hithink_item_number(item: dict, *keys: str) -> float | None:
    return _number(next((item[key] for key in keys if key in item), None))


def _hithink_raw_quotes(items: Iterable[dict], watch: dict) -> list[Quote]:
    values = sorted(items, key=_hithink_item_date)
    quotes: list[Quote] = []
    previous_close: float | None = None
    for item in values:
        opening = _hithink_item_number(item, "open_price", "open")
        high = _hithink_item_number(item, "high_price", "high")
        low = _hithink_item_number(item, "low_price", "low")
        close = _hithink_item_number(item, "close_price", "close")
        volume = _hithink_item_number(item, "volume")
        if any(value is None for value in (opening, high, low, close, volume)):
            # The response envelope has already passed provider-schema
            # validation.  An incomplete bar belongs to this symbol and must
            # not turn a market-wide run into a provider outage.
            raise ProviderSymbolError("HITHINK_SYMBOL_SCHEMA_INCOMPLETE")
        trade_date = _hithink_item_date(item)
        preclose = _hithink_item_number(item, "preclose", "pre_close")
        if preclose is None:
            preclose = previous_close
        pct_change = _hithink_item_number(item, "pct_change", "pctChg")
        if pct_change is None and preclose not in (None, 0):
            pct_change = (close / preclose - 1) * 100
        quotes.append(
            Quote(
                symbol=str(watch["统一代码"]),
                name=str(watch.get("名称") or watch["统一代码"]),
                market=str(watch["市场"]),
                trade_date=trade_date,
                source=CN_SINGLE_SOURCE_PROVIDER,
                open=opening,
                high=high,
                low=low,
                close=close,
                preclose=preclose,
                pct_change=pct_change,
                volume=volume,
                amount=_hithink_item_number(item, "turnover", "amount", "turnover_amount"),
                turnover_rate=_hithink_item_number(item, "turnover_rate", "turnoverRate"),
                currency=str(watch.get("币种") or "CNY"),
            )
        )
        previous_close = close
    return quotes


def _hithink_adjustment_items(payload: dict) -> list[dict]:
    return _hithink_items(payload)


def _adjust_hithink_quotes(
    quotes: Sequence[Quote],
    actions: Iterable[dict],
) -> tuple[list[Quote], str]:
    """Apply a deterministic forward-adjustment chain to raw HITHINK bars."""

    events: list[tuple[date, float, float, float]] = []
    raw = tuple(sorted(quotes, key=lambda item: item.trade_date))
    for item in actions:
        value = item.get("ex_date_ms", item.get("ex_date", item.get("date")))
        if value is None:
            raise AdjustmentUnverifiedError("HITHINK_ACTION_DATE_MISSING")
        try:
            if isinstance(value, (int, float)) or str(value).isdigit():
                ex_date = datetime.fromtimestamp(float(value) / 1000, ZoneInfo("Asia/Shanghai")).date()
            else:
                ex_date = date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError, OSError) as exc:
            raise AdjustmentUnverifiedError("HITHINK_ACTION_DATE_INVALID") from exc
        dividend = _hithink_item_number(item, "dividend_per_share", "dividend")
        bonus = _hithink_item_number(item, "per_share_bonus", "bonus")
        if dividend is None or bonus is None:
            raise AdjustmentUnverifiedError("HITHINK_ACTION_FIELDS_INCOMPLETE")
        prior = max((quote for quote in raw if quote.trade_date < ex_date), key=lambda quote: quote.trade_date, default=None)
        if prior is None:
            if raw and raw[0].trade_date < ex_date <= raw[-1].trade_date:
                raise AdjustmentUnverifiedError("HITHINK_ACTION_PRIOR_BAR_MISSING")
            continue
        denominator = prior.close * (1 + bonus)
        numerator = prior.close - dividend
        if denominator <= 0 or numerator <= 0:
            raise AdjustmentUnverifiedError("HITHINK_ACTION_FACTOR_INVALID")
        events.append((ex_date, dividend, bonus, numerator / denominator))
    events.sort(key=lambda item: item[0])
    adjusted: list[Quote] = []
    for quote in raw:
        factor = 1.0
        for ex_date, _dividend, _bonus, event_factor in events:
            if quote.trade_date < ex_date:
                factor *= event_factor
        preclose = quote.preclose * factor if quote.preclose is not None else None
        pct_change = quote.pct_change
        if preclose not in (None, 0):
            pct_change = (quote.close * factor / preclose - 1) * 100
        adjusted.append(
            replace(
                quote,
                open=quote.open * factor,
                high=quote.high * factor,
                low=quote.low * factor,
                close=quote.close * factor,
                preclose=preclose,
                pct_change=pct_change,
            )
        )
    chain_payload = json.dumps(
        [
            {
                "ex_date": ex_date.isoformat(),
                "dividend_per_share": dividend,
                "per_share_bonus": bonus,
                "factor": factor,
            }
            for ex_date, dividend, bonus, factor in events
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return adjusted, hashlib.sha256(chain_payload).hexdigest()


def fetch_hithink_with_provenance(
    watch: dict,
    adjust: str,
    start: date,
    end: date,
) -> SingleSourceFetchResult:
    if str(watch.get("市场")) != "CN":
        raise ProviderSymbolError("HITHINK_MARKET_UNSUPPORTED")
    symbol = _hithink_symbol(watch)
    asset_type, metadata_requests = _hithink_asset_type(watch)
    if asset_type == HITHINK_ETF_ASSET_TYPE:
        payload = _hithink_json(
            "/api/fund/market/historical",
            {
                "thscode": symbol,
                "interval": "1d",
                "start": _hithink_epoch_ms(start),
                "end": _hithink_epoch_ms(end),
            },
        )
        raw_quotes = _hithink_raw_quotes(_hithink_items(payload), watch)
        if not raw_quotes:
            raise ProviderSymbolError("HITHINK_ETF_SYMBOL_NO_HISTORY")
        # The fund endpoint is explicitly documented by HiThink as an ETF
        # historical endpoint whose OHLC is already forward-adjusted.  Keep
        # this same-vendor contract visible instead of pretending it is the
        # stock raw+corporate-action formula or sending the ETF to the stock
        # endpoint.
        provenance = source_provenance(
            market="CN",
            provider=CN_SINGLE_SOURCE_PROVIDER,
            adjustment=adjust,
            adjustment_engine_version=CN_ETF_ADJUSTMENT_ENGINE_VERSION,
            raw_source="HITHINK_FINANCIAL_API:/api/fund/market/historical",
            asset_type=asset_type,
            adjustment_source="HITHINK_PROVIDER_FORWARD_ADJUSTED",
        )
        provenance["provider_adjustment_policy"] = "FORWARD_ADJUSTED"
        provenance["requested_adjustment"] = adjust
        return SingleSourceFetchResult(
            tuple(raw_quotes),
            CN_SINGLE_SOURCE_PROVIDER,
            provenance,
            metadata_requests + 1,
        )
    payload = _hithink_json(
        "/api/a-share/prices/historical",
        {
            "thscode": symbol,
            "interval": "1d",
            "start": _hithink_epoch_ms(start),
            "end": _hithink_epoch_ms(end),
            "adjust": "none",
        },
    )
    raw_quotes = _hithink_raw_quotes(_hithink_items(payload), watch)
    if not raw_quotes:
        raise ProviderSymbolError("HITHINK_SYMBOL_NO_HISTORY")
    provenance = source_provenance(
        market="CN",
        provider=CN_SINGLE_SOURCE_PROVIDER,
        adjustment=adjust,
        adjustment_engine_version=CN_ADJUSTMENT_ENGINE_VERSION,
        raw_source="HITHINK_FINANCIAL_API:/api/a-share/prices/historical?adjust=none",
        asset_type=asset_type,
    )
    requests = metadata_requests + 1
    if adjust == "raw":
        return SingleSourceFetchResult(tuple(raw_quotes), CN_SINGLE_SOURCE_PROVIDER, provenance, requests)
    if adjust != "qfq":
        raise ValueError(f"unsupported HITHINK adjustment: {adjust}")
    try:
        actions = _hithink_json(
            "/api/a-share/corporate-actions/adjustment-factors",
            {
                "thscode": symbol,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
    except ProviderSymbolError as exc:
        # HiThink code 3002 means the action dataset is not prepared.  It is
        # not evidence that the symbol has no actions; fail closed instead of
        # silently treating an unobservable corporate-action stream as an
        # identity adjustment chain.
        if "3002" in str(exc):
            raise AdjustmentUnverifiedError(
                "HITHINK_CORPORATE_ACTIONS_NOT_READY"
            ) from exc
        raise
    adjusted, chain_sha = _adjust_hithink_quotes(raw_quotes, _hithink_adjustment_items(actions))
    provenance = source_provenance(
        market="CN",
        provider=CN_SINGLE_SOURCE_PROVIDER,
        adjustment="qfq",
        adjustment_engine_version=CN_ADJUSTMENT_ENGINE_VERSION,
        raw_source="HITHINK_FINANCIAL_API:/api/a-share/prices/historical?adjust=none",
        corporate_action_source="HITHINK_FINANCIAL_API:/api/a-share/corporate-actions/adjustment-factors",
        adjustment_chain_sha256=chain_sha,
        asset_type=asset_type,
        adjustment_source="HITHINK_RAW_PLUS_HITHINK_CORPORATE_ACTIONS",
    )
    return SingleSourceFetchResult(tuple(adjusted), CN_SINGLE_SOURCE_PROVIDER, provenance, requests + 1)


def fetch_hithink(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    return list(fetch_hithink_with_provenance(watch, adjust, start, end).quotes)


def fetch_hithink_latest(watch: dict, end: date) -> list[Quote]:
    return fetch_hithink(watch, "raw", end - timedelta(days=14), end)


def fetch_yahoo_chart_with_provenance(
    watch: dict,
    adjust: str,
    start: date,
    end: date,
) -> SingleSourceFetchResult:
    if str(watch.get("市场")) != "US":
        raise ProviderSymbolError("YAHOO_CHART_MARKET_UNSUPPORTED")
    try:
        quotes = _fetch_yahoo_chart(watch, adjust, start, end)
    except ProviderGlobalFailure:
        raise
    except ProviderSymbolError:
        raise
    except Exception as exc:
        raise ProviderGlobalFailure(f"YAHOO_CHART_PROVIDER_FAILURE:{type(exc).__name__}") from exc
    if not quotes:
        raise ProviderSymbolError("YAHOO_CHART_SYMBOL_NO_HISTORY")
    provenance = source_provenance(
        market="US",
        provider=US_SINGLE_SOURCE_PROVIDER,
        adjustment=adjust,
        adjustment_engine_version=US_ADJUSTMENT_ENGINE_VERSION,
        raw_source="YAHOO_CHART:/v8/finance/chart",
        asset_type="equity",
        adjustment_source=(
            "YAHOO_CHART:/v8/finance/chart.result.indicators.adjclose"
            if adjust == "qfq"
            else "YAHOO_CHART:/v8/finance/chart.result.indicators.quote"
        ),
    )
    provenance["exact_completed_session_required"] = True
    provenance["adjusted_ohlcv_source"] = (
        "YAHOO_CHART:/v8/finance/chart.result.indicators.adjclose"
        if adjust == "qfq"
        else None
    )
    return SingleSourceFetchResult(tuple(quotes), US_SINGLE_SOURCE_PROVIDER, provenance, 1)


def fetch_yahoo_chart_single(watch: dict, adjust: str, start: date, end: date) -> list[Quote]:
    return list(fetch_yahoo_chart_with_provenance(watch, adjust, start, end).quotes)


def fetch_yahoo_chart_single_latest(watch: dict, end: date) -> list[Quote]:
    return fetch_yahoo_chart_single(watch, "raw", end - timedelta(days=14), end)


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


def fetch_yfinance(
    watch: dict,
    adjust: str,
    start: date,
    end: date,
    target_trade_date: date | None = None,
) -> list[Quote]:
    """Fetch yfinance history, retrying Yahoo Chart when the target is stale.

    A complete yfinance payload can still end at T-1.  When the caller has an
    exact target session, that payload is not accepted as a successful
    provider result; the existing Yahoo Chart fallback gets the opportunity
    to supply the same adjusted history through T.
    """
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
                    latest_date = quotes[-1].trade_date
                    if (
                        target_trade_date is None
                        or latest_date >= target_trade_date
                    ):
                        return quotes
                    yfinance_error = LookupError(
                        f"返回数据日期{latest_date.isoformat()}落后于目标交易日"
                        f"{target_trade_date.isoformat()}"
                    )
                else:
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
                    if yfinance_rows[-1].preclose is not None:
                        return yfinance_rows
                    try:
                        chart_rows = _fetch_yahoo_chart_latest(watch, end)
                    except Exception:
                        chart_rows = []
                    return chart_rows or yfinance_rows
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
    observed: dict[date, Quote] = {}
    for offset in range(8):
        day = end - timedelta(days=offset)
        try:
            rows = _fetch_yahoo_chart(
                watch, "raw", day - timedelta(days=7), day
            )
        except Exception as exc:
            errors.append(f"{day.isoformat()}: {exc}")
            continue
        for quote in rows:
            existing = observed.get(quote.trade_date)
            if existing is None or (
                existing.preclose is None and quote.preclose is not None
            ):
                observed[quote.trade_date] = quote
        if not observed:
            continue
        latest_date = max(observed)
        latest = observed[latest_date]
        if latest.preclose is None:
            prior = max(
                (
                    quote
                    for trade_date, quote in observed.items()
                    if trade_date < latest_date and quote.close is not None
                ),
                key=lambda quote: quote.trade_date,
                default=None,
            )
            if prior is not None:
                pct_change = latest.pct_change
                if pct_change is None and prior.close not in (None, 0):
                    pct_change = (latest.close / prior.close - 1) * 100
                observed[latest_date] = replace(
                    latest,
                    preclose=prior.close,
                    pct_change=pct_change,
                )
                latest = observed[latest_date]
        if latest.preclose is not None:
            return [observed[trade_date] for trade_date in sorted(observed)]
    if observed:
        return [observed[trade_date] for trade_date in sorted(observed)]
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
    symbol_errors: list[str] = []
    global_errors: list[str] = []
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
            if not isinstance(payload, dict) or not isinstance(payload.get("chart"), dict):
                raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
            chart_error = payload["chart"].get("error")
            if chart_error:
                error_text = str(chart_error)
                lowered = error_text.lower()
                if any(
                    marker in lowered
                    for marker in ("not found", "no data found", "delisted", "bad request")
                ):
                    symbol_errors.append(f"{host}:{error_text}")
                else:
                    global_errors.append(f"{host}:{error_text}")
                payload = None
                continue
            break
        except ProviderGlobalFailure as exc:
            global_errors.append(f"{host}:{exc}")
            payload = None
        except HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            error_text = f"HTTP_{code or 'UNKNOWN'}"
            if code in {401, 403, 429} or code >= 500:
                global_errors.append(f"{host}:{error_text}")
            elif 400 <= code < 500:
                symbol_errors.append(f"{host}:{error_text}")
            else:
                global_errors.append(f"{host}:{error_text}")
            payload = None
        except (URLError, TimeoutError, OSError) as exc:
            global_errors.append(f"{host}:{type(exc).__name__}")
            payload = None
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            global_errors.append(f"{host}:YAHOO_CHART_PROVIDER_SCHEMA_INVALID:{type(exc).__name__}")
            payload = None
        except Exception as exc:
            global_errors.append(f"{host}:{type(exc).__name__}:{exc}")
            payload = None
    if payload is None:
        if global_errors:
            raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_FAILURE:" + "；".join(global_errors))
        if symbol_errors:
            raise ProviderSymbolError("YAHOO_CHART_SYMBOL_ERROR:" + "；".join(symbol_errors))
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_FAILURE")

    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
    results = chart.get("result") or []
    if not isinstance(results, list):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
    if not results:
        return []
    result = results[0]
    if not isinstance(result, dict):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
    price = (indicators.get("quote") or [{}])[0]
    if not isinstance(price, dict):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID")
    adjusted_block = indicators.get("adjclose") or []
    if adjust == "qfq" and (
        not isinstance(adjusted_block, list)
        or not adjusted_block
        or not isinstance(adjusted_block[0], dict)
        or not isinstance(adjusted_block[0].get("adjclose"), list)
    ):
        raise ProviderGlobalFailure("YAHOO_CHART_PROVIDER_SCHEMA_INVALID_ADJCLOSE")
    adjusted = (
        adjusted_block[0].get("adjclose")
        if adjusted_block and isinstance(adjusted_block[0], dict)
        else []
    ) or []
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
    CN_SINGLE_SOURCE_PROVIDER: fetch_hithink,
    US_SINGLE_SOURCE_PROVIDER: fetch_yahoo_chart_single,
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
    CN_SINGLE_SOURCE_PROVIDER: fetch_hithink_latest,
    US_SINGLE_SOURCE_PROVIDER: fetch_yahoo_chart_single_latest,
}

# Only these configured sources provide historical qfq bars. YahooChart remains
# an internal qfq-capable fallback behind the yfinance provider.
QFQ_HISTORY_SOURCES = frozenset({"BaoStock", "yfinance"})
SINGLE_SOURCE_QFQ_SOURCES = frozenset({CN_SINGLE_SOURCE_PROVIDER, US_SINGLE_SOURCE_PROVIDER})


def fetch_single_source_with_retry(
    market: str,
    watch: dict,
    adjust: str,
    start: date,
    end: date,
    retry_count: int,
    retry_wait_seconds: float,
    target_trade_date: date | None = None,
) -> SingleSourceFetchResult:
    """Fetch one market through its canonical provider, with no vendor fallback."""

    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError(f"single-source provider unsupported for market: {market}")
    provider = CN_SINGLE_SOURCE_PROVIDER if normalized_market == "CN" else US_SINGLE_SOURCE_PROVIDER
    attempts = max(1, int(retry_count))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if provider == CN_SINGLE_SOURCE_PROVIDER:
                result = fetch_hithink_with_provenance(watch, adjust, start, end)
            else:
                result = fetch_yahoo_chart_with_provenance(watch, adjust, start, end)
            quotes = tuple(sorted(result.quotes, key=lambda item: item.trade_date))
            if target_trade_date is not None and (
                not quotes or quotes[-1].trade_date < target_trade_date
            ):
                raise LookupError(
                    f"{provider}返回日期落后于目标交易日："
                    f"{quotes[-1].trade_date.isoformat() if quotes else 'empty'}<"
                    f"{target_trade_date.isoformat()}"
                )
            provenance = dict(result.provenance)
            if not provenance.get("acquired_at"):
                provenance["acquired_at"] = datetime.now(timezone.utc).isoformat()
            return replace(
                result,
                quotes=quotes,
                provider=provider,
                provenance=provenance,
            )
        except ProviderSymbolError:
            raise
        except ProviderGlobalFailure as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(max(0, retry_wait_seconds))
        except (AdjustmentUnverifiedError, ValueError):
            raise
        except LookupError as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(max(0, retry_wait_seconds))
                continue
            raise
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(max(0, retry_wait_seconds))
    assert last_error is not None
    if isinstance(last_error, (ProviderGlobalFailure, LookupError)):
        raise last_error
    raise ProviderGlobalFailure(
        f"{provider} provider failed after {attempts} attempts: {last_error}"
    ) from last_error


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
                provider = PROVIDERS[candidate]
                if (
                    candidate == "yfinance"
                    and adjust == "qfq"
                    and target_trade_date is not None
                ):
                    quotes = provider(
                        watch,
                        adjust,
                        start,
                        end,
                        target_trade_date=target_trade_date,
                    )
                else:
                    quotes = provider(watch, adjust, start, end)
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
                    # A non-empty Yahoo Chart response can still be a transient
                    # provider tail lag.  Keep the exact-T guard, but let the
                    # existing bounded retry budget ask yfinance/Chart again
                    # before failing closed.  Never return the stale series.
                    if (
                        candidate == "yfinance"
                        and adjust == "qfq"
                        and attempt < attempts
                    ):
                        time.sleep(max(0, retry_wait_seconds))
                        continue
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
    excluded_sources: Iterable[str] = (),
) -> list[Quote]:
    """Fetch recent quote evidence without entering full-history fetch.

    ``target_trade_date`` is optional to preserve the existing latest-mode
    behavior.  Cloud reports pass the exact completed session so a stale
    configured source can use the existing raw-snapshot fallback chain before
    two-source validation, matching ``fetch_with_retry`` semantics.
    ``excluded_sources`` is used by the verifier path to keep configured
    fallback chains from reusing an already selected actual source.
    """
    market = str(watch.get("市场"))
    candidates = _configured_source_candidates(source, market, "raw")
    unknown = [candidate for candidate in candidates if candidate not in LATEST_PROVIDERS]
    if unknown:
        raise ValueError(f"未知数据源：{unknown[0]}")
    excluded = {
        str(value).strip()
        for value in excluded_sources
        if str(value).strip()
    }
    candidates = [candidate for candidate in candidates if candidate not in excluded]
    if not candidates:
        excluded_text = "、".join(sorted(excluded)) or "无"
        raise RuntimeError(f"没有可用的独立最新行情数据源：已排除{excluded_text}")

    errors: list[str] = []
    last_error: Exception | None = None
    attempts = max(1, retry_count)
    for candidate in candidates:
        stale_error: Exception | None = None
        source_collision_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                quotes = LATEST_PROVIDERS[candidate](watch, end)
                if not quotes:
                    raise LookupError("返回空数据")
                sorted_quotes = sorted(quotes, key=lambda item: item.trade_date)
                actual_sources = {
                    str(getattr(quote, "source", "")).strip()
                    for quote in sorted_quotes
                    if str(getattr(quote, "source", "")).strip()
                }
                collision = sorted(actual_sources.intersection(excluded))
                if collision:
                    source_collision_error = LookupError(
                        "返回数据实际来源与已使用来源冲突：" + "、".join(collision)
                    )
                    last_error = source_collision_error
                    break
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
        elif source_collision_error is not None:
            errors.append(f"{candidate}最新行情来源冲突：{source_collision_error}")
        else:
            errors.append(f"{candidate}最新行情连续{attempts}次抓取失败：{last_error}")
    raise RuntimeError("；".join(errors)) from last_error
