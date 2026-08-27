"""Read-only HiThink CN API capability/provenance smoke test.

The probes are intentionally small and never download a market dump or build
the Phase 5K validation dataset.  An API key is read only from the process
environment and is never written to the report, raw-response files, or logs.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
SOURCE_ID = "HITHINK-FINANCIAL-API-FUYAO"
SOURCE_DOC = "https://github.com/HiThink-Tech/Financial-API"


def endpoint_specs() -> list[dict[str, str]]:
    """Return bounded GET probes for the five requested capabilities."""
    specs: list[dict[str, str]] = []

    def add(capability: str, label: str, path: str, **params: str) -> None:
        query = urlencode(params)
        specs.append({
            "capability": capability,
            "label": label,
            "endpoint": f"{BASE_URL}{path}{'?' + query if query else ''}",
        })

    add(
        "a_share_ticker_list",
        "A股股票代码列表",
        "/api/meta/tickers/list",
        exchange="SH,SZ",
        asset_type="a-share",
        limit="1",
        offset="0",
    )
    for index_id, thscode in (
        ("CSI300", "000300.SH"),
        ("CSI500", "000905.SH"),
        ("CSI1000", "000852.SH"),
    ):
        add(
            "index_constituents",
            f"{index_id}成分股",
            "/api/a-share-index/constituents/ths-stock-list",
            thscode=thscode,
        )
    add(
        "full_market_historical_daily_k",
        "全市场历史日K/market dump签名端点",
        "/api/dump/market-dumps/daily-k/download-url",
    )
    add(
        "corporate_actions_adjustment_factors",
        "公司行动/复权因子",
        "/api/a-share/corporate-actions/adjustment-factors",
        thscode="600519.SH",
        **{"from": "2024-01-01", "to": "2024-12-31"},
    )
    add(
        "trading_calendar",
        "交易日历",
        "/api/a-share/calendar/trading-days",
    )
    return specs


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _response_summary(status: int | None, raw: bytes, error: str | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "http_status": status,
        "api_code": None,
        "response_envelope_fields": [],
        "data_fields": [],
        "item_fields": [],
        "source_data_timestamp": None,
        "source_data_timestamp_field": None,
        "as_of_semantics_observed": "NOT_OBSERVABLE",
        "error": error,
    }
    if error:
        return summary
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        summary["error"] = f"non-JSON response: {exc}"
        return summary
    if not isinstance(payload, dict):
        summary["error"] = "response JSON is not an object"
        return summary
    summary["response_envelope_fields"] = sorted(str(key) for key in payload)
    summary["api_code"] = payload.get("code")
    data = payload.get("data")
    if isinstance(data, dict):
        summary["data_fields"] = sorted(str(key) for key in data)
        if "timestamp" in data:
            summary["source_data_timestamp"] = data["timestamp"]
            summary["source_data_timestamp_field"] = "data.timestamp"
            summary["as_of_semantics_observed"] = "source-provided data.timestamp; endpoint-specific semantics require provider confirmation"
        items = data.get("item")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            summary["item_fields"] = sorted(str(key) for key in items[0])
    return summary


def probe_endpoint(endpoint: str, api_key: str | None) -> tuple[int | None, bytes, str | None]:
    """Perform exactly one GET and return status, exact response bytes, error."""
    headers = {"Accept": "application/json", "User-Agent": "stock-data-pipeline-capability-smoke/1"}
    if api_key:
        headers["X-api-key"] = api_key
    request = Request(endpoint, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read(), None
    except HTTPError as exc:
        return exc.code, exc.read(), f"HTTPError {exc.code}"
    except URLError as exc:
        return None, b"", f"URLError: {exc.reason}"
    except OSError as exc:
        return None, b"", f"OS error: {exc}"


def run_smoke_test(
    output_dir: Path,
    probe: Any = probe_endpoint,
) -> dict[str, Any]:
    """Run bounded probes and write exact raw responses plus a summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    api_key = os.environ.get(API_KEY_ENV, "").strip() or None
    results: list[dict[str, Any]] = []
    for index, spec in enumerate(endpoint_specs(), start=1):
        status, raw, error = probe(spec["endpoint"], api_key)
        raw_path = output_dir / f"{index:02d}_{spec['capability']}.response"
        raw_path.write_bytes(raw)
        summary = _response_summary(status, raw, error)
        if summary["api_code"] == 0 and status == 200:
            outcome = "CAPABILITY_RESPONSE_SUCCESS"
        elif summary["api_code"] in (2001, 2003) or status in (401, 403):
            outcome = "AUTH_REQUIRED_OR_UNAUTHORIZED"
        elif error:
            outcome = "NETWORK_OR_TRANSPORT_ERROR"
        else:
            outcome = "API_RESPONSE_ERROR"
        results.append({
            **spec,
            **summary,
            "outcome": outcome,
            "raw_response_path": str(raw_path),
            "raw_response_sha256": sha256_bytes(raw),
        })

    report = {
        "smoke_test_version": "HITHINK-CN-CAPABILITY-SMOKE-2026-08-27-v1",
        "retrieved_at": retrieved_at,
        "source": {
            "source_id": SOURCE_ID,
            "provider_source_name": "同花顺金融数据服务（HiThink Financial API）",
            "base_url": BASE_URL,
            "documentation": SOURCE_DOC,
            "authentication": "X-api-key header from HITHINK_FINANCE_API_KEY only",
        },
        "api_key_configured": api_key is not None,
        "scope": {
            "read_only_get_only": True,
            "market_dump_download_followed": False,
            "formal_phase5k_dataset_built": False,
            "phase5k_validation_ohlcv_accessed": False,
            "setup03_output_accessed": False,
            "final_oos_accessed": False,
        },
        "results": results,
        "raw_response_sha256_supported": True,
        "interpretation": (
            "Capability is proven only by HTTP 200 plus response code 0. "
            "A missing/invalid key does not prove endpoint data availability; "
            "it proves that an authenticated entitlement is still required."
        ),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report_path": str(report_path), "api_key_configured": api_key is not None, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_smoke_test(args.output_dir)
    print(json.dumps({
        "report_path": result["report_path"],
        "api_key_configured": result["api_key_configured"],
        "outcomes": [row["outcome"] for row in result["results"]],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
