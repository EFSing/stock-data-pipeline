"""Run the read-only Wave Scenario Engine against enabled holdings.

The script reads the existing watchlist/configuration and fetches only the
explicit qfq history source needed for structural context. It writes local
JSON/CSV report artifacts and a step-summary line; it never writes a Google
Sheet, production decision, entry, return, or OOS artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading.models import WaveScenarioFamily
from trading.wave import (
    WAVE_ENGINE_PROTOCOL_VERSION,
    evaluate_wave_scenario,
    evaluation_to_dict,
)


UNKNOWN_FAMILIES = {
    WaveScenarioFamily.UPTREND_UNKNOWN_WAVE.value,
    WaveScenarioFamily.NO_VALID_SCENARIO.value,
}


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    primary = row.get("primary_scenario", {})
    alternate = row.get("alternate_scenario", {})
    return {
        "统一代码": row.get("symbol", ""),
        "名称": row.get("name", ""),
        "市场": row.get("market", ""),
        "as_of_date": row.get("as_of_date", ""),
        "weekly_state": row.get("weekly_state", ""),
        "daily_state": row.get("daily_state", ""),
        "primary_scenario": primary.get("family", ""),
        "alternate_scenario": alternate.get("family", ""),
        "primary_evidence_score": primary.get("evidence_score", ""),
        "alternate_evidence_score": alternate.get("evidence_score", ""),
        "primary_confirmed_swings": _json(primary.get("confirmed_swings", [])),
        "alternate_confirmed_swings": _json(alternate.get("confirmed_swings", [])),
        "candidate_impulse_leg": _json(primary.get("candidate_impulse_leg")),
        "candidate_retracement_leg": _json(primary.get("candidate_retracement_leg")),
        "fibonacci_retracement_regions": _json(primary.get("fibonacci_retracement_regions", [])),
        "fibonacci_extension_regions": _json(primary.get("fibonacci_extension_regions", [])),
        "structural_invalidation": primary.get("structural_invalidation", ""),
        "scenario_invalidation_reason": primary.get("scenario_invalidation_reason", ""),
        "SETUP_01_context": primary.get("setup01_context_eligible", False),
        "SETUP_02_context": primary.get("setup02_context_eligible", False),
        "error": row.get("error", ""),
    }


def _write_reports(output_dir: Path, document: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "wave_shadow_report.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = [_csv_row(row) for row in document["rows"]]
    fieldnames = list(rows[0]) if rows else ["统一代码", "as_of_date", "error"]
    with (output_dir / "wave_shadow_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_wave_shadow(
    group: str = "all",
    output_dir: str | Path = "artifacts/wave_shadow",
    *,
    client=None,
    fetched_at: datetime | None = None,
    fetch_history=None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> dict[str, Any]:
    """Evaluate every enabled holding in ``group`` without Sheet writes."""
    from main import wanted_markets_for_group
    from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
    from sheets_client import SheetsClient

    if client is None:
        client = SheetsClient()
    if fetch_history is None:
        fetch_history = fetch_with_retry
    now = fetched_at or datetime.now().astimezone()
    config = client.config()
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    history_days = int(float(config.get("history_days", 1000)))
    end = now.date()
    start = end - timedelta(days=max(history_days * 2, 365))
    wanted_markets = wanted_markets_for_group(group)
    watches = [
        watch for watch in client.records("自选清单")
        if _as_bool(watch.get("启用")) and str(watch.get("市场")) in wanted_markets
    ]

    rows: list[dict[str, Any]] = []
    errors = 0
    family_counts: dict[str, int] = {}
    unknown_count = 0
    for watch in watches:
        symbol = str(watch.get("统一代码") or "").strip()
        row_base = {
            "symbol": symbol,
            "name": str(watch.get("名称") or ""),
            "market": str(watch.get("市场") or ""),
        }
        source = str(watch.get("历史数据源") or "").strip()
        try:
            if source not in QFQ_HISTORY_SOURCES:
                raise ValueError(f"历史数据源{source or '<empty>'}不支持qfq shadow")
            quotes = fetch_history(
                source,
                watch,
                "qfq",
                start,
                end,
                retry_count,
                retry_wait,
            )
            if not quotes:
                raise ValueError("qfq历史为空")
            evaluation = evaluate_wave_scenario(
                quotes,
                as_of_date=max(quote.trade_date for quote in quotes),
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
            row = {
                **row_base,
                **evaluation_to_dict(evaluation),
                "history_last_date": max(quote.trade_date for quote in quotes).isoformat(),
                "data_source": source,
                "error": "",
            }
            family = evaluation.primary_scenario.family.value
            family_counts[family] = family_counts.get(family, 0) + 1
            unknown_count += family in UNKNOWN_FAMILIES
        except Exception as exc:
            errors += 1
            row = {
                **row_base,
                "protocol_version": WAVE_ENGINE_PROTOCOL_VERSION,
                "as_of_date": None,
                "weekly_state": "UNKNOWN",
                "daily_state": "UNKNOWN",
                "primary_scenario": {
                    "family": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                    "evidence": [],
                    "counter_evidence": [],
                    "evidence_score": 0,
                    "confirmed_swings": [],
                    "candidate_impulse_leg": None,
                    "candidate_retracement_leg": None,
                    "fibonacci_retracement_regions": [],
                    "fibonacci_extension_regions": [],
                    "structural_invalidation": None,
                    "scenario_invalidation_reason": "shadow history could not be evaluated",
                    "setup01_context_eligible": False,
                    "setup02_context_eligible": False,
                },
                "alternate_scenario": {
                    "family": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                    "evidence": [],
                    "counter_evidence": [],
                    "evidence_score": 0,
                    "confirmed_swings": [],
                    "candidate_impulse_leg": None,
                    "candidate_retracement_leg": None,
                    "fibonacci_retracement_regions": [],
                    "fibonacci_extension_regions": [],
                    "structural_invalidation": None,
                    "scenario_invalidation_reason": "shadow history could not be evaluated",
                    "setup01_context_eligible": False,
                    "setup02_context_eligible": False,
                },
                "history_last_date": None,
                "data_source": source,
                "error": str(exc),
            }
            family_counts[WaveScenarioFamily.NO_VALID_SCENARIO.value] = (
                family_counts.get(WaveScenarioFamily.NO_VALID_SCENARIO.value, 0) + 1
            )
            unknown_count += 1
        rows.append(row)

    evaluated_count = len(rows) - errors
    summary = {
        "protocol_version": WAVE_ENGINE_PROTOCOL_VERSION,
        "mode": "READ_ONLY_SHADOW",
        "group": group,
        "symbols_requested": len(watches),
        "evaluated": evaluated_count,
        "errors": errors,
        "unknown_primary": unknown_count,
        "unknown_primary_ratio": (unknown_count / len(rows)) if rows else None,
        "primary_family_counts": family_counts,
        "returns_accessed": False,
        "oos_accessed": False,
        "sheets_written": False,
        "status": "SUCCESS" if errors == 0 else "PARTIAL_DATA_QUALITY",
        "generated_at": now.isoformat(),
        "rows": rows,
    }
    _write_reports(Path(output_dir), summary)
    print("WAVE_SHADOW_SUMMARY " + json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["asia", "us", "all"], default="all")
    parser.add_argument("--output-dir", default="artifacts/wave_shadow")
    parser.add_argument("--daily-lookback", type=int, default=5)
    parser.add_argument("--weekly-lookback", type=int, default=5)
    args = parser.parse_args()
    summary = run_wave_shadow(
        args.group,
        args.output_dir,
        daily_swing_lookback=args.daily_lookback,
        weekly_swing_lookback=args.weekly_lookback,
    )
    raise SystemExit(1 if summary["errors"] else 0)


if __name__ == "__main__":
    main()
