import csv
import io
import json
import unittest
from datetime import date, timedelta

from core import Quote
from trading.candidate_universe import (
    AffordabilityTier,
    SeedSecurity,
    select_candidate_universe,
)
from trading.candidate_universe_sources import parse_iwb_holdings_csv
from trading.candidate_universe_sources import BaoStockCandidateSeedAdapter


AS_OF = date(2026, 9, 4)


def _seed(
    symbol: str,
    market: str = "CN",
    sector: str = "Technology",
    *,
    exchange: str | None = None,
) -> SeedSecurity:
    return SeedSecurity(
        market=market,
        symbol=symbol,
        name=symbol,
        sector=sector,
        asset_class="Equity",
        exchange=exchange,
        currency="CNY" if market == "CN" else "USD",
        source="fixture",
    )


def _history(symbol: str, price: float, *, amount: float = 100_000.0, count: int = 60, last: date = AS_OF):
    return [
        Quote(
            symbol=symbol,
            name=symbol,
            market="CN" if "." in symbol else "US",
            trade_date=last - timedelta(days=count - index - 1),
            source="fixture",
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            preclose=price,
            pct_change=0.0,
            volume=1_000.0,
            amount=amount + index,
            turnover_rate=None,
            currency="CNY" if "." in symbol else "USD",
        )
        for index in range(count)
    ]


class CandidateUniverseTests(unittest.TestCase):
    def test_cn_preferred_extended_and_over_limit(self):
        seeds = [
            _seed("688001.SH"),
            _seed("688002.SH"),
            _seed("688003.SH"),
        ]
        histories = {
            "688001.SH": _history("688001.SH", 40.0),  # 200 * 40 = 8,000
            "688002.SH": _history("688002.SH", 75.0),  # 200 * 75 = 15,000
            "688003.SH": _history("688003.SH", 105.0),  # 200 * 105 = 21,000
        }
        universe = select_candidate_universe(seeds, histories, AS_OF, top_n_per_sector=20)
        by_symbol = {record.symbol: record for record in universe.records}
        self.assertEqual(by_symbol["688001.SH"].affordability_tier, AffordabilityTier.CN_PREFERRED)
        self.assertEqual(by_symbol["688001.SH"].minimum_quantity, 200)
        self.assertTrue(by_symbol["688001.SH"].included)
        self.assertEqual(
            by_symbol["688002.SH"].affordability_tier,
            AffordabilityTier.CN_EXTENDED_LOWER_PRIORITY,
        )
        self.assertTrue(by_symbol["688002.SH"].included)
        self.assertEqual(by_symbol["688003.SH"].exclusion_reason, "CN_MINIMUM_NOTIONAL_OVER_20000")

    def test_board_specific_minimum_quantity_is_not_hardcoded_to_100(self):
        seeds = [_seed("600001.SH"), _seed("688001.SH"), _seed("300001.SZ")]
        histories = {
            seed.symbol: _history(seed.symbol, 50.0) for seed in seeds
        }
        universe = select_candidate_universe(seeds, histories, AS_OF)
        by_symbol = {record.symbol: record for record in universe.records}
        self.assertEqual(by_symbol["600001.SH"].minimum_quantity, 100)
        self.assertEqual(by_symbol["300001.SZ"].minimum_quantity, 100)
        self.assertEqual(by_symbol["688001.SH"].minimum_quantity, 200)
        self.assertEqual(by_symbol["688001.SH"].board, "SSE_STAR")

    def test_us_one_share_over_1000_is_excluded(self):
        seed = _seed("EXPENSIVE", "US", "Industrials")
        result = select_candidate_universe(
            [seed], {seed.symbol: _history(seed.symbol, 1001.0)}, AS_OF
        ).records[0]
        self.assertFalse(result.included)
        self.assertEqual(result.exclusion_reason, "US_ONE_SHARE_NOTIONAL_OVER_1000")
        self.assertEqual(result.minimum_quantity, 1)

    def test_sector_top_n_prevents_total_liquidity_dominance(self):
        seeds = [
            _seed("600001.SH", sector="Technology"),
            _seed("600002.SH", sector="Technology"),
            _seed("600003.SH", sector="Technology"),
            _seed("600004.SH", sector="Financials"),
        ]
        histories = {
            "600001.SH": _history("600001.SH", 10.0, amount=500_000),
            "600002.SH": _history("600002.SH", 10.0, amount=400_000),
            "600003.SH": _history("600003.SH", 10.0, amount=300_000),
            "600004.SH": _history("600004.SH", 10.0, amount=1),
        }
        universe = select_candidate_universe(seeds, histories, AS_OF, top_n_per_sector=2)
        included = {(record.sector, record.symbol) for record in universe.included}
        self.assertEqual(
            included,
            {
                ("Technology", "600001.SH"),
                ("Technology", "600002.SH"),
                ("Financials", "600004.SH"),
            },
        )
        self.assertEqual(
            next(record for record in universe.records if record.symbol == "600003.SH").exclusion_reason,
            "SECTOR_TOP_N_EXCEEDED",
        )

    def test_extended_affordability_is_lower_priority_than_preferred(self):
        seeds = [_seed("688001.SH"), _seed("688002.SH")]
        histories = {
            "688001.SH": _history("688001.SH", 75.0, amount=1_000_000),
            "688002.SH": _history("688002.SH", 40.0, amount=1),
        }
        universe = select_candidate_universe(seeds, histories, AS_OF, top_n_per_sector=1)
        by_symbol = {record.symbol: record for record in universe.records}
        self.assertEqual(by_symbol["688002.SH"].rank, 1)
        self.assertTrue(by_symbol["688002.SH"].included)
        self.assertEqual(by_symbol["688001.SH"].exclusion_reason, "SECTOR_TOP_N_EXCEEDED")

    def test_stale_and_insufficient_history_fail_closed(self):
        stale = _seed("600001.SH")
        short = _seed("600002.SH")
        universe = select_candidate_universe(
            [stale, short],
            {
                stale.symbol: _history(stale.symbol, 10.0, last=AS_OF - timedelta(days=8)),
                short.symbol: _history(short.symbol, 10.0, count=59),
            },
            AS_OF,
        )
        reasons = {record.symbol: record.exclusion_reason for record in universe.records}
        self.assertEqual(reasons[stale.symbol], "HISTORY_STALE")
        self.assertEqual(reasons[short.symbol], "HISTORY_INSUFFICIENT")

    def test_unsupported_cn_board_rule_fails_closed(self):
        seed = _seed("900001.SH")
        result = select_candidate_universe(
            [seed], {seed.symbol: _history(seed.symbol, 10.0)}, AS_OF
        ).records[0]
        self.assertFalse(result.included)
        self.assertEqual(result.exclusion_reason, "UNSUPPORTED_BOARD_RULE")

    def test_selector_never_emits_strategy_entry_action(self):
        seed = _seed("600001.SH")
        universe = select_candidate_universe(
            [seed], {seed.symbol: _history(seed.symbol, 10.0)}, AS_OF
        )
        payload = json.dumps(universe.rows(), ensure_ascii=False)
        self.assertNotIn("ENTRY_ALLOWED", payload)


