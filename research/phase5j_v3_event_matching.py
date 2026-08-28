"""Frozen deterministic event matching for Phase 5J-v3.

This module is research-only.  It does not call SETUP_03, mutate production
parameters, or read outcome metrics.  Exact event identities are retained
first; only residual same-market/same-symbol events may be matched.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROTOCOL_PATH = Path(__file__).with_name("setup03_phase5j_v3_event_matching_protocol.json")
EXPECTED_PROTOCOL_VERSION = "SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1"
EXPECTED_PROTOCOL_SHA256 = "sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816"
MAX_MATCHING_DISTANCE = 40


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def protocol_integrity_hash(protocol: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(protocol))
    payload.pop("integrity", None)
    return f"sha256:{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _validate_protocol(protocol)
    return protocol


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != EXPECTED_PROTOCOL_VERSION:
        raise ValueError("Phase 5J-v3 protocol version changed")
    stored = protocol.get("integrity", {}).get("protocol_sha256")
    if stored != protocol_integrity_hash(protocol):
        raise ValueError("Phase 5J-v3 protocol integrity mismatch")
    if stored != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Phase 5J-v3 protocol version is bound to a different hash")
    if protocol.get("status") != "EVENT_MATCHING_PROTOCOL_FROZEN_NOT_EXECUTED":
        raise ValueError("Phase 5J-v3 protocol must remain frozen and unexecuted")
    identity = protocol.get("matching_identity", {})
    if identity.get("exact_identity") != ["market", "symbol", "confirmed_date"]:
        raise ValueError("Phase 5J-v3 event identity changed")
    window = protocol.get("matching_window", {})
    if window.get("max_distance") != MAX_MATCHING_DISTANCE or not window.get("inclusive"):
        raise ValueError("Phase 5J-v3 matching window changed")
    objective = protocol.get("matching_objective", {})
    if (
        objective.get("primary") != "maximum_cardinality"
        or objective.get("secondary") != "minimum_total_trading_session_distance"
        or objective.get("tertiary") != "lexicographically_smallest_pair_sequence"
    ):
        raise ValueError("Phase 5J-v3 matching objective changed")
    invariants = protocol.get("order_invariants", {})
    if not all(invariants.get(key) is True for key in ("order_preserving", "non_crossing", "matching_is_restricted_to_same_market_and_symbol")):
        raise ValueError("Phase 5J-v3 order invariant weakened")
    tie_break = protocol.get("deterministic_tie_break", {})
    if not tie_break.get("rule") or tie_break.get("cross_machine_output") != "same canonical JSON output for the same input":
        raise ValueError("Phase 5J-v3 deterministic tie-break changed")
    drift = protocol.get("drift_accounting", {})
    if (
        drift.get("drift_statistics_scope") != "合法 matched pairs only"
        or drift.get("unmatched_participates_in") != ["jaccard", "retention", "added", "disappeared"]
        or drift.get("unmatched_must_not_be_hidden_by_matching") is not True
    ):
        raise ValueError("Phase 5J-v3 unmatched accounting changed")
    bindings = protocol.get("frozen_qualification_bindings", {})
    if bindings.get("production_tolerance_candidates_pct") != [0.03, 0.04, 0.05]:
        raise ValueError("Phase 5J-v3 candidate tolerances changed")
    if bindings.get("stress_only_tolerances_pct") != [0.025, 0.055, 0.075, 0.1]:
        raise ValueError("Phase 5J-v3 stress tolerances changed")
    if bindings.get("setup_swing_lookback") != 5 or bindings.get("platform_window") != 40 or bindings.get("arm_proximity_pct") != 0.0:
        raise ValueError("Phase 5J-v3 setup bindings changed")
    if bindings.get("selection") != "LEXICOGRAPHIC_CONSERVATIVE" or bindings.get("selection_order_pct") != [0.03, 0.04, 0.05]:
        raise ValueError("Phase 5J-v3 selection binding changed")
    if bindings.get("market_qualification_is_independent") is not True or bindings.get("market_compensation_allowed") is not False:
        raise ValueError("Phase 5J-v3 market qualification binding changed")
    prohibited = protocol.get("prohibited_actions", [])
    required = {
        "modify SETUP_03 production logic",
        "add a tolerance candidate",
        "fit the matching window or tie-break to PR29 extreme pairs",
        "use returns, MFE, MAE, P&L, win rate, profit factor, or expectancy",
        "access Final OOS",
        "start formal Phase 5K-B1",
        "use IBKR",
        "switch provider or replace symbols based on SETUP_03 output",
    }
    if not required.issubset(set(prohibited)):
        raise ValueError("Phase 5J-v3 prohibited actions were weakened")


EventKey = tuple[str, str, date]


def _normalize_keys(keys: Iterable[EventKey]) -> tuple[EventKey, ...]:
    normalized = tuple(sorted((str(market), str(symbol), event_date) for market, symbol, event_date in keys))
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate event identity cannot be matched")
    return normalized


def _session_ordinals(
    keys: Iterable[EventKey],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[EventKey, int]:
    ordinals: dict[str, dict[date, int]] = {}
    for market, sessions in market_session_dates.items():
        ordered = tuple(sessions)
        if ordered != tuple(sorted(set(ordered))):
            raise ValueError(f"{market} session dates must be sorted and unique")
        ordinals[market] = {session_date: index for index, session_date in enumerate(ordered)}
    result: dict[EventKey, int] = {}
    for market, symbol, event_date in keys:
        if event_date not in ordinals.get(market, {}):
            raise ValueError(f"event date is not in {market} market session set: {event_date.isoformat()}")
        result[(market, symbol, event_date)] = ordinals[market][event_date]
    return result


def _better(
    first: tuple[int, int, tuple[tuple[int, int], ...]],
    second: tuple[int, int, tuple[tuple[int, int], ...]],
) -> tuple[int, int, tuple[tuple[int, int], ...]]:
    """Choose maximum cardinality, minimum cost, then lexicographically first."""
    if first[0] != second[0]:
        return first if first[0] > second[0] else second
    if first[1] != second[1]:
        return first if first[1] < second[1] else second
    return first if first[2] < second[2] else second


def _match_group(
    old: Sequence[tuple[date, int]],
    new: Sequence[tuple[date, int]],
) -> tuple[tuple[int, int], ...]:
    empty: tuple[int, int, tuple[tuple[int, int], ...]] = (0, 0, ())
    dp: list[list[tuple[int, int, tuple[tuple[int, int], ...]]]] = [
        [empty for _ in range(len(new) + 1)] for _ in range(len(old) + 1)
    ]
    for old_index in range(1, len(old) + 1):
        for new_index in range(1, len(new) + 1):
            best = _better(dp[old_index - 1][new_index], dp[old_index][new_index - 1])
            old_ordinal = old[old_index - 1][1]
            new_ordinal = new[new_index - 1][1]
            if abs(new_ordinal - old_ordinal) <= MAX_MATCHING_DISTANCE:
                prior = dp[old_index - 1][new_index - 1]
                matched = (
                    prior[0] + 1,
                    prior[1] + abs(new_ordinal - old_ordinal),
                    prior[2] + ((old_ordinal, new_ordinal),),
                )
                best = _better(best, matched)
            dp[old_index][new_index] = best
    return dp[-1][-1][2]


def match_event_identities(
    previous: Iterable[EventKey],
    current: Iterable[EventKey],
    *,
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    """Match residual event identities with the frozen v3 protocol."""
    protocol = load_protocol()
    if protocol["matching_window"]["max_distance"] != MAX_MATCHING_DISTANCE:
        raise ValueError("runtime matching window does not equal frozen protocol")
    old = _normalize_keys(previous)
    new = _normalize_keys(current)
    old_set, new_set = set(old), set(new)
    retained = sorted(old_set & new_set)
    disappeared = sorted(old_set - new_set)
    added = sorted(new_set - old_set)
    all_keys = tuple(old) + tuple(new)
    ordinals = _session_ordinals(all_keys, market_session_dates)

    old_groups: dict[tuple[str, str], list[tuple[date, int]]] = {}
    new_groups: dict[tuple[str, str], list[tuple[date, int]]] = {}
    for market, symbol, event_date in disappeared:
        old_groups.setdefault((market, symbol), []).append((event_date, ordinals[(market, symbol, event_date)]))
    for market, symbol, event_date in added:
        new_groups.setdefault((market, symbol), []).append((event_date, ordinals[(market, symbol, event_date)]))

    pairs: list[dict[str, Any]] = []
    matched_old: set[EventKey] = set()
    matched_new: set[EventKey] = set()
    for market, symbol in sorted(set(old_groups) | set(new_groups)):
        old_group = sorted(old_groups.get((market, symbol), ()), key=lambda item: (item[1], item[0]))
        new_group = sorted(new_groups.get((market, symbol), ()), key=lambda item: (item[1], item[0]))
        for old_index, new_index in _match_group(old_group, new_group):
            old_date, old_ordinal = old_group[next(index for index, item in enumerate(old_group) if item[1] == old_index)]
            new_date, new_ordinal = new_group[next(index for index, item in enumerate(new_group) if item[1] == new_index)]
            old_key = (market, symbol, old_date)
            new_key = (market, symbol, new_date)
            matched_old.add(old_key)
            matched_new.add(new_key)
            pairs.append({
                "market": market,
                "symbol": symbol,
                "old_date": old_date.isoformat(),
                "new_date": new_date.isoformat(),
                "old_session_ordinal": old_ordinal,
                "new_session_ordinal": new_ordinal,
                "trading_session_distance": abs(new_ordinal - old_ordinal),
            })

    pairs.sort(key=lambda pair: (pair["market"], pair["symbol"], pair["old_session_ordinal"], pair["new_session_ordinal"]))
    return {
        "previous_count": len(old),
        "current_count": len(new),
        "retained": [list(key[:2]) + [key[2].isoformat()] for key in retained],
        "added": [list(key[:2]) + [key[2].isoformat()] for key in added],
        "disappeared": [list(key[:2]) + [key[2].isoformat()] for key in disappeared],
        "matched_pairs": pairs,
        "unmatched_previous": [list(key[:2]) + [key[2].isoformat()] for key in disappeared if key not in matched_old],
        "unmatched_current": [list(key[:2]) + [key[2].isoformat()] for key in added if key not in matched_new],
    }


__all__ = ["EXPECTED_PROTOCOL_SHA256", "EXPECTED_PROTOCOL_VERSION", "MAX_MATCHING_DISTANCE", "load_protocol", "match_event_identities", "protocol_integrity_hash"]
