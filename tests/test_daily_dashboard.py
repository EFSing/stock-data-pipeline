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
        self.assertEqual(rows["600002.SH"]["stage_label"], "接近确认")
        self.assertEqual(rows["AAA"]["stage_label"], "今天出现新的确认")
        self.assertEqual(rows["BBB"]["stage_label"], "已形成交易方案")
        self.assertEqual(rows["CCC"]["stage_label"], "可入场")
        self.assertEqual(rows["600003.SH"]["stage_label"], "持仓管理")

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
        self.assertEqual(position["targets"], ("120", "130", "140"))
        self.assertEqual(position["current_r"], "+1.20R")
        self.assertEqual(position["mfe_r"], "+1.80R")
        self.assertEqual(position["mae_r"], "-0.20R")
        self.assertEqual(position["mfe_drawdown_r"], "+0.60R")
        self.assertEqual(position["action"], "HOLD")
        self.assertEqual(position["action_label"], "继续持有")

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
        self.assertEqual(rows["600003.SH"]["identity_labels"], ("正式策略池", "持仓管理"))
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


if __name__ == "__main__":
    unittest.main()