class IwbContractTests(unittest.TestCase):
    def test_parser_uses_official_preamble_and_equity_fields(self):
        rows = [
            ["iShares Russell 1000 ETF"],
            ["Fund Holdings as of", "Sep 03, 2026"],
            [],
            ["Ticker", "Name", "Sector", "Asset Class", "Market Value", "Weight (%)", "Notional Value", "Quantity", "Price", "Location", "Exchange", "Currency"],
            ["AAPL", "APPLE", "Information Technology", "Equity", "1", "1", "1", "1", "200.00", "United States", "NASDAQ", "USD"],
            ["BRK B", "BERKSHIRE", "Financials", "Equity", "1", "1", "1", "1", "500.00", "United States", "NYSE", "USD"],
            ["CASH", "Cash", "-", "Cash", "1", "1", "1", "1", "1", "United States", "-", "USD"],
        ]
        payload = io.StringIO()
        csv.writer(payload, lineterminator="\n").writerows(rows)
        source_date, seeds = parse_iwb_holdings_csv(payload.getvalue())
        self.assertEqual(source_date, date(2026, 9, 3))
        self.assertEqual(len(seeds), 2)
        self.assertEqual(seeds[0].symbol, "AAPL")
        self.assertEqual(seeds[0].sector, "Information Technology")
        self.assertEqual(seeds[0].reference_price, 200.0)
        self.assertEqual(seeds[1].symbol, "BRK-B")
        self.assertEqual(seeds[1].source_symbol, "BRK B")


class BaoStockContractTests(unittest.TestCase):
    class _Result:
        def __init__(self, fields, rows):
            self.error_code = "0"
            self.error_msg = "success"
            self.fields = fields
            self._rows = iter(rows)

        def next(self):
            try:
                self._current = next(self._rows)
                return True
            except StopIteration:
                return False

        def get_row_data(self):
            return self._current

    class _Login:
        error_code = "0"
        error_msg = "success"

    class _BaoStock:
        def __init__(self):
            self.calls = []

        def login(self):
            self.calls.append(("login",))
            return BaoStockContractTests._Login()

        def logout(self):
            self.calls.append(("logout",))

        def query_hs300_stocks(self, **kwargs):
            self.calls.append(("hs300", kwargs))
            return BaoStockContractTests._Result(
                ["updateDate", "code", "code_name"], [["2026-09-04", "sh.600001", "A"]]
            )

        def query_zz500_stocks(self, **kwargs):
            self.calls.append(("zz500", kwargs))
            return BaoStockContractTests._Result(
                ["updateDate", "code", "code_name"], [["2026-09-04", "sz.300001", "B"]]
            )

        def query_stock_basic(self, **kwargs):
            self.calls.append(("basic", kwargs))
            return BaoStockContractTests._Result(
                ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                [["sh.600001", "A", "2020-01-01", "", "1", "1"], ["sz.300001", "B", "2020-01-01", "", "1", "1"]],
            )

        def query_stock_industry(self, **kwargs):
            self.calls.append(("industry", kwargs))
            return BaoStockContractTests._Result(
                ["updateDate", "code", "code_name", "industry", "industryClassification"],
                [["2026-09-04", "sh.600001", "A", "J66", "CSRC"], ["2026-09-04", "sz.300001", "B", "C39", "CSRC"]],
            )

    def test_adapter_uses_verified_metadata_signatures_and_unions_indices(self):
        fake = self._BaoStock()
        seeds = BaoStockCandidateSeedAdapter(fake).load(as_of=AS_OF)
        self.assertEqual({seed.symbol for seed in seeds}, {"600001.SH", "300001.SZ"})
        self.assertEqual({seed.sector for seed in seeds}, {"J66", "C39"})
        self.assertEqual(fake.calls[1], ("hs300", {"date": "2026-09-04"}))
        self.assertEqual(fake.calls[2], ("zz500", {"date": "2026-09-04"}))
        self.assertEqual(fake.calls[3], ("basic", {}))
        self.assertEqual(fake.calls[4], ("industry", {}))


if __name__ == "__main__":
    unittest.main()
