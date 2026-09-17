from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from trading.daily_dashboard import (
    build_dashboard_projection,
    dashboard_search_matches,
    load_dashboard_json,
    render_dashboard_html,
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
        self.assertEqual(projection["demo_label"], "示例数据 / Synthetic Demo")
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
        self.assertIn("3.7375", user_view)
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
                ("确认成功", "仍在入场区", "T1空间 3.00% < 5.00%", "→ 不交易"),
            ),
            (
                "RR_BELOW_MINIMUM",
                {
                    "target_upside_pct": 0.1426,
                    "entry_zone_upper_distance_pct": -0.01,
                    "rr": {"rr_ratios": [0.88], "quality": "NO_TRADE"},
                },
                ("确认成功", "仍在入场区", "T1空间 14.26%", "R/R 0.88 < 2", "→ 不交易"),
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

        self.assertIn("R/R 0.88 < 2", row["waiting"])
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
        self.assertIn("尚未形成交易计划", rejected_card)
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
        self.assertIn("Wave3 结构目标（最近 Fib 投射）", rendered)
        self.assertIn("系统不是认为 Wave3 只有 1.00% 空间", rendered)
        self.assertIn("按现有保守规则不交易", rendered)

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
        self.assertIn("示例数据 / Synthetic Demo", html)
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
        watch_start = html.index('<article class="stock-row" hidden data-market="CN" data-stage="WATCH"')
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

        watch_start = html.index('<article class="stock-row" hidden data-market="CN" data-stage="WATCH"')
        watch_end = html.index("</article>", watch_start)
        proposal_start = html.index('<article class="stock-row" data-market="US" data-stage="STRATEGY_PROPOSAL"')
        proposal_end = html.index("</article>", proposal_start)
        armed_start = html.index('<article class="stock-row" data-market="CN" data-stage="ARMED"')
        armed_end = html.index("</article>", armed_start)

        self.assertNotIn("交易方案", html[watch_start:watch_end])
        self.assertNotIn("交易方案", html[armed_start:armed_end])
        self.assertIn("交易方案", html[proposal_start:proposal_end])
        self.assertIn("200", html[proposal_start:proposal_end])
        self.assertIn("目标价 T1", html[proposal_start:proposal_end])
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


if __name__ == "__main__":
    unittest.main()
