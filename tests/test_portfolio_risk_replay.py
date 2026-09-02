import unittest

from research.portfolio_risk_replay import build_portfolio_risk_replay


class PortfolioRiskReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_portfolio_risk_replay()

    def test_frozen_replay_is_successful_and_conservative(self):
        self.assertEqual(self.report["status"], "SUCCESS")
        self.assertEqual(self.report["symbols_requested"], 40)
        self.assertEqual(self.report["bars_observed"], 84284)
        self.assertEqual(self.report["individual_entry_allowed_count"], 8)
        self.assertEqual(self.report["portfolio_proposals"], 8)
        self.assertEqual(self.report["approved_count"], 8)
        self.assertEqual(self.report["released_count"], 5)
        self.assertEqual(self.report["executed_count"], 3)
        self.assertLessEqual(
            self.report["maximum_observed_total_open_risk_fraction"], 0.02
        )

    def test_frozen_upstream_invariance_and_ledger(self):
        self.assertTrue(self.report["upstream_invariance"]["all_upstream_invariants"])
        self.assertTrue(self.report["upstream_invariance"]["cache_semantic_parity"])
        conservation = self.report["conservation_exact_once"]
        self.assertTrue(conservation["exact_once_reservation_ids"])
        self.assertTrue(conservation["executed_positions_match_settled_executions"])
        self.assertEqual(
            conservation["portfolio_reservation_rows"],
            conservation["approved_reservation_rows"]
            + conservation["blocked_reservation_rows"],
        )

    def test_unknown_is_advisory_and_production_prerequisites_are_explicit(self):
        self.assertEqual(self.report["risk_group_unknown_advisory_count"], 8)
        self.assertTrue(
            self.report["production_prerequisites"][
                "PRODUCTION_PORTFOLIO_NAV_INPUT_REQUIRED"
            ]
        )
        self.assertTrue(
            self.report["production_prerequisites"][
                "PRODUCTION_RISK_GROUP_METADATA_REQUIRED_FOR_NEW_ENTRY"
            ]
        )


if __name__ == "__main__":
    unittest.main()
