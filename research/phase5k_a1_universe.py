"""Phase 5K-A1 current universe snapshots and deterministic manifest freeze.

This module is deliberately metadata-only.  It reads the verified Phase 5J-v2
protocol, fetches only the declared CN index constituent and US constituent /
holding sources, and freezes a deterministic manifest.  It does not import
providers, OHLCV/replay code, Trading Core, Decision, SETUP_03, Sheets, or any
performance-analysis code.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research.structural_validation_protocol_v2 import (
    EXPECTED_PROTOCOL_VERSION,
    PINNED_PROTOCOL_SHA256_BY_VERSION,
    PROTOCOL_STATUS,
    load_protocol,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTION_SPEC_PATH = Path(__file__).with_name("phase5k_a1_selection_spec.json")
SNAPSHOT_DIR = Path(__file__).with_name("snapshots") / "phase5k_a1_cn_us_2026-08-27-v2"
SNAPSHOT_PROVENANCE_PATH = SNAPSHOT_DIR / "snapshot_provenance.json"
MANIFEST_PATH = Path(__file__).with_name("phase5k_a1_universe_manifest_v2.json")
LEGACY_SNAPSHOT_DIR = Path(__file__).with_name("snapshots") / "phase5k_a1_cn_us_2026-08-27-v1"
LEGACY_MANIFEST_PATH = Path(__file__).with_name("phase5k_a1_universe_manifest.json")

MANIFEST_SCHEMA_VERSION = "setup03-phase5k-a1-universe-manifest-v2"
MANIFEST_VERSION = "SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2"
LEGACY_MANIFEST_VERSION = "SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v1"
MANIFEST_STATUS = "MANIFEST_FROZEN_NOT_FETCHED"
SELECTION_SPEC_VERSION = "SETUP_03-CN-US-UNIVERSE-SELECTION-2026-08-27-v1"
PINNED_SELECTION_SPEC_SHA256 = "sha256:327e8f20b7ff3464d5bd8b44133ed1fc4633f143ca38e3a2cdeeeb216559b30f"
PINNED_MANIFEST_SHA256_BY_VERSION = MappingProxyType(
    {
        LEGACY_MANIFEST_VERSION: "sha256:4a33391d57488937bcdd7e501ca65a2ae3dc1c5475e41203f22bbe2e03c057eb",
        MANIFEST_VERSION: "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433",
    }
)

HITHINK_BASE_URL = "https://fuyao.aicubes.cn"
HITHINK_API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
SP500_SPDJI_URL = "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"
SP500_IVV_HOLDINGS_URL = "https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv"
SP500_PROXY_SOURCE_IDENTITY = "S&P500_UNIVERSE_PROXY_IVV_OFFICIAL_HOLDINGS"
SP500_SPDJI_SOURCE_IDENTITY = "S&P-DJI-OFFICIAL-SP500-CONSTITUENTS"
SP500_PROXY_LIMITATION = (
    "IVV is an official iShares issuer holdings snapshot for a fund that seeks to track the S&P 500. "
    "It is an explicit proxy, not official S&P 500 constituent data: holdings may include cash, derivatives, "
    "temporary positions, or issuer/share-class representation differences and may differ from the index roster."
)
SP500_SPDJI_PROBE_CONTRACT = (
    "GET the public S&P DJI S&P 500 index page and require a complete machine-readable constituent table "
    "with Constituent/Symbol fields and at least 400 rows; a page shell, top-10-only response, or an "
    "unavailable client-side full-list payload is not sufficient."
)
NASDAQ_WEIGHTING_URL = "https://indexes.nasdaq.com/Index/WeightingData"
IGV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239771/"
    "ishares-north-american-techsoftware-etf/latest-holdings.csv"
)

CN_COHORTS = ("CSI300", "CSI500", "CSI1000")
US_COHORTS = ("SP500", "NASDAQ100", "SOX", "IGV")
CN_INDEX_CODES = {"CSI300": "000300.SH", "CSI500": "000905.SH", "CSI1000": "000852.SH"}
CN_PRIMARY_QUOTAS = {"CSI300": 12, "CSI500": 14, "CSI1000": 14}
US_PRIMARY_QUOTAS = {"SP500": 12, "NASDAQ100": 10, "SOX": 8, "IGV": 10}
RESERVE_TARGETS = {"CN": 20, "US": 20}
CN_MAIN_ACTIVE = ("SSE_MAIN_BOARD_COMMON_A", "SZSE_MAIN_BOARD_COMMON_A")
CN_REGISTERED_INACTIVE = ("CN_STAR_REGISTERED_INACTIVE", "CN_CHINEXT_REGISTERED_INACTIVE")
AGGREGATE_DIAGNOSTIC_INSTRUMENTS = ("QQQ", "SOX_INDEX", "IGV_ETF")
FORBIDDEN_SELECTION_FRAGMENTS = (
    "watch", "armed", "confirmed", "entry", "setup03", "signal", "return",
    "forward", "mfe", "mae", "win_rate", "p&l", "pnl", "profit_factor",
    "expectancy", "frequency", "performance",
)


class SnapshotError(RuntimeError):
    """Raised when a source snapshot fails its strict retrieval contract."""


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _integrity_hash(value: Mapping[str, Any], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def selection_spec_integrity_hash(spec: Mapping[str, Any]) -> str:
    return _integrity_hash(spec, "integrity")


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    return _integrity_hash(manifest, "integrity")


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_selection_spec(path: Path = SELECTION_SPEC_PATH) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    _validate_selection_spec(spec)
    return spec


def _validate_selection_spec(spec: Mapping[str, Any]) -> None:
    actual = selection_spec_integrity_hash(spec)
    stored = spec.get("integrity", {}).get("selection_spec_sha256")
    if stored != actual:
        raise ValueError("A1 selection spec integrity mismatch")
    if spec.get("selection_spec_version") != SELECTION_SPEC_VERSION:
        raise ValueError("unexpected A1 selection spec version")
    if stored != PINNED_SELECTION_SPEC_SHA256:
        raise ValueError("A1 selection spec version is bound to a different canonical hash")
    if spec.get("fixed_seed") is None or not str(spec["fixed_seed"]).strip():
        raise ValueError("A1 fixed SHA-256 ranking seed is missing")
    if spec.get("cohort_order") != {"CN": list(CN_COHORTS), "US": list(US_COHORTS)}:
        raise ValueError("A1 cohort order changed")
    if spec.get("primary_quota") != {"CN": CN_PRIMARY_QUOTAS, "US": US_PRIMARY_QUOTAS}:
        raise ValueError("A1 primary quota rule changed")
    if spec.get("reserve_rule", {}).get("total_by_market") != RESERVE_TARGETS:
        raise ValueError("A1 reserve quota rule changed")
    if spec.get("ranking", {}).get("algorithm") != "SHA-256":
        raise ValueError("A1 ranking algorithm changed")
    if spec.get("ranking", {}).get("input_template") != "fixed_seed|market|cohort|canonical_symbol":
        raise ValueError("A1 ranking input rule changed")
    if spec.get("ranking", {}).get("sort_order") != "digest_ascending_then_canonical_symbol_ascending":
        raise ValueError("A1 ranking sort rule changed")


def _validate_parent_protocol(parent_protocol: Mapping[str, Any] | None = None) -> dict[str, Any]:
    actual = load_protocol()
    if actual["protocol_version"] != EXPECTED_PROTOCOL_VERSION:
        raise ValueError("unexpected Phase 5J-v2 parent version")
    if actual["integrity"]["protocol_sha256"] != PINNED_PROTOCOL_SHA256_BY_VERSION[EXPECTED_PROTOCOL_VERSION]:
        raise ValueError("Phase 5J-v2 parent hash is not pinned")
    if actual["phase5j_status"] != PROTOCOL_STATUS:
        raise ValueError("Phase 5J-v2 parent was executed or changed status")
    if parent_protocol is not None:
        if parent_protocol.get("protocol_version") != actual["protocol_version"]:
            raise ValueError("parent Phase 5J-v2 protocol version mismatch")
        if parent_protocol.get("integrity", {}).get("protocol_sha256") != actual["integrity"]["protocol_sha256"]:
            raise ValueError("parent Phase 5J-v2 protocol hash mismatch")
    return actual


def _response_payload(raw: bytes, source_id: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{source_id} response is not valid UTF-8 JSON") from exc


def _fetch_raw(
    endpoint: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int | None, bytes, str | None]:
    request_headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "stock-data-pipeline/phase5k-a1"}
    request_headers.update(headers or {})
    request = Request(endpoint, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.read(), None
    except HTTPError as exc:
        return exc.code, exc.read(), f"HTTPError {exc.code}"
    except URLError as exc:
        return None, b"", f"URLError: {exc.reason}"
    except OSError as exc:
        return None, b"", f"OS error: {exc}"


def _api_success(raw: bytes, status: int | None, source_id: str) -> tuple[Any, str, Any, str | None]:
    payload = _response_payload(raw, source_id)
    if not isinstance(payload, dict):
        raise SnapshotError(f"{source_id} response envelope is not an object")
    code = payload.get("code")
    if status != 200 or code != 0:
        raise SnapshotError(f"{source_id} requires HTTP 200 plus API code 0")
    data = payload.get("data")
    timestamp = data.get("timestamp") if isinstance(data, dict) else None
    return payload, "HTTP_200_API_CODE_0", timestamp, "data.timestamp" if timestamp is not None else None


def _write_raw(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha256_bytes(raw)


def _snapshot_record(
    *,
    source_id: str,
    source_identity: str,
    endpoint: str,
    method: str,
    retrieval_timestamp: str,
    raw_path: Path,
    raw: bytes,
    http_status: int | None,
    api_success_state: str,
    constituent_count: int,
    parser: str,
    api_data_timestamp: Any = None,
    api_data_timestamp_field: str | None = None,
    request_body: str | None = None,
    source_role: str = "CURRENT_UNIVERSE_SNAPSHOT",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_identity": source_identity,
        "source_role": source_role,
        "endpoint": endpoint,
        "http_method": method,
        "request_body": request_body,
        "retrieval_timestamp": retrieval_timestamp,
        "api_data_timestamp": api_data_timestamp,
        "api_data_timestamp_field": api_data_timestamp_field,
        "http_status": http_status,
        "api_success_state": api_success_state,
        "raw_snapshot_path": str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "raw_snapshot_sha256": sha256_bytes(raw),
        "constituent_count": constituent_count,
        "parser": parser,
    }


def _hithink_endpoint(thscode: str) -> str:
    query = urlencode({"thscode": thscode})
    return f"{HITHINK_BASE_URL}/api/a-share-index/constituents/ths-stock-list?{query}"


def _hithink_items(payload: Mapping[str, Any], source_id: str) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    items = data.get("item") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise SnapshotError(f"{source_id} constituent item list is missing")
    return list(items)


def _source_symbol_from_thscode(item: Mapping[str, Any], source_id: str) -> str:
    raw = str(item.get("thscode") or "").strip().upper()
    if not re.fullmatch(r"\d{6}\.(SH|SZ)", raw):
        raise SnapshotError(f"{source_id} has an invalid THS security identity")
    return raw


def cn_board_status(canonical_symbol: str) -> str:
    ticker, venue = canonical_symbol.split(".")
    if venue == "SH":
        if ticker.startswith(("688", "689")):
            return "CN_STAR_REGISTERED_INACTIVE"
        if ticker.startswith(("600", "601", "603", "605")):
            return "SSE_MAIN_BOARD_COMMON_A"
        return "CN_SSE_OTHER_OR_UNCLASSIFIED"
    if venue == "SZ":
        if ticker.startswith(("300", "301", "302", "303")):
            return "CN_CHINEXT_REGISTERED_INACTIVE"
        if ticker.startswith(("000", "001", "002", "003")):
            return "SZSE_MAIN_BOARD_COMMON_A"
        return "CN_SZSE_OTHER_OR_UNCLASSIFIED"
    return "CN_OTHER_VENUE_OR_UNCLASSIFIED"


def _stable_source_row(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    canonical = str(row["canonical_symbol"])
    return canonical, dict(row)


def filter_cn_cohort_items(
    cohort: str,
    items: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if cohort not in CN_COHORTS:
        raise ValueError(f"unknown CN cohort: {cohort}")
    items = list(items)
    candidates: dict[str, dict[str, Any]] = {}
    excluded: dict[str, int] = {}
    for item in items:
        symbol = _source_symbol_from_thscode(item, cohort)
        board = cn_board_status(symbol)
        row = {
            "market": "CN",
            "cohort": cohort,
            "canonical_symbol": symbol,
            "canonical_identity": symbol,
            "source_ticker": str(item.get("ticker") or symbol.split(".")[0]),
            "source_name": str(item.get("name") or ""),
            "board_status": board,
        }
        if board not in CN_MAIN_ACTIVE:
            excluded[board] = excluded.get(board, 0) + 1
            continue
        existing = candidates.get(symbol)
        if existing is None or canonical_json(row) < canonical_json(existing):
            candidates[symbol] = row
    result = [candidates[key] for key in sorted(candidates)]
    diagnostics = {
        "source_cohort": cohort,
        "raw_constituent_count": len(items),
        "eligible_active_main_board_count": len(result),
        "excluded_by_board_status": dict(sorted(excluded.items())),
        "registered_inactive_statuses_preserved": list(CN_REGISTERED_INACTIVE),
    }
    return result, diagnostics


class _SP500TableParser(HTMLParser):
    """Extract the first MediaWiki table with Symbol and Security headers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._cell_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
        elif tag == "tr" and self._table_depth == 1:
            self._current_row = []
        elif tag in {"th", "td"} and self._table_depth == 1 and self._current_row is not None:
            self._cell_tag = tag
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._current_cell is not None and self._current_row is not None:
            value = " ".join("".join(self._current_cell).split())
            self._current_row.append(value)
            self._current_cell = None
            self._cell_tag = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._table_depth == 1:
            if self._current_table is not None:
                self.tables.append(self._current_table)
            self._current_table = None
            self._table_depth = 0


