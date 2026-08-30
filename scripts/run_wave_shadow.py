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

from core import latest_completed_market_session, ordinary_calendar_freshness_guard
from trading.models import WaveScenarioFamily
from trading.setup01 import (
    SETUP01_PROTOCOL_VERSION,
    evaluate_setup01,
    setup01_evaluation_to_dict,
)
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
    setup01 = row.get("SETUP_01", {})
    return {
        "统一代码": row.get("symbol", ""),
        "名称": row.get("name", ""),
        "市场": row.get("market", ""),
        "as_of_date": row.get("as_of_date", ""),
        "latest_completed_session": row.get("latest_completed_session", ""),
        "history_last_date": row.get("history_last_date", ""),
        "freshness_status": row.get("freshness_status", ""),
        "weekly_state": row.get("weekly_state", ""),
        "daily_state": row.get("daily_state", ""),
        "primary": row.get("primary", primary.get("family", "")),
        "alternate": row.get("alternate", alternate.get("family", "")),
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
        "SETUP_01_context": row.get(
            "SETUP_01_context", primary.get("setup01_context_eligible", False)
        ),
        "SETUP_02_context": row.get(
            "SETUP_02_context", primary.get("setup02_context_eligible", False)
        ),
        "SETUP_01_state": setup01.get("state", ""),
        "SETUP_01_as_of_date": setup01.get("as_of_date", ""),
        "SETUP_01_wave1_origin_price": setup01.get("wave1_origin_price", ""),
        "SETUP_01_wave1_origin_date": setup01.get("wave1_origin_date", ""),
        "SETUP_01_wave1_peak_price": setup01.get("wave1_peak_price", ""),
        "SETUP_01_wave1_peak_date": setup01.get("wave1_peak_date", ""),
        "SETUP_01_wave2_low_price": setup01.get("wave2_low_price", ""),
        "SETUP_01_wave2_low_date": setup01.get("wave2_low_date", ""),
        "SETUP_01_fib_retracement_ratio": setup01.get("fib_retracement_ratio", ""),
        "SETUP_01_fib_retracement_region": setup01.get("fib_retracement_region", ""),
        "SETUP_01_confirmation_level": setup01.get("confirmation_level", ""),
        "SETUP_01_structural_invalidation": setup01.get("structural_invalidation", ""),
        "SETUP_01_wave_scenario_invalidation": setup01.get("wave_scenario_invalidation", ""),
        "SETUP_01_reason": setup01.get("reason", ""),
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
    setup01_state_counts: dict[str, int] = {}
    unknown_count = 0
    for watch in watches:
        symbol = str(watch.get("统一代码") or "").strip()
        row_base = {
            "symbol": symbol,
            "name": str(watch.get("名称") or ""),
            "market": str(watch.get("市场") or ""),
        }
        source = str(watch.get("历史数据源") or "").strip()
        history_last_date: date | None = None
        latest_completed_session: date | None = None
        freshness_status = "DATA_STALE"
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
            history_last_date = max(quote.trade_date for quote in quotes)
            timezone_name = str(watch.get("时区") or "UTC")
            close_time = str(watch.get("收盘时间") or "23:59")
            latest_completed_session = latest_completed_market_session(
                timezone_name,
                close_time,
                now,
                quotes,
            )
            freshness_floor = ordinary_calendar_freshness_guard(
                timezone_name,
                close_time,
                now,
            )
            if latest_completed_session is None:
                raise ValueError(
                    "DATA_STALE: qfq历史没有有效的最新已完成市场交易日"
                )
            if history_last_date != latest_completed_session:
                raise ValueError(
                    "DATA_STALE: qfq history_last_date "
                    f"{history_last_date.isoformat()}未对齐最新已完成来源交易日"
                    f"{latest_completed_session.isoformat()}"
                )
            if latest_completed_session < freshness_floor:
                raise ValueError(
                    "DATA_STALE: qfq历史最新日期"
                    f"{history_last_date.isoformat()}早于普通日历freshness下限"
                    f"{freshness_floor.isoformat()}"
                )
            freshness_status = "FRESH"
            evaluation = evaluate_wave_scenario(
                quotes,
                as_of_date=latest_completed_session,
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
            setup01_evaluation = evaluate_setup01(
                quotes,
                as_of_date=latest_completed_session,
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
            setup01_row = setup01_evaluation_to_dict(setup01_evaluation)
            row = {
                **row_base,
                **evaluation_to_dict(evaluation),
                "latest_completed_session": latest_completed_session.isoformat(),
                "history_last_date": history_last_date.isoformat(),
                "freshness_status": freshness_status,
                "primary": evaluation.primary_scenario.family.value,
                "alternate": evaluation.alternate_scenario.family.value,
                "SETUP_01_context": evaluation.primary_scenario.setup01_context_eligible,
                "SETUP_02_context": evaluation.primary_scenario.setup02_context_eligible,
                "SETUP_01": setup01_row,
                "data_source": source,
                "error": "",
            }
            family = evaluation.primary_scenario.family.value
            family_counts[family] = family_counts.get(family, 0) + 1
            unknown_count += family in UNKNOWN_FAMILIES
            setup01_state = setup01_evaluation.state.value
            setup01_state_counts[setup01_state] = (
                setup01_state_counts.get(setup01_state, 0) + 1
            )
        except Exception as exc:
            errors += 1
            row = {
                **row_base,
                "protocol_version": WAVE_ENGINE_PROTOCOL_VERSION,
                "as_of_date": None,
                "latest_completed_session": (
                    latest_completed_session.isoformat()
                    if latest_completed_session is not None else None
                ),
                "freshness_status": freshness_status,
                "weekly_state": "UNKNOWN",
                "daily_state": "UNKNOWN",
                "primary": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                "alternate": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                "SETUP_01_context": False,
                "SETUP_02_context": False,
                "SETUP_01": {
                    "setup_type": "SETUP_01",
                    "protocol_version": SETUP01_PROTOCOL_VERSION,
                    "state": "NONE",
                    "as_of_date": None,
                    "wave1_origin_price": None,
                    "wave1_origin_date": None,
                    "wave1_origin_confirmed_date": None,
                    "wave1_peak_price": None,
                    "wave1_peak_date": None,
                    "wave1_peak_confirmed_date": None,
                    "wave2_low_price": None,
                    "wave2_low_date": None,
                    "wave2_low_confirmed_date": None,
                    "fib_retracement_ratio": None,
                    "fib_retracement_region": None,
                    "confirmation_level": None,
                    "structural_invalidation": None,
                    "wave_scenario_invalidation": None,
                    "state_entered_index": None,
                    "state_entered_date": None,
                    "confirmed_index": None,
                    "confirmed_date": None,
                    "failed_index": None,
                    "failed_date": None,
                    "primary_wave_scenario": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                    "alternate_wave_scenario": WaveScenarioFamily.NO_VALID_SCENARIO.value,
                    "reason": "shadow history could not be evaluated",
                    "diagnostics": [],
                    "lifecycle_index": None,
                    "wave1_origin": None,
                    "wave1_peak": None,
                    "wave2_low": None,
                },
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
                "history_last_date": (
                    history_last_date.isoformat()
                    if history_last_date is not None else None
                ),
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
        "setup01_state_counts": setup01_state_counts,
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
