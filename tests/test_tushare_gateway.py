import sys
import types
import unittest
from datetime import date
from unittest.mock import patch

from core import Quote
from scripts.run_candidate_strategy_shadow_bridge_v1_tushare_probe import (
    _qfq_history_from_factors,
)
from trading.tushare_gateway import (
    TUSHARE_LOCAL_CONFIG_REQUIRED,
    TushareGateway,
    TushareGatewayError,
    create_tushare_pro,
    fetch_tushare_daily_history,
    parse_tushare_daily_rows,
)


class _FakePro:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "trade_date": "20260904",
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10.5",
                "pre_close": "10",
                "pct_chg": "5",
                "vol": "100",
                "amount": "200",
                "turnover_rate": "1.2",
            }
        ]

    def adj_factor(self, **kwargs):
        self.calls.append(kwargs)
        return []


class _FakeTushare:
    def __init__(self, pro):
        self.pro_instance = pro
        self.received_token = None

    def pro_api(self, token):
        self.received_token = token
        return self.pro_instance


class TushareGatewayTests(unittest.TestCase):
    def _local_config_module(self):
        module = types.ModuleType("local_tushare_config")
        module.TUSHARE_TOKEN = "test-token"
        module.TUSHARE_API_URL = "https://gateway.example"
        return module

    def test_missing_local_config_fails_closed_with_exact_marker(self):
        with patch.dict(sys.modules, {"local_tushare_config": None}):
            with self.assertRaisesRegex(
                TushareGatewayError, f"^{TUSHARE_LOCAL_CONFIG_REQUIRED}$"
            ):
                create_tushare_pro(types.SimpleNamespace())

    def test_initialization_uses_local_config_and_vendor_private_fields(self):
        pro = _FakePro()
        tushare = _FakeTushare(pro)
        with patch.dict(sys.modules, {"local_tushare_config": self._local_config_module()}):
            result = create_tushare_pro(tushare)
        self.assertIs(result, pro)
        self.assertEqual(tushare.received_token, "test-token")
        self.assertEqual(pro._DataApi__token, "test-token")
        self.assertEqual(pro._DataApi__http_url, "https://gateway.example")

    def test_daily_history_normalizes_tushare_units_without_future_rows(self):
        pro = _FakePro()
        gateway = TushareGateway()
        with patch.dict(sys.modules, {"local_tushare_config": self._local_config_module()}):
            with patch("trading.tushare_gateway.create_tushare_pro", return_value=pro):
                quotes = fetch_tushare_daily_history(
                    gateway,
                    "000001.SZ",
                    date(2026, 9, 1),
                    date(2026, 9, 4),
                )
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].trade_date, date(2026, 9, 4))
        self.assertEqual(quotes[0].volume, 10_000.0)
        self.assertEqual(quotes[0].amount, 200_000.0)
        self.assertEqual(pro.calls[0]["ts_code"], "000001.SZ")
        self.assertEqual(pro.calls[0]["start_date"], "20260901")
        self.assertEqual(pro.calls[0]["end_date"], "20260904")

    def test_bulk_contracts_use_one_multi_code_or_one_trade_date_call(self):
        pro = _FakePro()
        gateway = TushareGateway()
        with patch("trading.tushare_gateway.create_tushare_pro", return_value=pro):
            gateway.daily_multi_symbol(
                ["000001.SZ", "600000.SH"],
                start_date=date(2026, 7, 1),
                end_date=date(2026, 9, 4),
            )
            gateway.daily_trade_date(date(2026, 9, 4))
        self.assertEqual(
            pro.calls,
            [
                {
                    "ts_code": "000001.SZ,600000.SH",
                    "start_date": "20260701",
                    "end_date": "20260904",
                },
                {"trade_date": "20260904"},
            ],
        )

    def test_adjustment_factor_batch_uses_one_multi_code_call(self):
        pro = _FakePro()
        gateway = TushareGateway()
        with patch("trading.tushare_gateway.create_tushare_pro", return_value=pro):
            gateway.adj_factor_multi_symbol(
                ["000001.SZ", "600000.SH"],
                start_date=date(2026, 7, 1),
                end_date=date(2026, 9, 4),
            )
        self.assertEqual(
            pro.calls[-1],
            {
                "ts_code": "000001.SZ,600000.SH",
                "start_date": "20260701",
                "end_date": "20260904",
            },
        )

    def test_bulk_rows_are_grouped_by_requested_symbol(self):
        rows = [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260904",
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10.5",
                "vol": "100",
                "amount": "200",
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260904",
                "open": "20",
                "high": "21",
                "low": "19",
                "close": "20.5",
                "vol": "100",
                "amount": "200",
            },
        ]
        histories = parse_tushare_daily_rows(
            rows,
            ["000001.SZ", "600000.SH", "688001.SH"],
            start_date=date(2026, 9, 4),
            end_date=date(2026, 9, 4),
        )
        self.assertEqual(len(histories["000001.SZ"]), 1)
        self.assertEqual(len(histories["600000.SH"]), 1)
        self.assertEqual(histories["688001.SH"], [])

    def test_qfq_formula_uses_exact_as_of_factor_anchor(self):
        raw = Quote(
            "000001.SZ", "000001.SZ", "CN", date(2026, 9, 3), "raw",
            10.0, 11.0, 9.0, 10.0, 10.0, 0.0, 100.0, 1000.0, None, "CNY",
        )
        adjusted = _qfq_history_from_factors(
            [raw],
            {date(2026, 9, 3): 2.0, date(2026, 9, 4): 4.0},
            anchor_date=date(2026, 9, 4),
        )[0]
        self.assertEqual(adjusted.close, 5.0)
        self.assertEqual(adjusted.open, 5.0)
        self.assertEqual(adjusted.preclose, 5.0)
        with self.assertRaisesRegex(ValueError, "TUSHARE_QFQ_EXACT_AS_OF_FACTOR_REQUIRED"):
            _qfq_history_from_factors(
                [raw], {date(2026, 9, 3): 2.0}, anchor_date=date(2026, 9, 4)
            )


if __name__ == "__main__":
    unittest.main()
