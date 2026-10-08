from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from trading.daily_dashboard import (
    build_dashboard_projection,
    dashboard_search_matches,
    daily_report_consistency_matrix,
    html_consistency_audit,
    load_dashboard_json,
    render_dashboard_html,
    render_daily_report_email_html,
    USER_VISIBLE_ALLOWED_ABBREVIATIONS,
    user_visible_language_audit,
    write_dashboard_html,
)


FIXTURE = Path(__file__).with_name("fixtures") / "daily_dashboard_v1.json"


def _new_confirmation_no_trade_payload(gate_reason: str, **decision_fields) -> dict:
    decision = {
        "action": "NO_TRADE",
        "gate_reason": gate_reason,
        **decision_fields,
    }
    return {
        "as_of_date": "2026-09-14",
        "results": [{
            "symbol": "CONFIRM_REJECT",
            "market": "US",
            "data_status": "DATA_OK",
            "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
            "alternate_wave_scenario": "UNKNOWN",
            "setup01_state": "CONFIRMED",
            "setup02_state": "NONE",
            "primary_action": "NO_TRADE",
            "event_was_new": True,
            "individual_decision": decision,
            "portfolio_result": None,
            "position_management": None,
            "reasons": [],
            "blocking_prerequisites": [],
            "final_status": "NO_TRADE",
        }],
    }


def _candidate_closeout_payload(
    *,
    candidate_status: str = "PARTIAL",
    candidate_runtime_status: str = "PARTIAL_DATA_QUALITY",
    quality_errors: list[str] | None = None,
    exclusions: dict[str, int] | None = None,
    readiness: str = "FINAL_REPORT_ELIGIBLE",
    readiness_reason: str = "EXACT_SESSION_AND_ANALYSIS_COVERAGE",
    ledger_status: str = "NOT_RUN",
) -> dict:
    return {
        "as_of_date": "2026-10-07",
        "results": [],
        "candidate_markets": {
            "US": {
                "market": "US",
                "status": candidate_runtime_status,
                "candidate_status": candidate_status,
                "candidate_selection_outcome": "CANDIDATES_INCLUDED",
                "seed_count": 1024,
                "candidate_data_qualified_count": 1017,
                "candidate_included_count": 999,
                "deep_history_requested_count": 999,
                "deep_history_ready_count": 999,
                "deep_analysis_count": 999,
                "strategy_analysis_count": 999,
                "candidate_exclusion_reason_counts": exclusions or {
                    "INCLUDED": 999,
                    "US_ONE_SHARE_NOTIONAL_OVER_1000": 18,
                    "HISTORY_INSUFFICIENT": 6,
                    "LIFECYCLE_UNLISTED_OR_NO_MARKET": 1,
                },
                "stage_timings": {
                    "candidate_short_history": {"status": candidate_runtime_status},
                    "deep_history": {"status": "SUCCESS"},
                },
            }
        },
        "cloud_daily_report": {
            "market": "US",
            "status": candidate_runtime_status,
            "delivery_readiness": readiness,
            "delivery_readiness_reason": readiness_reason,
            "final_report_eligible": readiness == "FINAL_REPORT_ELIGIBLE",
            "OPPORTUNITY_LEDGER_STATUS": ledger_status,
            "data_quality": {
                "candidate_quality_errors": list(quality_errors or ()),
                "failed_symbols": [],
            },
        },
    }


def _setup02_target_candidates(
    *,
    planned_entry: float = 6.94,
    profile: str = "CN",
) -> list[dict]:
    if planned_entry == 6.94:
        prices = (7.046002994011976, 7.0796, 7.2699, 7.48, 7.8199)
        origin, peak, wave2_low = 6.2, 6.75, 6.38
    elif profile == "RR":
        prices = (108.0, 119.08, 124.27, 130.0, 139.27)
        origin, peak, wave2_low = 90.0, 105.0, 100.0
    else:
        prices = (103.0, 103.36, 105.09, 107.0, 110.09)
        origin, peak, wave2_low = 90.0, 95.0, 97.0
    return [
        {
            "price": prices[0],
            "source": "CONFIRMED_SWING_HIGH",
            "reason": "T-known confirmed swing high",
            "provenance": [{
                "source": "CONFIRMED_SWING_HIGH",
                "pivot_date": "2026-05-06",
                "confirmed_date": "2026-05-07",
                "extension_ratio": None,
            }],
        },
        {
            "price": prices[1],
            "source": "WAVE3_FIB_EXTENSION",
            "reason": "existing extension 1.272",
            "provenance": [{
                "source": "WAVE3_FIB_EXTENSION",
                "extension_ratio": 1.272,
                "wave1_origin_price": origin,
                "wave1_peak_price": peak,
                "wave2_low_price": wave2_low,
                "formula_identity": "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
            }],
        },
        {
            "price": prices[2],
            "source": "WAVE3_FIB_EXTENSION",
            "reason": "existing extension 1.618",
            "provenance": [{
                "source": "WAVE3_FIB_EXTENSION",
                "extension_ratio": 1.618,
                "wave1_origin_price": origin,
                "wave1_peak_price": peak,
                "wave2_low_price": wave2_low,
                "formula_identity": "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
            }],
        },
        {
            "price": prices[3],
            "source": "WAVE3_FIB_EXTENSION",
            "reason": "existing extension 2.0",
            "provenance": [{
                "source": "WAVE3_FIB_EXTENSION",
                "extension_ratio": 2.0,
                "wave1_origin_price": origin,
                "wave1_peak_price": peak,
                "wave2_low_price": wave2_low,
                "formula_identity": "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
            }],
        },
        {
            "price": prices[4],
            "source": "WAVE3_FIB_EXTENSION",
            "reason": "existing extension 2.618",
            "provenance": [{
                "source": "WAVE3_FIB_EXTENSION",
                "extension_ratio": 2.618,
                "wave1_origin_price": origin,
                "wave1_peak_price": peak,
                "wave2_low_price": wave2_low,
                "formula_identity": "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
            }],
        },
    ]


def _setup02_confirmation_payload(
    gate_reason: str,
    *,
    market: str = "CN",
    symbol: str = "600901.SH",
    above_entry_zone: bool = False,
) -> dict:
    planned_entry = 7.1 if above_entry_zone else (6.94 if market == "CN" else 100.0)
    candidates = [] if above_entry_zone else _setup02_target_candidates(
        planned_entry=planned_entry,
        profile="RR" if gate_reason == "RR_BELOW_MINIMUM" else market,
    )
    targets = [item["price"] for item in candidates[:3]]
    if above_entry_zone:
        target_upside = None
        rr = None
    elif gate_reason == "RR_BELOW_MINIMUM":
        target_upside = 0.08
        rr = {"rr_ratios": [1.8, 2.4, 3.1], "quality": "NO_TRADE"}
    else:
        target_upside = (targets[0] - planned_entry) / planned_entry
        rr = {"rr_ratios": [0.1692458211783177, 0.22, 0.53], "quality": "NO_TRADE"}
    decision = {
        "action": "NO_TRADE",
        "gate_reason": gate_reason,
        "planned_entry": planned_entry,
        "confirmation_level": 7.0 if above_entry_zone else (6.89 if market == "CN" else 100.0),
        "entry_zone_low": 7.0 if above_entry_zone else (6.89 if market == "CN" else 99.0),
        "entry_zone_high": 7.05 if above_entry_zone else (6.9563 if market == "CN" else 102.0),
        "structural_invalidation": 6.38 if above_entry_zone else (6.38 if market == "CN" else 90.0),
        "execution_stop": None if above_entry_zone else (6.3137 if market == "CN" else 90.0),
        "targets": targets,
        "target_candidates": candidates,
        "target_upside_pct": target_upside,
        "target_upside_band": "BELOW_MINIMUM" if gate_reason == "TARGET_UPSIDE_BELOW_MINIMUM" else "PREFERRED_UPSIDE",
        "minimum_target_upside_pct": 0.05,
        "rr": rr,
    }
    if above_entry_zone:
        decision.update({
            "continuation_low0": {"price": 6.2},
            "continuation_high1": {"price": 6.75},
            "continuation_low2": {"price": 6.38},
        })
    return {
        "as_of_date": "2026-09-30",
        "results": [{
            "symbol": symbol,
            "market": market,
            "data_status": "DATA_OK",
            "primary_wave_scenario": "WAVE_3_CONTINUATION_CANDIDATE",
            "alternate_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
            "setup01_state": "NONE",
            "setup02_state": "CONFIRMED",
            "primary_action": "NO_TRADE",
            "event_was_new": True,
            "new_confirmed_event_identities": [f"{symbol}|SETUP_02|2026-09-30|CONFIRMED"],
            "individual_decision": decision,
            "opportunity_freshness": {
                "target_upside_pct": target_upside,
                "target_upside_band": decision["target_upside_band"],
                "minimum_target_upside_pct": 0.05,
                "entry_zone_upper_distance_pct": 0.01 if above_entry_zone else -0.002,
            },
            "portfolio_result": None,
            "position_management": None,
            "reasons": [],
            "blocking_prerequisites": [],
            "final_status": "NO_TRADE",
        }],
    }


class DailyDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = load_dashboard_json(FIXTURE)

    def test_projection_covers_required_stages_and_summary(self):
        projection = build_dashboard_projection(self.payload)
        rows = {row["symbol"]: row for row in projection["rows"]}

        self.assertEqual(
            {row["stage_key"] for row in projection["rows"]},
            {
                "WATCH",
                "ARMED",
                "CONFIRMED",
                "STRATEGY_PROPOSAL",
                "ENTRY_ALLOWED",
                "POSITION_MANAGEMENT",
            },
        )
        self.assertEqual(
            projection["summary"],
            {
                "candidate_total": 6,
                "analysis_count": 6,
                "completed_analysis_count": 6,
                "watch_count": 1,
                "armed_count": 1,
                "new_confirmed_count": 1,
                "strategy_proposal_count": 1,
                "entry_allowed_count": 1,
                "position_count": 1,
                "data_blocked_count": 0,
            },
        )
        self.assertEqual(projection["as_of_date"], "2026-09-03")
        self.assertEqual(projection["demo_label"], "示例数据")
        self.assertEqual(
            {item["market"]: item["status_key"] for item in projection["markets"]},
            {"CN": "DATA_OK", "US": "DATA_OK"},
        )
        self.assertEqual(rows["600001.SH"]["stage_label"], "观察中")
        self.assertEqual(rows["600002.SH"]["stage_label"], "等待确认")
        self.assertEqual(rows["AAA"]["stage_label"], "今天出现新的确认")
        self.assertEqual(rows["BBB"]["stage_label"], "已形成交易方案")
        self.assertEqual(rows["CCC"]["stage_label"], "可入场")
        self.assertEqual(rows["600003.SH"]["stage_label"], "策略跟踪持仓")

    def test_diagnostics_show_candidate_funnel_filters_and_symbol_quality_reason(self):
        payload = deepcopy(self.payload)
        payload["candidate_markets"]["CN"].update({
            "seed_count": 12,
            "candidate_data_qualified_count": 7,
            "deep_history_requested_count": 4,
            "deep_history_ready_count": 4,
            "deep_analysis_count": 4,
            "candidate_exclusion_reason_counts": {
                "INCLUDED": 3,
                "HISTORY_INSUFFICIENT": 4,
                "SECTOR_TOP_N_EXCEEDED": 5,
            },
        })
        payload["funnel"] = {
            "CN": {
                "seed": 12,
                "candidate_data_qualified": 7,
                "candidate_included": 3,
                "deep_analysis": 4,
                "NO_TRADE": 4,
                "DATA_BLOCKED": 0,
            }
        }
        payload["cloud_daily_report"] = {
            "market": "CN",
            "status": "PARTIAL_DATA_QUALITY",
            "data_quality": {
                "counts": {"DATA_OK": 2, "DATA_BAD": 1},
                "failed_symbols": ["600001.SH"],
            },
            "provider_status": {
                "600001.SH": {"qfq": "FAILED:RuntimeError"},
            },
            "errors": ["CN|600001.SH: qfq yfinance 数据日期落后于 T"],
        }

        projection = build_dashboard_projection(payload)
        diagnostics = projection["diagnostics"]
        self.assertEqual(diagnostics["status"], "DATA_ISSUE")
        self.assertEqual(diagnostics["coverage"]["deep_analysis_count"], 4)
        self.assertEqual(
            diagnostics["candidate"]["filter_reasons"],
            [
                {"reason": "SECTOR_TOP_N_EXCEEDED", "count": 5},
                {"reason": "HISTORY_INSUFFICIENT", "count": 4},
            ],
        )
        self.assertTrue(any(item["symbol"] == "600001.SH" for item in diagnostics["data_issues"]))
        rendered = render_dashboard_html(payload)
        self.assertIn("少量标的数据异常", rendered)
        self.assertIn("复权行情日期早于数据日期", rendered)
        self.assertIn("历史行情不足", rendered)

    def test_closeout_case_a_partial_candidate_keeps_report_warning_level(self):
        payload = _candidate_closeout_payload(
            quality_errors=[
                "US Candidate status: PARTIAL_DATA_QUALITY",
                "US Candidate candidate_short_history: PARTIAL_DATA_QUALITY",
                "US Candidate candidate_selector: PARTIAL_DATA_QUALITY",
                "US Candidate: HOLX:PROVIDER_SYMBOL_ERROR:YAHOO_CHART_SYMBOL_ERROR:HTTP_404",
                "US Candidate: HUBB:LookupError:YAHOO_CHART返回日期落后于目标交易日：2026-10-06<2026-10-07",
                "US Candidate: UHAL-B:LookupError:YAHOO_CHART返回日期落后于目标交易日：2026-10-06<2026-10-07",
                "US Candidate: UWMC-RTWI:PROVIDER_SYMBOL_ERROR:YAHOO_CHART_SYMBOL_ERROR:HTTP_404",
                "US Candidate: WBD:LookupError:YAHOO_CHART返回日期落后于目标交易日：2026-10-05<2026-10-07",
            ],
        )
        projection = build_dashboard_projection(payload)
        diagnostics = projection["diagnostics"]
        rendered = render_dashboard_html(payload)

        self.assertEqual(diagnostics["severity"], "PARTIAL_WARNING")
        self.assertEqual(len(diagnostics["presentation_issues"]), 5)
        self.assertEqual(len(diagnostics["component_summaries"]), 1)
        self.assertIn("候选发现：部分完成", rendered)
        self.assertEqual(rendered.count("候选发现：部分完成"), 1)
        self.assertIn("日报主体可用，少量候选标的数据异常", rendered)
        self.assertIn("正常筛选排除", rendered)
        self.assertIn("单股价格超过1000美元预算", rendered)
        self.assertNotIn('class="diagnostic-panel diagnostic-danger"', rendered)

    def test_closeout_case_b_translated_component_reasons_are_one_summary(self):
        payload = _candidate_closeout_payload(
            quality_errors=[
                "US Candidate status: PARTIAL_DATA_QUALITY",
                "US Candidate candidate_short_history: PARTIAL_DATA_QUALITY",
                "US Candidate candidate_selector: PARTIAL_DATA_QUALITY",
                "US Candidate: HOLX:PROVIDER_SYMBOL_ERROR:YAHOO_CHART_SYMBOL_ERROR:query1:HTTP_404",
                "US Candidate: HOLX:LookupError:YAHOO_CHART_SYMBOL_ERROR:query2:HTTP_404",
            ]
        )
        projection = build_dashboard_projection(payload)
        rendered = render_dashboard_html(payload)
        self.assertEqual(len(projection["diagnostics"]["data_issues"]), 2)
        self.assertEqual(len(projection["diagnostics"]["presentation_issues"]), 1)
        self.assertEqual(projection["diagnostics"]["presentation_deduplicated_count"], 1)
        self.assertEqual(projection["diagnostics"]["presentation_duplicate_count"], 0)
        self.assertEqual(rendered.count("候选发现：部分完成"), 1)
        self.assertEqual(rendered.count("行情接口未提供该标的数据"), 1)
        self.assertNotIn("候选发现组件", rendered)

    def test_closeout_case_c_symbol_prefixed_error_keeps_symbol_identity(self):
        payload = _candidate_closeout_payload(
            quality_errors=[
                "US Candidate: HOLX:PROVIDER_SYMBOL_ERROR:YAHOO_CHART_SYMBOL_ERROR:HTTP_404",
            ]
        )
        diagnostics = build_dashboard_projection(payload)["diagnostics"]
        self.assertEqual(diagnostics["presentation_issues"][0]["symbol"], "HOLX")
        self.assertNotIn("候选发现组件", str(diagnostics["presentation_issues"]))
        rendered = render_dashboard_html(payload)
        self.assertIn("HOLX", rendered)
        self.assertIn("行情接口未提供该标的数据", rendered)

    def test_closeout_case_d_normal_exclusions_are_not_abnormal_issues(self):
        payload = _candidate_closeout_payload(
            candidate_status="SUCCESS",
            candidate_runtime_status="SUCCESS",
            quality_errors=[],
        )
        projection = build_dashboard_projection(payload)
        rendered = render_dashboard_html(payload)
        self.assertEqual(projection["diagnostics"]["presentation_issues"], [])
        self.assertIn("正常筛选排除", rendered)
        self.assertIn("历史行情不足", rendered)
        self.assertNotIn('class="diagnostic-issues"', rendered)

    def test_closeout_case_e_exact_session_readiness_reason_is_translated(self):
        payload = _candidate_closeout_payload(quality_errors=[])
        rendered = render_dashboard_html(payload)
        self.assertIn("数据日期与分析覆盖满足正式日报要求", rendered)
        self.assertNotIn("正式日报状态：正式日报可发送；原因：未提供", rendered)

    def test_closeout_case_f_formal_not_ready_is_blocking_red(self):
        payload = _candidate_closeout_payload(
            candidate_status="SUCCESS",
            candidate_runtime_status="SUCCESS",
            quality_errors=[],
            readiness="UPSTREAM_NOT_READY",
            readiness_reason="FORMAL_EXACT_T_NOT_READY",
        )
        projection = build_dashboard_projection(payload)
        rendered = render_dashboard_html(payload)
        self.assertEqual(projection["diagnostics"]["severity"], "BLOCKING_ERROR")
        self.assertIn("diagnostic-danger", rendered)
        self.assertIn("正式标的没有覆盖到数据日期", rendered)

    def test_closeout_case_g_ledger_failure_is_separate_from_candidate_warning(self):
        payload = _candidate_closeout_payload(
            quality_errors=[
                "US Candidate: HOLX:PROVIDER_SYMBOL_ERROR:YAHOO_CHART_SYMBOL_ERROR:HTTP_404",
            ],
            ledger_status="FAILED",
        )
        projection = build_dashboard_projection(payload)
        rendered = render_dashboard_html(payload)
        self.assertEqual(projection["diagnostics"]["severity"], "PARTIAL_WARNING")
        self.assertIsNotNone(projection["diagnostics"]["ledger_blocker"])
        self.assertIn("机会观察账本写入失败", rendered)
        self.assertIn("候选发现：部分完成", rendered)
        self.assertIn("diagnostic-warning", rendered)
        self.assertLess(rendered.index("候选发现：部分完成"), rendered.index("机会观察账本写入失败"))

    def test_diagnostics_distinguish_normal_no_signal_from_missing_coverage(self):
        payload = _new_confirmation_no_trade_payload("RR_BELOW_MINIMUM")
        payload["results"][0]["event_was_new"] = False
        payload["candidate_markets"] = {
            "CN": {
                "status": "SUCCESS",
                "seed_count": 4,
                "candidate_data_qualified_count": 3,
                "candidate_included_count": 1,
                "deep_history_ready_count": 1,
                "deep_analysis_count": 1,
                "candidate_exclusion_reason_counts": {
                    "INCLUDED": 1,
                    "CN_MINIMUM_NOTIONAL_OVER_20000": 2,
                    "HISTORY_STALE": 1,
                },
            }
        }
        payload["funnel"] = {"CN": {"deep_analysis": 1, "NO_TRADE": 1}}
        diagnostics = build_dashboard_projection(payload)["diagnostics"]
        self.assertEqual(diagnostics["status"], "NORMAL_NO_SIGNAL")
        self.assertEqual(diagnostics["coverage"]["signal_count"], 0)

    def test_html_prioritizes_focus_and_retains_all_static_stock_results(self):
        rendered = render_dashboard_html(self.payload)

        self.assertIn("今日重点", rendered)
        self.assertIn("let activeView = 'focus';", rendered)
        self.assertNotIn('<article class="stock-row" hidden', rendered)
        for symbol in ("600001.SH", "600002.SH", "AAA", "BBB", "CCC", "600003.SH"):
            self.assertIn(f'<span class="ticker">{symbol}</span>', rendered)
        self.assertIn("已满足条件 / 现有依据", rendered)
        self.assertIn("未满足条件 / 不交易原因", rendered)

    def test_core_evaluation_error_is_not_presented_as_normal_no_trade(self):
        payload = _new_confirmation_no_trade_payload("RR_BELOW_MINIMUM")
        row = payload["results"][0]
        row.update(data_status="DATA_OK", final_status="NO_TRADE", event_was_new=False,
                   new_confirmed_event_identities=[], individual_decision=None,
                   individual_decision_candidates=[], setup01_state="NONE", setup02_state="NONE",
                   reasons=["UPSTREAM_EVALUATION_FAILED: controlled"])
        projection = build_dashboard_projection(payload)
        self.assertEqual(projection["rows"][0]["stage_key"], "DATA_BLOCKED")
        self.assertEqual(projection["summary"]["completed_analysis_count"], 0)
        self.assertEqual(row["final_status"], "NO_TRADE")
        rendered = render_dashboard_html(payload)
        self.assertIn('<details class="diagnostic-issues"><summary>', rendered)
        self.assertIn("UPSTREAM_EVALUATION_FAILED: controlled", rendered)
        self.assertIn('<details class="diagnostic-technical"><summary>', rendered)

    def test_diagnostics_keep_normal_zero_partial_and_all_unavailable_distinct(self):
        normal = _new_confirmation_no_trade_payload("RR_BELOW_MINIMUM")
        normal["results"][0]["event_was_new"] = False
        normal["candidate_markets"] = {
            "CN": {
                "status": "NO_CANDIDATES",
                "candidate_selection_outcome": "NO_CANDIDATES",
                "seed_count": 20,
                "candidate_data_qualified_count": 20,
                "candidate_included_count": 0,
                "candidate_exclusion_reason_counts": {
                    "CN_MINIMUM_NOTIONAL_OVER_20000": 20,
                },
                "stage_timings": {
                    "candidate_short_history": {"status": "SUCCESS"},
                    "deep_history": {"status": "NOT_REQUIRED"},
                },
            }
        }
        normal_html = render_dashboard_html(normal)
        self.assertIn("初筛数据完整，按既有规则没有候选", normal_html)
        self.assertIn("覆盖已完成，今天没有交易信号", normal_html)
        self.assertIn("CONFIRM_REJECT", normal_html)

        partial = deepcopy(self.payload)
        partial["candidate_markets"]["CN"].update({
            "status": "PARTIAL_DATA_QUALITY",
            "candidate_selection_outcome": "CANDIDATES_INCLUDED",
            "errors": ["CANDIDATE_SHORT_HISTORY_INCOMPLETE:usable=0,seed=20"],
            "stage_timings": {
                "candidate_short_history": {"status": "PARTIAL_DATA_QUALITY"},
                "deep_history": {"status": "NOT_REQUIRED"},
            },
        })
        partial_html = render_dashboard_html(partial)
        self.assertIn("候选链路存在少量待复核项", partial_html)
        self.assertIn("日报主体可用，少量候选标的数据异常", partial_html)
        self.assertIn("CANDIDATE_SHORT_HISTORY_INCOMPLETE", partial_html)

        unavailable = _new_confirmation_no_trade_payload("DATA_QUALITY_STALE")
        unavailable["results"][0].update({
            "symbol": "NO_DATA",
            "data_status": "DATA_UNAVAILABLE",
            "event_was_new": False,
            "final_status": "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED",
            "reasons": ["QFQ_HISTORY_MUST_REACH_COMPLETED_SESSION_T"],
        })
        unavailable["candidate_markets"] = {
            "CN": {
                "status": "FAILED",
                "candidate_selection_outcome": "DISCOVERY_FAILED",
                "seed_count": 20,
                "candidate_data_qualified_count": 0,
                "candidate_included_count": 0,
                "errors": ["CANDIDATE_SHORT_HISTORY_yfinance: returned empty batch"],
                "stage_timings": {
                    "candidate_short_history": {"status": "FAILED"},
                },
            }
        }
        unavailable["cloud_daily_report"] = {
            "market": "CN",
            "status": "FAILED",
            "data_quality": {"failed_symbols": ["NO_DATA"]},
        }
        unavailable_html = render_dashboard_html(unavailable)
        self.assertIn("候选发现失败，覆盖不完整", unavailable_html)
        self.assertIn("少量标的数据异常", unavailable_html)
        self.assertIn("NO_DATA", unavailable_html)

    def test_default_focus_contains_only_actionable_or_exception_rows(self):
        projection = build_dashboard_projection(self.payload)
        focus_rows = [row for row in projection["rows"] if row["default_focus"]]

        self.assertEqual(
            {row["stage_key"] for row in focus_rows},
            {
                "ARMED",
                "CONFIRMED",
                "STRATEGY_PROPOSAL",
                "ENTRY_ALLOWED",
                "POSITION_MANAGEMENT",
            },
        )
        self.assertFalse(
            any(row["stage_key"] in {"WATCH", "NO_TRADE", "FAILED"} for row in focus_rows)
        )
        self.assertEqual(len(focus_rows), 5)
        self.assertEqual(len(projection["rows"]), 6)

    def test_low_priority_rows_remain_in_all_data_and_diagnostics(self):
        payload = deepcopy(self.payload)
        results = payload["reports"][0]["报告"]["results"]
        results.extend(
            [
                {
                    "symbol": "LOW1",
                    "market": "CN",
                    "data_status": "DATA_OK",
                    "primary_wave_scenario": "NO_VALID_SCENARIO",
                    "setup01_state": "NONE",
                    "setup02_state": "NONE",
                    "primary_action": "NO_TRADE",
                    "event_was_new": False,
                    "individual_decision": None,
                    "portfolio_result": None,
                    "position_management": None,
                    "reasons": ["not today"],
                    "blocking_prerequisites": [],
                    "final_status": "NO_TRADE",
                },
                {
                    "symbol": "LOW2",
                    "market": "CN",
                    "data_status": "DATA_OK",
                    "primary_wave_scenario": "NO_VALID_SCENARIO",
                    "setup01_state": "FAILED",
                    "setup02_state": "NONE",
                    "primary_action": "NO_TRADE",
                    "event_was_new": False,
                    "individual_decision": None,
                    "portfolio_result": None,
                    "position_management": None,
                    "reasons": ["failed"],
                    "blocking_prerequisites": [],
                    "overall_status": "FAILED",
                    "final_status": "FAILED",
                },
            ]
        )

        projection = build_dashboard_projection(payload)
        rows = {row["symbol"]: row for row in projection["rows"]}

        self.assertFalse(rows["LOW1"]["default_focus"])
        self.assertFalse(rows["LOW2"]["default_focus"])
        self.assertEqual({rows["LOW1"]["stage_key"], rows["LOW2"]["stage_key"]}, {"NO_TRADE", "FAILED"})
        self.assertEqual({row["symbol"] for row in projection["rows"]}, set(rows))

    def test_setup_local_failure_does_not_invalidate_whole_symbol(self):
        payload = deepcopy(self.payload)
        payload["reports"][0]["报告"]["results"].append(
            {
                "symbol": "MIXED1",
                "market": "CN",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_3_CONTINUATION_CANDIDATE",
                "setup01_state": "FAILED",
                "setup02_state": "CONFIRMED",
                "primary_action": "NO_TRADE",
                "event_was_new": False,
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": ["T 日没有新的 CONFIRMED event"],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
            }
        )

        row = next(
            row for row in build_dashboard_projection(payload)["rows"]
            if row["symbol"] == "MIXED1"
        )

        self.assertEqual(row["stage_key"], "NO_TRADE")
        self.assertEqual(row["stage_label"], "今天不交易")
        self.assertNotEqual(row["waiting"], "结构已失效，今天不交易")

    def test_persistent_confirmed_is_not_rendered_as_a_new_confirmation(self):
        payload = deepcopy(self.payload)
        payload["reports"][0]["报告"]["results"].append(
            {
                "symbol": "PERSISTENT1",
                "market": "CN",
                "as_of_date": "2026-09-03",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "setup01_state": "CONFIRMED",
                "setup02_state": "NONE",
                "primary_action": "NO_TRADE",
                "event_was_new": False,
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": [],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
            }
        )

        row = next(
            row for row in build_dashboard_projection(payload)["rows"]
            if row["symbol"] == "PERSISTENT1"
        )

        self.assertEqual(row["stage_key"], "NO_TRADE")
        self.assertEqual(row["stage_label"], "今天不交易")
        self.assertEqual(row["waiting"], "今天没有新的交易信号。")
        self.assertNotEqual(row["status_label"], "今日确认")

    def test_single_setup_failure_is_not_overall_failure_without_overall_status(self):
        payload = deepcopy(self.payload)
        payload["reports"][0]["报告"]["results"].append(
            {
                "symbol": "LOCALFAIL1",
                "market": "CN",
                "as_of_date": "2026-09-03",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "setup01_state": "FAILED",
                "setup02_state": "NONE",
                "primary_action": "NO_TRADE",
                "event_was_new": False,
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": ["setup01 failed"],
                "blocking_prerequisites": [],
                "final_status": "FAILED",
            }
        )

        row = next(
            row for row in build_dashboard_projection(payload)["rows"]
            if row["symbol"] == "LOCALFAIL1"
        )

        self.assertEqual(row["stage_key"], "NO_TRADE")
        self.assertEqual(row["stage_label"], "今天不交易")
        self.assertNotIn("已失效", row["waiting"])

    def test_plain_view_formats_prices_and_keeps_long_float_in_audit_only(self):
        payload = deepcopy(self.payload)
        payload["reports"][1]["报告"]["results"].append(
            {
                "symbol": "FLOAT1",
                "market": "US",
                "as_of_date": "2026-09-03",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "setup01_state": "CONFIRMED",
                "setup02_state": "NONE",
                "primary_action": "ENTRY_ALLOWED",
                "event_was_new": False,
                "individual_decision": {
                    "action": "ENTRY_ALLOWED",
                    "planned_entry": 3.737499999999997,
                    "execution_stop": 1.0658307210031355,
                    "targets": [4.25],
                    "rr": {"rr_ratios": [2.73456789]},
                },
                "portfolio_result": {"status": "PORTFOLIO_ALLOWED"},
                "position_management": None,
                "reasons": [],
                "blocking_prerequisites": [],
                "final_status": "PORTFOLIO_ALLOWED",
            }
        )

        projection = build_dashboard_projection(payload)
        row = next(row for row in projection["rows"] if row["symbol"] == "FLOAT1")
        self.assertEqual(row["plan"]["planned_entry"], "3.7375")
        self.assertEqual(row["plan"]["execution_stop"], "1.0658")
        self.assertEqual(row["plan"]["rr"], "2.73")

        rendered = render_dashboard_html(payload)
        start = rendered.index('data-search="FLOAT1')
        end = rendered.index("</article>", start)
        float_card = rendered[start:end]
        user_view = float_card.split('<details class="technical-details">', 1)[0]
        self.assertIn("3.74", user_view)
        self.assertNotIn("3.737499999999997", user_view)
        self.assertIn("查看技术详情 / 审计信息", rendered)

    def test_new_confirmation_without_entry_plan_is_explained_as_not_trade(self):
        rows = {
            row["symbol"]: row
            for row in build_dashboard_projection(self.payload)["rows"]
        }

        self.assertEqual(rows["AAA"]["waiting"], "今天出现确认，但当前入场条件没有通过。")
        self.assertNotIn("等待交易方案形成", rows["AAA"]["waiting"])

    def test_new_confirmation_no_trade_first_layer_exposes_existing_gate_facts(self):
        cases = (
            (
                "ABOVE_ENTRY_ZONE",
                {"entry_zone_upper_distance_pct": 0.03},
                ("确认成功", "超过入场区", "→ 不交易"),
            ),
            (
                "TARGET_UPSIDE_BELOW_MINIMUM",
                {
                    "target_upside_pct": 0.03,
                    "minimum_target_upside_pct": 0.05,
                    "entry_zone_upper_distance_pct": -0.01,
                },
                ("确认成功", "仍在入场区", "第一目标空间 3.00% < 5.00%", "→ 不交易"),
            ),
            (
                "RR_BELOW_MINIMUM",
                {
                    "target_upside_pct": 0.1426,
                    "entry_zone_upper_distance_pct": -0.01,
                    "rr": {"rr_ratios": [0.88], "quality": "NO_TRADE"},
                },
                ("确认成功", "仍在入场区", "第一目标空间 14.26%", "R/R 0.88", "R/R不足", "→ 不交易"),
            ),
            (
                "STALE_CONFIRMATION_GEOMETRY",
                {},
                ("确认成功", "确认结构已过期", "→ 不交易"),
            ),
            (
                "NO_VALID_TARGET",
                {},
                ("确认成功", "没有有效 T1 目标", "→ 不交易"),
            ),
        )

        for gate_reason, fields, expected_fragments in cases:
            with self.subTest(gate_reason=gate_reason):
                payload = _new_confirmation_no_trade_payload(gate_reason, **fields)
                projection = build_dashboard_projection(payload)
                row = projection["rows"][0]
                self.assertEqual(row["stage_key"], "CONFIRMED")
                for fragment in expected_fragments:
                    self.assertIn(fragment, row["waiting"])

                rendered = render_dashboard_html(payload)
                card_start = rendered.index('data-search="CONFIRM_REJECT')
                card_end = rendered.index("</article>", card_start)
                first_layer = rendered[card_start:card_end].split(
                    '<details class="technical-details">', 1
                )[0]
                for fragment in expected_fragments:
                    self.assertIn(fragment.replace("<", "&lt;"), first_layer)

    def test_new_confirmation_no_trade_missing_display_facts_does_not_recompute_them(self):
        payload = _new_confirmation_no_trade_payload(
            "RR_BELOW_MINIMUM",
            planned_entry=100.0,
            targets=[114.26],
            execution_stop=90.0,
            rr={"rr_ratios": [0.88], "quality": "NO_TRADE"},
        )

        row = build_dashboard_projection(payload)["rows"][0]

        self.assertIn("R/R 0.88", row["waiting"])
        self.assertIn("R/R不足", row["waiting"])
        self.assertNotIn("< 2", row["waiting"])
        self.assertNotIn("T1空间", row["waiting"])
        self.assertNotIn("仍在入场区", row["waiting"])

    def test_unknown_confirmation_rejection_keeps_generic_fallback(self):
        payload = _new_confirmation_no_trade_payload("UNMAPPED_GATE")

        row = build_dashboard_projection(payload)["rows"][0]

        self.assertEqual(row["waiting"], "今天出现确认，但当前入场条件没有通过。")

    def test_watch_and_armed_never_invent_entry(self):
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        self.assertEqual(rows["600001.SH"]["waiting"], "继续观察，暂不买入")
        self.assertEqual(rows["600001.SH"]["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(rows["600002.SH"]["waiting"], "等待收盘突破 123.45。")
        self.assertEqual(rows["600002.SH"]["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(rows["600002.SH"]["plan"]["execution_stop"], "—")

    def test_armed_setup01_shows_estimated_wave3_targets_and_keeps_observation_semantics(self):
        payload = {
            "as_of_date": "2026-09-30",
            "results": [{
                "symbol": "ARMED.WAVE3",
                "market": "CN",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "alternate_wave_scenario": "UPTREND_UNKNOWN_WAVE",
                "setup01_state": "ARMED",
                "setup02_state": "NONE",
                "primary_action": "WAIT_CONFIRMATION",
                "event_was_new": False,
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": ["等待新的 CONFIRMED event"],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
                "armed_opportunity": {
                    "projection": "ARMED_OPPORTUNITY_PROJECTION_V1",
                    "status": "AVAILABLE",
                    "state": "ARMED",
                    "setup_type": "SETUP_01",
                    "current_close": 100.0,
                    "confirmation_level": 105.0,
                    "distance_to_confirmation": 5.0,
                    "distance_to_confirmation_pct": 0.05,
                    "structural_invalidation": 90.0,
                    "atr14": 2.0,
                    "expected_entry_zone_low": 105.0,
                    "expected_entry_zone_high": 106.0,
                    "wave3_projection_status": "AVAILABLE",
                    "wave3_missing_reasons": [],
                    "wave3_fib_extensions": [
                        {"ratio": 1.272, "ratio_label": "1.272", "price": 120.0, "upside_pct": 0.20},
                        {"ratio": 1.618, "ratio_label": "1.618", "price": 130.0, "upside_pct": 0.30},
                        {"ratio": 2.0, "ratio_label": "2.0", "price": 140.0, "upside_pct": 0.40},
                        {"ratio": 2.618, "ratio_label": "2.618", "price": 160.0, "upside_pct": 0.60},
                    ],
                    "guidance": "等待收盘确认；当前仅为观察，不是买入信号。",
                    "missing_reasons": [],
                    "is_trade_signal": False,
                },
            }],
        }

        projection = build_dashboard_projection(payload)
        row = projection["rows"][0]
        self.assertEqual(row["manual_opportunity"]["wave3_targets"][1]["price"], 130.0)
        rendered = render_dashboard_html(payload)
        self.assertIn("人工机会判断", rendered)
        self.assertIn("预估3浪目标与上涨空间", rendered)
        self.assertIn("斐波那契 1.618", rendered)
        self.assertIn("130", rendered)
        self.assertIn("+30.00%", rendered)
        self.assertIn("观察中，不是买入信号", rendered)
        self.assertNotIn("确认后的交易判断", rendered)

    def test_confirmed_target_projection_is_human_first_and_formal_gate_remains_visible(self):
        payload = _new_confirmation_no_trade_payload(
            "RR_BELOW_MINIMUM",
            planned_entry=100.0,
            confirmation_level=98.0,
            entry_zone_low=98.0,
            entry_zone_high=101.0,
            structural_invalidation=90.0,
            execution_stop=89.0,
            targets=[102.0, 130.0, 150.0],
            target_upside_pct=0.02,
            minimum_target_upside_pct=0.05,
            rr={"rr_ratios": [0.2], "quality": "NO_TRADE"},
            target_projection={
                "current_effective_t1": 102.0,
                "effective_t1_source": "CONFIRMED_SWING_HIGH",
                "nearest_overhead_confirmed_swing_high": {"price": 102.0},
                "overhead_resistance_upside_pct": 0.02,
                "wave3_fib_extensions": [
                    {"ratio": 1.272, "ratio_label": "1.272", "price": 120.0, "upside_pct": 0.20},
                    {"ratio": 1.618, "ratio_label": "1.618", "price": 140.0, "upside_pct": 0.40},
                    {"ratio": 2.0, "ratio_label": "2.0", "price": 160.0, "upside_pct": 0.60},
                    {"ratio": 2.618, "ratio_label": "2.618", "price": 190.0, "upside_pct": 0.90},
                ],
            },
        )
        payload["results"][0]["opportunity_freshness"] = {
            "target_upside_pct": 0.02,
            "target_upside_band": "BELOW_MINIMUM",
            "minimum_target_upside_pct": 0.05,
            "entry_zone_upper_distance_pct": -0.01,
        }

        row = build_dashboard_projection(payload)["rows"][0]
        self.assertEqual(row["stage_key"], "CONFIRMED")
        self.assertEqual(row["manual_opportunity"]["formal_t1"], 102.0)
        rendered = render_dashboard_html(payload)
        self.assertLess(rendered.index("人工机会判断"), rendered.index("确认后的交易判断"))
        self.assertIn("3浪斐波那契 1.618", rendered)
        self.assertIn("第一目标 R/R 未达到系统最低要求", rendered)
        self.assertIn("确认后的交易判断", rendered)
        self.assertIn("机会新鲜度", rendered)
        self.assertIn("结构与判断依据（展开）", rendered)
        self.assertNotIn("142.8699951171875", rendered)

    def test_above_entry_zone_is_explained_without_recomputing_targets(self):
        payload = _new_confirmation_no_trade_payload(
            "ABOVE_ENTRY_ZONE",
            planned_entry=110.0,
            confirmation_level=100.0,
            entry_zone_low=100.0,
            entry_zone_high=105.0,
            structural_invalidation=90.0,
            wave1_origin=60.0,
        )

        row = build_dashboard_projection(payload)["rows"][0]
        self.assertEqual(row["decision"]["action"], "NO_TRADE")
        self.assertEqual(row["decision"]["gate_reason"], "ABOVE_ENTRY_ZONE")
        self.assertIsNone(row["manual_opportunity"]["formal_t1"])
        self.assertIsNone(row["manual_opportunity"]["first_rr"])
        self.assertEqual(
            [item["label"] for item in row["manual_opportunity"]["wave3_targets"]],
            [
                "3浪结构目标 斐波那契 1.272",
                "3浪结构目标 斐波那契 1.618",
                "3浪结构目标 斐波那契 2.0",
                "3浪结构目标 斐波那契 2.618",
            ],
        )
        self.assertTrue(
            all(item["upside_pct"] is not None for item in row["manual_opportunity"]["wave3_targets"])
        )
        self.assertIn("允许入场区", row["manual_opportunity"]["system_conclusion"])
        rendered = render_dashboard_html(payload)
        self.assertIn("3浪结构目标 / 人工机会空间", rendered)
        self.assertIn("斐波那契 1.272", rendered)
        self.assertIn("斐波那契 1.618", rendered)
        self.assertIn("斐波那契 2.0", rendered)
        self.assertIn("斐波那契 2.618", rendered)
        self.assertIn("不等同正式第一至第三目标", rendered)
        self.assertIn("确认有效，但当前参考价已超过允许入场区上沿，因此本次不追高。", rendered)
        self.assertNotIn("第一障碍 / T1</div><div class=\"price\">140", rendered)

    def test_watch_with_and_without_wave3_context_are_explicit(self):
        base = {
            "as_of_date": "2026-09-30",
            "results": [{
                "symbol": "WATCH.WAVE3",
                "market": "US",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "alternate_wave_scenario": "UNKNOWN",
                "setup01_state": "WATCH",
                "setup02_state": "NONE",
                "primary_action": "WATCH",
                "event_was_new": False,
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": [],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
                "armed_opportunity": {
                    "status": "AVAILABLE",
                    "state": "WATCH",
                    "setup_type": "SETUP_01",
                    "current_close": 100.0,
                    "confirmation_level": 105.0,
                    "distance_to_confirmation_pct": 0.05,
                    "structural_invalidation": 90.0,
                    "expected_entry_zone_low": 105.0,
                    "expected_entry_zone_high": 106.0,
                    "wave3_projection_status": "DATA_UNAVAILABLE",
                    "wave3_missing_reasons": ["WAVE1_ORIGIN_UNAVAILABLE"],
                    "wave3_fib_extensions": [],
                    "missing_reasons": [],
                    "guidance": "当前仍在观察阶段；当前仅为观察，不是买入信号。",
                },
            }],
        }
        missing_html = render_dashboard_html(base)
        self.assertIn("当前缺少：缺少1浪起点", missing_html)
        self.assertIn("不能在展示层重新推算", missing_html)
        self.assertNotIn("斐波那契 1.618", missing_html)

        complete = deepcopy(base)
        complete["results"][0]["armed_opportunity"].update({
            "wave3_projection_status": "AVAILABLE",
            "wave3_missing_reasons": [],
            "wave3_fib_extensions": [
                {"ratio": 1.272, "ratio_label": "1.272", "price": 120.0, "upside_pct": 0.20},
                {"ratio": 1.618, "ratio_label": "1.618", "price": 130.0, "upside_pct": 0.30},
            ],
        })
        complete_html = render_dashboard_html(complete)
        self.assertIn("斐波那契 1.618", complete_html)
        self.assertIn("+30.00%", complete_html)

    def test_search_matches_ticker_and_company_name(self):
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        self.assertTrue(dashboard_search_matches(rows["600001.SH"], "600001.sh"))
        self.assertTrue(dashboard_search_matches(rows["600001.SH"], "示例科技"))
        self.assertTrue(dashboard_search_matches(rows["600001.SH"], ""))
        self.assertFalse(dashboard_search_matches(rows["600001.SH"], "不存在的股票"))

    def test_data_blocked_is_visible_without_fabricated_plan(self):
        payload = deepcopy(self.payload)
        payload["reports"][0]["报告"]["results"].append(
            {
                "symbol": "600099.SH",
                "market": "CN",
                "as_of_date": "2026-09-03",
                "data_status": "DATA_STALE",
                "primary_wave_scenario": "NO_VALID_SCENARIO",
                "alternate_wave_scenario": "UNKNOWN",
                "setup01_state": "NONE",
                "setup02_state": "NONE",
                "primary_action": "NO_TRADE",
                "individual_decision": None,
                "portfolio_result": None,
                "position_management": None,
                "reasons": ["DATA_QUALITY_STALE"],
                "blocking_prerequisites": [],
                "final_status": "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED",
            }
        )

        projection = build_dashboard_projection(payload)
        blocked = next(row for row in projection["rows"] if row["symbol"] == "600099.SH")
        self.assertEqual(blocked["stage_key"], "DATA_BLOCKED")
        self.assertEqual(blocked["stage_label"], "数据异常")
        self.assertTrue(blocked["default_focus"])
        self.assertEqual(blocked["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(projection["summary"]["data_blocked_count"], 1)
        self.assertEqual(
            next(item for item in projection["markets"] if item["market"] == "CN")["status_key"],
            "DATA_BLOCKED",
        )

    def test_existing_decision_and_position_fields_are_presented_with_safe_formatting(self):
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        proposal = rows["BBB"]["plan"]
        self.assertEqual(proposal["planned_entry"], "200")
        self.assertEqual(proposal["execution_stop"], "190")
        self.assertEqual(proposal["target_1"], "220")
        self.assertEqual(proposal["target_2"], "230")
        self.assertEqual(proposal["target_3"], "240")
        self.assertEqual(proposal["rr"], "2.00 / 3.00 / 4.00")
        self.assertEqual(rows["BBB"]["waiting"], "等待人工批准该交易方案")

        entry = rows["CCC"]["plan"]
        self.assertEqual(rows["CCC"]["stage_label"], "可入场")
        self.assertEqual(entry["planned_entry"], "300")
        self.assertEqual(rows["CCC"]["waiting"], "当前满足入场条件，等待 2026-09-04 US。")

        position = rows["600003.SH"]["position"]
        self.assertEqual(position["actual_entry"], "100")
        self.assertEqual(position["current_price"], "112")
        self.assertEqual(position["active_protective_stop"], "104")
        self.assertEqual(position["next_session_protective_stop"], "106")
        self.assertEqual(position["targets"], ("120", "130", "140"))
        self.assertEqual(position["current_r"], "+1.20R")
        self.assertEqual(position["mfe_r"], "+1.80R")
        self.assertEqual(position["mae_r"], "-0.20R")
        self.assertEqual(position["mfe_drawdown_r"], "+0.60R")
        self.assertEqual(position["action"], "HOLD")
        self.assertEqual(position["action_label"], "继续持有")

    def test_rejected_decision_calculation_is_not_rendered_as_dashboard_plan(self):
        payload = deepcopy(self.payload)
        result = payload["reports"][1]["报告"]["results"][1]
        result["symbol"] = "REJECTED"
        result["primary_action"] = "NO_TRADE"
        result["individual_decision"]["action"] = "NO_TRADE"
        result["individual_decision"]["gate_reason"] = "RR_BELOW_MINIMUM"
        result["final_status"] = "NO_TRADE"
        result["portfolio_result"] = None

        projection = build_dashboard_projection(payload)
        row = next(row for row in projection["rows"] if row["symbol"] == "REJECTED")

        self.assertEqual(row["stage_key"], "NO_TRADE")
        self.assertTrue(row["plan"]["has_decision"])
        self.assertEqual(row["plan"]["planned_entry"], "200")

        rendered = render_dashboard_html(payload)
        start = rendered.index('data-search="REJECTED')
        end = rendered.index("</article>", start)
        rejected_card = rendered[start:end]
        self.assertIn("人工机会判断", rejected_card)
        self.assertNotIn("关键价格", rejected_card)
        self.assertNotIn("入场区间", rejected_card)

    def test_target_upside_rejection_is_humanized_in_opportunity_freshness_detail(self):
        payload = {
            "as_of_date": "2026-09-14",
            "results": [{
                "symbol": "600941.SH",
                "market": "CN",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "alternate_wave_scenario": "UNKNOWN",
                "setup01_state": "CONFIRMED",
                "setup02_state": "NONE",
                "primary_action": "NO_TRADE",
                "event_was_new": True,
                "individual_decision": {
                    "action": "NO_TRADE",
                    "gate_reason": "TARGET_UPSIDE_BELOW_MINIMUM",
                    "planned_entry": 98.16,
                    "execution_stop": 94.31,
                    "targets": [98.6825],
                    "target_upside_pct": (98.6825 - 98.16) / 98.16,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                    "entry_zone_upper_distance_pct": -0.01,
                    "rr": {"rr_ratios": [0.14], "quality": "NO_TRADE"},
                },
                "opportunity_freshness": {
                    "target_upside_pct": (98.6825 - 98.16) / 98.16,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                    "entry_zone_upper_distance_pct": -0.01,
                },
                "portfolio_result": None,
                "position_management": None,
                "reasons": [],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
            }],
        }

        projection = build_dashboard_projection(payload)
        row = projection["rows"][0]
        self.assertEqual(row["plan"]["target_upside_pct"], "0.53%")
        rendered = render_dashboard_html(payload)
        self.assertIn("机会新鲜度", rendered)
        self.assertIn("目标空间不足", rendered)
        self.assertIn("0.53%", rendered)
        self.assertIn("5.00%", rendered)
        self.assertNotIn("最低 RR", rendered)

    def test_near_swing_only_projection_shows_resistance_and_farther_wave3_target(self):
        payload = {
            "as_of_date": "2026-09-14",
            "results": [{
                "symbol": "NEAR_SWING_ONLY",
                "market": "CN",
                "data_status": "DATA_OK",
                "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
                "alternate_wave_scenario": "UNKNOWN",
                "setup01_state": "CONFIRMED",
                "setup02_state": "NONE",
                "primary_action": "NO_TRADE",
                "event_was_new": True,
                "individual_decision": {
                    "action": "NO_TRADE",
                    "gate_reason": "TARGET_UPSIDE_BELOW_MINIMUM",
                    "planned_entry": 100.0,
                    "execution_stop": 95.0,
                    "targets": [101.0, 120.0, 130.0],
                    "target_upside_pct": 0.01,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                    "rr": {"rr_ratios": [0.2], "quality": "NO_TRADE"},
                    "target_projection": {
                        "current_effective_t1": 101.0,
                        "effective_t1_source": "CONFIRMED_SWING_HIGH",
                        "nearest_overhead_confirmed_swing_high": {"price": 101.0},
                        "overhead_resistance_upside_pct": 0.01,
                        "nearest_wave3_fib_extension": {
                            "price": 120.0,
                            "ratio": 1.272,
                            "upside_pct": 0.20,
                        },
                        "nearest_wave3_fib_extension_ratio": 1.272,
                        "wave3_fib_upside_pct": 0.20,
                        "wave3_fib_extensions": [
                            {"ratio": 1.272, "price": 120.0, "upside_pct": 0.20},
                            {"ratio": 1.618, "price": 130.0, "upside_pct": 0.30},
                        ],
                    },
                },
                "opportunity_freshness": {
                    "target_upside_pct": 0.01,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                },
                "portfolio_result": None,
                "position_management": None,
                "reasons": [],
                "blocking_prerequisites": [],
                "final_status": "NO_TRADE",
            }],
        }

        row = build_dashboard_projection(payload)["rows"][0]
        self.assertEqual(row["plan"]["effective_t1"], "101")
        self.assertEqual(row["plan"]["effective_t1_source_label"], "最近已确认历史阻力")
        self.assertEqual(row["plan"]["nearest_overhead_confirmed_swing_high"], "101")
        self.assertEqual(row["plan"]["nearest_wave3_fib_extension"], "120")
        self.assertEqual(row["plan"]["nearest_wave3_fib_extension_ratio"], "1.272")
        self.assertEqual(row["plan"]["wave3_fib_upside_pct"], "20.00%")

        rendered = render_dashboard_html(payload)
        self.assertIn("保守第一障碍（最近已确认历史阻力）", rendered)
        self.assertIn("3浪结构目标（最近斐波那契投射）", rendered)
        self.assertIn("系统不是认为3浪只有 1.00% 空间", rendered)
        self.assertIn("按现有保守规则不交易", rendered)

    def test_setup02_target_candidates_share_setup01_human_target_cards(self):
        for market, symbol in (("CN", "600901.SH"), ("US", "SETUP02.US")):
            with self.subTest(market=market):
                payload = _setup02_confirmation_payload(
                    "TARGET_UPSIDE_BELOW_MINIMUM",
                    market=market,
                    symbol=symbol,
                )
                row = build_dashboard_projection(payload)["rows"][0]
                decision = row["decision"]
                plan = row["plan"]
                manual = row["manual_opportunity"]
                expected_entry = 6.94 if market == "CN" else 100.0
                expected_t1 = 7.046002994011976 if market == "CN" else 103.0
                expected_fib = 7.0796 if market == "CN" else 103.36

                self.assertEqual(decision["gate_reason"], "TARGET_UPSIDE_BELOW_MINIMUM")
                self.assertEqual(plan["target_1"], "7.046" if market == "CN" else "103")
                self.assertEqual(
                    plan["target_upside_pct"],
                    "1.53%" if market == "CN" else "3.00%",
                )
                self.assertEqual(
                    plan["rr"],
                    "0.17 / 0.22 / 0.53",
                )
                self.assertEqual(plan["nearest_wave3_fib_extension_ratio"], "1.272")
                self.assertEqual(
                    plan["nearest_wave3_fib_extension"],
                    "7.0796" if market == "CN" else "103.36",
                )
                self.assertEqual(
                    plan["wave3_fib_upside_pct"],
                    "2.01%" if market == "CN" else "3.36%",
                )
                self.assertEqual(
                    tuple(item["ratio_label"] for item in plan["target_projection"]["wave3_fib_extensions"]),
                    ("1.272", "1.618", "2.0", "2.618"),
                )
                self.assertEqual(
                    plan["target_projection"]["wave3_fib_extensions"][0]["provenance"][0]["formula_identity"],
                    "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
                )
                self.assertEqual(
                    [item["label"] for item in manual["wave3_targets"]],
                    [
                        "第一障碍 / T1",
                        "3浪斐波那契 1.272",
                        "3浪斐波那契 1.618",
                        "3浪斐波那契 2.0",
                        "3浪斐波那契 2.618",
                    ],
                )
                self.assertAlmostEqual(
                    manual["wave3_targets"][1]["upside_pct"],
                    (expected_fib - expected_entry) / expected_entry,
                )
                self.assertEqual(manual["formal_t1"], expected_t1)
                self.assertEqual(row["today_conclusion"], "不交易：目标上涨空间不足")

                rendered = render_dashboard_html(payload)
                for label in ("第一障碍 / T1", "3浪斐波那契 1.272", "3浪斐波那契 1.618", "3浪斐波那契 2.0", "3浪斐波那契 2.618"):
                    self.assertIn(label, rendered)
                self.assertIn(
                    "较参考价 +2.01%" if market == "CN" else "较参考价 +3.36%",
                    rendered,
                )
                self.assertIn("确认有效，但第一目标剩余上涨空间不足最低要求，因此不交易。", rendered)

    def test_setup02_rr_gate_keeps_formal_rr_and_shows_all_fib_targets(self):
        payload = _setup02_confirmation_payload(
            "RR_BELOW_MINIMUM",
            market="US",
            symbol="RR.SETUP02",
        )
        row = build_dashboard_projection(payload)["rows"][0]

        self.assertEqual(row["decision"]["gate_reason"], "RR_BELOW_MINIMUM")
        self.assertEqual(row["plan"]["target_1"], "108")
        self.assertEqual(row["plan"]["target_upside_pct"], "8.00%")
        self.assertEqual(row["plan"]["rr"], "1.80 / 2.40 / 3.10")
        self.assertEqual(
            [item["label"] for item in row["manual_opportunity"]["wave3_targets"]],
            [
                "第一障碍 / T1",
                "3浪斐波那契 1.272",
                "3浪斐波那契 1.618",
                "3浪斐波那契 2.0",
                "3浪斐波那契 2.618",
            ],
        )
        rendered = render_dashboard_html(payload)
        self.assertIn("第一目标 R/R", rendered)
        self.assertIn("确认有效，但第一目标对应的 R/R 未达到系统最低要求，因此不交易。", rendered)
        self.assertIn("3浪斐波那契 2.618", rendered)

    def test_setup02_above_entry_zone_uses_causal_geometry_as_presentation_only(self):
        payload = _setup02_confirmation_payload(
            "ABOVE_ENTRY_ZONE",
            market="CN",
            symbol="600901.ABOVE",
            above_entry_zone=True,
        )
        row = build_dashboard_projection(payload)["rows"][0]
        manual = row["manual_opportunity"]

        self.assertIsNone(manual["formal_t1"])
        self.assertIsNone(manual["first_rr"])
        self.assertTrue(manual["wave3_presentation_only"])
        self.assertEqual(
            [item["label"] for item in manual["wave3_targets"]],
            [
                "3浪结构目标 斐波那契 1.272",
                "3浪结构目标 斐波那契 1.618",
                "3浪结构目标 斐波那契 2.0",
                "3浪结构目标 斐波那契 2.618",
            ],
        )
        self.assertIn("超过允许入场区上沿", manual["system_conclusion"])
        self.assertEqual(row["decision"]["gate_reason"], "ABOVE_ENTRY_ZONE")
        rendered = render_dashboard_html(payload)
        self.assertIn("不等同正式第一至第三目标", rendered)
        self.assertIn("确认有效，但当前参考价已超过允许入场区上沿，因此本次不追高。", rendered)

    def test_above_entry_zone_renders_reference_target_diagnostics_separately(self):
        payload = _setup02_confirmation_payload(
            "ABOVE_ENTRY_ZONE",
            above_entry_zone=True,
            symbol="002436.SZ",
            market="CN",
        )
        payload["results"][0]["reference_target_diagnostics"] = {
            "status": "AVAILABLE",
            "reference_t1": 44.12,
            "reference_t1_source": "CONFIRMED_SWING_HIGH",
            "reference_t1_upside_pct": 0.077,
            "reference_first_rr": 2.31,
            "note": (
                "正式系统已在超过允许入场区处判定不交易，以下数值仅供人工判断，"
                "不参与正式系统放行。"
            ),
        }

        html = render_dashboard_html(payload)

        self.assertIn("第一目标 T1", html)
        self.assertIn("未生成", html)
        self.assertIn("参考第一目标", html)
        self.assertIn("参考上涨空间", html)
        self.assertIn("参考第一目标盈亏比 R/R", html)
        self.assertIn("44.12", html)
        self.assertIn("不参与正式系统放行", html)
        self.assertEqual(
            user_visible_language_audit(html)["user_visible_raw_enum_count"],
            0,
        )

    def test_consistency_matrix_exposes_market_setup_stage_gate_metrics(self):
        payload = _setup02_confirmation_payload(
            "ABOVE_ENTRY_ZONE",
            above_entry_zone=True,
            symbol="002436.SZ",
            market="CN",
        )
        payload["results"][0]["reference_target_diagnostics"] = {
            "status": "AVAILABLE",
            "reference_t1": 44.12,
            "reference_t1_upside_pct": 0.077,
            "reference_first_rr": 2.31,
        }

        matrix = daily_report_consistency_matrix(payload)

        self.assertEqual(matrix["matrix_name"], "DAILY_REPORT_CONSISTENCY_MATRIX_V1")
        self.assertIn("CN", matrix["markets"])
        self.assertIn("SETUP_02", matrix["setups"])
        self.assertIn("CONFIRMED", matrix["stages"])
        self.assertIn("ABOVE_ENTRY_ZONE", matrix["gates"])
        case = next(
            item for item in matrix["cases"]
            if item["market"] == "CN"
            and item["setup"] == "SETUP_02"
            and item["gate"] == "ABOVE_ENTRY_ZONE"
        )
        self.assertEqual(case["count"], 1)
        self.assertEqual(case["missing_reference_or_formal_t1"], 0)
        self.assertEqual(case["missing_reference_or_formal_rr"], 0)

    def test_identity_metadata_wave_mapping_and_input_immutability(self):
        original = deepcopy(self.payload)
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        self.assertEqual(rows["600001.SH"]["name"], "示例科技<&")
        self.assertEqual(rows["600001.SH"]["sector"], "专用设备")
        self.assertEqual(rows["600002.SH"]["name"], "示例软件")
        self.assertEqual(rows["600002.SH"]["sector"], "软件服务")
        self.assertEqual(rows["600003.SH"]["name"], "示例制造")
        self.assertEqual(rows["AAA"]["name"], "示例半导体")
        self.assertEqual(rows["AAA"]["sector"], "半导体")
        self.assertEqual(rows["BBB"]["name"], "示例云计算")
        self.assertEqual(rows["CCC"]["name"], "示例安全科技")
        self.assertFalse(
            any(
                row["name"] in {"确认候选", "方案示例", "入场示例"}
                for row in rows.values()
            )
        )
        self.assertEqual(rows["600001.SH"]["primary_wave_label"], "2浪调整结束候选，等待3浪启动")
        self.assertEqual(rows["AAA"]["identity_labels"], ("候选观察池", "尚未进入正式策略池"))
        self.assertEqual(rows["BBB"]["identity_labels"], ("正式策略池",))
        self.assertEqual(rows["600003.SH"]["identity_labels"], ("正式策略池", "策略跟踪持仓"))
        self.assertEqual(self.payload, original)

    def test_missing_name_falls_back_to_dash(self):
        payload = deepcopy(self.payload)
        del payload["reports"][0]["universe"]["candidate_metadata"]["600001.SH"]["name"]

        rows = {
            row["symbol"]: row
            for row in build_dashboard_projection(payload)["rows"]
        }

        self.assertEqual(rows["600001.SH"]["name"], "—")
        self.assertEqual(rows["600001.SH"]["sector"], "专用设备")

    def test_html_is_escaped_and_contains_user_facing_guards(self):
        html = render_dashboard_html(self.payload)

        self.assertIn("示例科技&lt;&amp;", html)
        self.assertIn("示例数据", html)
        self.assertIn("专用设备", html)
        self.assertNotIn("示例科技<&", html)
        self.assertIn("关键价格", html)
        self.assertIn("候选观察池", html)
        self.assertIn("尚未进入正式策略池", html)
        self.assertIn("今天出现新的确认", html)
        self.assertIn("等待确认", html)
        self.assertIn("策略跟踪持仓", html)
        self.assertNotIn("接近确认", html)
        self.assertNotIn("当前持仓", html)
        self.assertIn("查看详情", html)
        self.assertIn("查看技术详情 / 审计信息", html)
        self.assertNotIn('<details class="technical-details" open>', html)
        self.assertIn("id=\"search-filter\"", html)
        self.assertIn("data-view=\"focus\"", html)
        self.assertIn("data-view=\"WATCH\"", html)
        self.assertIn("data-view=\"all\"", html)
        self.assertIn("querySelectorAll('.stock-row')", html)
        self.assertIn("toLocaleLowerCase", html)
        self.assertIn("data-market=\"CN\"", html)
        self.assertIn("data-stage=\"ARMED\"", html)
        self.assertIn("data-setup=\"SETUP_01\"", html)
        self.assertIn("data-sector=\"专用设备\"", html)
        watch_start = html.index('<article class="stock-row" data-market="CN" data-stage="WATCH"')
        watch_end = html.index("</article>", watch_start)
        watch_card = html[watch_start:watch_end]
        armed_start = html.index('<article class="stock-row" data-market="CN" data-stage="ARMED"')
        armed_end = html.index("</article>", armed_start)
        armed_card = html[armed_start:armed_end]
        self.assertLess(armed_card.index('<span class="ticker">600002.SH</span>'), armed_card.index('<span class="company">示例软件</span>'))
        self.assertNotIn('<section class="panel plan-panel">', watch_card)
        self.assertIn('data-focus="0"', watch_card)
        self.assertIn('data-search="600001.SH 示例科技&lt;&amp;"', watch_card)
        self.assertIn("${visible}", html)
        self.assertIn("${cards.length}", html)

    def test_compact_rows_only_render_formal_plan_fields_for_decision_stages(self):
        html = render_dashboard_html(self.payload)

        watch_start = html.index('<article class="stock-row" data-market="CN" data-stage="WATCH"')
        watch_end = html.index("</article>", watch_start)
        proposal_start = html.index('<article class="stock-row" data-market="US" data-stage="STRATEGY_PROPOSAL"')
        proposal_end = html.index("</article>", proposal_start)
        armed_start = html.index('<article class="stock-row" data-market="CN" data-stage="ARMED"')
        armed_end = html.index("</article>", armed_start)

        self.assertNotIn("交易方案", html[watch_start:watch_end])
        self.assertNotIn("交易方案", html[armed_start:armed_end])
        self.assertIn("交易方案", html[proposal_start:proposal_end])
        self.assertIn("200", html[proposal_start:proposal_end])
        self.assertIn("第一目标 T1", html[proposal_start:proposal_end])
        self.assertIn("已形成交易方案", html[proposal_start:proposal_end])

    def test_same_input_is_deterministic_and_writer_creates_latest_and_date_copy(self):
        first = render_dashboard_html(self.payload)
        second = render_dashboard_html(self.payload)
        self.assertEqual(first, second)

        with tempfile.TemporaryDirectory() as directory:
            paths = write_dashboard_html(self.payload, directory)
            self.assertEqual(
                {path.name for path in paths},
                {"latest.html", "2026-09-03.html"},
            )
            self.assertEqual(
                (Path(directory) / "latest.html").read_text(encoding="utf-8"),
                (Path(directory) / "2026-09-03.html").read_text(encoding="utf-8"),
            )

    def test_paper_workspaces_project_lifecycle_stats_and_plain_language(self):
        payload = deepcopy(self.payload)
        payload["paper_tracking"] = {
            "enabled": True,
            "result": {
                "trades": [{
                    "event_identity": "E|SETUP_01|CONFIRMED",
                    "symbol": "PAPER1",
                    "market": "US",
                    "name": "模拟示例",
                    "source_provenance": "DYNAMIC_CANDIDATE",
                    "source_setup": "SETUP_01",
                    "signal_date": "2026-09-03",
                    "expected_execution_date": "2026-09-04",
                    "status": "CLOSED",
                    "planned_entry": 100,
                    "execution_date": "2026-09-04",
                    "t1_open": 101,
                    "execution_outcome": "EXECUTED",
                    "actual_entry": 101,
                    "exit_date": "2026-09-08",
                    "exit_price": 110,
                    "exit_reason": "PROFIT_PROTECTION_EXIT_PENDING",
                    "realized_r": 1.8,
                    "return_pct": 0.089,
                    "holding_days": 3,
                    "final_mfe": 2.2,
                    "final_mae": -0.1,
                    "current_r": 1.8,
                    "why_entry": "T日收盘形成方案",
                    "why_execution": "T+1开盘满足条件",
                    "why_hold": "继续持有",
                    "why_protect": "保护利润",
                    "why_exit": "收盘触发利润保护，下一交易日退出",
                    "logic_explanation": {
                        "why_plan": "2浪调整结束 → 等待3浪启动",
                        "when_execute": "最早 exact T+1 market-session OPEN",
                        "execution_checks": "沿用现有执行检查",
                        "target_policy": "不是机械到价自动卖出",
                    },
                    "promotion_required": True,
                    "state_persistence_eligible": False,
                    "production_execution_eligible": False,
                }],
                "coverage": [{
                    "market": "US",
                    "tracking_start_date": "2026-09-03",
                    "latest_processed_session": "2026-09-08",
                    "coverage_status": "CONTINUOUS",
                    "coverage_gap": None,
                }],
                "performance": {
                    "plans": 1,
                    "executed": 1,
                    "skipped": 0,
                    "open": 0,
                    "closed": 1,
                    "wins": 1,
                    "losses": 0,
                    "flats": 0,
                    "win_rate": 1.0,
                    "average_r": 1.8,
                    "median_r": 1.8,
                    "average_return_pct": 0.089,
                    "average_holding_days": 3.0,
                    "average_mfe": 2.2,
                    "average_mae": -0.1,
                },
                "grouped_performance": {},
                "errors": [],
            },
        }

        projection = build_dashboard_projection(payload)
        self.assertTrue(projection["paper"]["enabled"])
        self.assertEqual(projection["paper"]["status_counts"], {"CLOSED": 1})
        self.assertFalse(projection["paper"]["coverage_warning"])
        html = render_dashboard_html(payload)
        for label in ("模拟交易", "绩效统计", "策略规则", "为什么买／为什么关注", "有没有真正模拟成交", "现在怎么样", "目标价只记录状态，不自动止盈"):
            self.assertIn(label, html)
        self.assertIn("模拟持仓", html)
        self.assertNotIn("当前持仓", html)
        self.assertIn("样本连续", html)
        self.assertIn("平均收益", html)
        self.assertIn("2浪调整结束后，价格重新突破1浪高点", html)
        self.assertIn("上涨趋势中的3浪延续结构完成", html)
        self.assertIn("结构失效是波浪结构被破坏的底线", html)
        self.assertIn("DYNAMIC_CANDIDATE", html)

    def test_user_visible_language_audit_excludes_developer_evidence_and_lists_allowed_abbreviations(self):
        audit = html_consistency_audit(self.payload)
        self.assertEqual(audit["USER_VISIBLE_LANGUAGE_AUDIT"]["audit_name"], "USER_VISIBLE_LANGUAGE_AUDIT")
        for key in (
            "user_visible_raw_enum_count",
            "user_visible_internal_field_count",
            "user_visible_unnecessary_english_count",
            "user_visible_mixed_language_count",
        ):
            self.assertEqual(audit[key], 0)
        self.assertEqual(audit["allowed_abbreviations"], list(USER_VISIBLE_ALLOWED_ABBREVIATIONS))
        self.assertTrue(audit["passed"])

        synthetic = (
            "<main>ABOVE_ENTRY_ZONE Decision planned_entry Wave3</main>"
            '<details class="technical-details"><summary>开发者原始数据</summary>'
            "<pre>ABOVE_ENTRY_ZONE planned_entry Wave3</pre></details>"
        )
        violation = user_visible_language_audit(synthetic)
        self.assertGreater(violation["user_visible_raw_enum_count"], 0)
        self.assertGreater(violation["user_visible_internal_field_count"], 0)
        self.assertGreater(violation["user_visible_unnecessary_english_count"], 0)
        self.assertEqual(
            user_visible_language_audit(
                '<details class="technical-details"><pre>ABOVE_ENTRY_ZONE planned_entry Wave3</pre></details>'
            )["user_visible_raw_enum_count"],
            0,
        )

        email_audit = user_visible_language_audit(render_daily_report_email_html(self.payload))
        self.assertTrue(email_audit["passed"])


if __name__ == "__main__":
    unittest.main()
