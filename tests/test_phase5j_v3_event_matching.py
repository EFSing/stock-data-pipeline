from datetime import date, timedelta
import copy
import unittest

from research.phase5j_v3_event_matching import (
    EXPECTED_PROTOCOL_SHA256,
    EXPECTED_PROTOCOL_VERSION,
    load_protocol,
    match_event_identities,
    protocol_integrity_hash,
)


class Phase5JV3ProtocolTests(unittest.TestCase):
    def test_protocol_has_immutable_matching_contract(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(protocol["integrity"]["protocol_sha256"], EXPECTED_PROTOCOL_SHA256)
        self.assertEqual(protocol["matching_window"]["max_distance"], 40)
        self.assertTrue(protocol["order_invariants"]["non_crossing"])
        self.assertIn("use returns, MFE, MAE, P&L, win rate, profit factor, or expectancy", protocol["prohibited_actions"])

    def test_synchronized_hash_change_does_not_change_version(self):
        protocol = load_protocol()
        changed = copy.deepcopy(protocol)
        changed["matching_window"]["max_distance"] = 41
        changed["integrity"]["protocol_sha256"] = protocol_integrity_hash(changed)
        self.assertNotEqual(changed["integrity"]["protocol_sha256"], EXPECTED_PROTOCOL_SHA256)


class Phase5JV3MatchingTests(unittest.TestCase):
    SESSIONS = {"US": tuple(date(2026, 1, day) for day in range(1, 12))}

    def test_exact_identity_is_retained_and_unmatched_is_conserved(self):
        result = match_event_identities(
            [("US", "T", date(2026, 1, 1)), ("US", "T", date(2026, 1, 3))],
            [("US", "T", date(2026, 1, 1)), ("US", "T", date(2026, 1, 4))],
            market_session_dates=self.SESSIONS,
        )
        self.assertEqual(result["retained"], [["US", "T", "2026-01-01"]])
        self.assertEqual(len(result["matched_pairs"]), 1)
        self.assertEqual(result["matched_pairs"][0]["trading_session_distance"], 1)
        self.assertEqual(result["unmatched_previous"], [])
        self.assertEqual(result["unmatched_current"], [])

    def test_matching_is_max_cardinality_min_cost_and_non_crossing(self):
        sessions = {"US": tuple(date(2026, 1, day) for day in range(1, 21))}
        result = match_event_identities(
            [("US", "T", date(2026, 1, 2)), ("US", "T", date(2026, 1, 5))],
            [("US", "T", date(2026, 1, 4)), ("US", "T", date(2026, 1, 6))],
            market_session_dates=sessions,
        )
        pairs = result["matched_pairs"]
        self.assertEqual(len(pairs), 2)
        self.assertEqual([(pair["old_date"], pair["new_date"]) for pair in pairs], [("2026-01-02", "2026-01-04"), ("2026-01-05", "2026-01-06")])
        self.assertEqual(sum(pair["trading_session_distance"] for pair in pairs), 3)

    def test_distance_over_40_sessions_remains_unmatched(self):
        start = date(2026, 1, 1)
        sessions = {"US": tuple(start + timedelta(days=index) for index in range(60))}
        result = match_event_identities(
            [("US", "T", start)],
            [("US", "T", start + timedelta(days=41))],
            market_session_dates=sessions,
        )
        self.assertEqual(result["matched_pairs"], [])

    def test_cross_market_or_symbol_events_do_not_match(self):
        sessions = {"CN": (date(2026, 1, 1), date(2026, 1, 2)), "US": (date(2026, 1, 1), date(2026, 1, 2))}
        result = match_event_identities(
            [("CN", "T", date(2026, 1, 1))],
            [("US", "T", date(2026, 1, 2))],
            market_session_dates=sessions,
        )
        self.assertEqual(result["matched_pairs"], [])
        self.assertEqual(len(result["unmatched_previous"]), 1)
        self.assertEqual(len(result["unmatched_current"]), 1)


if __name__ == "__main__":
    unittest.main()
