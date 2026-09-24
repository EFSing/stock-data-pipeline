"""Read-only T-day geometry attribution on the existing frozen Development input."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from research.development_holdout_dataset import load_frozen_holdout
from research.development.system_signal_scarcity_audit_v1 import (
    _all_fail_gates,
    _build_structural_replays,
    _decision_first_fail,
    _geometry_for_event,
)
from trading.setup01_decision import evaluate_setup01_decision
from trading.setup02_decision import evaluate_setup02_decision


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "FROZEN_DEVELOPMENT_T1_ZONE_STOP_GEOMETRY_V1"
INPUT = ROOT / "artifacts/phase5j_v3_development_holdout/development_holdout_replay_input.jsonl.gz"
MANIFEST = ROOT / "research/development_holdout/dataset_manifest.json"
REPLAY_MANIFEST = ROOT / "research/development_holdout/replay_manifest.json"
OUTPUT_JSON = ROOT / "research/development/frozen_development_geometry_attribution_v1.json"
OUTPUT_MD = ROOT / "research/development/frozen_development_geometry_attribution_v1.md"
EXPECTED = {
    ("CN", "SETUP_01"): (299, 188, 86, 25, 0),
    ("CN", "SETUP_02"): (77, 44, 20, 8, 0),
    ("US", "SETUP_01"): (446, 276, 112, 53, 5),
    ("US", "SETUP_02"): (177, 87, 59, 14, 3),
}


def _value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _source(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (tuple, list, set)):
        return sorted(filter(None, (_value(item) for item in value)))
    return [_value(value)]


def decompose(record: dict[str, Any]) -> dict[str, float | None]:
    """Price-space identities only; no execution or forward bar is used."""
    p, u, t1 = (record.get(key) for key in ("planned_entry", "entry_zone_high", "t1"))
    invalidation, stop, atr = (
        record.get(key) for key in ("structural_invalidation", "execution_stop", "atr14")
    )
    zone_extension = p - u if p is not None and u is not None else None
    reward = t1 - p if t1 is not None and p is not None else None
    structure = p - invalidation if p is not None and invalidation is not None else None
    buffer = invalidation - stop if invalidation is not None and stop is not None else None
    risk = p - stop if p is not None and stop is not None else None
    return {
        "zone_extension": zone_extension,
        "target_space": reward,
        "target_space_pct": reward / p if reward is not None and p and p > 0 else None,
        "structural_distance": structure,
        "stop_buffer": buffer,
        "execution_risk": risk,
        "execution_risk_pct": risk / p if risk is not None and p and p > 0 else None,
        "target_space_atr": reward / atr if reward is not None and atr and atr > 0 else None,
        "execution_risk_atr": risk / atr if risk is not None and atr and atr > 0 else None,
        "t1_rr": reward / risk if reward is not None and risk and risk > 0 else None,
        "risk_identity_residual": risk - structure - buffer if None not in (risk, structure, buffer) else None,
    }


def _event_row(setup: str, event: Any, quotes: list[Any]) -> dict[str, Any]:
    # The single-event evaluators truncate quotes at T.  The shared audit
    # geometry uses the same causal prefix to expose gates skipped by the
    # incumbent's primary-gate order; neither call reads T+1 outcome.
    evaluate = evaluate_setup01_decision if setup == "SETUP_01" else evaluate_setup02_decision
    decision = evaluate(event, quotes, risk_capital=None)
    geometry = _geometry_for_event(setup, event, quotes)
    targets = geometry.targets
    candidate = next((item for item in geometry.target_candidates
                      if targets and float(item.price) == targets[0]), None)
    row = {
        "identity": str(decision.event_identity),
        "market": str(decision.market),
        "symbol": str(decision.symbol),
        "T": decision.trade_date.isoformat(),
        "setup": setup,
        "action": _value(decision.action),
        "primary_rejection": _decision_first_fail(decision),
        "all_fail": list(_all_fail_gates(decision, geometry)),
        "planned_entry": geometry.planned_entry,
        "entry_zone_low": geometry.entry_zone_low,
        "entry_zone_high": geometry.entry_zone_high,
        "t1": targets[0] if targets else None,
        "t1_source": _source(getattr(candidate, "source", None)),
        "structural_invalidation": geometry.structural_invalidation,
        "execution_stop": geometry.execution_stop,
        "atr14": geometry.atr14,
        "geometry_status": "CALCULABLE" if geometry.calculable else geometry.reason or "UNKNOWN",
    }
    row.update(decompose(row))
    row["all_rejections"] = [gate for gate in row["all_fail"]
                             if gate != "FORMAL_T1_CONFIRMED_SWING_HIGH"]
    row["unknown_fields"] = [
        key for key in ("planned_entry", "entry_zone_low", "entry_zone_high", "t1",
                        "structural_invalidation", "execution_stop", "atr14", "t1_rr")
        if row.get(key) is None
    ]
    if row["risk_identity_residual"] is not None and abs(row["risk_identity_residual"]) > 1e-8:
        raise AssertionError(f"stop-distance identity failed: {row['identity']}")
    return row


def _summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    primary = Counter(row["primary_rejection"] or "ENTRY_ALLOWED" for row in values)
    gates = Counter(gate for row in values for gate in row["all_fail"])
    pairs = Counter(
        "+".join(pair)
        for row in values for pair in combinations(sorted(set(row["all_fail"])), 2)
    )
    def middle(key: str) -> float | None:
        numbers = [row[key] for row in values if row.get(key) is not None]
        return median(numbers) if numbers else None
    return {
        "denominator": len(values),
        "entry_allowed": primary.get("ENTRY_ALLOWED", 0),
        "primary": dict(sorted(primary.items())),
        "all_fail": dict(sorted(gates.items())),
        "intersections": dict(sorted(pairs.items())),
        "geometry_complete": sum(not row["unknown_fields"] for row in values),
        "unknown_by_field": dict(sorted(Counter(field for row in values for field in row["unknown_fields"]).items())),
        "median_target_space_pct": middle("target_space_pct"),
        "median_execution_risk_pct": middle("execution_risk_pct"),
        "median_t1_rr": middle("t1_rr"),
    }


def build_attribution() -> dict[str, Any]:
    manifest, quotes_by_symbol, replay_manifest = load_frozen_holdout(MANIFEST, INPUT, REPLAY_MANIFEST)
    _, _, events01, events02 = _build_structural_replays(quotes_by_symbol)
    rows: list[dict[str, Any]] = []
    for setup, events in (("SETUP_01", events01), ("SETUP_02", events02)):
        for event in events:
            if _value(event.event_type) != "CONFIRMED":
                continue
            rows.append(_event_row(setup, event, quotes_by_symbol[event.symbol]))
    rows.sort(key=lambda row: (row["market"], row["setup"], row["T"], row["symbol"], row["identity"]))
    identities = [(row["setup"], row["identity"]) for row in rows]
    if len(rows) != 999 or len(set(identities)) != len(identities):
        raise AssertionError("first-confirmation denominator/identity changed")
    by_market_setup = {
        f"{market}/{setup}": _summary(row for row in rows if row["market"] == market and row["setup"] == setup)
        for market in ("CN", "US") for setup in ("SETUP_01", "SETUP_02")
    }
    for (market, setup), (total, above, upside, rr, allowed) in EXPECTED.items():
        actual = by_market_setup[f"{market}/{setup}"]
        if (actual["denominator"], actual["primary"].get("ABOVE_ENTRY_ZONE", 0),
            actual["primary"].get("TARGET_UPSIDE_BELOW_MINIMUM", 0),
            actual["primary"].get("RR_BELOW_MINIMUM", 0), actual["entry_allowed"]) != (total, above, upside, rr, allowed):
            raise AssertionError(f"frozen primary-gate audit mismatch: {market}/{setup}")
    overall = _summary(rows)
    if any(overall["all_fail"].get(gate) != expected for gate, expected in (
        ("ABOVE_ENTRY_ZONE", 595), ("TARGET_UPSIDE_BELOW_MINIMUM", 745), ("RR_BELOW_MINIMUM", 942)
    )):
        raise AssertionError("frozen all-fail audit mismatch")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_input_aggregate_sha256": replay_manifest.aggregate_hash,
        "clock": "T_CLOSE_ONLY",
        "forward_outcomes_read": False,
        "denominator": 999,
        "summary": overall,
        "by_market_setup": by_market_setup,
        "by_t1_source": {
            source: _summary(row for row in rows if source in row["t1_source"])
            for source in sorted({source for row in rows for source in row["t1_source"]})
        },
        "events": rows,
    }


def main() -> None:
    result = build_attribution()
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Frozen Development T-day geometry attribution", "",
             f"Protocol: `{PROTOCOL_VERSION}`. Common denominator: **{result['denominator']}** first CONFIRMED Decisions. No T+1 outcome was read.", "",
             "| Market / Setup | N | Entry allowed | Above zone | T1 upside <5% | T1 RR <2R | Complete geometry |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for key, item in result["by_market_setup"].items():
        p = item["primary"]
        lines.append(f"| {key} | {item['denominator']} | {item['entry_allowed']} | {p.get('ABOVE_ENTRY_ZONE',0)} | {p.get('TARGET_UPSIDE_BELOW_MINIMUM',0)} | {p.get('RR_BELOW_MINIMUM',0)} | {item['geometry_complete']} |")
    summary = result["summary"]
    lines += ["", "## Paired geometry on the common 999-event denominator", "",
              f"Calculable complete tuples: {summary['geometry_complete']}/999. Median gross T1 space: {summary['median_target_space_pct']:.4%}; median execution-risk distance: {summary['median_execution_risk_pct']:.4%}; median T1/R: {summary['median_t1_rr']:.3f}. Medians use available fields; missing events remain in the 999 denominator.", "",
              f"Unknown fields: `{json.dumps(summary['unknown_by_field'], sort_keys=True)}`.", "",
              "## Overlapping rejection conditions", "",
              f"Above zone and RR below minimum: {summary['intersections'].get('ABOVE_ENTRY_ZONE+RR_BELOW_MINIMUM', 0)}; upside below 5% and RR below 2R: {summary['intersections'].get('RR_BELOW_MINIMUM+TARGET_UPSIDE_BELOW_MINIMUM', 0)}. These intersections are events counted in both conditions, not additional rejected plans.", "",
              "The existing aggregate audit's `FORMAL_T1_CONFIRMED_SWING_HIGH` is a T1-source attribute, not a rejection; event rows retain it in `all_fail` only for exact audit reconciliation and expose actual `all_rejections` separately. Primary counts and all-market flags reconcile with the frozen scarcity audit. JSON contains all 999 T-day event rows plus market, Setup and T1-source summaries. Unknown fields remain null. Neither targets nor stops were changed.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"denominator": result["denominator"], "summary": result["summary"], "by_market_setup": result["by_market_setup"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
