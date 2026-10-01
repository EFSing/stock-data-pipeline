"""Bounded CN/US candidate seed adapters.

The adapters return lightweight ``SeedSecurity`` values only.  They do not
write Sheets, create a database, fetch full history, or call any strategy
engine.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any, Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from market_data_contract import ProviderGlobalFailure
from providers import _hithink_items, _hithink_json
from trading.candidate_universe import SeedSecurity


IWB_OFFICIAL_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "latest-holdings.csv"
)


class CandidateSeedDataError(RuntimeError):
    pass


def require_snapshot_as_of(
    snapshot_date: date | None, as_of: date | None, *, source: str,
    snapshot_mode: str = "CURRENT_ONLY",
) -> None:
    """Reject undated/future membership or metadata, including cached payloads."""
    if snapshot_date is None:
        raise CandidateSeedDataError(f"{source}_SNAPSHOT_DATE_MISSING")
    if as_of is not None and snapshot_date > as_of:
        raise CandidateSeedDataError(
            f"{source}_SNAPSHOT_AFTER_AS_OF:{snapshot_date.isoformat()}:"
            f"report_as_of={as_of.isoformat()}:snapshot_mode={snapshot_mode}:"
            "NO_ELIGIBLE_SNAPSHOT"
        )


HITHINK_INDEX_CONSTITUENT_ENDPOINT = (
    "/api/a-share-index/constituents/ths-stock-list"
)
HITHINK_CN_INDEXES = (
    ("HS300", "000300.SH"),
    ("CSI500", "000905.SH"),
)


def _result_rows(result: Any, endpoint: str) -> list[dict[str, str]]:
    if str(getattr(result, "error_code", "")) != "0":
        raise CandidateSeedDataError(
            f"{endpoint} failed: {getattr(result, 'error_code', '')} "
            f"{getattr(result, 'error_msg', '')}"
        )
    fields = list(getattr(result, "fields", ()) or ())
    if not fields:
        raise CandidateSeedDataError(f"{endpoint} returned no fields")
    rows: list[dict[str, str]] = []
    while result.next():
        values = list(result.get_row_data())
        rows.append({field: values[index] if index < len(values) else "" for index, field in enumerate(fields)})
    return rows


def _as_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _canonical_cn(code: str) -> tuple[str, str] | None:
    raw = str(code or "").strip().lower()
    prefix, separator, digits = raw.partition(".")
    if not separator:
        return None
    if prefix in {"sh", "sz"} and len(digits) == 6 and digits.isdigit():
        return f"{digits}.{prefix.upper()}", prefix.upper()
    if len(prefix) == 6 and prefix.isdigit() and digits in {"sh", "sz"}:
        return f"{prefix}.{digits.upper()}", digits.upper()
    return None


class BaoStockCandidateSeedAdapter:
    """Build HS300 ∪ CSI500 from verified BaoStock contracts.

    Metadata is fetched with the real no-argument full-table contracts:
    ``query_stock_basic()`` and ``query_stock_industry()``.  In particular,
    ``query_stock_basic(fields=...)`` is not used because BaoStock 0.9.3 does
    not accept that keyword.
    """

    def __init__(self, baostock_module: Any | None = None):
        self._baostock_module = baostock_module

    def load(self, as_of: date | None = None) -> tuple[SeedSecurity, ...]:
        bs = self._baostock_module
        if bs is None:
            import baostock as bs  # type: ignore[no-redef]

        login = bs.login()
        if str(getattr(login, "error_code", "")) != "0":
            raise CandidateSeedDataError(
                f"BaoStock login failed: {login.error_code} {login.error_msg}"
            )
        try:
            hs300 = self._query_index(bs.query_hs300_stocks, "query_hs300_stocks", as_of)
            csi500 = self._query_index(bs.query_zz500_stocks, "query_zz500_stocks", as_of)
            basics = _result_rows(bs.query_stock_basic(), "query_stock_basic")
            industries = _result_rows(bs.query_stock_industry(), "query_stock_industry")
        finally:
            bs.logout()

        basic_by_code = {str(row.get("code") or "").lower(): row for row in basics}
        industry_by_code = {str(row.get("code") or "").lower(): row for row in industries}
        output: dict[str, SeedSecurity] = {}
        for endpoint, rows in (("query_hs300_stocks", hs300), ("query_zz500_stocks", csi500)):
            for index_row in rows:
                source_code = str(index_row.get("code") or "").lower()
                canonical = _canonical_cn(source_code)
                if canonical is None:
                    continue
                symbol, exchange = canonical
                basic = basic_by_code.get(source_code, {})
                industry = industry_by_code.get(source_code, {})
                require_snapshot_as_of(
                    _as_date(index_row.get("updateDate")), as_of,
                    source=f"BAOSTOCK_INDEX:{endpoint}", snapshot_mode="DATE_QUERY",
                )
                if industry:
                    require_snapshot_as_of(
                        _as_date(industry.get("updateDate")), as_of,
                        source=f"BAOSTOCK_INDUSTRY:{source_code}",
                    )
                security_type = str(basic.get("type") or "").strip()
                asset_class = "Equity" if security_type == "1" else "Unknown"
                sector = str(industry.get("industry") or "").strip() or None
                metadata_status = (
                    "BASIC_MISSING"
                    if not basic
                    else "BASIC_STATUS_NOT_ACTIVE"
                    if str(basic.get("status") or "").strip() != "1"
                    else "BASIC_OUTDATED"
                    if str(basic.get("outDate") or "").strip()
                    else "INDUSTRY_MISSING"
                    if not industry
                    else "OK"
                )
                output[symbol] = SeedSecurity(
                    market="CN",
                    symbol=symbol,
                    source_symbol=source_code,
                    name=str(basic.get("code_name") or index_row.get("code_name") or "").strip(),
                    sector=sector,
                    asset_class=asset_class,
                    exchange=exchange,
                    currency="CNY",
                    source="BaoStock",
                    source_as_of=_as_date(
                        industry.get("updateDate") or index_row.get("updateDate")
                    ),
                    board_rule=None,
                    metadata_status=metadata_status,
                    provenance=(endpoint, "query_stock_basic", "query_stock_industry"),
                )
        return tuple(sorted(output.values(), key=lambda item: item.symbol))

    @staticmethod
    def _query_index(
        query: Callable[..., Any], endpoint: str, as_of: date | None
    ) -> list[dict[str, str]]:
        result = query(date=as_of.isoformat()) if as_of is not None else query()
        return _result_rows(result, endpoint)


def _hithink_snapshot_timestamp(payload: dict[str, Any]) -> tuple[str, date | None]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    raw = data.get("timestamp") or payload.get("timestamp")
    if raw is None or not str(raw).strip():
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID")
    text = str(raw).strip()
    try:
        if isinstance(raw, (int, float)) or text.isdigit():
            return text, datetime.fromtimestamp(
                float(raw) / 1000, ZoneInfo("Asia/Shanghai")
            ).date()
        if len(text) == 10:
            return text, date.fromisoformat(text)
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return text, timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
    except (TypeError, ValueError, OSError) as exc:
        raise ProviderGlobalFailure("HITHINK_PROVIDER_SCHEMA_INVALID") from exc


def parse_hithink_index_constituents(
    payload: dict[str, Any],
    *,
    index_name: str,
    index_code: str,
) -> tuple[date | None, str, tuple[SeedSecurity, ...]]:
    """Parse one official HiThink HS300/CSI500 membership snapshot."""

    source_timestamp, source_as_of = _hithink_snapshot_timestamp(payload)
    rows = _hithink_items(payload)
    output: list[SeedSecurity] = []
    for row in rows:
        source_symbol = str(row.get("thscode") or row.get("ticker") or "").strip()
        canonical = _canonical_cn(source_symbol)
        if canonical is None:
            continue
        symbol, exchange = canonical
        output.append(
            SeedSecurity(
                market="CN",
                symbol=symbol,
                source_symbol=source_symbol,
                name=str(row.get("name") or symbol).strip(),
                # Industry/sector metadata is presentation-only.  Official
                # index membership is the bounded seed contract.
                sector=None,
                asset_class="Equity",
                exchange=exchange,
                currency="CNY",
                source="HITHINK_FINANCIAL_API",
                source_as_of=source_as_of,
                metadata_status="OK",
                provenance=(
                    f"HITHINK_FINANCIAL_API:{HITHINK_INDEX_CONSTITUENT_ENDPOINT}",
                    f"index_name:{index_name}",
                    f"index_code:{index_code}",
                    f"snapshot_timestamp:{source_timestamp}",
                    "snapshot_mode:CURRENT_ONLY",
                ),
                index_memberships=(index_code,),
                source_snapshot_timestamps=(source_timestamp,),
            )
        )
    if not output:
        raise CandidateSeedDataError(
            f"HITHINK index {index_code} returned no canonical constituents"
        )
    return source_as_of, source_timestamp, tuple(output)


class HithinkCandidateSeedAdapter:
    """Build the CN seed union from HiThink's official index endpoint.

    HiThink currently exposes a current membership snapshot rather than a
    historical constituent selector.  The snapshot timestamp is retained on
    every seed and a future snapshot is rejected for an as-of run, so current
    membership cannot be silently applied retroactively.
    """

    def __init__(self, request_json: Callable[[str, dict[str, object]], dict] | None = None):
        self._request_json = request_json or _hithink_json

    def load(self, as_of: date | None = None) -> tuple[SeedSecurity, ...]:
        merged: dict[str, SeedSecurity] = {}
        for index_name, index_code in HITHINK_CN_INDEXES:
            payload = self._request_json(
                HITHINK_INDEX_CONSTITUENT_ENDPOINT,
                {"thscode": index_code},
            )
            source_as_of, _timestamp, seeds = parse_hithink_index_constituents(
                payload,
                index_name=index_name,
                index_code=index_code,
            )
            require_snapshot_as_of(
                source_as_of, as_of, source="HITHINK_INDEX",
                snapshot_mode=f"CURRENT_ONLY:index_code={index_code}",
            )
            for seed in seeds:
                existing = merged.get(seed.symbol)
                if existing is None:
                    merged[seed.symbol] = seed
                    continue
                merged[seed.symbol] = SeedSecurity(
                    **{
                        **existing.__dict__,
                        "index_memberships": tuple(sorted(set(existing.index_memberships) | set(seed.index_memberships))),
                        "source_snapshot_timestamps": tuple(sorted(set(existing.source_snapshot_timestamps) | set(seed.source_snapshot_timestamps))),
                        "provenance": tuple(sorted(set(existing.provenance) | set(seed.provenance))),
                        "source_as_of": max(
                            value for value in (existing.source_as_of, seed.source_as_of)
                            if value is not None
                        ) if existing.source_as_of is not None or seed.source_as_of is not None else None,
                    }
                )
        if not merged:
            raise CandidateSeedDataError("HITHINK_INDEX_UNION_EMPTY")
        return tuple(sorted(merged.values(), key=lambda item: item.symbol))


def _parse_float(value: str | None) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number else None


def _normalize_us_symbol(ticker: str) -> str:
    # yfinance-compatible canonical identity while preserving source_symbol.
    return str(ticker or "").strip().upper().replace(".", "-").replace("/", "-").replace(" ", "-")


def parse_iwb_holdings_csv(payload: bytes | str) -> tuple[date | None, tuple[SeedSecurity, ...]]:
    """Parse the actual iShares CSV shape, including its metadata preamble."""

    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) else payload
    rows = list(csv.reader(io.StringIO(text)))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if {"Ticker", "Sector", "Asset Class", "Price"}.issubset(set(row))
        ),
        None,
    )
    if header_index is None:
        raise CandidateSeedDataError("IWB holdings CSV header not found")
    header = rows[header_index]
    positions = {name: header.index(name) for name in ("Ticker", "Name", "Sector", "Asset Class", "Price", "Exchange", "Currency")}
    source_as_of = None
    for row in rows[:header_index]:
        if row and row[0].strip() == "Fund Holdings as of" and len(row) > 1:
            source_as_of = _as_date(row[1])
            break
    require_snapshot_as_of(source_as_of, None, source="IWB_HOLDINGS")

    output: list[SeedSecurity] = []
    for row in rows[header_index + 1 :]:
        if len(row) <= max(positions.values()):
            continue
        source_symbol = row[positions["Ticker"]].strip()
        asset_class = row[positions["Asset Class"]].strip()
        if not source_symbol or source_symbol == "-" or asset_class != "Equity":
            continue
        symbol = _normalize_us_symbol(source_symbol)
        output.append(
            SeedSecurity(
                market="US",
                symbol=symbol,
                source_symbol=source_symbol,
                name=row[positions["Name"]].strip(),
                sector=row[positions["Sector"]].strip() or None,
                asset_class=asset_class,
                exchange=row[positions["Exchange"]].strip() or None,
                currency=row[positions["Currency"]].strip() or "USD",
                source="iShares_IWB_OFFICIAL_HOLDINGS",
                source_as_of=source_as_of,
                reference_price=_parse_float(row[positions["Price"]]),
                metadata_status="OK",
                provenance=(IWB_OFFICIAL_HOLDINGS_URL, "snapshot_mode:CURRENT_ONLY"),
            )
        )
    if not output:
        raise CandidateSeedDataError("IWB holdings CSV contained no equity rows")
    return source_as_of, tuple(sorted(output, key=lambda item: item.symbol))


class IwbOfficialHoldingsAdapter:
    """Read the official public iShares IWB holdings download."""

    def __init__(self, url: str = IWB_OFFICIAL_HOLDINGS_URL, timeout: int = 20):
        self.url = url
        self.timeout = timeout

    def load(self, as_of: date | None = None) -> tuple[date | None, tuple[SeedSecurity, ...]]:
        request = Request(
            self.url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = response.read()
        source_as_of, seeds = parse_iwb_holdings_csv(payload)
        require_snapshot_as_of(source_as_of, as_of, source="IWB_HOLDINGS")
        return source_as_of, seeds


__all__ = [
    "BaoStockCandidateSeedAdapter",
    "CandidateSeedDataError",
    "HITHINK_CN_INDEXES",
    "HITHINK_INDEX_CONSTITUENT_ENDPOINT",
    "HithinkCandidateSeedAdapter",
    "IWB_OFFICIAL_HOLDINGS_URL",
    "IwbOfficialHoldingsAdapter",
    "parse_iwb_holdings_csv",
    "parse_hithink_index_constituents",
    "require_snapshot_as_of",
]