def parse_sp500_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    parsed = payload.get("parse")
    html = parsed.get("text") if isinstance(parsed, dict) else None
    if not isinstance(html, str):
        raise SnapshotError("S&P 500 source has no parsed HTML")
    parser = _SP500TableParser()
    parser.feed(html)
    for table in parser.tables:
        if not table:
            continue
        header = [cell.strip() for cell in table[0]]
        if "Symbol" not in header or "Security" not in header:
            continue
        rows = []
        for values in table[1:]:
            if len(values) < len(header):
                continue
            row = dict(zip(header, values))
            if row.get("Symbol") and row.get("Security"):
                rows.append(row)
        if len(rows) < 400:
            raise SnapshotError("S&P 500 source table is implausibly small")
        return rows
    raise SnapshotError("S&P 500 source table with Symbol/Security headers was not found")


def parse_sp500_spdji_payload(raw: bytes) -> list[dict[str, Any]]:
    """Parse only a complete S&P DJI HTML constituent table.

    The public page may expose a shell or only top constituents.  The strict
    row-count contract makes that an explicit fallback condition rather than
    silently treating a partial page as the index roster.
    """
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotError("S&P DJI source is not valid UTF-8 HTML") from exc
    parser = _SP500TableParser()
    parser.feed(html)
    for table in parser.tables:
        if not table:
            continue
        header = [cell.strip() for cell in table[0]]
        if "Constituent" not in header or "Symbol" not in header:
            continue
        rows = []
        for values in table[1:]:
            if len(values) < len(header):
                continue
            row = dict(zip(header, values))
            if row.get("Constituent") and row.get("Symbol"):
                rows.append({"Symbol": row["Symbol"], "Security": row["Constituent"], "Sector": row.get("Sector*", "")})
        if len(rows) < 400:
            raise SnapshotError("S&P DJI source did not provide a complete constituent table")
        return rows
    raise SnapshotError("S&P DJI source has no complete Constituent/Symbol table")


