"""First-stage independent-sample validation of the pre-defined SETUP_01 ARMED entry.

The experimental group is fixed by
``SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1``: the existing production
SETUP_01 ARMED milestone used as an entry trigger, compared with the incumbent
first-``close > H1`` CONFIRMED entry.  The cohort is rebuilt from every causal
Wave2 anchor context of the frozen independent sample, including FAILED,
never-CONFIRMED, screened-out and right-censored lifecycles.

This module reads no Final OOS, no production state, no Paper ledger, no broker
and no real holdings.  Future bars are used only after a signal is fixed, for
the descriptive evaluation required by the protocol.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development.pre_confirmation_early_entry_causal_research_v1 import (
    EVENTUAL_STATUSES,
    INCUMBENT_POLICY,
    RESOLUTIONS,
    CandidateLifecycle,
    PolicySignal,
    _cohort_composition,
    _paired_headroom,
    _percentile,
    _rate,
    _robustness,
    build_causal_cohort,
    evaluate_policy_signals,
    summarize_policy,
)
from research.development.setup01_early_entry_independent_validation_dataset import (
    DATASET_MANIFEST_PATH,
    DATASET_VERSION,
    FROZEN_INPUT_PATH,
    load_validation_sample,
)
from research.market_sessions import build_market_session_dates
from trading.setup01 import SETUP01_RECOVERY_RATIO


PROTOCOL_VERSION = "SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1"
PROTOCOL_PATH = (
    PROJECT_ROOT / "research" / "protocols" / "setup01_early_entry_independent_validation_v1.json"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT / "research" / "development" / "setup01_early_entry_independent_validation_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT / "research" / "development" / "setup01_early_entry_independent_validation_v1.md"
)
EXPERIMENTAL_POLICY = "ARMED_HALF_RECOVERY"
REGISTERED_GROUP_IDS = (EXPERIMENTAL_POLICY, INCUMBENT_POLICY)
MARKETS = ("CN", "US")
CLASSIFICATION_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
CLASSIFICATION_SUPPORTED = "FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION"
CLASSIFICATION_NOT_SUPPORTED = "FIRST_STAGE_NOT_SUPPORTED"


def _sha256_file(path: Path, *, normalize_lf: bool = False) -> str:
    payload = path.read_bytes()
    if normalize_lf:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _source_artifact(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": f"sha256:{_sha256_file(path)}",
    }


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if _finite(value) is not None]
    return {
        "n": len(clean),
        "p10": _percentile(clean, 0.10),
        "p25": _percentile(clean, 0.25),
        "median": _percentile(clean, 0.50),
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
    }


def exact_sign_test_p_value(positive: int, negative: int) -> float:
    """Exact two-sided binomial sign test with p = 0.5 and ties excluded."""
    trials = positive + negative
    if trials == 0:
        return 1.0
    tail = sum(math.comb(trials, index) for index in range(max(positive, negative), trials + 1))
    return min(1.0, 2.0 * tail / float(2**trials))


def paired_evidence(
    candidates: Sequence[CandidateLifecycle],
    early_signals: Sequence[PolicySignal],
    incumbent_signals: Sequence[PolicySignal],
) -> dict[str, Any]:
    """Pair the experimental and incumbent entries on the same lifecycle."""
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    incumbent_by_key = {signal.candidate_key: signal for signal in incumbent_signals}
    rows: list[dict[str, Any]] = []
    missing_incumbent = 0
    for signal in early_signals:
        incumbent = incumbent_by_key.get(signal.candidate_key)
        if incumbent is None:
            missing_incumbent += 1
            continue
        if signal.entry_index is None or incumbent.entry_index is None:
            continue
        candidate = candidate_by_key[signal.candidate_key]
        if signal.entry_price is None or incumbent.entry_price is None:
            continue
        range_R = candidate.wave1_range_R
        gain = (float(incumbent.entry_price) - float(signal.entry_price)) / range_R
        if gain > 0:
            sign = 1
        elif gain < 0:
            sign = -1
        else:
            sign = 0
        rows.append(
            {
                "candidate_key": signal.candidate_key,
                "symbol": signal.symbol,
                "market": signal.market,
                "signal_date": signal.signal_date.isoformat(),
                "incumbent_signal_date": incumbent.signal_date.isoformat(),
                "early_entry_date": signal.entry_date.isoformat() if signal.entry_date else None,
                "incumbent_entry_date": incumbent.entry_date.isoformat() if incumbent.entry_date else None,
                "early_entry_price": float(signal.entry_price),
                "incumbent_entry_price": float(incumbent.entry_price),
                "wave1_range_R": range_R,
                "gain_R": gain,
                "gain_sign": sign,
                "eventual_status": signal.eventual_status,
                "resolution": signal.resolution,
                "depth_band": candidate.depth_band,
                "time_half": candidate.time_half,
            }
        )
    gains = [row["gain_R"] for row in rows]
    positives = sum(row["gain_sign"] > 0 for row in rows)
    negatives = sum(row["gain_sign"] < 0 for row in rows)
    return {
        "paired_definition": "(incumbent exact next-session OPEN - early exact next-session OPEN) / Wave1 R",
        "paired_count": len(rows),
        "early_signals_without_incumbent_signal": missing_incumbent,
        "early_signals_without_executable_pair": len(early_signals) - len(rows) - missing_incumbent,
        "positive_gain_count": positives,
        "negative_gain_count": negatives,
        "tie_count": len(rows) - positives - negatives,
        "positive_gain_share": _rate(positives, positives + negatives),
        "sign_test": {
            "sides": 2,
            "p_value": exact_sign_test_p_value(positives, negatives),
            "trials": positives + negatives,
        },
        "gain_R": _distribution(gains),
        "later_confirmed_paired_count": sum(row["eventual_status"] == "LATER_CONFIRMED" for row in rows),
        "rows": rows,
    }


def _by_market(evidence: Mapping[str, Any], market: str) -> dict[str, Any]:
    rows = [row for row in evidence["rows"] if row["market"] == market]
    gains = [row["gain_R"] for row in rows]
    positives = sum(row["gain_sign"] > 0 for row in rows)
    negatives = sum(row["gain_sign"] < 0 for row in rows)
    return {
        "paired_count": len(rows),
        "later_confirmed_paired_count": sum(row["eventual_status"] == "LATER_CONFIRMED" for row in rows),
        "positive_gain_count": positives,
        "negative_gain_count": negatives,
        "tie_count": len(rows) - positives - negatives,
        "positive_gain_share": _rate(positives, positives + negatives),
        "sign_test_p_value": exact_sign_test_p_value(positives, negatives),
        "gain_R": _distribution(gains),
    }


def market_metrics(
    market: str,
    robustness_row: Mapping[str, Any],
    paired: Mapping[str, Any],
) -> dict[str, Any]:
    """Pre-registered per-market metrics on the common anchor-context denominator."""
    executable = int(robustness_row["actual_executable_next_session_entry_count"])
    signaled = int(robustness_row["signaled_candidate_count"])
    invalidation_first = int(robustness_row["structural_invalidation_before_confirmation"]["count"])
    later_confirmed = int(robustness_row["eventually_confirmed_count"])
    return {
        "market": market,
        "anchor_contexts": int(robustness_row["total_candidate_count"]),
        "signaled": signaled,
        "not_signaled": int(robustness_row["total_candidate_count"]) - signaled,
        "executable_early_signals": executable,
        "not_executable_early_signals": signaled - executable,
        "later_confirmed": later_confirmed,
        "failed": int(robustness_row["failed_count"]),
        "never_confirmed": int(robustness_row["never_confirmed_count"]),
        "structural_invalidation_first": invalidation_first,
        "later_confirmed_share_of_executable_signals": _rate(later_confirmed, executable),
        "structural_invalidation_share_of_executable_signals": _rate(invalidation_first, executable),
        "paired_later_confirmed_executable": paired["later_confirmed_paired_count"],
        "paired_count": paired["paired_count"],
        "paired_median_gain_R": paired["gain_R"]["median"],
        "paired_positive_gain_share": paired["positive_gain_share"],
        "paired_sign_test_p_value": paired["sign_test_p_value"],
        "adverse_excursion_until_resolution": robustness_row["adverse_excursion_until_resolution"],
        "censored_ambiguous": robustness_row.get("censored_ambiguous"),
    }


def classify_market(metrics: Mapping[str, Any], decision_rules: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the frozen floors and gates; never re-derive a threshold here."""
    floors = decision_rules["floors"]
    gates = decision_rules["gates"]
    failed_floors = []
    if metrics["anchor_contexts"] < floors["min_anchor_contexts_per_market"]:
        failed_floors.append("MIN_ANCHOR_CONTEXTS_PER_MARKET")
    if metrics["executable_early_signals"] < floors["min_executable_early_signals_per_market"]:
        failed_floors.append("MIN_EXECUTABLE_EARLY_SIGNALS_PER_MARKET")
    if metrics["paired_later_confirmed_executable"] < floors[
        "min_paired_later_confirmed_executable_per_market"
    ]:
        failed_floors.append("MIN_PAIRED_LATER_CONFIRMED_EXECUTABLE_PER_MARKET")
    if failed_floors:
        return {
            "classification": CLASSIFICATION_INSUFFICIENT,
            "failed_floors": failed_floors,
            "failed_gates": [],
        }
    gate_rules = gates["space_improvement"]
    median_gain = _finite(metrics["paired_median_gain_R"])
    p_value = _finite(metrics["paired_sign_test_p_value"])
    invalidation_share = _finite(metrics["structural_invalidation_share_of_executable_signals"])
    confirmed_share = _finite(metrics["later_confirmed_share_of_executable_signals"])
    failed_gates = []
    if (
        median_gain is None
        or median_gain <= gate_rules["median_min"]
        or p_value is None
        or p_value >= gate_rules["exact_sign_test"]["alpha"]
    ):
        failed_gates.append("SPACE_IMPROVEMENT")
    if invalidation_share is None or invalidation_share > gates["invalidation_control"][
        "structural_invalidation_share_of_executable_signals_max"
    ]:
        failed_gates.append("INVALIDATION_CONTROL")
    if confirmed_share is None or confirmed_share < gates["confirmation_control"][
        "later_confirmed_share_of_executable_signals_min"
    ]:
        failed_gates.append("CONFIRMATION_CONTROL")
    return {
        "classification": CLASSIFICATION_NOT_SUPPORTED if failed_gates else CLASSIFICATION_SUPPORTED,
        "failed_floors": [],
        "failed_gates": failed_gates,
    }


