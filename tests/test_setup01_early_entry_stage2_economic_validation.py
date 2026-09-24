import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import unittest

from core import Quote
from research.development.setup01_early_entry_stage2_economic_validation_v1 import (
    DEFAULT_JSON_OUTPUT,
    PINNED_PROTOCOL_SHA256,
    PROTOCOL_PATH,
    OUTCOME_INSUFFICIENT,
    _mean_net_r,
)
from research.development.setup01_early_entry_stage2_engine import (
    CENSORED_AT_DATA_END,
    EXIT_GAP_BELOW_STOP,
    EXIT_LIFECYCLE_TERMINATED,
    EXIT_PRE_CONFIRMATION_TIMEOUT,
    EXIT_STOP_TRIGGERED,
    EXIT_TARGET_T1_REACHED,
    IDENTITY_A,
    IDENTITY_B,
    IDENTITY_C,
    IDENTITY_IDS,
    SCENARIO_BASELINE,
    SCENARIO_STRESS,
    TIMEOUT_SESSIONS,
    TradeGeometry,
    active_targets_for_session,
    buy_cost_per_share,
    cn_limit_price,
    limit_flags,
    sell_cost_per_share,
    simulate_trade,
    size_position,
)


def _quote(index: int, *, open_: float, high: float, low: float, close: float) -> Quote:
    return Quote(
        symbol="STAGE2.TEST",
        name="stage2 synthetic",
        market="US",
        trade_date=date(2021, 1, 1) + timedelta(days=index),
        source="test",
        open=open_,
        high=high,
        low=low,
        close=close,
        preclose=close,
        pct_change=None,
        volume=1_000_000.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _flat(index: int, price: float = 100.0) -> Quote:
    return _quote(index, open_=price, high=price + 0.5, low=price - 0.5, close=price)


def _geometry(
    *,
    entry_index: int = 2,
    entry_price: float = 100.0,
    stop: float = 94.0,
    structural_low: float = 95.0,
    initial_targets: tuple[float, ...] = (),
    confirmation_index: int | None = None,
    confirmation_targets: tuple[float, ...] = (),
    lifecycle_termination_index: int | None = None,
    manage_pre_confirmation: bool = True,
    identity: str = IDENTITY_C,
) -> TradeGeometry:
    return TradeGeometry(
        identity=identity,
        symbol="STAGE2.TEST",
        market="US",
        candidate_key="STAGE2.TEST|TEST",
        signal_date="2021-01-01",
        entry_index=entry_index,
        entry_date="2021-01-03",
        entry_price=entry_price,
        execution_stop=stop,
        one_r=entry_price - stop,
        structural_low=structural_low,
        initial_targets=initial_targets,
        confirmation_index=confirmation_index,
        confirmation_targets=confirmation_targets,
        lifecycle_termination_index=lifecycle_termination_index,
        manage_pre_confirmation=manage_pre_confirmation,
    )


class SizingTests(unittest.TestCase):
    def test_cn_lot_rounding_and_standardised_budget(self):
        sized = size_position("CN", 10.0, 9.0)
        self.assertIsNotNone(sized)
        self.assertEqual(sized.quantity, 5000.0)
        self.assertAlmostEqual(sized.risk_capital, 5000.0)
        self.assertAlmostEqual(sized.notional, 50000.0)

    def test_position_below_one_lot_is_not_executable(self):
        self.assertIsNone(size_position("CN", 1000.0, 900.0))

    def test_us_uses_single_share_granularity(self):
        sized = size_position("US", 100.0, 95.0)
        self.assertIsNotNone(sized)
        self.assertEqual(sized.quantity, 100.0)


class CostModelTests(unittest.TestCase):
    def test_cn_minimum_commission_binds_on_small_orders(self):
        quantity = 100.0
        cost = buy_cost_per_share("CN", 10.0, quantity, SCENARIO_BASELINE)
        self.assertAlmostEqual(cost, 5.0 / quantity + 10.0 * 10.0 / 10_000.0)

    def test_cn_commission_scales_above_the_minimum(self):
        quantity = 100_000.0
        cost = buy_cost_per_share("CN", 10.0, quantity, SCENARIO_BASELINE)
        self.assertAlmostEqual(cost, 10.0 * 2.5 / 10_000.0 + 10.0 * 10.0 / 10_000.0)

    def test_cn_stamp_duty_halves_from_the_registered_date(self):
        before = sell_cost_per_share("CN", 10.0, 100_000.0, "2023-08-25", SCENARIO_BASELINE)
        after = sell_cost_per_share("CN", 10.0, 100_000.0, "2023-08-28", SCENARIO_BASELINE)
        self.assertAlmostEqual(
            before - after,
            10.0 * 5.0 / 10_000.0,
        )

    def test_stress_scenario_adds_fifteen_basis_points_per_side(self):
        baseline = buy_cost_per_share("CN", 10.0, 100_000.0, SCENARIO_BASELINE)
        stress = buy_cost_per_share("CN", 10.0, 100_000.0, SCENARIO_STRESS)
        self.assertAlmostEqual(stress - baseline, 10.0 * 15.0 / 10_000.0)


class ExitPolicyTests(unittest.TestCase):
    def test_gap_below_the_stop_exits_at_the_open(self):
        quotes = [_flat(0), _flat(1), _quote(2, open_=93.0, high=93.5, low=92.0, close=92.5)]
        outcome = simulate_trade(_geometry(), quotes)
        self.assertEqual(outcome.exit_reason, EXIT_GAP_BELOW_STOP)
        self.assertAlmostEqual(outcome.exit_price, 93.0)
        self.assertEqual(outcome.exit_index, 2)

    def test_intraday_stop_touch_exits_at_the_stop_price(self):
        quotes = [_flat(0), _flat(1), _flat(2), _quote(3, open_=99.0, high=101.0, low=93.5, close=95.0)]
        outcome = simulate_trade(_geometry(), quotes)
        self.assertEqual(outcome.exit_reason, EXIT_STOP_TRIGGERED)
        self.assertAlmostEqual(outcome.exit_price, 94.0)
        self.assertEqual(outcome.exit_index, 3)

    def test_stop_takes_precedence_over_a_same_bar_target_touch(self):
        quotes = [
            _flat(0),
            _flat(1),
            _flat(2),
            _quote(3, open_=99.0, high=112.0, low=93.0, close=110.0),
        ]
        geometry = _geometry(initial_targets=(108.0,), manage_pre_confirmation=False)
        outcome = simulate_trade(geometry, quotes)
        self.assertEqual(outcome.exit_reason, EXIT_STOP_TRIGGERED)
        self.assertAlmostEqual(outcome.exit_price, 94.0)

    def test_target_exit_uses_t1_and_can_be_disabled(self):
        quotes = [
            _flat(0),
            _flat(1),
            _flat(2),
            _quote(3, open_=101.0, high=109.0, low=100.5, close=106.0),
            _quote(4, open_=106.0, high=107.0, low=105.0, close=106.5),
        ]
        geometry = _geometry(initial_targets=(108.0,), manage_pre_confirmation=False)
        outcome = simulate_trade(geometry, quotes)
        self.assertEqual(outcome.exit_reason, EXIT_TARGET_T1_REACHED)
        self.assertAlmostEqual(outcome.exit_price, 108.0)
        without_target = simulate_trade(geometry, quotes, target_exit_enabled=False)
        self.assertEqual(without_target.exit_reason, CENSORED_AT_DATA_END)
        self.assertTrue(without_target.censored)

    def test_confirmation_targets_are_active_only_after_the_confirmation_bar(self):
        geometry = _geometry(
            confirmation_index=4,
            confirmation_targets=(110.0,),
        )
        self.assertEqual(active_targets_for_session(geometry, 4), ())
        self.assertEqual(active_targets_for_session(geometry, 5), (110.0,))

    def test_pre_confirmation_targets_are_never_used(self):
        quotes = [
            _flat(0),
            _flat(1),
            _flat(2),
            _quote(3, open_=100.0, high=120.0, low=99.0, close=118.0),
        ] + [_flat(index, 118.0) for index in range(4, 30)]
        geometry = _geometry(
            confirmation_index=None,
            confirmation_targets=(110.0,),
        )
        outcome = simulate_trade(geometry, quotes)
        self.assertEqual(outcome.exit_reason, EXIT_PRE_CONFIRMATION_TIMEOUT)

    def test_waiting_bound_closes_at_the_next_session_open(self):
        quotes = [_flat(0), _flat(1)] + [
            _flat(index) for index in range(2, TIMEOUT_SESSIONS + 5)
        ]
        outcome = simulate_trade(_geometry(entry_index=2), quotes)
        self.assertEqual(outcome.exit_reason, EXIT_PRE_CONFIRMATION_TIMEOUT)
        self.assertEqual(outcome.exit_index, 2 + TIMEOUT_SESSIONS)
        self.assertAlmostEqual(outcome.exit_price, 100.0)

    def test_lifecycle_termination_forces_a_next_session_exit(self):
        quotes = [_flat(0), _flat(1), _flat(2), _flat(3), _flat(4), _flat(5)]
        geometry = _geometry(lifecycle_termination_index=3)
        outcome = simulate_trade(geometry, quotes)
        self.assertEqual(outcome.exit_reason, EXIT_LIFECYCLE_TERMINATED)
        self.assertEqual(outcome.exit_index, 4)

    def test_series_end_without_exit_is_right_censored(self):
        quotes = [_flat(0), _flat(1), _flat(2), _flat(3)]
        outcome = simulate_trade(_geometry(entry_index=2), quotes)
        self.assertTrue(outcome.censored)
        self.assertEqual(outcome.exit_reason, CENSORED_AT_DATA_END)
        self.assertEqual(outcome.exit_index, 3)

    def test_structural_invalidation_decides_on_the_next_open(self):
        quotes = [
            _flat(0),
            _flat(1),
            _flat(2),
            _quote(3, open_=99.0, high=99.5, low=95.5, close=94.5),
            _flat(4, 96.0),
        ]
        outcome = simulate_trade(_geometry(), quotes)
        self.assertEqual(outcome.exit_reason, "EXIT_STRUCTURAL_INVALIDATION")
        self.assertEqual(outcome.exit_index, 4)
        self.assertAlmostEqual(outcome.exit_price, 96.0)


class LimitFlagTests(unittest.TestCase):
    def test_cn_limit_price_rounds_to_two_decimals(self):
        self.assertAlmostEqual(cn_limit_price(10.0, up=True), 11.0)
        self.assertAlmostEqual(cn_limit_price(9.99, up=False), 8.99)

    def test_limit_flags_are_model_only_and_reported(self):
        flags = limit_flags(
            market="CN",
            symbol="600000.SH",
            entry_open=11.0,
            entry_preclose=10.0,
            exit_price=100.0,
            exit_preclose=100.0,
            limit_data_available=True,
        )
        self.assertIn("MODEL_ONLY_LIMIT_AT_ENTRY", flags)
        missing = limit_flags(
            market="CN",
            symbol="600000.SH",
            entry_open=11.0,
            entry_preclose=None,
            exit_price=10.0,
            exit_preclose=None,
            limit_data_available=False,
        )
        self.assertEqual(missing, ("LIMIT_DATA_UNAVAILABLE",))
        self.assertEqual(
            limit_flags(
                market="US",
                symbol="TEST",
                entry_open=1.0,
                entry_preclose=None,
                exit_price=1.0,
                exit_preclose=None,
                limit_data_available=False,
            ),
            (),
        )


class Stage2ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(DEFAULT_JSON_OUTPUT.read_text(encoding="utf-8"))
        cls.stage1 = json.loads(
            (
                PROTOCOL_PATH.parents[2]
                / "research"
                / "development"
                / "setup01_early_entry_independent_validation_v1.json"
            ).read_text(encoding="utf-8")
        )

    def test_protocol_hash_is_the_registered_one(self):
        raw = PROTOCOL_PATH.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(
            "sha256:" + hashlib.sha256(raw).hexdigest(), PINNED_PROTOCOL_SHA256
        )
        self.assertEqual(
            self.document["protocol"]["sha256"], PINNED_PROTOCOL_SHA256
        )
        self.assertEqual(
            self.document["protocol"]["selected_package"],
            "PKG_B_ATR_EXECUTION_STOP",
        )

    def test_denominator_and_funnels_match_the_frozen_sample(self):
        self.assertEqual(
            self.document["denominator"]["anchor_contexts"],
            self.stage1["cohort_construction"]["total_candidate_count"],
        )
        self.assertEqual(
            self.document["denominator"]["armed_signals"],
            self.stage1["policies"]["ARMED_HALF_RECOVERY"]["signaled_candidate_count"],
        )
        self.assertTrue(all(self.document["denominator"]["checks"].values()))
        for identity, funnel in self.document["funnels"]["primary_policy"].items():
            self.assertEqual(
                funnel["admitted"] + sum(funnel["skip_counts"].values()),
                funnel["eligible"],
                identity,
            )

    def test_controls_remain_research_only(self):
        controls = self.document["controls"]
        self.assertFalse(controls["portfolio_drawdown_estimated"])
        self.assertFalse(controls["broker_fills_claimed"])
        self.assertFalse(controls["final_oos_accessed"])
        self.assertFalse(controls["real_holdings_accessed"])
        self.assertFalse(controls["production_authorization"])
        self.assertEqual(controls["state_writes"], 0)
        self.assertEqual(controls["sheets_writes"], 0)
        self.assertEqual(controls["broker_orders"], 0)

    def test_registered_cost_scenarios_are_applied(self):
        scenarios = self.document["cost_model"]["scenarios"]
        self.assertEqual(scenarios["BASELINE"]["spread_slippage_bp_per_side"], 10.0)
        self.assertEqual(scenarios["STRESS"]["spread_slippage_bp_per_side"], 25.0)
        self.assertEqual(
            self.document["cost_model"]["CN"]["lot_size"], 100
        )
        self.assertEqual(self.document["cost_model"]["US"]["lot_size"], 1)
        self.assertEqual(
            self.document["cost_model"]["CN"]["transfer_fee_status"],
            "UNKNOWN_NOT_MODELED",
        )

    def test_identity_c_is_negative_in_both_markets_at_baseline(self):
        for market in ("CN", "US"):
            mean_net_r = self.document["results"]["primary_policy"]["per_market"][
                market
            ][IDENTITY_C]["net_r"]["mean"]
            self.assertIsNotNone(mean_net_r)
            self.assertLess(mean_net_r, 0.0, market)
        self.assertEqual(
            self.document["decision"]["absolute_net_r_negative_markets"], ["CN", "US"]
        )

    def test_incumbent_floor_failure_drives_the_classification(self):
        decision = self.document["decision"]
        self.assertEqual(decision["overall_classification"], OUTCOME_INSUFFICIENT)
        for market in ("CN", "US"):
            self.assertIn(
                "MIN_REALIZED_TRADES_A", decision["floors_failed"][market]
            )
            self.assertEqual(
                decision["per_market"][market]["realized_counts"][IDENTITY_C]
                > decision["per_market"][market]["realized_counts"][IDENTITY_B],
                True,
            )
        self.assertIn("rule_precedence_applied", decision)
        self.assertIn("censoring_caveat", decision)
        self.assertFalse(decision["supports_next_independent_execution_validation"])

    def test_bootstrap_intervals_match_the_reported_differences(self):
        intervals = self.document["decision"]["pooled_bootstrap_intervals_baseline"]
        vs_b = intervals[f"{IDENTITY_C}_minus_{IDENTITY_B}"]
        vs_a = intervals[f"{IDENTITY_C}_minus_{IDENTITY_A}"]
        self.assertGreater(vs_b["lower"], 0.0)
        self.assertLess(vs_a["lower"], 0.0)
        pooled = self.document["decision"]["pooled_baseline_differences"]
        self.assertAlmostEqual(
            pooled[f"{IDENTITY_C}_minus_{IDENTITY_B}"],
            self.document["results"]["primary_policy"]["combined"][IDENTITY_C]["net_r"][
                "mean"
            ]
            - self.document["results"]["primary_policy"]["combined"][IDENTITY_B]["net_r"][
                "mean"
            ],
            places=9,
        )

    def test_cost_stress_and_no_target_variant_are_reported(self):
        stress = self.document["results"]["primary_policy"]["stress_costs"]["combined"]
        baseline = self.document["results"]["primary_policy"]["combined"]
        for identity in IDENTITY_IDS:
            self.assertLess(
                stress[identity]["net_r"]["mean"], baseline[identity]["net_r"]["mean"]
            )
        secondary = self.document["results"]["secondary_policy_no_target_exit"]["combined"]
        self.assertLess(
            secondary[IDENTITY_C]["net_r"]["mean"], baseline[IDENTITY_C]["net_r"]["mean"]
        )

    def test_paired_subset_and_censoring_sensitivity_are_reported(self):
        paired = self.document["paired_subset"][
            f"{IDENTITY_C}_minus_{IDENTITY_B}"
        ]
        self.assertGreater(paired["paired_lifecycles"], 0)
        for identity in IDENTITY_IDS:
            block = self.document["results"]["primary_policy"]["combined"][identity][
                "including_censored_at_final_close"
            ]
            self.assertIn("sensitivity only", block["note"])


if __name__ == "__main__":
    unittest.main()