def _canonical_us_ticker(raw: Any, source_id: str) -> str:
    symbol = str(raw or "").strip().upper().replace("/", ".")
    if not symbol or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", symbol):
        raise SnapshotError(f"{source_id} has an invalid US ticker")
    return symbol


def _us_rows(cohort: str, rows: Iterable[Mapping[str, Any]], source_id: str) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for source_row in rows:
        raw_symbol = source_row.get("Symbol", source_row.get("Ticker"))
        symbol = _canonical_us_ticker(raw_symbol, source_id)
        row = {
            "market": "US",
            "cohort": cohort,
            "canonical_symbol": symbol,
            "canonical_identity": f"US|{symbol}",
            "source_name": str(source_row.get("Security", source_row.get("Name", ""))).strip(),
            "source_sector": str(source_row.get("GICS Sector", source_row.get("Sector", ""))).strip(),
            "source_asset_class": str(source_row.get("Asset Class", "Equity")).strip(),
        }
        existing = candidates.get(symbol)
        if existing is None or canonical_json(row) < canonical_json(existing):
            candidates[symbol] = row
    return [candidates[key] for key in sorted(candidates)]


def parse_nasdaq_weighting_payload(payload: Mapping[str, Any], source_id: str) -> list[dict[str, Any]]:
    rows = payload.get("aaData")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SnapshotError(f"{source_id} has no aaData component list")
    expected = payload.get("iTotalRecords")
    if isinstance(expected, int) and expected != len(rows):
        raise SnapshotError(f"{source_id} component count does not match its response total")
    return list(rows)


def parse_ishares_holdings_payload(raw: bytes) -> tuple[list[dict[str, Any]], str | None, int]:
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header_index = next((i for i, row in enumerate(rows) if row and row[0] == "Ticker"), None)
    if header_index is None:
        raise SnapshotError("IGV holdings CSV header is missing")
    header = rows[header_index]
    parsed = [dict(zip(header, row)) for row in rows[header_index + 1:] if len(row) >= len(header)]
    equity_rows = [row for row in parsed if row.get("Asset Class", "").strip().lower() == "equity" and row.get("Ticker", "").strip()]
    if not equity_rows:
        raise SnapshotError("IGV holdings contains no equity rows")
    as_of = None
    for row in rows[:header_index]:
        if len(row) >= 2 and row[0] == "Fund Holdings as of":
            as_of = row[1]
            break
    return equity_rows, as_of, len(parsed)