def validate_registered_pair(
    candidates: Sequence[CandidateLifecycle],
    signals_by_policy: Mapping[str, Sequence[PolicySignal]],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    """Causal invariants for exactly the two registered groups.

    The existing Development validator enumerates its five registered milestones;
    this stage deliberately computes only the single pre-registered experimental
    group and the incumbent, so the same causal invariants are asserted here for
    those two policies alone.
    """
    if tuple(signals_by_policy) != REGISTERED_GROUP_IDS:
        raise ValueError("only the registered experimental group and comparator may be evaluated")
    candidate_keys = [candidate.key for candidate in candidates]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise ValueError("causal cohort contains duplicate lifecycle identities")
    status_total = sum(
        sum(candidate.eventual_status == status for candidate in candidates)
        for status in EVENTUAL_STATUSES
    )
    resolution_total = sum(
        sum(candidate.resolution == resolution for candidate in candidates)
        for resolution in RESOLUTIONS
    )
    if status_total != len(candidates) or resolution_total != len(candidates):
        raise ValueError("causal cohort composition is not conserved")
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    for candidate in candidates:
        if not (
            candidate.ready_index <= candidate.first_observed_index
            and candidate.first_observed_index <= candidate.last_observed_index
            and candidate.last_observed_index < len(symbol_quotes[candidate.symbol])
        ):
            raise ValueError("candidate chronology is not causal")
        for observation in candidate.observations:
            if any(
                anchor.confirmed_index is None or anchor.confirmed_index > observation.index
                for anchor in (observation.origin, observation.peak, observation.wave2_low)
            ):
                raise ValueError("cohort observation uses a future/unconfirmed Swing")
    policy_validation: dict[str, Any] = {}
    for policy_id in REGISTERED_GROUP_IDS:
        signals = tuple(signals_by_policy[policy_id])
        if len({signal.candidate_key for signal in signals}) != len(signals):
            raise ValueError(f"duplicate signal identity for {policy_id}")
        for signal in signals:
            if signal.policy_id != policy_id:
                raise ValueError("signal policy identity changed")
            candidate = candidate_by_key.get(signal.candidate_key)
            if candidate is None:
                raise ValueError("policy signal is not in the causal cohort")
            if not candidate.geometry_valid:
                raise ValueError("invalid Wave2 geometry produced a policy signal")
            if signal.entry_index is not None:
                if signal.entry_index <= signal.signal_index:
                    raise ValueError("entry is not strictly next-session")
                entry_quote = symbol_quotes[signal.symbol][signal.entry_index]
                if signal.entry_date != entry_quote.trade_date or signal.entry_price != entry_quote.open:
                    raise ValueError("entry does not match exact next-session OPEN")
                sessions = tuple(market_session_dates[signal.market])
                if signal.entry_date != sessions[bisect_right(sessions, signal.signal_date)]:
                    raise ValueError("entry does not use the next frozen market session")
            if policy_id != INCUMBENT_POLICY:
                if candidate.ready_index > signal.signal_index:
                    raise ValueError("pre-confirmation signal used an unconfirmed anchor")
                if signal.confirmed_index is not None and signal.signal_index >= signal.confirmed_index:
                    raise ValueError("early policy signal is not pre-confirmation")
        policy_validation[policy_id] = {
            "signal_count": len(signals),
            "unique_candidate_signal_count": len(signals),
            "entry_index_strictly_after_signal": True,
            "early_signals_strictly_before_confirmation": policy_id == INCUMBENT_POLICY
            or all(
                signal.confirmed_index is None or signal.signal_index < signal.confirmed_index
                for signal in signals
            ),
        }
    return {
        "cohort_unique_lifecycle_count": len(candidates),
        "cohort_eventual_status_conserved": status_total == len(candidates),
        "cohort_resolution_conserved": resolution_total == len(candidates),
        "all_anchor_confirmed_as_of_observation": True,
        "preconfirmation_window_rows_retained_even_when_not_observed": True,
        "early_policy_signals_strictly_before_confirmation": all(
            policy_id == INCUMBENT_POLICY
            or all(
                signal.confirmed_index is None or signal.signal_index < signal.confirmed_index
                for signal in signals_by_policy[policy_id]
            )
            for policy_id in REGISTERED_GROUP_IDS
        ),
        "policy_ids_match_registered_pair": True,
        "signal_definition_uses_outcomes": False,
        "future_data_used_only_after_signal_for_evaluation": True,
        "exact_next_session_open_only": True,
        "policy_validation": policy_validation,
    }


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("independent validation protocol version changed")
    group = protocol.get("single_experimental_group", {})
    comparator = protocol.get("comparator", {})
    if group.get("policy_id") != EXPERIMENTAL_POLICY or comparator.get("policy_id") != INCUMBENT_POLICY:
        raise ValueError("registered experimental group or comparator changed")
    if group.get("production_equivalence") is None or group.get("no_extra_filter") is not True:
        raise ValueError("experimental group definition changed")
    if protocol.get("governance", {}).get("final_oos_accessed") is not False:
        raise ValueError("protocol must remain Final OOS-free")
    if protocol.get("governance", {}).get("protocol_frozen_before_signal_access") is not True:
        raise ValueError("protocol freeze control weakened")
    rules = protocol.get("decision_rules", {})
    if rules.get("overall_requires_all_markets_to_pass") is not True:
        raise ValueError("decision rule must require both markets")
    if sorted(rules.get("applied_per_market", ())) != sorted(MARKETS):
        raise ValueError("decision rule markets changed")
    forbidden = set(protocol.get("forbidden", ()))
    required = {
        "production rule change",
        "Final OOS",
        "parameter optimization or threshold sweep",
        "milestone search or new filter combinations",
        "broker, state write or Sheets mutation",
    }
    if not required.issubset(forbidden):
        raise ValueError("independent validation forbidden boundary changed")
    if protocol.get("sample", {}).get("dataset_version") != DATASET_VERSION:
        raise ValueError("sample dataset identity changed")


def run_validation(
    *,
    protocol_path: Path = PROTOCOL_PATH,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    frozen_input_path: Path = FROZEN_INPUT_PATH,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    _validate_protocol(protocol)
    if float(SETUP01_RECOVERY_RATIO) != 0.5:
        raise ValueError("the pre-defined SETUP_01 recovery milestone changed")
    manifest, symbol_quotes, replay_manifest = load_validation_sample(
        dataset_manifest_path=dataset_manifest_path,
        frozen_input_path=frozen_input_path,
    )
    market_session_dates = build_market_session_dates(symbol_quotes)
    candidates = build_causal_cohort(symbol_quotes)
    signals = {
        policy_id: evaluate_policy_signals(policy_id, candidates, symbol_quotes, market_session_dates)
        for policy_id in REGISTERED_GROUP_IDS
    }
    validation = validate_registered_pair(candidates, signals, symbol_quotes, market_session_dates)
    summaries = {
        policy_id: summarize_policy(
            policy_id, candidates, signals[policy_id], symbol_quotes, market_session_dates
        )
        for policy_id in REGISTERED_GROUP_IDS
    }
    robustness = {
        policy_id: _robustness(
            policy_id, candidates, signals[policy_id], symbol_quotes, market_session_dates
        )
        for policy_id in REGISTERED_GROUP_IDS
    }
    paired_all = paired_evidence(candidates, signals[EXPERIMENTAL_POLICY], signals[INCUMBENT_POLICY])
    paired_market = {market: _by_market(paired_all, market) for market in MARKETS}
    paired_headroom = _paired_headroom(
        EXPERIMENTAL_POLICY,
        candidates,
        signals[EXPERIMENTAL_POLICY],
        signals[INCUMBENT_POLICY],
        symbol_quotes,
    )
    metrics = {
        market: market_metrics(market, robustness[EXPERIMENTAL_POLICY]["CN_US"][market], paired_market[market])
        for market in MARKETS
    }
    decision_rules = protocol["decision_rules"]
    per_market_decision = {
        market: classify_market(metrics[market], decision_rules) for market in MARKETS
    }
    classifications = {market: value["classification"] for market, value in per_market_decision.items()}
    if any(value == CLASSIFICATION_INSUFFICIENT for value in classifications.values()):
        overall = CLASSIFICATION_INSUFFICIENT
    elif all(value == CLASSIFICATION_SUPPORTED for value in classifications.values()):
        overall = CLASSIFICATION_SUPPORTED
    else:
        overall = CLASSIFICATION_NOT_SUPPORTED
    cohort = _cohort_composition(candidates)
    diagnostics = {
        "protocol_thresholds_are_read_from_the_protocol_file": True,
        "post_hoc_rule_change": False,
        "experimental_group_single": len(REGISTERED_GROUP_IDS) == 2,
        "cohort_rebuilt_from_anchor_contexts": len(candidates) > cohort["eventually_confirmed_count"],
        "cohort_eventual_status_conserved": (
            cohort["eventually_confirmed_count"] + cohort["failed_count"] + cohort["never_confirmed_count"]
            == len(candidates)
        ),
        "signal_definition_uses_outcome": False,
        "same_bar_fill": False,
        "later_bar_substitution": False,
        "exact_next_session_open_only": validation.get("exact_next_session_open_only", True),
        "independent_symbol_roster": sorted(symbol_quotes) == sorted(
            item["canonical_symbol"] for item in manifest["symbols"]
        ),
        "final_oos_accessed": False,
        "real_holdings_accessed": False,
        "state_writes": 0,
        "sheets_writes": 0,
        "broker_orders": 0,
    }
    document: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "artifact_type": "SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION",
        "artifact_version": "v1",
        "status": overall,
        "source_artifacts": {
            "protocol": _source_artifact(protocol_path),
            "dataset_manifest": _source_artifact(dataset_manifest_path),
            "frozen_replay_input": _source_artifact(frozen_input_path),
            "dataset_version": manifest["dataset_version"],
            "replay_aggregate_hash": replay_manifest.aggregate_hash,
            "universe_manifest_sha256": manifest["universe"]["manifest_sha256"],
            "universe_symbol_list_sha256": manifest["universe"]["symbol_list_sha256"],
            "payload_recovery_check": manifest.get("recovery_check_vs_frozen_2026_08_29"),
        },
        "sample_coverage": {
            "symbols": manifest["aggregate_symbol_count"],
            "bars": manifest["aggregate_valid_bar_count"],
            "market_coverage": manifest["market_coverage"],
            "qc_exceptions": manifest["provider_qc_exceptions"],
            "date_window": manifest["provider_contract"]["CN"]["date_window"],
        },
        "cohort_construction": cohort,
        "fixed_comparison": {
            "experimental_group": EXPERIMENTAL_POLICY,
            "comparator": INCUMBENT_POLICY,
            "setup_scope": "SETUP_01 (Wave 2 -> Wave 3) Wave2 anchor contexts only",
            "entry": "exact next frozen market-session OPEN",
            "wave1_R": "H1 - LOW0",
        },
        "policies": summaries,
        "market_metrics": metrics,
        "paired_evidence": {
            "aggregate": {
                key: value for key, value in paired_all.items() if key != "rows"
            },
            "by_market": paired_market,
            "paired_headroom_vs_incumbent": paired_headroom,
        },
        "robustness": {
            policy_id: {
                "CN_US": robustness[policy_id]["CN_US"],
                "time_split_by_candidate_ready_date": robustness[policy_id][
                    "time_split_by_candidate_ready_date"
                ],
                "depth_bands": robustness[policy_id]["depth_bands"],
                "later_confirmed_vs_never_confirmed_failed": robustness[policy_id][
                    "later_confirmed_vs_never_confirmed_failed"
                ],
                "symbol_concentration": {
                    key: value
                    for key, value in robustness[policy_id]["symbol_concentration"].items()
                    if key != "signal_counts_by_symbol"
                },
            }
            for policy_id in REGISTERED_GROUP_IDS
        },
        "decision": {
            "overall_classification": overall,
            "per_market": per_market_decision,
            "criteria": {
                "floors": decision_rules["floors"],
                "gates": decision_rules["gates"],
            },
            "supports_second_stage_application": overall == CLASSIFICATION_SUPPORTED,
            "production_authorization": False,
            "reason": _decision_reason(overall, per_market_decision, metrics),
        },
        "diagnostics": diagnostics,
        "validation": validation,
        "controls": {
            "research_only": True,
            "production_strategy_unchanged": True,
            "final_oos_accessed": False,
            "real_holdings_accessed": False,
            "parameter_search": False,
            "threshold_sweep": False,
            "execution_cost_or_net_return_computed": False,
            "state_writes": 0,
            "sheets_writes": 0,
            "broker_orders": 0,
        },
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_output.write_text(render_markdown(document), encoding="utf-8")
    return document


def _decision_reason(
    overall: str,
    per_market: Mapping[str, Mapping[str, Any]],
    metrics: Mapping[str, Mapping[str, Any]],
) -> str:
    parts = []
    for market, decision in per_market.items():
        detail = metrics[market]
        parts.append(
            f"{market}: {decision['classification']} "
            f"(cohort {detail['anchor_contexts']}, executable early signals {detail['executable_early_signals']}, "
            f"paired later-CONFIRMED {detail['paired_later_confirmed_executable']}, "
            f"median paired gain {_render(detail['paired_median_gain_R'])} R, "
            f"sign-test p {_render(detail['paired_sign_test_p_value'], 4)}, "
            f"invalidation share {_render(detail['structural_invalidation_share_of_executable_signals'])}, "
            f"confirmed share {_render(detail['later_confirmed_share_of_executable_signals'])}; "
            f"failed floors {decision['failed_floors'] or 'none'}; "
            f"failed gates {decision['failed_gates'] or 'none'})"
        )
    tail = {
        CLASSIFICATION_SUPPORTED: "Both markets met the pre-registered space, invalidation and confirmation gates; this supports applying for a separate execution-cost/net-return stage and authorizes no production policy.",
        CLASSIFICATION_NOT_SUPPORTED: "At least one market failed a pre-registered gate on the independent sample; the first-stage question is not supported and no production policy is authorized.",
        CLASSIFICATION_INSUFFICIENT: "At least one market fell below the pre-registered sample floors; the evidence is insufficient and no conclusion about the milestone is drawn.",
    }[overall]
    return f"{tail} " + "; ".join(parts) + "."


def _render(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render_markdown(document: Mapping[str, Any]) -> str:
    coverage = document["sample_coverage"]
    cohort = document["cohort_construction"]
    metrics = document["market_metrics"]
    lines = [
        "# SETUP_01 earlier-entry independent validation V1 — first stage",
        "",
        "> Independent-sample research only. No production entry rule, confirmation, target, stop, RR, state, Sheets, or broker behavior is changed. No execution cost, net return, win rate or Final OOS is touched.",
        "",
        f"- Protocol: `{document['protocol_version']}`",
        f"- Status: `{document['status']}`",
        f"- Sample: `{document['source_artifacts']['dataset_version']}`",
        f"- Symbols / bars: `{coverage['symbols']}` / `{coverage['bars']}`",
        f"- Experimental group / comparator: `{document['fixed_comparison']['experimental_group']}` / `{document['fixed_comparison']['comparator']}`",
        "",
        "## Cohort and coverage",
        "",
        "| item | count |",
        "|---|---:|",
        f"| anchor contexts | {cohort['total_candidate_count']} |",
        f"| later CONFIRMED | {cohort['eventually_confirmed_count']} |",
        f"| FAILED | {cohort['failed_count']} |",
        f"| never CONFIRMED | {cohort['never_confirmed_count']} |",
        f"| screened out by the current system | {cohort['resolution']['SCREENED_OUT_BY_CURRENT_SYSTEM']} |",
        f"| timeout/unresolved at data end | {cohort['resolution']['TIMEOUT_UNRESOLVED_AT_DATA_END']} |",
        f"| invalid Wave2 geometry retained/screened | {cohort['geometry_validity']['invalid_wave2_geometry_count']} |",
        f"| CN / US symbols accepted | {coverage['market_coverage']['CN']['valid_accepted']} / {coverage['market_coverage']['US']['valid_accepted']} |",
        "",
        "## Common-denominator comparison",
        "",
        "| market | anchor contexts | early signaled | early executable | later CONFIRMED | FAILED | never CONFIRMED | invalidation share | confirmed share |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in MARKETS:
        detail = metrics[market]
        lines.append(
            f"| {market} | {detail['anchor_contexts']} | {detail['signaled']} | "
            f"{detail['executable_early_signals']} | {detail['later_confirmed']} | {detail['failed']} | "
            f"{detail['never_confirmed']} | "
            f"{_render(detail['structural_invalidation_share_of_executable_signals'])} | "
            f"{_render(detail['later_confirmed_share_of_executable_signals'])} |"
        )
    lines.extend(
        [
            "",
            "## Paired price space versus the incumbent",
            "",
            "Positive gain means the earlier entry obtained a lower exact next-session OPEN than the incumbent on the same lifecycle, normalized by Wave1 `R`.",
            "",
            "| market | paired | paired later CONFIRMED | positive share | median gain/R | sign-test p |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for market in MARKETS:
        detail = metrics[market]
        lines.append(
            f"| {market} | {detail['paired_count']} | {detail['paired_later_confirmed_executable']} | "
            f"{_render(detail['paired_positive_gain_share'])} | {_render(detail['paired_median_gain_R'])} | "
            f"{_render(detail['paired_sign_test_p_value'], 4)} |"
        )
    lines.extend(
        [
            "",
            "## Adverse excursion and censoring",
            "",
            "| market | adverse median/R | adverse P90/R | censored executable paths |",
            "|---|---:|---:|---:|",
        ]
    )
    for market in MARKETS:
        adverse = metrics[market]["adverse_excursion_until_resolution"]
        lines.append(
            f"| {market} | {_render(adverse['adverse_magnitude_R']['median'])} | "
            f"{_render(adverse['adverse_magnitude_R']['p90'])} | {adverse['censored_path_count']} |"
        )
    lines.extend(["", "## Pre-registered decision", ""])
    decision = document["decision"]
    lines.append(f"Overall: **{decision['overall_classification']}**")
    lines.append("")
    lines.append("| market | classification | failed floors | failed gates |")
    lines.append("|---|---|---|---|")
    for market, value in decision["per_market"].items():
        lines.append(
            f"| {market} | {value['classification']} | "
            f"{', '.join(value['failed_floors']) or '—'} | {', '.join(value['failed_gates']) or '—'} |"
        )
    lines.extend(
        [
            "",
            f"- Supports applying for a stage-2 execution-cost / net-return study: `{str(decision['supports_second_stage_application']).lower()}`",
            f"- Production authorization: `{str(decision['production_authorization']).lower()}`",
            "",
            decision["reason"],
            "",
            "## Boundaries",
            "",
            "- Independent sample by symbol and lifecycle; the calendar window matches the frozen Development window, so market-regime overlap is a disclosed limitation and not a controlled factor.",
            "- Coercion-free controls: no same-bar fill, no later-bar substitution, no symbol replacement, no provider switch after the roster freeze, no parameter or milestone search.",
            "- Not in scope: execution cost, net return, win rate, expectancy, portfolio allocation, new Stop/Target/Entry/5%/2R/position rules, Paper, production state, Sheets, broker and Final OOS.",
            "",
            "Status: "
            + {
                CLASSIFICATION_SUPPORTED: "`FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`",
                CLASSIFICATION_NOT_SUPPORTED: "`FIRST_STAGE_NOT_SUPPORTED`",
                CLASSIFICATION_INSUFFICIENT: "`INSUFFICIENT_EVIDENCE`",
            }[decision["overall_classification"]],
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--dataset-manifest", type=Path, default=DATASET_MANIFEST_PATH)
    parser.add_argument("--frozen-input", type=Path, default=FROZEN_INPUT_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    document = run_validation(
        protocol_path=args.protocol,
        dataset_manifest_path=args.dataset_manifest,
        frozen_input_path=args.frozen_input,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "cohort": document["cohort_construction"]["total_candidate_count"],
                "markets": {
                    market: {
                        "classification": document["decision"]["per_market"][market]["classification"],
                        "paired": document["market_metrics"][market]["paired_count"],
                        "median_gain_R": document["market_metrics"][market]["paired_median_gain_R"],
                    }
                    for market in MARKETS
                },
                "final_oos_accessed": document["controls"]["final_oos_accessed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
