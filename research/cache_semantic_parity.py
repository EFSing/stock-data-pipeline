"""One-time strict-prefix versus cached replay semantic parity audit.

The strict side deliberately uses only ``quotes[:index + 1]`` and the normal
Wave Engine call.  The cached side uses the current SETUP evaluator path and
the private Wave Engine cache arguments.  This module is an audit helper, not
a trading protocol or a source of production decisions.
"""
from __future__ import annotations

from hashlib import sha256
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

from core import Quote
from research.development_dataset import DATASET_MANIFEST_PATH, load_frozen_dataset
from trading.models import Setup01Evaluation, WaveScenarioEvaluation
from trading.setup01 import evaluate_setup01_history, setup01_evaluation_to_dict
from trading.setup01_replay import setup01_event_identity
from trading.setup02 import (
    Setup02Evaluation,
    evaluate_setup02_history,
    setup02_evaluation_to_dict,
)
from trading.setup02_replay import setup02_event_identity
from trading.wave import evaluation_to_dict


CACHE_PARITY_AUDIT_VERSION = (
    "FROZEN-REPLAY-CACHE-SEMANTIC-PARITY-AUDIT-2026-09-02-v1"
)


def _canonical_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


class _CanonicalDigest:
    """Incremental digest for a deterministic JSON list of rows."""

    def __init__(self) -> None:
        self._hash = sha256(b"[")
        self._first = True

    def extend(self, rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            if not self._first:
                self._hash.update(b",")
            self._hash.update(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self._first = False

    def hexdigest(self) -> str:
        result = self._hash.copy()
        result.update(b"]")
        return "sha256:" + result.hexdigest()


def _first_difference(
    reference: Any,
    cached: Any,
    path: str = "",
) -> tuple[str, Any, Any] | None:
    if type(reference) is not type(cached):
        return path or "$", reference, cached
    if isinstance(reference, Mapping):
        reference_keys = sorted(reference)
        cached_keys = sorted(cached)
        if reference_keys != cached_keys:
            return (path + ".keys" if path else "$.keys", reference_keys, cached_keys)
        for key in reference_keys:
            difference = _first_difference(
                reference[key], cached[key], f"{path}.{key}" if path else str(key)
            )
            if difference is not None:
                return difference
        return None
    if isinstance(reference, (list, tuple)):
        if len(reference) != len(cached):
            return (path + ".length" if path else "$.length", len(reference), len(cached))
        for index, (reference_item, cached_item) in enumerate(zip(reference, cached)):
            difference = _first_difference(
                reference_item,
                cached_item,
                f"{path}[{index}]" if path else f"[{index}]",
            )
            if difference is not None:
                return difference
        return None
    if reference != cached:
        return path or "$", reference, cached
    return None


def _compare_rows(
    label: str,
    reference_rows: Sequence[Mapping[str, Any]],
    cached_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if len(reference_rows) != len(cached_rows):
        index = min(len(reference_rows), len(cached_rows))
        reference_row = reference_rows[index] if index < len(reference_rows) else None
        cached_row = cached_rows[index] if index < len(cached_rows) else None
        return {
            "dataset": label,
            "row_index": index,
            "symbol": (reference_row or cached_row or {}).get("symbol"),
            "trade_date": (reference_row or cached_row or {}).get("trade_date"),
            "field": "row_count",
            "reference": len(reference_rows),
            "cached": len(cached_rows),
        }
    for index, (reference_row, cached_row) in enumerate(
        zip(reference_rows, cached_rows)
    ):
        difference = _first_difference(reference_row, cached_row)
        if difference is not None:
            field, reference_value, cached_value = difference
            return {
                "dataset": label,
                "row_index": index,
                "symbol": reference_row.get("symbol", cached_row.get("symbol")),
                "trade_date": reference_row.get(
                    "trade_date", cached_row.get("trade_date")
                ),
                "field": field,
                "reference": reference_value,
                "cached": cached_value,
            }
    return None


def _run_setup_with_wave_capture(
    module_name: str,
    evaluator: Callable[..., tuple[Any, ...]],
    quotes: list[Quote],
    *,
    use_cache: bool,
    daily_swing_lookback: int,
    weekly_swing_lookback: int,
) -> tuple[tuple[Any, ...], tuple[WaveScenarioEvaluation, ...]]:
    """Run one setup evaluator while capturing its exact Wave evaluations."""
    module = importlib.import_module(module_name)
    captured: list[WaveScenarioEvaluation] = []
    original = module.evaluate_wave_scenario

    def capture(*args: Any, **kwargs: Any) -> WaveScenarioEvaluation:
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    with patch.object(module, "evaluate_wave_scenario", capture):
        snapshots = evaluator(
            quotes,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
            _use_cache=use_cache,
        )
    return tuple(snapshots), tuple(captured)


def _wave_rows(
    quotes: Sequence[Quote], evaluations: Sequence[WaveScenarioEvaluation]
) -> list[dict[str, Any]]:
    return [
        {
            "symbol": quote.symbol,
            "market": quote.market,
            "trade_date": quote.trade_date.isoformat(),
            "projection": evaluation_to_dict(evaluation),
        }
        for quote, evaluation in zip(quotes, evaluations)
    ]


def _setup_rows(
    quotes: Sequence[Quote],
    snapshots: Sequence[Setup01Evaluation | Setup02Evaluation],
    serializer: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "symbol": quote.symbol,
            "market": quote.market,
            "trade_date": quote.trade_date.isoformat(),
            "snapshot": serializer(snapshot),
        }
        for quote, snapshot in zip(quotes, snapshots)
    ]


def _event_rows(
    setup_name: str,
    quotes: Sequence[Quote],
    snapshots: Sequence[Setup01Evaluation | Setup02Evaluation],
) -> list[dict[str, Any]]:
    if setup_name == "SETUP_01":
        serializer = setup01_evaluation_to_dict
        identity = setup01_event_identity
    else:
        serializer = setup02_evaluation_to_dict
        identity = setup02_event_identity

    rows: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    for quote, snapshot in zip(quotes, snapshots):
        confirmed = snapshot.is_new_confirmed_event_as_of
        failed = snapshot.is_new_failed_event_as_of
        if not confirmed and not failed:
            continue
        event_type = snapshot.state
        event_id = identity(
            quote.symbol,
            quote.trade_date,
            event_type,
            snapshot.lifecycle_index,
        )
        if event_id in event_ids:
            continue
        event_ids.add(event_id)
        rows.append(
            {
                "event_identity": event_id,
                "symbol": quote.symbol,
                "market": quote.market,
                "trade_date": quote.trade_date.isoformat(),
                "event_type": event_type.value,
                "snapshot": serializer(snapshot),
            }
        )
    return rows


def build_cache_semantic_parity_audit(
    *,
    manifest_path: str | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> dict[str, Any]:
    """Compare strict reference and cached semantics over every frozen bar."""
    manifest, quotes_by_symbol = load_frozen_dataset(
        Path(manifest_path) if manifest_path is not None else DATASET_MANIFEST_PATH
    )
    counts = {
        "symbols": len(quotes_by_symbol),
        "bars": sum(len(quotes) for quotes in quotes_by_symbol.values()),
    }
    digest_names = (
        "strict_wave",
        "cached_wave",
        "strict_setup01_snapshots",
        "cached_setup01_snapshots",
        "strict_setup02_snapshots",
        "cached_setup02_snapshots",
        "strict_setup01_events",
        "cached_setup01_events",
        "strict_setup02_events",
        "cached_setup02_events",
    )
    digesters = {name: _CanonicalDigest() for name in digest_names}
    mismatches: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}

    for symbol in sorted(quotes_by_symbol):
        quotes = list(quotes_by_symbol[symbol])
        strict_setup01, strict_waves = _run_setup_with_wave_capture(
            "trading.setup01",
            evaluate_setup01_history,
            quotes,
            use_cache=False,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
        )
        cached_setup01, cached_waves = _run_setup_with_wave_capture(
            "trading.setup01",
            evaluate_setup01_history,
            quotes,
            use_cache=True,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
        )
        strict_setup02, _ = _run_setup_with_wave_capture(
            "trading.setup02",
            evaluate_setup02_history,
            quotes,
            use_cache=False,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
        )
        cached_setup02, _ = _run_setup_with_wave_capture(
            "trading.setup02",
            evaluate_setup02_history,
            quotes,
            use_cache=True,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
        )

        strict_wave_rows = _wave_rows(quotes, strict_waves)
        cached_wave_rows = _wave_rows(quotes, cached_waves)
        strict_setup01_rows = _setup_rows(
            quotes, strict_setup01, setup01_evaluation_to_dict
        )
        cached_setup01_rows = _setup_rows(
            quotes, cached_setup01, setup01_evaluation_to_dict
        )
        strict_setup02_rows = _setup_rows(
            quotes, strict_setup02, setup02_evaluation_to_dict
        )
        cached_setup02_rows = _setup_rows(
            quotes, cached_setup02, setup02_evaluation_to_dict
        )
        strict_setup01_event_rows = _event_rows("SETUP_01", quotes, strict_setup01)
        cached_setup01_event_rows = _event_rows("SETUP_01", quotes, cached_setup01)
        strict_setup02_event_rows = _event_rows("SETUP_02", quotes, strict_setup02)
        cached_setup02_event_rows = _event_rows("SETUP_02", quotes, cached_setup02)

        paired = {
            "wave": (strict_wave_rows, cached_wave_rows),
            "setup01_snapshots": (strict_setup01_rows, cached_setup01_rows),
            "setup02_snapshots": (strict_setup02_rows, cached_setup02_rows),
            "setup01_events": (strict_setup01_event_rows, cached_setup01_event_rows),
            "setup02_events": (strict_setup02_event_rows, cached_setup02_event_rows),
        }
        for name, (reference_rows, cached_rows) in paired.items():
            strict_key = f"strict_{name}"
            cached_key = f"cached_{name}"
            digesters[strict_key].extend(reference_rows)
            digesters[cached_key].extend(cached_rows)
            row_counts[strict_key] = row_counts.get(strict_key, 0) + len(reference_rows)
            row_counts[cached_key] = row_counts.get(cached_key, 0) + len(cached_rows)
            if not mismatches:
                mismatch = _compare_rows(name, reference_rows, cached_rows)
                if mismatch is not None:
                    mismatch["symbol"] = symbol
                    mismatches.append(mismatch)

    digests = {name: digester.hexdigest() for name, digester in digesters.items()}
    parity_confirmed = not mismatches
    return {
        "audit_version": CACHE_PARITY_AUDIT_VERSION,
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "counts": counts,
        "row_counts": row_counts,
        "digests": digests,
        "first_mismatch": mismatches[0] if mismatches else None,
        "strict_cached_semantic_parity": parity_confirmed,
        "status": "SUCCESS" if parity_confirmed else "FAILED",
    }


__all__ = [
    "CACHE_PARITY_AUDIT_VERSION",
    "build_cache_semantic_parity_audit",
]
