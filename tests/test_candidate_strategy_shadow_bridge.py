from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Quote
from scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe import (
    _qfq_comparison,
    _qfq_history_from_factors,
    _candidate_network_api_request_count,
    _run_daily_decision_shadow,
    _run_us_market,
    _run_tushare_strategy_history,
    US_COMPLETED_SESSION_REQUIRED,
    US_HISTORICAL_QFQ_ASOF_UNVERIFIED,
    _validate_us_qfq_as_of,
    run_probe,
)


AS_OF = date(2026, 9, 4)


def _quote(symbol: str, day: date, close: float = 10.0) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        market="CN",
        trade_date=day,
        source="TushareDaily",
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        preclose=close,
        pct_change=0.0,
        volume=1000.0,
        amount=10000.0,
        turnover_rate=None,
        currency="CNY",
    )


class _FakeGateway:
    def __init__(self):
        self.calls = []

    def daily_multi_symbol(self, symbols, *, start_date, end_date):
        self.calls.append(tuple(symbols))
        rows = []
        for symbol in symbols:
            for index in range(60):
                day = start_date + timedelta(days=index)
                rows.append(
                    {
                        "ts_code": symbol,
                        "trade_date": day.strftime("%Y%m%d"),
                        "open": "10",
                        "high": "11",
                        "low": "9",
                        "close": "10",
                        "vol": "100",
                        "amount": "10",
                    }
                )
        return rows


