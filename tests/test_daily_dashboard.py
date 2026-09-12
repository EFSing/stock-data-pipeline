from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from trading.daily_dashboard import (
    build_dashboard_projection,
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
        self.assertEqual(rows["AAA"]["stage_label"], "今日确认")
        self.assertEqual(rows["BBB"]["stage_label"], "已形成交易方案")
        self.assertEqual(rows["CCC"]["stage_label"], "可入场")
        self.assertEqual(rows["600003.SH"]["stage_label"], "持仓管理")

    def test_watch_and_armed_never_invent_entry(self):
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        self.assertEqual(rows["600001.SH"]["waiting"], "下一步：等待结构进一步形成")
        self.assertEqual(rows["600001.SH"]["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(rows["600002.SH"]["waiting"], "确认价：123.45")
        self.assertEqual(rows["600002.SH"]["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(rows["600002.SH"]["plan"]["execution_stop"], "—")

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
        self.assertEqual(blocked["plan"]["planned_entry"], "尚未形成")
        self.assertEqual(projection["summary"]["data_blocked_count"], 1)
        self.assertEqual(
            next(item for item in projection["markets"] if item["market"] == "CN")["status_key"],
            "DATA_BLOCKED",
        )

    def test_existing_decision_and_position_fields_are_displayed_verbatim(self):
        rows = {row["symbol"]: row for row in build_dashboard_projection(self.payload)["rows"]}

        proposal = rows["BBB"]["plan"]
        self.assertEqual(proposal["planned_entry"], "200.0")
        self.assertEqual(proposal["execution_stop"], "190.0")
        self.assertEqual(proposal["target_1"], "220.0")
        self.assertEqual(proposal["target_2"], "230.0")
        self.assertEqual(proposal["target_3"], "240.0")
        self.assertEqual(proposal["rr"], "2.0R / 3.0R / 4.0R")
        self.assertEqual(rows["BBB"]["waiting"], "等待人工批准该交易方案")

        entry = rows["CCC"]["plan"]
        self.assertEqual(rows["CCC"]["stage_label"], "可入场")
        self.assertEqual(entry["planned_entry"], "300.0")
        self.assertEqual(rows["CCC"]["waiting"], "最早执行 session：2026-09-04 US")

        position = rows["600003.SH"]["position"]
        self.assertEqual(position["actual_entry"], "100.0")
        self.assertEqual(position["current_price"], "112.0")
        self.assertEqual(position["active_protective_stop"], "104.0")
        self.assertEqual(position["targets"], (120.0, 130.0, 140.0))
        self.assertEqual(position["current_r"], "1.2")
        self.assertEqual(position["mfe_r"], "1.8")
        self.assertEqual(position["mae_r"], "-0.2")
        self.assertEqual(position["mfe_drawdown_r"], "0.6")
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
        self.assertIn("计划入场", html)
        self.assertIn("尚未形成", html)
        self.assertIn("候选观察池", html)
        self.assertIn("尚未进入正式策略池", html)
        self.assertIn("今日确认", html)
        self.assertIn("data-market=\"CN\"", html)
        self.assertIn("data-stage=\"ARMED\"", html)
        self.assertIn("data-setup=\"SETUP_01\"", html)
        self.assertIn("data-sector=\"专用设备\"", html)
        card_start = html.index('<span class="ticker">600002.SH</span>')
        card_end = html.index("</article>", card_start)
        card = html[card_start:card_end]
        self.assertLess(card.index('<span class="ticker">600002.SH</span>'), card.index("<h2>示例软件</h2>"))
        self.assertLess(card.index("<h2>示例软件</h2>"), card.index('<div class="sector">软件服务</div>'))
        self.assertIn(".stock-card h2 { margin:12px 0 0; font-size:22px; font-weight:800; }", html)
        self.assertIn("${visible}", html)
        self.assertIn("${cards.length}", html)

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
