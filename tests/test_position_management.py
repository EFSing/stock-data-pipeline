from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Quote
from trading.models import SwingKind, SwingPoint
from trading.position_management import (
    PositionAction,
    PositionAnchor,
    PositionExitReason,
    PositionOrigin,
    PositionTarget,
    TargetReachStatus,
    position_origin_from_execution,
    position_replay_to_dict,
    replay_position,
)
from trading.setup01_decision import Setup01TargetCandidate, Setup01TargetProvenance
from trading.setup02_decision import Setup02TargetCandidate, Setup02TargetProvenance
from trading.wave5_context import Wave5ContextState, evaluate_wave5_context


def _quote(
    day: date,
    opening: float,
    high: float,
    low: float,
    close: float,
    *,
    volume: float | None = 100.0,
) -> Quote:
    return Quote(
        symbol="SYNTH",
        name="Synthetic",
        market="US",
        trade_date=day,
        source="SYNTHETIC",
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


def _swing(
    kind: SwingKind,
    price: float,
    index: int,
    day: date,
    *,
    confirmed: bool = True,
) -> SwingPoint:
    return SwingPoint(
        kind=kind,
        price=price,
        pivot_index=index,
        pivot_date=day,
        confirmed_index=index if confirmed else None,
        confirmed_date=day if confirmed else None,
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


def _origin(*, stop: float = 90.0, invalidation: float = 92.0) -> PositionOrigin:
    start = date(2026, 1, 1)
    return PositionOrigin(
        source_setup="SETUP_01",
        source_event_identity="SYNTH|SETUP_01|2026-01-01|CONFIRMED|lifecycle=1",
        symbol="SYNTH",
        market="US",
        entry_date=start,
        actual_entry=100.0,
        initial_execution_stop=stop,
        initial_structural_invalidation=invalidation,
        targets=tuple(_target(price) for price in (110.0, 120.0, 130.0)),
        wave_anchors=(
            _anchor("LOW0", SwingKind.LOW, 80.0, -2, start - timedelta(days=2)),
            _anchor("HIGH1", SwingKind.HIGH, 95.0, -1, start - timedelta(days=1)),
            _anchor("LOW2", SwingKind.LOW, 90.0, 0, start),
        ),
        initial_risk_per_share=100.0 - stop,
    )


def _target(
    price: float,
    *,
    sources: tuple[str, ...] = ("CONFIRMED_SWING_HIGH",),
) -> PositionTarget:
    source = "+".join(sorted(sources))
    provenance = tuple(
        Setup01TargetProvenance(source=item) for item in sorted(sources)
    )
    return PositionTarget(price=price, source=source, provenance=provenance)


class PositionManagementTests(unittest.TestCase):
    def test_origin_adapter_accepts_only_executed_and_copies_setup02_anchors(self):
        day = date(2026, 1, 2)
        event = SimpleNamespace(
            setup02=SimpleNamespace(
                continuation_low0=_swing(SwingKind.LOW, 80.0, 1, day),
                continuation_high1=_swing(SwingKind.HIGH, 95.0, 2, day),
                continuation_low2=_swing(SwingKind.LOW, 90.0, 3, day),
                continuation_high3=_swing(SwingKind.HIGH, 105.0, 4, day),
            )
        )
        decision = SimpleNamespace(
            execution_stop=90.0,
            structural_invalidation=92.0,
            target_candidates=(
                Setup02TargetCandidate(
                    price=110.0,
                    source="CONFIRMED_SWING_HIGH",
                    reason="synthetic confirmed swing",
                    provenance=(
                        Setup02TargetProvenance(
                            source="CONFIRMED_SWING_HIGH",
                            pivot_date=day,
                            confirmed_date=day,
                        ),
                    ),
                ),
                Setup02TargetCandidate(
                    price=120.0,
                    source="WAVE3_FIB_EXTENSION",
                    reason="synthetic Fib extension",
                    provenance=(
                        Setup02TargetProvenance(
                            source="WAVE3_FIB_EXTENSION",
                            extension_ratio=1.272,
                        ),
                    ),
                ),
                Setup02TargetCandidate(
                    price=130.0,
                    source="CONFIRMED_SWING_HIGH",
                    reason="synthetic confirmed swing",
                    provenance=(
                        Setup02TargetProvenance(
                            source="CONFIRMED_SWING_HIGH",
                            pivot_date=day,
                            confirmed_date=day,
                        ),
                    ),
                ),
            ),
            targets=(110.0, 120.0, 130.0),
        )
        executed = SimpleNamespace(
            outcome="EXECUTED",
            actual_entry=100.0,
            execution_date=day,
            event_identity="event-1",
            symbol="SYNTH",
            market="US",
        )
        origin = position_origin_from_execution("SETUP_02", event, decision, executed)
        self.assertIsNotNone(origin)
        assert origin is not None
        self.assertEqual(origin.initial_risk_per_share, 10.0)
        self.assertEqual([item.name for item in origin.wave_anchors], ["LOW0", "HIGH1", "LOW2", "HIGH3"])
        self.assertEqual(origin.target_prices, (110.0, 120.0, 130.0))
        self.assertEqual(origin.targets[0].source, "CONFIRMED_SWING_HIGH")
        self.assertEqual(origin.targets[1].source, "WAVE3_FIB_EXTENSION")
        self.assertEqual(origin.targets[1].provenance[0].extension_ratio, 1.272)
        self.assertIsNone(
            position_origin_from_execution(
                "SETUP_02", event, decision, replace_execution(executed, outcome="SKIP")
            )
        )

    def test_metrics_use_frozen_one_r_and_causal_daily_extremes(self):
        origin = _origin()
        start = origin.entry_date
        quotes = [
            _quote(start, 100.0, 105.0, 99.0, 104.0),
            _quote(start + timedelta(days=1), 104.0, 107.0, 100.0, 104.0),
        ]
        replay = replay_position(origin, quotes)
        day = replay.days[-1]
        self.assertAlmostEqual(day.current_r, 0.4)
        self.assertAlmostEqual(day.mfe_r, 0.7)
        self.assertAlmostEqual(day.mae_r, -0.1)
        self.assertAlmostEqual(day.mfe_drawdown_r, 0.3)
        self.assertEqual(origin.one_r, 10.0)

    def test_structural_stop_raises_only_from_confirmed_higher_low_and_next_session(self):
        origin = _origin()
        start = origin.entry_date
        higher_low = _swing(SwingKind.LOW, 96.0, 1, start + timedelta(days=1))
        quotes = [
            _quote(start, 100.0, 102.0, 99.0, 101.0),
            _quote(start + timedelta(days=1), 101.0, 103.0, 100.0, 102.0),
            _quote(start + timedelta(days=2), 102.0, 104.0, 101.0, 103.0),
        ]
        with patch("trading.position_management.find_swings", return_value=[higher_low]), patch(
            "trading.position_management.atr",
            side_effect=lambda values, period: [1.0] * len(values),
        ):
            replay = replay_position(origin, quotes)
        self.assertFalse(replay.days[0].stop_raised)
        self.assertTrue(replay.days[1].stop_raised)
        self.assertAlmostEqual(replay.days[1].active_stop_at_open, 90.0)
        self.assertAlmostEqual(replay.days[1].active_stop_next_session, 95.5)
        self.assertAlmostEqual(replay.days[2].active_stop_at_open, 95.5)

    def test_provisional_higher_low_cannot_raise_stop(self):
        origin = _origin()
        start = origin.entry_date
        provisional = _swing(
            SwingKind.LOW, 96.0, 1, start + timedelta(days=1), confirmed=False
        )
        quotes = [
            _quote(start, 100.0, 102.0, 99.0, 101.0),
            _quote(start + timedelta(days=1), 101.0, 103.0, 100.0, 102.0),
        ]
        with patch("trading.position_management.find_swings", return_value=[provisional]), patch(
            "trading.position_management.atr",
            side_effect=lambda values, period: [1.0] * len(values),
        ):
            replay = replay_position(origin, quotes)
        self.assertEqual(replay.stop_raise_count, 0)
        self.assertEqual(replay.final_active_stop, origin.initial_execution_stop)

    def test_stop_gap_and_intraday_touch_have_distinct_mechanical_exits(self):
        origin = _origin(stop=90.0)
        start = origin.entry_date
        gap = replay_position(
            origin,
            [_quote(start, 89.0, 101.0, 88.0, 100.0)],
        )
        self.assertEqual(gap.exit_reason, PositionExitReason.EXIT_GAP_BELOW_STOP)
        self.assertEqual(gap.exit_price, 89.0)

        touch = replay_position(
            _origin(stop=90.0),
            [_quote(start, 100.0, 105.0, 89.0, 104.0)],
        )
        self.assertEqual(touch.exit_reason, PositionExitReason.EXIT_STOP_TRIGGERED)
        self.assertEqual(touch.exit_price, 90.0)

    def test_mfe_two_r_activates_one_r_giveback_floor_next_session(self):
        origin = _origin()
        start = origin.entry_date
        quotes = [
            _quote(start, 100.0, 130.0, 99.0, 125.0),
            _quote(start + timedelta(days=1), 121.0, 124.0, 121.0, 123.0),
        ]
        replay = replay_position(origin, quotes)
        self.assertAlmostEqual(replay.days[0].mfe_floor or 0.0, 120.0)
        self.assertAlmostEqual(replay.days[0].active_stop_next_session, 120.0)
        self.assertAlmostEqual(replay.days[1].active_stop_at_open, 120.0)
        self.assertIsNone(replay.exit_reason)

    def test_mfe_floor_is_monotonic_after_first_activation(self):
        origin = _origin()
        start = origin.entry_date
        replay = replay_position(
            origin,
            [
                _quote(start, 100.0, 120.0, 99.0, 115.0),
                _quote(start + timedelta(days=1), 115.0, 119.0, 114.0, 114.0),
                _quote(start + timedelta(days=2), 114.0, 130.0, 113.0, 125.0),
                _quote(start + timedelta(days=3), 125.0, 131.0, 124.0, 128.0),
            ],
        )
        floors = [day.mfe_floor for day in replay.days]
        self.assertEqual(floors, [110.0, 110.0, 120.0, 121.0])
        self.assertTrue(
            all(
                later >= earlier
                for earlier, later in zip(floors, floors[1:])
            )
        )
        self.assertIsNone(replay.exit_reason)

    def test_close_below_mfe_floor_is_pending_until_next_open(self):
        origin = _origin()
        start = origin.entry_date
        replay = replay_position(
            origin,
            [
                _quote(start, 100.0, 130.0, 99.0, 115.0),
                _quote(start + timedelta(days=1), 116.0, 118.0, 115.0, 117.0),
            ],
        )
        self.assertEqual(replay.days[0].action, PositionAction.PROFIT_PROTECTION)
        self.assertIn(
            "PROFIT_PROTECTION_EXIT_PENDING", replay.days[0].secondary_reasons
        )
        self.assertEqual(len(replay.days), 2)
        self.assertEqual(replay.exit_reason, PositionExitReason.PROFIT_PROTECTION_EXIT_PENDING)
        self.assertEqual(replay.exit_price, 116.0)

    def test_structural_exit_is_pending_and_has_no_same_close_execution(self):
        origin = _origin(invalidation=95.0)
        start = origin.entry_date
        replay = replay_position(
            origin,
            [
                _quote(start, 100.0, 102.0, 99.0, 94.0),
                _quote(start + timedelta(days=1), 93.0, 96.0, 92.0, 94.0),
            ],
        )
        self.assertIsNone(replay.days[0].exit_price)
        self.assertEqual(replay.exit_reason, PositionExitReason.STRUCTURAL_EXIT_PENDING)
        self.assertEqual(replay.exit_price, 93.0)

    def test_targets_are_tracked_without_automatic_exit(self):
        origin = _origin()
        replay = replay_position(
            origin,
            [_quote(origin.entry_date, 100.0, 111.0, 99.0, 105.0)],
        )
        self.assertEqual(replay.days[0].target_status, TargetReachStatus.T1_REACHED)
        self.assertIsNone(replay.exit_reason)

    def test_confirmed_swing_target_is_not_mislabeled_as_fib(self):
        origin = _origin()
        replay = replay_position(
            origin,
            [_quote(origin.entry_date, 100.0, 111.0, 99.0, 105.0)],
        )
        flags = replay.days[0].risk_flags
        self.assertIn("CONFIRMED_SWING_TARGET_REACHED", flags)
        self.assertNotIn("FIB_TARGET_REACHED", flags)

    def test_fib_target_provenance_emits_fib_flag(self):
        origin = _origin()
        origin = PositionOrigin(
            **{
                **vars(origin),
                "targets": tuple(
                    _target(price, sources=("WAVE3_FIB_EXTENSION",))
                    for price in (110.0, 120.0, 130.0)
                ),
            }
        )
        replay = replay_position(
            origin,
            [_quote(origin.entry_date, 100.0, 111.0, 99.0, 105.0)],
        )
        flags = replay.days[0].risk_flags
        self.assertIn("FIB_TARGET_REACHED", flags)
        self.assertNotIn("CONFIRMED_SWING_TARGET_REACHED", flags)

    def test_dual_source_target_preserves_both_advisory_flags(self):
        origin = _origin()
        origin = PositionOrigin(
            **{
                **vars(origin),
                "targets": (
                    _target(
                        110.0,
                        sources=("CONFIRMED_SWING_HIGH", "WAVE3_FIB_EXTENSION"),
                    ),
                    *_origin().targets[1:],
                ),
            }
        )
        replay = replay_position(
            origin,
            [_quote(origin.entry_date, 100.0, 111.0, 99.0, 105.0)],
        )
        flags = replay.days[0].risk_flags
        self.assertIn("FIB_TARGET_REACHED", flags)
        self.assertIn("CONFIRMED_SWING_TARGET_REACHED", flags)

    def test_wave5_context_requires_confirmed_high3_low4_and_strict_break(self):
        start = date(2026, 1, 1)
        quotes = [
            _quote(start + timedelta(days=i), 100.0, 101.0, 99.0, close)
            for i, close in enumerate((108.0, 118.0, 119.0, 121.0))
        ]
        origin = _origin()
        new_high = _swing(SwingKind.HIGH, 120.0, 1, start + timedelta(days=1))
        low4 = _swing(SwingKind.LOW, 105.0, 2, start + timedelta(days=2))
        with patch("trading.wave5_context.find_swings", return_value=[new_high, low4]):
            pullback = evaluate_wave5_context(
                quotes=quotes,
                as_of_index=2,
                wave_anchors=origin.wave_anchors,
                structural_invalidation=92.0,
            )
            candidate = evaluate_wave5_context(
                quotes=quotes,
                as_of_index=3,
                wave_anchors=origin.wave_anchors,
                structural_invalidation=92.0,
            )
        self.assertEqual(pullback.state, Wave5ContextState.WAVE4_PULLBACK_CONTEXT)
        self.assertEqual(candidate.state, Wave5ContextState.WAVE5_CANDIDATE)
        self.assertEqual(candidate.low4.price, 105.0)

    def test_wave5_provisional_swing_is_not_context(self):
        start = date(2026, 1, 1)
        quotes = [_quote(start, 100.0, 101.0, 99.0, 100.0)]
        origin = _origin()
        provisional = _swing(SwingKind.LOW, 105.0, 0, start, confirmed=False)
        with patch("trading.wave5_context.find_swings", return_value=[provisional]):
            context = evaluate_wave5_context(
                quotes=quotes,
                as_of_index=0,
                wave_anchors=origin.wave_anchors,
                structural_invalidation=92.0,
            )
        self.assertEqual(context.state, Wave5ContextState.NO_WAVE5_CONTEXT)

    def test_wave5_candidate_is_no_add_and_never_a_new_entry(self):
        start = date(2026, 1, 1)
        origin = _origin()
        quotes = [
            _quote(start + timedelta(days=i), 100.0, 101.0, 99.0, close)
            for i, close in enumerate((101.0, 108.0, 109.0, 121.0))
        ]
        new_high = _swing(SwingKind.HIGH, 120.0, 1, start + timedelta(days=1))
        low4 = _swing(SwingKind.LOW, 105.0, 2, start + timedelta(days=2))
        with patch(
            "trading.position_management.find_swings", return_value=[new_high, low4]
        ):
            replay = replay_position(origin, quotes)
        self.assertEqual(replay.days[-1].action, PositionAction.NO_ADD)
        self.assertIn("WAVE5_CANDIDATE", replay.days[-1].risk_flags)

    def test_high_risk_flags_are_independent_advisories(self):
        origin = _origin()
        start = origin.entry_date
        quotes = [
            _quote(start + timedelta(days=i), 100.0, 101.0, 99.0, 100.0)
            for i in range(20)
        ]
        quotes.append(_quote(start + timedelta(days=20), 100.0, 110.0, 99.0, 101.0, volume=300.0))
        replay = replay_position(origin, quotes)
        flags = replay.days[-1].risk_flags
        self.assertIn("ABNORMAL_HIGH_VOLUME", flags)
        self.assertIn("PRICE_STALL", flags)
        self.assertIn("LONG_UPPER_WICK", flags)
        self.assertEqual(replay.days[-1].action, PositionAction.PROFIT_PROTECTION)
        self.assertIsNone(replay.exit_reason)

    def test_future_append_invariance_and_json_projection(self):
        origin = _origin()
        start = origin.entry_date
        short_quotes = [
            _quote(start, 100.0, 102.0, 99.0, 101.0),
            _quote(start + timedelta(days=1), 101.0, 103.0, 100.0, 102.0),
        ]
        appended = [*short_quotes, _quote(start + timedelta(days=2), 102.0, 104.0, 101.0, 103.0)]
        short = replay_position(origin, short_quotes)
        full = replay_position(origin, appended)
        self.assertEqual(short.days, full.days[: len(short.days)])
        json_ready = position_replay_to_dict(short)
        self.assertEqual(json_ready["initial_risk_per_share"], 10.0)
        self.assertIn("mfe_drawdown_r", json_ready["days"][0])


def replace_execution(execution: object, **changes: object) -> SimpleNamespace:
    values = vars(execution).copy()
    values.update(changes)
    return SimpleNamespace(**values)


if __name__ == "__main__":
    unittest.main()
