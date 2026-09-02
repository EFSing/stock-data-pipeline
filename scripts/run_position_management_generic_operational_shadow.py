"""Run controlled synthetic Position Management / Exit validation."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from trading.position_management import (
    PositionAnchor,
    PositionOrigin,
    replay_position,
)
from trading.models import SwingKind


FIXTURE_VERSION = "POSITION-MANAGEMENT-GENERIC-OPERATIONAL-SHADOW-FIXTURE-2026-09-02-v1"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "position_management_generic_operational_shadow"


def _quote(day: date, opening: float, high: float, low: float, close: float, volume: float = 100.0) -> Quote:
    return Quote(
        symbol="SYNTH",
        name="Synthetic",
        market="US",
        trade_date=day,
        source="CONTROLLED_PUBLIC_SYNTHETIC_HOLDINGS_FIXTURE",
        open=opening,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=volume,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _anchor(name: str, kind: SwingKind, price: float, index: int, day: date) -> PositionAnchor:
    return PositionAnchor(
        name=name,
        kind=kind.value,
        price=price,
        pivot_index=index,
        pivot_date=day,
        confirmed_index=index,
        confirmed_date=day,
    )


def run_position_management_generic_operational_shadow(
    *, output_dir: str | Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    start = date(2026, 1, 1)
    origin = PositionOrigin(
        source_setup="SETUP_01",
        source_event_identity="SYNTH|SETUP_01|2026-01-01|CONFIRMED|lifecycle=1",
        symbol="SYNTH",
        market="US",
        entry_date=start,
        actual_entry=100.0,
        initial_execution_stop=90.0,
        initial_structural_invalidation=92.0,
        targets=(110.0, 120.0, 130.0),
        wave_anchors=(
            _anchor("LOW0", SwingKind.LOW, 80.0, 0, start),
            _anchor("HIGH1", SwingKind.HIGH, 95.0, 1, start + timedelta(days=1)),
            _anchor("LOW2", SwingKind.LOW, 90.0, 2, start + timedelta(days=2)),
        ),
        initial_risk_per_share=10.0,
    )
    quotes = [
        _quote(start, 100.0, 104.0, 99.0, 103.0),
        _quote(start + timedelta(days=1), 103.0, 111.0, 102.0, 108.0),
        _quote(start + timedelta(days=2), 108.0, 114.0, 107.0, 112.0),
    ]
    replay = replay_position(origin, quotes)
    checks = {
        "initial_r_frozen": origin.initial_risk_per_share == 10.0,
        "targets_do_not_auto_exit": replay.exit_reason is None,
        "target_tracking_reached": replay.days[-1].target_status.value == "T1_REACHED",
        "stop_never_moves_down": all(
            day.active_stop_next_session >= day.active_stop_at_open
            for day in replay.days
        ),
        "causal_day_count": replay.position_days == 3,
        "synthetic_only": True,
        "returns_accessed": False,
        "mfe_accessed": True,
        "mae_accessed": True,
        "pnl_accessed": False,
        "sheets_written": False,
        "broker_accessed": False,
    }
    correctness_checks = {
        key: value
        for key, value in checks.items()
        if key in {
            "initial_r_frozen",
            "targets_do_not_auto_exit",
            "target_tracking_reached",
            "stop_never_moves_down",
            "causal_day_count",
        }
    }
    document = {
        "protocol_version": "POSITION-MANAGEMENT-EXIT-2026-09-02-v1",
        "mode": "GENERIC_OPERATIONAL_SHADOW",
        "fixture_version": FIXTURE_VERSION,
        "fixture_source": "CONTROLLED_PUBLIC_SYNTHETIC_HOLDINGS_FIXTURE",
        "positions": 1,
        "position_days": replay.position_days,
        "checks": checks,
        "status": "SUCCESS" if all(correctness_checks.values()) else "FAILED",
    }
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "position_management_generic_operational_shadow.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "POSITION_MANAGEMENT_GENERIC_OPERATIONAL_SHADOW_SUMMARY "
        + json.dumps(document, ensure_ascii=False)
    )
    return document


def main() -> None:
    document = run_position_management_generic_operational_shadow()
    raise SystemExit(0 if document["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