parse_igv_holdings_payload = parse_ishares_holdings_payload


def _rank_key(row: Mapping[str, Any], *, fixed_seed: str, market: str, cohort: str) -> tuple[str, str]:
    symbol = str(row["canonical_symbol"])
    material = f"{fixed_seed}|{market}|{cohort}|{symbol}".encode("utf-8")
    return hashlib.sha256(material).hexdigest(), symbol


def _select_market(
    market: str,
    cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    cohort_order: Sequence[str],
    primary_quotas: Mapping[str, int],
    reserve_target: int,
    fixed_seed: str,
) -> list[dict[str, Any]]:
    claimed: set[str] = set()
    primary: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    for cohort in cohort_order:
        ranked = sorted(
            (dict(row) for row in cohorts.get(cohort, ())),
            key=lambda row: _rank_key(row, fixed_seed=fixed_seed, market=market, cohort=cohort),
        )
        selected_in_cohort = 0
        cohort_position = 0
        for row in ranked:
            identity = str(row["canonical_identity"])
            if identity in claimed:
                continue
            claimed.add(identity)
            cohort_position += 1
            row["ranking_digest"] = _rank_key(row, fixed_seed=fixed_seed, market=market, cohort=cohort)[0]
            row["cohort_rank"] = cohort_position
            if selected_in_cohort < primary_quotas[cohort]:
                row["intended_role"] = "PRIMARY"
                primary.append(row)
                selected_in_cohort += 1
            else:
                row["intended_role"] = "RESERVE"
                remainder.append(row)
        if selected_in_cohort != primary_quotas[cohort]:
            raise ValueError(f"{market}/{cohort} cannot fill its primary quota")
    if len(remainder) < reserve_target:
        raise ValueError(f"{market} cannot fill its reserve quota")
    selected = primary + remainder[:reserve_target]
    for rank, row in enumerate(selected, start=1):
        row["manifest_rank"] = rank
    return selected


