from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from core import Quote
from trading.daily_dashboard import build_dashboard_projection, render_dashboard_html
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_OK,
    DailySymbolInput,
    _armed_opportunity_projection,
)
from trading.models import SetupState
from trading.setup01_decision import SETUP01_ENTRY_ZONE_ATR
from trading.setup02_decision import SETUP02_ENTRY_ZONE_ATR


def _quotes(market: str, symbol: str, count: int = 20) -> tuple[Quote, ...]:
    start = date(2026, 1, 1)
    return tuple(
        Quote(
            symbol=symbol,
            name="Projection fixture",
            market=market,
            trade_date=start + timedelta(days=index),
            source="synthetic",
            open=95.0 + index,
            high=97.0 + index,
            low=94.0 + index,
            close=96.0 + index,
            preclose=None,
            pct_change=None,
            volume=100.0,
            amount=None,
            turnover_rate=None,
            currency="CNY" if market == "CN" else "USD",
        )
        for index in range(count)
    )


def _input(market: str, symbol: str) -> DailySymbolInput:
    history = _quotes(market, symbol)
    as_of = history[-1].trade_date
    return DailySymbolInput(
        symbol=symbol,
        market=market,
        as_of_date=as_of,
        qfq_history=history,
        data_quality_status=DATA_OK,
        completed_session_identity=CompletedSessionIdentity(
            market=market,
            trade_date=as_of,
            identity=f"{market}-SYNTHETIC-T",
            session_dates=(as_of,),
        ),
    )


def _snapshot(state: SetupState, confirmation=118.0, invalidation=90.0):
    return SimpleNamespace(
        state=state,
        confirmation_level=confirmation,
        structural_invalidation=invalidation,
    )


class ArmedOpportunityProjectionTests(unittest.TestCase):
    def test_setup01_us_projection_is_causal_and_uses_formal_entry_zone(self):
        item = _input("US", "AAA")
        projection = _armed_opportunity_projection(
            item,
            _snapshot(SetupState.ARMED),
            _snapshot(SetupState.NONE),
        )

        self.assertEqual(projection["status"], "AVAILABLE")
        self.assertEqual(projection["setup_type"], "SETUP_01")
        self.assertEqual(projection["as_of_date"], item.as_of_date.isoformat())
        self.assertEqual(projection["current_close"], item.qfq_history[-1].close)
        self.assertAlmostEqual(
            projection["expected_entry_zone_high"],
            projection["confirmation_level"]
            + SETUP01_ENTRY_ZONE_ATR * projection["atr14"],
        )
        self.assertFalse(projection["is_trade_signal"])

    def test_setup02_cn_projection_uses_same_as_of_prefix_and_formal_formula(self):
        item = _input("CN", "600001.SH")
        projection = _armed_opportunity_projection(
            item,
            _snapshot(SetupState.NONE),
            _snapshot(SetupState.ARMED, confirmation=120.0, invalidation=92.0),
        )

        self.assertEqual(projection["setup_type"], "SETUP_02")
        self.assertEqual(projection["expected_entry_zone_low"], 120.0)
        self.assertAlmostEqual(
            projection["expected_entry_zone_high"],
            120.0 + SETUP02_ENTRY_ZONE_ATR * projection["atr14"],
        )
        self.assertAlmostEqual(
            projection["distance_to_confirmation_pct"],
            (120.0 - item.qfq_history[-1].close) / item.qfq_history[-1].close,
        )

    def test_missing_causal_fields_fail_closed(self):
        projection = _armed_opportunity_projection(
            _input("US", "MISS"),
            _snapshot(SetupState.ARMED, confirmation=None, invalidation=None),
            _snapshot(SetupState.NONE),
        )

        self.assertEqual(projection["status"], "DATA_UNAVAILABLE")
        self.assertIn("CONFIRMATION_LEVEL_UNAVAILABLE", projection["missing_reasons"])
        self.assertIn("STRUCTURAL_INVALIDATION_UNAVAILABLE", projection["missing_reasons"])
        self.assertIsNone(projection["expected_entry_zone_high"])

    def test_dashboard_only_formats_projection_and_keeps_entry_priority(self):
        armed = {
            "symbol": "ARMED.NEAR",
            "market": "US",
            "data_status": "DATA_OK",
            "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
            "alternate_wave_scenario": "ABC_CORRECTION_CANDIDATE",
            "setup01_state": "ARMED",
            "setup02_state": "NONE",
            "event_was_new": False,
            "individual_decision": None,
            "portfolio_result": None,
            "position_management": None,
            "primary_action": "WAIT_CONFIRMATION",
            "reasons": ["等待新的 CONFIRMED event"],
            "blocking_prerequisites": [],
            "final_status": "NO_TRADE",
            "armed_opportunity": {
                "status": "AVAILABLE",
                "setup_type": "SETUP_01",
                "current_close": 99.0,
                "confirmation_level": 100.0,
                "distance_to_confirmation": 1.0,
                "distance_to_confirmation_pct": 0.01,
                "structural_invalidation": 88.0,
                "atr14": 7.0,
                "expected_entry_zone_low": 888.0,
                "expected_entry_zone_high": 999.0,
                "guidance": "等待确认；不追价；结构失效则放弃。",
                "missing_reasons": [],
                "is_trade_signal": False,
            },
        }
        entry = {
            **armed,
            "symbol": "ENTRY.FIRST",
            "setup01_state": "CONFIRMED",
            "individual_decision": {
                "action": "ENTRY_ALLOWED",
                "planned_entry": 101.0,
                "entry_zone_low": 100.0,
                "entry_zone_high": 102.0,
            },
            "primary_action": "ENTRY_ALLOWED",
            "final_status": "STRATEGY_PROPOSAL",
            "armed_opportunity": {},
        }
        payload = {"reports": [{"market": "US", "报告": {"results": [armed, entry]}}]}

        projection = build_dashboard_projection(payload)
        self.assertEqual(projection["rows"][0]["symbol"], "ENTRY.FIRST")
        html = render_dashboard_html(payload)
        self.assertIn("机会观察", html)
        self.assertIn("观察中，不是买入信号", html)
        self.assertIn("888 – 999", html)
        self.assertNotIn("891.50", html)


if __name__ == "__main__":
    unittest.main()
