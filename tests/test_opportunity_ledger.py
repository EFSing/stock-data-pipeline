from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import Quote
from scripts.run_cloud_daily_report import main, run_cloud_daily_report
from trading.daily_dashboard import render_dashboard_html
from trading.opportunity_ledger import (
    FOLLOWUP_SHEET, OPPORTUNITY_SHEET, SESSION_SHEET, SCHEMAS,
    active_symbols, birth_snapshots, followup, observation_sessions,
    persist_daily_opportunities, tracking_projection,
)
from trading.production_candidate_runtime import HistoryLoadResult, ProductionCandidateRuntime
from trading.production_prerequisites import ExactExchangeCalendarProvider


T = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 21, tzinfo=timezone.utc)
CALENDAR = ExactExchangeCalendarProvider()


class Sheets:
    def __init__(self):
        self.rows, self.writes = {}, []

    def ensure_worksheet(self, name, headers):
        assert tuple(headers) == SCHEMAS[name]
        self.rows.setdefault(name, [])

    def records(self, name):
        return deepcopy(self.rows[name])

    def append_rows(self, name, headers, rows):
        assert name in SCHEMAS  # forbid state, Paper, holdings and market writes
        self.writes.append((name, deepcopy(rows)))
        self.rows[name].extend(deepcopy(rows))
        return len(rows)

    def upsert_opportunity_summary(self, row, headers):
        for index, old in enumerate(self.rows[SESSION_SHEET]):
            if (old["market"], old["session_date"]) == (row["market"], row["session_date"]):
                if old["payload_json"] == row["payload_json"]:
                    return 0
                self.rows[SESSION_SHEET][index] = deepcopy(row)
                return 1
        return self.append_rows(SESSION_SHEET, headers, [row])


def quote(t=T, *, symbol="GENERIC.A", market="US", close=100, high=102, low=98):
    return Quote(symbol=symbol, name=symbol, market=market, trade_date=t,
                 source="YAHOO_CHART" if market == "US" else "HITHINK_FINANCIAL_API",
                 open=100, high=high, low=low, close=close, volume=1000,
                 preclose=None, pct_change=None, amount=None, turnover_rate=None,
                 currency="USD" if market == "US" else "CNY")


def payload(t=T, *, allowed=False, setup="SETUP_01", market="US", symbol="GENERIC.A"):
    identity = f"{symbol}|{setup}|{t}|CONFIRMED|lifecycle=1"
    decision = {"event_identity": identity, "action": "ENTRY_ALLOWED" if allowed else "NO_TRADE",
                "gate_reason": "ENTRY_ALLOWED" if allowed else "RR_BELOW_MINIMUM",
                "planned_entry": 100, "entry_zone_low": 99, "entry_zone_high": 101,
                "targets": [105, 110, 115], "execution_stop": 95,
                "structural_invalidation": 96, "target_upside_pct": .05,
                "rr": {"rr_ratios": [1, 2, 3]}}
    row = {"symbol": symbol, "market": market, "as_of_date": t.isoformat(), "data_status": "DATA_OK",
           "setup01_state": "CONFIRMED", "setup02_state": "WATCH", "final_status": "NO_TRADE",
           "new_confirmed_event_identities": [identity], "individual_decision_candidates": [decision]}
    return {"market": market, "as_of_date": t.isoformat(), "generated_at": NOW.isoformat(),
            "cloud_daily_report": {"RUN_STATUS": "COMPLETED", "DATA_STATUS": "OK", "CANDIDATE_STATUS": "SUCCESS"},
            "candidate_markets": {market: {"seed_count": 1, "candidate_data_qualified_count": 1,
                                          "candidate_included_count": 1, "deep_history_ready_count": 1}},
            "funnel": {market: {"WATCH": 0, "ARMED": 0, "new_CONFIRMED": 1, "individual_ENTRY_ALLOWED": int(allowed)}},
            "reports": [{"市场": market, "universe": {"formal_strategy_pool": [], "dynamic_candidate_set": [symbol]}, "报告": {"results": [row]}}]}


def inputs(bars, *, market="US", symbol="GENERIC.A"):
    return [SimpleNamespace(market=market, symbol=symbol, quotes=bars, data_status="DATA_OK")]