def _check_no_forbidden_fields(rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        for field in row:
            normalized = str(field).strip().lower().replace("-", "_")
            if any(fragment in normalized for fragment in FORBIDDEN_SELECTION_FRAGMENTS):
                raise ValueError(f"forbidden signal/result field in selection input: {field}")


def build_manifest(
    cn_cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    us_cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    source_snapshots: Sequence[Mapping[str, Any]] = (),
    source_selection: Mapping[str, Any] | None = None,
    parent_protocol: Mapping[str, Any] | None = None,
    selection_spec: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    parent = _validate_parent_protocol(parent_protocol)
    spec = load_selection_spec() if selection_spec is None else dict(selection_spec)
    _validate_selection_spec(spec)
    fixed_seed = str(spec["fixed_seed"])
    all_input_rows = [row for values in cn_cohorts.values() for row in values]
    all_input_rows.extend(row for values in us_cohorts.values() for row in values)
    _check_no_forbidden_fields(all_input_rows)
    cn_symbols = _select_market(
        "CN", cn_cohorts, cohort_order=CN_COHORTS,
        primary_quotas=CN_PRIMARY_QUOTAS, reserve_target=RESERVE_TARGETS["CN"], fixed_seed=fixed_seed,
    )
    us_symbols = _select_market(
        "US", us_cohorts, cohort_order=US_COHORTS,
        primary_quotas=US_PRIMARY_QUOTAS, reserve_target=RESERVE_TARGETS["US"], fixed_seed=fixed_seed,
    )
    symbols = []
    for row in cn_symbols + us_symbols:
        output = {
            "market": row["market"],
            "canonical_symbol": row["canonical_symbol"],
            "canonical_identity": row["canonical_identity"],
            "source_cohort": row["cohort"],
            "manifest_rank": row["manifest_rank"],
            "intended_role": row["intended_role"],
            "cohort_rank": row["cohort_rank"],
            "ranking_digest": row["ranking_digest"],
            "source_name": row.get("source_name", ""),
        }
        if row["market"] == "CN":
            output["board_status"] = row["board_status"]
            output["source_ticker"] = row["source_ticker"]
        else:
            output["source_sector"] = row.get("source_sector", "")
            output["source_asset_class"] = row.get("source_asset_class", "Equity")
        symbols.append(output)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "phase": "Phase 5K-A1",
        "status": MANIFEST_STATUS,
        "parent_protocol": {
            "version": parent["protocol_version"],
            "sha256": parent["integrity"]["protocol_sha256"],
            "phase5j_status": parent["phase5j_status"],
        },
        "source_snapshot_identities": [dict(item) for item in source_snapshots],
        "sp500_provenance": dict(source_selection or {}),
        "snapshot_bundle_status": "FROZEN_RAW_SOURCE_SNAPSHOTS_ONLY",
        "cohort_definitions": {
            "CN": {
                "cohorts": list(CN_COHORTS),
                "index_codes": dict(CN_INDEX_CODES),
                "active_board_scope": list(CN_MAIN_ACTIVE),
                "registered_inactive_board_scope": list(CN_REGISTERED_INACTIVE),
                "registered_inactive_excluded_from_manifest": True,
            },
            "US": {
                "cohorts": list(US_COHORTS),
                "source_roles": {
                    "SP500": "official_etf_issuer_holdings_proxy",
                    "NASDAQ100": "Nasdaq_Global_Index_Watch_official_weighting_components",
                    "SOX": "Nasdaq_Global_Index_Watch_official_weighting_components",
                    "IGV": "iShares_official_current_holdings",
                },
                "SP500_proxy_limitation": SP500_PROXY_LIMITATION,
            },
        },
        "quota_rules": {
            "primary_by_cohort": {"CN": dict(CN_PRIMARY_QUOTAS), "US": dict(US_PRIMARY_QUOTAS)},
            "primary_target_by_market": {"CN": 40, "US": 40},
            "reserve_target_by_market": dict(RESERVE_TARGETS),
            "total_primary": 80,
            "total_reserve": 40,
        },
        "deterministic_ranking": {
            "selection_spec_version": spec["selection_spec_version"],
            "selection_spec_sha256": spec["integrity"]["selection_spec_sha256"],
            "fixed_seed": fixed_seed,
            "algorithm": "SHA-256",
            "input_template": "fixed_seed|market|cohort|canonical_symbol",
            "sort_order": "digest_ascending_then_canonical_symbol_ascending",
            "ranking_is_cohort_local": True,
            "no_signal_or_performance_inputs": True,
        },
        "duplicate_attribution_rule": {
            "CN_identity": "canonical_symbol",
            "US_identity": "canonical_issuer_share_class_identity",
            "cohort_order": {"CN": list(CN_COHORTS), "US": list(US_COHORTS)},
            "rule": "first declared cohort claims an identity; later cohort occurrences are skipped; each identity appears once per market",
            "reserve_rule": "after primary quotas, take the next first-attributed members in cohort order and cohort-local hash order",
        },
        "aggregate_diagnostic_instruments": {
            "instruments": list(AGGREGATE_DIAGNOSTIC_INSTRUMENTS),
            "role": "AGGREGATE_DIAGNOSTIC_ONLY",
            "counts_toward_40_equities": False,
            "counts_toward_qualification": False,
            "participates_in_ranking": False,
        },
        "symbols": symbols,
        "counts": {
            "CN": {"PRIMARY": sum(row["intended_role"] == "PRIMARY" for row in cn_symbols), "RESERVE": sum(row["intended_role"] == "RESERVE" for row in cn_symbols)},
            "US": {"PRIMARY": sum(row["intended_role"] == "PRIMARY" for row in us_symbols), "RESERVE": sum(row["intended_role"] == "RESERVE" for row in us_symbols)},
            "total": {"PRIMARY": 80, "RESERVE": 40},
        },
        "phase5k_controls": {
            "historical_ohlcv_fetched": False,
            "validation_ohlcv_fetched": False,
            "setup03_evaluator_called": False,
            "setup03_output_accessed": False,
            "final_oos_accessed": False,
            "manifest_authoritative_before_acquisition": True,
        },
        "generated_at": generated_at or _iso_now(),
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    version = manifest.get("manifest_version")
    if version not in PINNED_MANIFEST_SHA256_BY_VERSION:
        raise ValueError("unexpected A1 manifest version")
    stored = manifest.get("integrity", {}).get("manifest_sha256")
    actual = manifest_integrity_hash(manifest)
    if stored != actual:
        raise ValueError("A1 manifest integrity mismatch")
    if stored != PINNED_MANIFEST_SHA256_BY_VERSION[version]:
        raise ValueError("A1 manifest version is bound to a different canonical hash")
    expected_schema = MANIFEST_SCHEMA_VERSION if version == MANIFEST_VERSION else "setup03-phase5k-a1-universe-manifest-v1"
    if manifest.get("schema_version") != expected_schema:
        raise ValueError("A1 manifest schema version changed")
    parent = manifest.get("parent_protocol", {})
    if parent.get("version") != EXPECTED_PROTOCOL_VERSION:
        raise ValueError("A1 manifest parent protocol version changed")
    if parent.get("sha256") != PINNED_PROTOCOL_SHA256_BY_VERSION[EXPECTED_PROTOCOL_VERSION]:
        raise ValueError("A1 manifest parent protocol hash changed")
    if manifest.get("status") != MANIFEST_STATUS:
        raise ValueError("A1 manifest status changed")
    if manifest.get("aggregate_diagnostic_instruments", {}).get("instruments") != list(AGGREGATE_DIAGNOSTIC_INSTRUMENTS):
        raise ValueError("aggregate diagnostic instruments changed")
    snapshots = manifest.get("source_snapshot_identities")
    if not isinstance(snapshots, list) or len(snapshots) != 7:
        raise ValueError("A1 manifest must contain exactly 7 source snapshot identities")
    sp500_records = [record for record in snapshots if record.get("cohort") == "SP500"]
    if len(sp500_records) != 1:
        raise ValueError("A1 manifest must contain exactly one SP500 source snapshot")
    sp500 = sp500_records[0]
    if version == MANIFEST_VERSION:
        if sp500.get("source_identity") not in {SP500_SPDJI_SOURCE_IDENTITY, SP500_PROXY_SOURCE_IDENTITY}:
            raise ValueError("frozen S&P 500 source identity is not an approved source class")
        if sp500.get("source_identity") == SP500_PROXY_SOURCE_IDENTITY:
            if sp500.get("source_role") != "CURRENT_UNIVERSE_PROXY":
                raise ValueError("IVV S&P 500 proxy role is missing")
            if sp500.get("proxy_for") != "S&P500" or not sp500.get("provenance_limitation"):
                raise ValueError("IVV S&P 500 proxy limitation is missing")
        if "WIKIMEDIA" in str(sp500.get("source_identity", "")).upper() or "wikipedia" in str(sp500.get("parser", "")).lower():
            raise ValueError("production S&P 500 provenance cannot be Wikimedia")
    elif sp500.get("source_identity") != "WIKIMEDIA-SP500-CURRENT-CONSTITUENTS-AUTHORITATIVE-PUBLIC-REFERENCE":
        raise ValueError("legacy v1 S&P 500 audit source changed")
    controls = manifest.get("phase5k_controls", {})
    for key in ("historical_ohlcv_fetched", "validation_ohlcv_fetched", "setup03_evaluator_called", "setup03_output_accessed", "final_oos_accessed"):
        if controls.get(key) is not False:
            raise ValueError(f"forbidden Phase 5K-A1 control changed: {key}")
    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 120:
        raise ValueError("A1 manifest must contain 120 symbols")
    for market, total in (("CN", 60), ("US", 60)):
        rows = [row for row in symbols if row.get("market") == market]
        if len(rows) != total:
            raise ValueError(f"{market} manifest count changed")
        if [row.get("manifest_rank") for row in rows] != list(range(1, 61)):
            raise ValueError(f"{market} manifest ranks are not 1..60")
        if sum(row.get("intended_role") == "PRIMARY" for row in rows) != 40:
            raise ValueError(f"{market} primary count changed")
        if sum(row.get("intended_role") == "RESERVE" for row in rows) != 20:
            raise ValueError(f"{market} reserve count changed")
        if len({row.get("canonical_identity") for row in rows}) != total:
            raise ValueError(f"{market} contains duplicate canonical identities")
    for row in symbols:
        if row.get("market") == "CN" and row.get("board_status") not in CN_MAIN_ACTIVE:
            raise ValueError("CN STAR/ChiNext or another inactive board entered manifest")
        if row.get("canonical_symbol") in AGGREGATE_DIAGNOSTIC_INSTRUMENTS:
            raise ValueError("aggregate diagnostic instrument entered equity manifest")


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_parent_protocol()
    _validate_manifest_shape(manifest)
    return manifest


def _raw_path_from_record(record: Mapping[str, Any], bundle_dir: Path) -> Path:
    path_text = str(record["raw_snapshot_path"])
    relative = Path(path_text)
    if relative.is_absolute() or relative.name in {"", ".", ".."}:
        raise SnapshotError("snapshot raw path is not a relative file path")
    # Provenance keeps the repository-relative path for auditability; the
    # bundle loader resolves the immutable file name inside the supplied
    # bundle so copied test bundles remain independently verifiable.
    path = bundle_dir / relative.name
    bundle_root = bundle_dir.resolve()
    try:
        path.resolve().relative_to(bundle_root)
    except ValueError as exc:
        raise SnapshotError("snapshot raw path escapes the bundle directory") from exc
    return path


def load_snapshot_bundle(bundle_dir: Path = SNAPSHOT_DIR) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    provenance_path = bundle_dir / "snapshot_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("snapshot_bundle_version") != "SETUP_03-CN-US-OFFICIAL-SNAPSHOT-BUNDLE-2026-08-27-v2":
        raise SnapshotError("only the active v2 source bundle may generate a new manifest")
    records = provenance.get("source_snapshots")
    if not isinstance(records, list) or len(records) != 7:
        raise SnapshotError("A1 frozen source bundle must contain exactly 7 source snapshots")
    cn: dict[str, list[dict[str, Any]]] = {}
    us: dict[str, list[dict[str, Any]]] = {}
    sp500_records = [record for record in records if record.get("cohort") == "SP500"]
    if len(sp500_records) != 1:
        raise SnapshotError("active source bundle must contain exactly one SP500 source snapshot")
    if sp500_records[0].get("source_identity") not in {SP500_SPDJI_SOURCE_IDENTITY, SP500_PROXY_SOURCE_IDENTITY}:
        raise SnapshotError("active S&P 500 source is not an approved source class")
    if "WIKIMEDIA" in str(sp500_records[0].get("source_identity", "")).upper():
        raise SnapshotError("Wikimedia cannot participate in a new manifest generation")
    for record in records:
        raw_path = _raw_path_from_record(record, bundle_dir)
        raw = raw_path.read_bytes()
        if sha256_bytes(raw) != record.get("raw_snapshot_sha256"):
            raise SnapshotError(f"source snapshot hash changed: {record.get('source_id')}")
        if record.get("http_status") != 200:
            raise SnapshotError(f"source snapshot was not retrieved with HTTP 200: {record.get('source_id')}")
        source_id = str(record["source_id"])
        parser = record.get("parser")
        if parser == "hithink_index_constituents_v1":
            payload = _response_payload(raw, source_id)
            if payload.get("code") != 0 or record.get("api_success_state") != "HTTP_200_API_CODE_0":
                raise SnapshotError(f"HiThink source does not satisfy HTTP 200 plus API code 0: {source_id}")
            items = _hithink_items(payload, source_id)
            if len(items) != record.get("constituent_count"):
                raise SnapshotError(f"source constituent count changed: {source_id}")
            cohort = str(record["cohort"])
            eligible, _ = filter_cn_cohort_items(cohort, items)
            cn[cohort] = eligible
        elif parser == "sp_dji_sp500_html_table_v1":
            rows = parse_sp500_spdji_payload(raw)
            if len(rows) != record.get("constituent_count"):
                raise SnapshotError(f"source constituent count changed: {source_id}")
            us["SP500"] = _us_rows("SP500", rows, source_id)
        elif parser == "ishares_holdings_csv_equity_rows_v1" and record.get("cohort") == "SP500":
            if record.get("source_identity") != SP500_PROXY_SOURCE_IDENTITY:
                raise SnapshotError("SP500 iShares holdings source identity changed")
            if record.get("source_role") != "CURRENT_UNIVERSE_PROXY":
                raise SnapshotError("SP500 iShares holdings proxy role changed")
            holdings, _, _ = parse_ishares_holdings_payload(raw)
            if len(holdings) != record.get("constituent_count"):
                raise SnapshotError(f"source holding count changed: {source_id}")
            us["SP500"] = _us_rows("SP500", holdings, source_id)
        elif parser == "nasdaq_weighting_components_v1":
            payload = _response_payload(raw, source_id)
            cohort = str(record["cohort"])
            if record.get("api_success_state") != "HTTP_200_SOURCE_PAYLOAD_OK":
                raise SnapshotError(f"Nasdaq source success state changed: {source_id}")
            rows = parse_nasdaq_weighting_payload(payload, source_id)
            if len(rows) != record.get("constituent_count"):
                raise SnapshotError(f"source constituent count changed: {source_id}")
            us[cohort] = _us_rows(cohort, rows, source_id)
        elif parser == "ishares_holdings_csv_equity_rows_v1":
            if record.get("api_success_state") != "HTTP_200_SOURCE_PAYLOAD_OK":
                raise SnapshotError(f"iShares source success state changed: {source_id}")
            holdings, _, _ = parse_ishares_holdings_payload(raw)
            if len(holdings) != record.get("constituent_count"):
                raise SnapshotError(f"source holding count changed: {source_id}")
            us["IGV"] = _us_rows("IGV", holdings, source_id)
        else:
            raise SnapshotError(f"unknown frozen source parser: {parser}")
    if set(cn) != set(CN_COHORTS) or set(us) != set(US_COHORTS):
        raise SnapshotError("frozen source bundle is missing a declared cohort")
    return provenance, cn, us


def rebuild_frozen_manifest(
    bundle_dir: Path = SNAPSHOT_DIR,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    provenance, cn, us = load_snapshot_bundle(bundle_dir)
    manifest = build_manifest(
        cn,
        us,
        source_snapshots=provenance["source_snapshots"],
        source_selection=provenance.get("sp500_source_selection"),
        generated_at=provenance["manifest_generated_at"],
    )
    if manifest_path is not None:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def fetch_current_snapshots(output_dir: Path = SNAPSHOT_DIR) -> dict[str, Any]:
    """Fetch exactly the seven declared constituent/holding sources.

    The only authenticated request is the three HiThink index endpoints.  The
    key is read from HITHINK_FINANCE_API_KEY and is never included in a record,
    exception message, output, or file.
    """
    api_key = os.environ.get(HITHINK_API_KEY_ENV, "").strip()
    if not api_key:
        raise SnapshotError(f"{HITHINK_API_KEY_ENV} is not configured")
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, cohort in enumerate(CN_COHORTS, start=1):
        endpoint = _hithink_endpoint(CN_INDEX_CODES[cohort])
        retrieved_at = _iso_now()
        status, raw, error = _fetch_raw(
            endpoint,
            headers={"X-api-key": api_key},
        )
        if error:
            raise SnapshotError(f"{cohort} snapshot transport failed: {error}")
        payload, state, timestamp, timestamp_field = _api_success(raw, status, cohort)
        items = _hithink_items(payload, cohort)
        eligible, diagnostics = filter_cn_cohort_items(cohort, items)
        raw_path = output_dir / f"{index:02d}_{cohort.lower()}_constituents.json"
        _write_raw(raw_path, raw)
        record = _snapshot_record(
            source_id=f"HITHINK_{cohort}",
            source_identity="HITHINK-FINANCIAL-API-FUYAO",
            endpoint=endpoint,
            method="GET",
            retrieval_timestamp=retrieved_at,
            raw_path=raw_path,
            raw=raw,
            http_status=status,
            api_success_state=state,
            constituent_count=len(items),
            parser="hithink_index_constituents_v1",
            api_data_timestamp=timestamp,
            api_data_timestamp_field=timestamp_field,
        )
        record["cohort"] = cohort
        record["source_index_code"] = CN_INDEX_CODES[cohort]
        record["eligible_active_main_board_count"] = diagnostics["eligible_active_main_board_count"]
        record["excluded_by_board_status"] = diagnostics["excluded_by_board_status"]
        record["registered_inactive_statuses_preserved"] = diagnostics["registered_inactive_statuses_preserved"]
        records.append(record)
    for index, (cohort, index_symbol) in enumerate((("NASDAQ100", "NDX"), ("SOX", "SOX")), start=4):
        body = urlencode({"id": index_symbol, "tradeDate": datetime.now().date().isoformat(), "timeOfDay": "SOD"}).encode()
        retrieved_at = _iso_now()
        status, raw, error = _fetch_raw(
            NASDAQ_WEIGHTING_URL,
            method="POST",
            body=body,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://indexes.nasdaq.com",
                "Referer": f"https://indexes.nasdaq.com/Index/Weighting/{index_symbol}",
            },
        )
        if error or status != 200:
            raise SnapshotError(f"{cohort} snapshot transport failed")
        payload = _response_payload(raw, cohort)
        rows = parse_nasdaq_weighting_payload(payload, cohort)
        raw_path = output_dir / f"{index}_{cohort.lower()}_components.json"
        _write_raw(raw_path, raw)
        record = _snapshot_record(
            source_id=f"NASDAQ_{cohort}",
            source_identity="NASDAQ-GLOBAL-INDEX-WATCH-OFFICIAL",
            endpoint=NASDAQ_WEIGHTING_URL,
            method="POST",
            request_body=body.decode("ascii"),
            retrieval_timestamp=retrieved_at,
            raw_path=raw_path,
            raw=raw,
            http_status=status,
            api_success_state="HTTP_200_SOURCE_PAYLOAD_OK",
            constituent_count=len(rows),
            parser="nasdaq_weighting_components_v1",
        )
        record["cohort"] = cohort
        record["official_index_symbol"] = index_symbol
        records.append(record)

    sp500_probe_at = _iso_now()
    sp500_status, sp500_raw, sp500_error = _fetch_raw(
        SP500_SPDJI_URL,
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "stock-data-pipeline/phase5k-a1"},
    )
    sp500_probe = {
        "source_identity": SP500_SPDJI_SOURCE_IDENTITY,
        "endpoint": SP500_SPDJI_URL,
        "http_method": "GET",
        "retrieval_timestamp": sp500_probe_at,
        "retrieval_contract": SP500_SPDJI_PROBE_CONTRACT,
    }
    official_rows: list[dict[str, Any]] | None = None
    if sp500_status == 200 and not sp500_error:
        try:
            official_rows = parse_sp500_spdji_payload(sp500_raw)
        except SnapshotError as exc:
            sp500_probe["outcome"] = "UNAVAILABLE_FOR_RELIABLE_COMPLETE_MACHINE_RETRIEVAL"
            sp500_probe["failure_reason"] = str(exc)
        else:
            sp500_probe["outcome"] = "COMPLETE_MACHINE_READABLE_CONSTITUENT_SNAPSHOT"
    else:
        sp500_probe["outcome"] = "UNAVAILABLE_FOR_RELIABLE_COMPLETE_MACHINE_RETRIEVAL"
        sp500_probe["failure_reason"] = sp500_error or f"HTTP status {sp500_status}"

    if official_rows is not None:
        raw_path = output_dir / "06_sp500_spdji_constituents.html"
        _write_raw(raw_path, sp500_raw)
        record = _snapshot_record(
            source_id="SP500_SPDJI_OFFICIAL",
            source_identity=SP500_SPDJI_SOURCE_IDENTITY,
            endpoint=SP500_SPDJI_URL,
            method="GET",
            retrieval_timestamp=sp500_probe_at,
            raw_path=raw_path,
            raw=sp500_raw,
            http_status=sp500_status,
            api_success_state="HTTP_200_COMPLETE_CONSTITUENT_TABLE",
            constituent_count=len(official_rows),
            parser="sp_dji_sp500_html_table_v1",
        )
        record["cohort"] = "SP500"
        records.append(record)
        sp500_source_selection = {
            "preferred_source_identity": SP500_SPDJI_SOURCE_IDENTITY,
            "preferred_endpoint": SP500_SPDJI_URL,
            "preferred_retrieval_contract": SP500_SPDJI_PROBE_CONTRACT,
            "preferred_source_outcome": sp500_probe["outcome"],
            "selected_source_identity": SP500_SPDJI_SOURCE_IDENTITY,
            "selected_source_class": "OFFICIAL_SPDJI_COMPLETE_CONSTITUENT_SNAPSHOT",
            "proxy_selected": False,
            "provenance_limitation": "Official S&P DJI constituent table as retrieved; index methodology, licensing, and public endpoint availability remain external dependencies.",
            "probe": sp500_probe,
        }
    else:
        retrieved_at = _iso_now()
        status, raw, error = _fetch_raw(
            SP500_IVV_HOLDINGS_URL,
            headers={"Accept": "text/csv,*/*", "User-Agent": "stock-data-pipeline/phase5k-a1"},
        )
        if error or status != 200:
            raise SnapshotError("S&P 500 proxy IVV source transport failed")
        holdings, as_of, total_rows = parse_ishares_holdings_payload(raw)
        raw_path = output_dir / "06_sp500_proxy_ivv_holdings.csv"
        _write_raw(raw_path, raw)
        record = _snapshot_record(
            source_id="SP500_PROXY_IVV_ISHARES",
            source_identity=SP500_PROXY_SOURCE_IDENTITY,
            source_role="CURRENT_UNIVERSE_PROXY",
            endpoint=SP500_IVV_HOLDINGS_URL,
            method="GET",
            retrieval_timestamp=retrieved_at,
            raw_path=raw_path,
            raw=raw,
            http_status=status,
            api_success_state="HTTP_200_SOURCE_PAYLOAD_OK",
            constituent_count=len(holdings),
            parser="ishares_holdings_csv_equity_rows_v1",
            api_data_timestamp=as_of,
            api_data_timestamp_field="Fund Holdings as of",
        )
        record["cohort"] = "SP500"
        record["proxy_for"] = "S&P500"
        record["proxy_type"] = "OFFICIAL_ETF_ISSUER_HOLDINGS"
        record["official_constituent_snapshot"] = False
        record["provenance_limitation"] = SP500_PROXY_LIMITATION
        record["fund_ticker"] = "IVV"
        record["raw_holding_row_count"] = total_rows
        records.append(record)
        sp500_source_selection = {
            "preferred_source_identity": SP500_SPDJI_SOURCE_IDENTITY,
            "preferred_endpoint": SP500_SPDJI_URL,
            "preferred_retrieval_contract": SP500_SPDJI_PROBE_CONTRACT,
            "preferred_source_outcome": sp500_probe["outcome"],
            "selected_source_identity": SP500_PROXY_SOURCE_IDENTITY,
            "selected_source_class": "OFFICIAL_ETF_ISSUER_HOLDINGS_PROXY",
            "proxy_selected": True,
            "provenance_limitation": SP500_PROXY_LIMITATION,
            "probe": sp500_probe,
        }

    retrieved_at = _iso_now()
    status, raw, error = _fetch_raw(
        IGV_HOLDINGS_URL,
        headers={"Accept": "text/csv,*/*", "User-Agent": "stock-data-pipeline/phase5k-a1"},
    )
    if error or status != 200:
        raise SnapshotError("IGV source transport failed")
    holdings, as_of, total_rows = parse_ishares_holdings_payload(raw)
    raw_path = output_dir / "07_igv_holdings.csv"
    _write_raw(raw_path, raw)
    record = _snapshot_record(
        source_id="IGV_ISHARES",
        source_identity="ISHARES-IGV-OFFICIAL-HOLDINGS",
        endpoint=IGV_HOLDINGS_URL,
        method="GET",
        retrieval_timestamp=retrieved_at,
        raw_path=raw_path,
        raw=raw,
        http_status=status,
        api_success_state="HTTP_200_SOURCE_PAYLOAD_OK",
        constituent_count=len(holdings),
        parser="ishares_holdings_csv_equity_rows_v1",
        api_data_timestamp=as_of,
        api_data_timestamp_field="Fund Holdings as of",
    )
    record["cohort"] = "IGV"
    record["raw_holding_row_count"] = total_rows
    record["aggregate_instrument_excluded"] = "IGV_ETF"
    records.append(record)

    records.sort(key=lambda record: record["source_id"])
    provenance = {
        "snapshot_bundle_version": "SETUP_03-CN-US-OFFICIAL-SNAPSHOT-BUNDLE-2026-08-27-v2",
        "parent_protocol_version": EXPECTED_PROTOCOL_VERSION,
        "parent_protocol_sha256": PINNED_PROTOCOL_SHA256_BY_VERSION[EXPECTED_PROTOCOL_VERSION],
        "retrieval_scope": "current constituent/holding snapshots only; no historical OHLCV",
        "manifest_generated_at": _iso_now(),
        "sp500_source_selection": sp500_source_selection,
        "source_snapshots": records,
    }
    SNAPSHOT_PROVENANCE_PATH_LOCAL = output_dir / "snapshot_provenance.json"
    SNAPSHOT_PROVENANCE_PATH_LOCAL.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return provenance


def freeze_manifest(
    *,
    bundle_dir: Path = SNAPSHOT_DIR,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = rebuild_frozen_manifest(bundle_dir)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _cli_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": manifest["manifest_version"],
        "status": manifest["status"],
        "manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "counts": manifest["counts"],
        "source_snapshot_hashes": {
            row["source_id"]: {"sha256": row["raw_snapshot_sha256"], "count": row["constituent_count"]}
            for row in manifest["source_snapshot_identities"]
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="fetch the seven declared current source snapshots")
    parser.add_argument("--freeze", action="store_true", help="rebuild and write the frozen manifest from saved raw snapshots")
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)
    if not args.fetch and not args.freeze:
        parser.error("choose --fetch and/or --freeze")
    if args.fetch:
        fetch_current_snapshots(args.snapshot_dir)
    if args.freeze:
        manifest = freeze_manifest(bundle_dir=args.snapshot_dir, manifest_path=args.manifest_path)
        print(json.dumps(_cli_summary(manifest), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