class CandidateStrategyShadowBridgeTests(unittest.TestCase):
    def test_latest_completed_us_session_is_allowed_with_injected_now(self):
        result = _validate_us_qfq_as_of(
            AS_OF,
            now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["as_of_mode"], "LATEST_COMPLETED_SESSION_ONLY")
        self.assertFalse(result["historical_replay_supported"])

    def test_older_completed_us_session_fails_closed(self):
        with self.assertRaisesRegex(
            RuntimeError, f"^{US_HISTORICAL_QFQ_ASOF_UNVERIFIED}$"
        ):
            _validate_us_qfq_as_of(
                date(2026, 9, 3),
                now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
            )

    def test_future_or_not_completed_us_session_fails_closed(self):
        with self.assertRaisesRegex(
            RuntimeError, f"^{US_COMPLETED_SESSION_REQUIRED}$"
        ):
            _validate_us_qfq_as_of(
                AS_OF,
                now=datetime(2026, 9, 4, 19, 59, tzinfo=timezone.utc),
            )

    def test_historical_us_qfq_gate_runs_before_deep_yfinance_request(self):
        seed = SimpleNamespace(symbol="US.A", market="US")
        universe = SimpleNamespace(included=(SimpleNamespace(symbol="US.A"),))
        candidate_summary = {
            "seed_count": 1,
            "history_usable": 1,
            "final_included_count": 1,
            "included": 1,
        }
        history = {"US.A": [_quote("US.A", AS_OF)]}
        history_report = {
            "status": "SUCCESS",
            "symbols_requested": 1,
            "symbols_strategy_ready": 1,
            "rows": 1,
            "api_request_count": 1,
            "errors": [],
            "bars_distribution": {"1": 1},
        }
        with patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe.IwbOfficialHoldingsAdapter"
        ) as adapter, patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._completed_us_sessions",
            return_value=(AS_OF,),
        ), patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._candidate_summary",
            return_value=(candidate_summary, universe),
        ), patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._run_yfinance_batch_history",
            return_value=(history, history_report),
        ) as yfinance_history, patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._validate_us_qfq_as_of",
            side_effect=RuntimeError(US_HISTORICAL_QFQ_ASOF_UNVERIFIED),
        ):
            adapter.return_value.load.return_value = (AS_OF, (seed,))
            report = _run_us_market(
                as_of=AS_OF,
                now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(report["decision_marker"], "READY_FOR_DECISION_US_HISTORICAL_QFQ_ASOF")
        self.assertEqual(yfinance_history.call_count, 1)
        self.assertEqual(
            report["stage_timings"]["deep_raw_history_network"]["status"],
            "NOT_RUN",
        )
        self.assertEqual(
            report["strategy"]["qfq"]["as_of_mode"],
            "LATEST_COMPLETED_SESSION_ONLY",
        )

    def test_cn_candidate_request_accounting_does_not_double_count_reused_80_probe(self):
        probes = (
            {"probe_size": 20, "api_request_count": 1},
            {"probe_size": 50, "api_request_count": 1},
            {"probe_size": 80, "api_request_count": 1},
        )
        bulk = {"api_request_count": 10}
        self.assertEqual(
            _candidate_network_api_request_count(
                probes, bulk, "MULTI_SYMBOL_DAILY_BATCH"
            ),
            12,
        )

    def test_us_market_report_has_independent_stage_contract(self):
        seed = SimpleNamespace(symbol="US.A", market="US")
        universe = SimpleNamespace(
            included=(SimpleNamespace(symbol="US.A"),)
        )
        candidate_summary = {
            "seed_count": 1,
            "history_usable": 1,
            "final_included_count": 1,
            "included": 1,
        }
        history = {"US.A": [_quote("US.A", AS_OF)]}
        history_report = {
            "status": "SUCCESS",
            "symbols_requested": 1,
            "symbols_strategy_ready": 1,
            "rows": 1,
            "api_request_count": 1,
            "errors": [],
            "bars_distribution": {"1": 1},
        }
        decision = {
            "status": "SUCCESS",
            "evaluated": 1,
            "failed": 0,
            "symbols_requested": 1,
        }

        def sessions(_as_of, bars):
            return tuple(
                AS_OF - timedelta(days=bars - index - 1)
                for index in range(bars)
            )

        with patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe.IwbOfficialHoldingsAdapter"
        ) as adapter, patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._completed_us_sessions",
            side_effect=sessions,
        ), patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._candidate_summary",
            return_value=(candidate_summary, universe),
        ), patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._run_yfinance_batch_history",
            return_value=(history, history_report),
        ), patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe._run_daily_decision_shadow",
            return_value=decision,
        ):
            adapter.return_value.load.return_value = (AS_OF, (seed,))
            report = _run_us_market(
                as_of=AS_OF,
                now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(report["status"], "CANDIDATE_SUCCESS")
        self.assertEqual(
            list(report["stage_timings"]),
            [
                "seed_metadata",
                "candidate_short_history_network",
                "candidate_selector",
                "deep_raw_history_network",
                "adj_factor_network",
                "qfq_construction",
                "daily_decision_chain",
                "report_construction",
                "total",
            ],
        )
        self.assertEqual(report["candidate"]["included"], 1)
        self.assertEqual(report["strategy"]["decision_chain"]["evaluated"], 1)
        self.assertEqual(report["runtime_acceptance"], "ACCEPTED")

    def test_all_keeps_each_market_result_when_the_other_market_fails(self):
        cn = {
            "market": "CN",
            "status": "READY_FOR_DECISION_CN_STRATEGY_RUNTIME",
            "candidate": {"seed_count": 800},
            "strategy": None,
            "stage_timings": {},
            "runtime": {"total_elapsed_seconds": 1801.0},
        }
        us = {
            "market": "US",
            "status": "CANDIDATE_SUCCESS",
            "candidate": {"seed_count": 1018, "included": 513},
            "strategy": {"decision_chain": {"evaluated": 513}},
            "stage_timings": {},
            "runtime": {"total_elapsed_seconds": 900.0},
        }
        with patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe.run_market_probe",
            side_effect=[cn, us],
        ) as run_market:
            report = run_probe(market="all", as_of=AS_OF)

        self.assertEqual([call.kwargs["market"] for call in run_market.call_args_list], ["CN", "US"])
        self.assertEqual(report["status"], "PARTIAL_MARKET_FAILURE")
        self.assertIs(report["markets"]["CN"], cn)
        self.assertIs(report["markets"]["US"], us)
        self.assertEqual(report["candidate"]["US"]["included"], 513)
        self.assertTrue(report["all_is_convenience_only"])
        self.assertEqual(report["runtime_acceptance"], "NOT_AN_ACCEPTANCE_STANDARD")

    def test_strategy_history_uses_only_included_symbols_and_fixed_chunk_five(self):
        gateway = _FakeGateway()
        symbols = tuple(f"00000{index}.SZ" for index in range(6))
        histories, report = _run_tushare_strategy_history(
            gateway,
            symbols,
            start_date=AS_OF - timedelta(days=59),
            end_date=AS_OF,
        )
        self.assertEqual(gateway.calls, [symbols[:5], symbols[5:]])
        self.assertEqual(report["api_request_count"], 2)
        self.assertEqual(report["symbols_strategy_ready"], 6)
        self.assertEqual(report["shorter_than_requested_symbols"], list(symbols))
        self.assertEqual(report["last_bar_not_exact_as_of_symbols"], [])
        self.assertTrue(all(len(history) == 60 for history in histories.values()))

    def test_qfq_factor_change_checks_boundary_and_direction(self):
        day_before = AS_OF - timedelta(days=1)
        raw = [_quote("000001.SZ", day_before), _quote("000001.SZ", AS_OF)]
        factors = {day_before: 2.0, AS_OF: 4.0}
        adjusted = _qfq_history_from_factors(raw, factors, anchor_date=AS_OF)
        existing = [replace(quote, source="BaoStock") for quote in adjusted]
        comparison = _qfq_comparison(adjusted, existing, factors)
        self.assertEqual(comparison["factor_change_count"], 1)
        self.assertTrue(comparison["corporate_action_boundary_checked"])
        self.assertEqual(comparison["factor_change_examples"][0]["factor_direction"], "UP")
        self.assertEqual(comparison["mismatch_count"], 0)

    def test_decision_summary_keeps_watch_armed_and_proposal_separate_from_no_trade(self):
        fake_results = (
            SimpleNamespace(
                symbol="CN.WATCH",
                final_status="NO_TRADE",
                primary_action="WAIT_CONFIRMATION",
                setup01_state="WATCH",
                setup02_state="NONE",
                primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
            ),
            SimpleNamespace(
                symbol="CN.ARMED",
                final_status="NO_TRADE",
                primary_action="WAIT_CONFIRMATION",
                setup01_state="NONE",
                setup02_state="ARMED",
                primary_wave_scenario="WAVE_3_CONTINUATION_CANDIDATE",
            ),
            SimpleNamespace(
                symbol="CN.PROPOSAL",
                final_status="STRATEGY_PROPOSAL",
                primary_action="ENTRY_ALLOWED",
                setup01_state="CONFIRMED",
                setup02_state="NONE",
                primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
            ),
        )

        class FakeChain:
            def __init__(self, *, store):
                self.store = store

            def evaluate(self, *args, **kwargs):
                return SimpleNamespace(results=fake_results)

        histories = {
            symbol: [_quote(symbol, AS_OF)]
            for symbol in ("CN.WATCH", "CN.ARMED", "CN.PROPOSAL")
        }
        with patch(
            "scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe.DailyDecisionChain",
            FakeChain,
        ):
            summary = _run_daily_decision_shadow(
                histories,
                AS_OF,
                market="CN",
                requested_symbols=tuple(histories),
                history_ready_symbols=tuple(histories),
            )

        self.assertEqual(summary["final_status_counts"], {"NO_TRADE": 2, "STRATEGY_PROPOSAL": 1})
        self.assertEqual(summary["primary_action_counts"], {"ENTRY_ALLOWED": 1, "WAIT_CONFIRMATION": 2})
        self.assertEqual(summary["setup01_watch_symbols"], ["CN.WATCH"])
        self.assertEqual(summary["setup02_armed_symbols"], ["CN.ARMED"])
        self.assertEqual(summary["strategy_proposal_symbols"], ["CN.PROPOSAL"])
        self.assertTrue(summary["in_memory_state_store"])
        self.assertFalse(summary["persistent_state_write"])
        self.assertFalse(summary["sheets_write"])
        self.assertFalse(summary["allocation"])
        self.assertFalse(summary["broker_order"])


if __name__ == "__main__":
    unittest.main()