class OpportunityLedgerTests(unittest.TestCase):
    def test_real_september30_diagnostic_five_rejected_events_create_five_births(self):
        fixture = json.loads((Path(__file__).with_name("fixtures") / "opportunity_ledger_20260930.json").read_text(encoding="utf-8"))
        original = deepcopy(fixture)
        births = birth_snapshots(fixture)
        self.assertEqual(len(births), 5)
        self.assertEqual(fixture["funnel"]["CN"]["individual_ENTRY_ALLOWED"], 0)
        self.assertEqual(sorted(b["primary_reject_reason"] for b in births),
                         ["ABOVE_ENTRY_ZONE", "RR_BELOW_MINIMUM"] + ["TARGET_UPSIDE_BELOW_MINIMUM"] * 3)
        self.assertTrue(all(b["signal_close"] is None for b in births))
        self.assertEqual(fixture, original)
        client, runtime = Sheets(), Mock()
        first = persist_daily_opportunities(client, fixture, [], CALENDAR, runtime, NOW)
        rerun = persist_daily_opportunities(client, fixture, [], CALENDAR, runtime, NOW)
        self.assertEqual((first["birth_rows_written"], len(client.rows[OPPORTUNITY_SHEET])), (5, 5))
        self.assertEqual((rerun["birth_rows_written"], rerun["session_rows_written"]), (0, 0))
        runtime.load_opportunity_continuation.assert_not_called()

    def test_allowed_and_rejected_both_setups_and_formal_candidate_enter_ledger(self):
        sheets, runtime = Sheets(), Mock()
        for allowed, setup, symbol in ((True, "SETUP_01", "GENERIC.A"), (False, "SETUP_02", "GENERIC.B")):
            p = payload(allowed=allowed, setup=setup, symbol=symbol)
            if allowed:
                p["reports"][0]["universe"]["formal_strategy_pool"] = [symbol]
            original = deepcopy(p)
            persist_daily_opportunities(sheets, p, inputs([quote(symbol=symbol)], symbol=symbol), CALENDAR, runtime, NOW)
            self.assertEqual(p, original)
        values = [json.loads(row["payload_json"]) for row in sheets.rows[OPPORTUNITY_SHEET]]
        self.assertEqual([row["action"] for row in values], ["ENTRY_ALLOWED", "NO_TRADE"])
        self.assertEqual([row["source_identity"] for row in values], ["FORMAL", "CANDIDATE"])
        self.assertTrue(all(row["confirmation_entry"] is None for row in values))
        runtime.load_opportunity_continuation.assert_not_called()
        self.assertEqual(set(sheets.rows), set(SCHEMAS))

    def test_session_rerun_is_noop_and_partial_write_recovery_is_idempotent(self):
        sheets, runtime, p = Sheets(), Mock(), payload()
        args = sheets, p, inputs([quote()]), CALENDAR, runtime, NOW
        first = persist_daily_opportunities(*args)
        second = persist_daily_opportunities(*args)
        self.assertEqual(first["new_observation_count"], second["new_observation_count"])
        self.assertEqual((second["birth_rows_written"], second["session_rows_written"], second["followup_rows_written"]), (0, 0, 0))
        self.assertEqual((len(sheets.rows[SESSION_SHEET]), len(sheets.rows[OPPORTUNITY_SHEET])), (1, 1))
        # Birth committed, summary write failed: retry must not duplicate it.
        sheets.rows[SESSION_SHEET] = []
        retry = persist_daily_opportunities(*args)
        self.assertEqual((retry["birth_rows_written"], retry["session_rows_written"]), (0, 1))

    def test_t_plus_one_candidate_dropout_uses_independent_continuation(self):
        sheets, p = Sheets(), payload()
        runtime = Mock()
        persist_daily_opportunities(sheets, p, inputs([quote(high=120, low=90)]), CALENDAR, runtime, NOW)
        next_day = CALENDAR.next_session("US", T)
        bars = (quote(high=120, low=90), quote(next_day, close=102, high=104))
        runtime.load_opportunity_continuation.return_value = HistoryLoadResult({"GENERIC.A": bars})
        empty = payload(next_day)
        empty["reports"][0]["报告"]["results"] = []
        empty["reports"][0]["universe"]["dynamic_candidate_set"] = []
        result = persist_daily_opportunities(sheets, empty, [], CALENDAR, runtime, NOW)
        runtime.load_opportunity_continuation.assert_called_once()
        self.assertEqual(runtime.load_opportunity_continuation.call_args.kwargs["symbols"], {"GENERIC.A"})
        row = json.loads(sheets.rows[FOLLOWUP_SHEET][0]["payload_json"])
        self.assertEqual((row["as_of_date"], row["sessions_since_confirmation"], row["coverage_status"]), (next_day.isoformat(), 1, "DATA_OK"))
        self.assertAlmostEqual(row["close_return"], .02)
        self.assertAlmostEqual(row["cumulative_max_favorable_move"], .04)
        self.assertFalse(row["touches"]["T1"])  # T-day 120 high is excluded
        self.assertIsNone(row["first_touch_sessions"]["execution_stop"])  # T-day 90 low excluded
        rerun = persist_daily_opportunities(sheets, empty, [], CALENDAR, runtime, NOW)
        self.assertEqual((result["followup_rows_written"], rerun["followup_rows_written"], len(sheets.rows[FOLLOWUP_SHEET])), (1, 0, 1))

    def test_missing_data_and_wrong_provider_or_changed_qfq_basis_are_gaps(self):
        birth = birth_snapshots(payload(), inputs([quote()]))[0]
        next_day = CALENDAR.next_session("US", T)
        histories = ((), (quote(), replace(quote(next_day), source="yfinance")),
                     (quote(close=99), quote(next_day)), (quote(), quote(next_day), quote(CALENDAR.next_session("US", next_day))))
        for history in histories:
            row = followup(birth, next_day, 1, history, [])
            self.assertNotEqual(row["coverage_status"], "DATA_OK")
            self.assertIsNone(row["close_return"])
            self.assertIsNone(row["close"])
            self.assertFalse(row["coverage_complete"])
            self.assertNotIn("NO_TRADE", row.values())
        with self.assertRaisesRegex(ValueError, "T_PLUS_ONE"):
            followup(birth, T, 0, [quote()], [])

    def test_same_bar_target_stop_is_ambiguous_without_simulated_pnl(self):
        birth = birth_snapshots(payload(), inputs([quote()]))[0]
        next_day = CALENDAR.next_session("US", T)
        row = followup(birth, next_day, 1, (quote(), quote(next_day, high=116, low=94)), [])
        self.assertEqual(row["bar_order_status"], "SAME_BAR_ORDER_AMBIGUOUS")
        self.assertTrue(all(row["touches"].values()))
        self.assertEqual(set(row["first_touch_sessions"].values()), {next_day.isoformat()})
        self.assertFalse(set(row) & {"pnl", "win", "loss", "normalized_r", "actual_entry"})
        later = dict(row, as_of_date=CALENDAR.next_session("US", next_day).isoformat(),
                     cumulative_max_favorable_move=100.0)
        self.assertEqual(followup(birth, next_day, 1, (quote(), quote(next_day, high=116, low=94)), [later]), row)

    def test_tenth_exchange_session_matures_and_gap_sample_is_excluded(self):
        birth = birth_snapshots(payload(), inputs([quote()]))[0]
        dates = observation_sessions(birth, date(2026, 11, 1), CALENDAR)
        self.assertEqual(len(dates), 10)
        rows = []
        for index, day in enumerate(dates, 1):
            bars = (quote(), quote(day)) if index != 3 else ()
            rows.append(followup(birth, day, index, bars, rows))
        projected = tracking_projection([birth], rows, "US", dates[-1].isoformat())
        self.assertEqual((projected["active_tracking_count"], projected["completed_today_count"]), (0, 1))
        stats = projected["matured_by_original_reason"][0]
        self.assertEqual((stats["complete_count"], stats["coverage_gap_count"]), (0, 1))
        self.assertIsNone(stats["mean_close_return"])
        self.assertEqual(active_symbols([birth], rows, "US"), ())
        self.assertIn("样本不足", render_dashboard_html({"opportunity_tracking": projected | {"status": "SUCCESS"}}))

    def test_cn_holiday_and_us_sessions_do_not_use_weekday_approximation(self):
        p = payload(date(2026, 9, 30), market="CN", symbol="600000.SH")
        birth = birth_snapshots(p, inputs([quote(date(2026, 9, 30), market="CN", symbol="600000.SH")], market="CN", symbol="600000.SH"))[0]
        self.assertEqual(observation_sessions(birth, date(2026, 10, 8), CALENDAR), (date(2026, 10, 8),))
        self.assertEqual(CALENDAR.next_session("US", date(2026, 10, 2)), date(2026, 10, 5))

    def test_continuation_uses_canonical_loader_without_seed_discovery(self):
        loader = Mock(return_value=HistoryLoadResult({}))
        runtime = ProductionCandidateRuntime(deep_history_loader=loader,
                                            session_window_loader=lambda *_: (T,))
        runtime.load_opportunity_continuation(market="US", symbols=("GENERIC.A",), as_of_date=T, now=NOW)
        seeds = loader.call_args.args[0]
        self.assertEqual(seeds[0].source, "OPPORTUNITY_OBSERVATION")
        self.assertNotIn("PAPER_TRACKED", seeds[0].provenance)
        with self.assertRaisesRegex(RuntimeError, "QFQ"):
            runtime.load_opportunity_continuation(market="US", symbols=("GENERIC.A",), as_of_date=date(2026, 10, 2), now=NOW)

    def test_failed_read_is_not_empty_and_missed_followup_remains_gap(self):
        sheets, runtime, p = Sheets(), Mock(), payload()
        persist_daily_opportunities(sheets, p, inputs([quote()]), CALENDAR, runtime, NOW)
        dates = observation_sessions(birth_snapshots(p)[0], date(2026, 10, 7), CALENDAR)
        runtime.load_opportunity_continuation.return_value = HistoryLoadResult({"GENERIC.A": (quote(), quote(dates[-1]))})
        later = payload(dates[-1])
        later["reports"] = []
        result = persist_daily_opportunities(sheets, later, [], CALENDAR, runtime, NOW)
        rows = [json.loads(row["payload_json"]) for row in sheets.rows[FOLLOWUP_SHEET]]
        self.assertEqual(rows[0]["coverage_status"], "MISSED_OBSERVATION_SESSION")
        self.assertIsNone(rows[0]["close_return"])
        self.assertFalse(rows[-1]["coverage_complete"])
        with patch.object(sheets, "records", side_effect=RuntimeError("denied")):
            with self.assertRaisesRegex(RuntimeError, "denied"):
                persist_daily_opportunities(sheets, later, [], CALENDAR, runtime, NOW)

    def test_cloud_natural_run_persists_and_failure_still_emits_artifacts_nonzero(self):
        p = payload()
        ephemeral = SimpleNamespace(latest_rows=(), qfq_rows=(), symbol_status={}, active_paper_symbols=(),
                                    to_dict=lambda: {})
        quality = {"run_status": "COMPLETED", "data_status": "OK", "candidate_status": "SUCCESS"}
        def run_once(client, automatic=True, t=T, current=NOW):
            with TemporaryDirectory() as directory, \
                    patch("scripts.run_cloud_daily_report.load_ephemeral_market_data", return_value=ephemeral), \
                    patch("scripts.run_cloud_daily_report.run_production_daily_decision", return_value=p), \
                    patch("scripts.run_cloud_daily_report._status_from_result", return_value=("SUCCESS", quality)):
                result = run_cloud_daily_report(market="US", as_of_date=t, now=current, output_dir=directory,
                                               client=client, notify=False, automatic_resolution=automatic)
                self.assertTrue((Path(directory) / "daily-report.json").exists())
                self.assertTrue((Path(directory) / "daily-report.html").exists())
                return result
        sheets = Sheets()
        success = run_once(sheets)
        self.assertEqual(success["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"], "SUCCESS")
        self.assertTrue(success["NO STATE WRITE"] if "NO STATE WRITE" in success else not success["cloud_daily_report"]["state_write"])
        failed = run_once(Mock(ensure_worksheet=Mock(side_effect=RuntimeError("403 permission denied"))))
        self.assertEqual(failed["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"], "FAILED")
        self.assertEqual(failed["cloud_daily_report"]["RUN_STATUS"], "COMPLETED")
        with TemporaryDirectory() as directory, patch("scripts.run_cloud_daily_report.resolve_cloud_trade_date", return_value=T), \
                patch("scripts.run_cloud_daily_report.run_cloud_daily_report", return_value=failed):
            self.assertEqual(main(["--market", "US", "--output", directory, "--no-notify"]), 1)
        manual = run_once(sheets, automatic=False)
        self.assertEqual(manual["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"], "SUCCESS")
        self.assertEqual(manual["opportunity_tracking"]["birth_rows_written"], 0)
        # Later natural history after release is still diagnostic-only once
        # its next-session open has passed; no Sheets access is attempted.
        diagnostic_client = Mock()
        diagnostic = run_once(diagnostic_client, automatic=False,
                              current=datetime(2026, 10, 7, 21, tzinfo=timezone.utc))
        self.assertEqual(diagnostic["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"], "NOT_ENABLED_FOR_DIAGNOSTIC")
        diagnostic_client.ensure_worksheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
