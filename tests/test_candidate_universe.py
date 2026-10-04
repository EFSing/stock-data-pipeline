import csv
import io
import json
import unittest
from datetime import date, timedelta
from dataclasses import replace
from unittest.mock import patch

from core import Quote
from trading.candidate_universe import (
    AffordabilityTier,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_UNLISTED_OR_NO_MARKET,
    LIFECYCLE_WHEN_ISSUED,
    SeedSecurity,
    select_candidate_universe,
)
from trading.candidate_universe_sources import (
    BaoStockCandidateSeedAdapter,
    CandidateSeedDataError,
    HithinkCandidateSeedAdapter,
    IwbOfficialHoldingsAdapter,
    parse_iwb_holdings_csv,
)


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

    def test_production_default_does_not_require_sector_or_apply_sector_cap(self):
        seeds = [
            _seed("600001.SH", sector=None),
            _seed("600002.SH", sector=None),
        ]
        histories = {seed.symbol: _history(seed.symbol, 10.0) for seed in seeds}
        universe = select_candidate_universe(seeds, histories, AS_OF)
        self.assertEqual([record.symbol for record in universe.included], [
            "600001.SH", "600002.SH",
        ])
        self.assertEqual([record.rank for record in universe.included], [1, 2])
        self.assertIsNone(universe.top_n_per_sector)


class IwbContractTests(unittest.TestCase):
    @staticmethod
    def _csv(snapshot_date):
        return (
            f'Fund Holdings as of,"{snapshot_date}"\n'
            'Ticker,Name,Sector,Asset Class,Price,Exchange,Currency\n'
            'AAPL,APPLE,Technology,Equity,200,NASDAQ,USD\n'
        ).encode()

    def test_dated_snapshot_is_checked_on_every_load_without_date_relabeling(self):
        adapter = IwbOfficialHoldingsAdapter()
        with patch("trading.candidate_universe_sources.urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.read.side_effect = [self._csv("Sep 03, 2026"), self._csv("Sep 05, 2026")]
            source_date, seeds = adapter.load(as_of=AS_OF)
            self.assertEqual(source_date, date(2026, 9, 3))
            self.assertEqual(seeds[0].source_as_of, source_date)
            with self.assertRaisesRegex(CandidateSeedDataError, "AFTER_AS_OF.*report_as_of=2026-09-04.*DATE_QUERY.*NO_ELIGIBLE_SNAPSHOT"):
                adapter.load(as_of=AS_OF)

    def test_historical_request_uses_report_date_and_official_response_date(self):
        with patch("trading.candidate_universe_sources.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = self._csv("30/Sept/2026")
            source_date, seeds = IwbOfficialHoldingsAdapter().load(as_of=date(2026, 9, 30))
            request = open_url.call_args.args[0]
            self.assertIn("asOfDate=20260930", request.full_url)
            self.assertIn("1495092304805.ajax", request.full_url)
            self.assertEqual(source_date, date(2026, 9, 30))
            self.assertEqual(seeds[0].source_as_of, source_date)
            self.assertIn(request.full_url, seeds[0].provenance)
            self.assertIn("snapshot_mode:DATE_QUERY", seeds[0].provenance)

    def test_undated_holdings_fail_closed(self):
        for value in ("", "invalid-date"):
            with self.subTest(value=value), self.assertRaisesRegex(CandidateSeedDataError, "SNAPSHOT_DATE_MISSING"):
                parse_iwb_holdings_csv(self._csv(value))

    def test_selector_rejects_future_metadata_in_both_markets(self):
        for market, symbol in (("CN", "600001.SH"), ("US", "AAPL")):
            seed = replace(_seed(symbol, market, exchange="SH" if market == "CN" else "NASDAQ"), source_as_of=AS_OF + timedelta(days=1))
            universe = select_candidate_universe((seed,), {symbol: _history(symbol, 10)}, AS_OF)
            self.assertEqual(universe.records[0].exclusion_reason, "SEED_METADATA_AFTER_AS_OF")
            self.assertFalse(universe.included)

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

    def test_iwb_parser_preserves_generic_lifecycle_metadata_and_identity(self):
        rows = [
            ["iShares Russell 1000 ETF"],
            ["Fund Holdings as of", "Sep 03, 2026"],
            [],
            ["Ticker", "Name", "Sector", "Asset Class", "Price", "Exchange", "Currency"],
            ["AAPL", "APPLE", "Technology", "Equity", "200", "NASDAQ", "USD"],
            ["JMKE", "NEW LISTED", "Industrials", "Equity", "20", "NASDAQ", "USD"],
            ["HOLX", "UNLISTED", "Health Care", "Equity", "20", "NO MARKET (E.G. UNLISTED)", "USD"],
            ["VYLR-WI", "WHEN ISSUED", "Industrials", "Equity", "20", "NASDAQ", "USD"],
            ["BLANK", "BLANK EXCHANGE", "Industrials", "Equity", "20", "", "USD"],
        ]
        payload = io.StringIO()
        csv.writer(payload, lineterminator="\n").writerows(rows)

        _source_date, seeds = parse_iwb_holdings_csv(payload.getvalue())
        by_symbol = {seed.symbol: seed for seed in seeds}

        self.assertEqual(by_symbol["AAPL"].lifecycle_status, LIFECYCLE_ACTIVE)
        self.assertEqual(by_symbol["JMKE"].lifecycle_status, LIFECYCLE_ACTIVE)
        self.assertEqual(by_symbol["HOLX"].lifecycle_status, LIFECYCLE_UNLISTED_OR_NO_MARKET)
        self.assertIn("lifecycle_status:UNLISTED_OR_NO_MARKET", by_symbol["HOLX"].provenance)
        self.assertEqual(by_symbol["BLANK"].lifecycle_status, LIFECYCLE_ACTIVE)
        self.assertNotIn("lifecycle_status:", "|".join(by_symbol["BLANK"].provenance))
        self.assertEqual(by_symbol["VYLR-WI"].source_symbol, "VYLR-WI")
        self.assertEqual(by_symbol["VYLR-WI"].lifecycle_status, LIFECYCLE_WHEN_ISSUED)
        self.assertIn("lifecycle_status:WHEN_ISSUED", by_symbol["VYLR-WI"].provenance)
        self.assertNotIn("VYLR", by_symbol)

    def test_lifecycle_exclusions_do_not_filter_new_listed_equity_as_metadata_bad(self):
        common = _seed("AAPL", "US", "Technology", exchange="NASDAQ")
        new_listed = _seed("JMKE", "US", "Industrials", exchange="NASDAQ")
        blank_exchange = _seed("BLANK", "US", "Industrials", exchange=None)
        unlisted = replace(
            _seed("HOLX", "US", "Health Care", exchange=None),
            lifecycle_status=LIFECYCLE_UNLISTED_OR_NO_MARKET,
            provenance=("official-iwb", "lifecycle_status:UNLISTED_OR_NO_MARKET"),
        )
        when_issued = replace(
            _seed("VYLR-WI", "US", "Industrials", exchange="NASDAQ"),
            lifecycle_status=LIFECYCLE_WHEN_ISSUED,
            provenance=("official-iwb", "lifecycle_status:WHEN_ISSUED"),
        )
        universe = select_candidate_universe(
            (common, new_listed, blank_exchange, unlisted, when_issued),
            {
                common.symbol: _history(common.symbol, 20.0),
                new_listed.symbol: _history(new_listed.symbol, 20.0, count=59),
                blank_exchange.symbol: _history(blank_exchange.symbol, 20.0),
                unlisted.symbol: _history(unlisted.symbol, 20.0),
                when_issued.symbol: _history(when_issued.symbol, 20.0),
            },
            AS_OF,
        )
        by_symbol = {record.symbol: record for record in universe.records}

        self.assertTrue(by_symbol["AAPL"].included)
        self.assertTrue(by_symbol["BLANK"].included)
        self.assertNotEqual(by_symbol["BLANK"].exclusion_reason, "LIFECYCLE_UNLISTED_OR_NO_MARKET")
        self.assertFalse(by_symbol["JMKE"].included)
        self.assertEqual(by_symbol["JMKE"].exclusion_reason, "HISTORY_INSUFFICIENT")
        self.assertFalse(by_symbol["HOLX"].included)
        self.assertEqual(by_symbol["HOLX"].exclusion_reason, "LIFECYCLE_UNLISTED_OR_NO_MARKET")
        self.assertIn("lifecycle_status:UNLISTED_OR_NO_MARKET", by_symbol["HOLX"].provenance)
        self.assertFalse(by_symbol["VYLR-WI"].included)
        self.assertEqual(by_symbol["VYLR-WI"].exclusion_reason, "LIFECYCLE_WHEN_ISSUED")
        self.assertIn("lifecycle_status:WHEN_ISSUED", by_symbol["VYLR-WI"].provenance)
        self.assertEqual(by_symbol["VYLR-WI"].symbol, "VYLR-WI")


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


class HithinkIndexContractTests(unittest.TestCase):
    def test_snapshot_timestamp_uses_shanghai_date_across_utc_midnight(self):
        payload = self._payload([{"thscode": "600001.SH", "name": "A"}])
        payload["data"]["timestamp"] = "2026-09-06T17:00:00Z"
        with self.assertRaisesRegex(CandidateSeedDataError, "2026-09-07.*report_as_of=2026-09-04"):
            HithinkCandidateSeedAdapter(lambda *_args: payload).load(as_of=AS_OF)

    def test_union_rejects_future_second_index_even_with_valid_first_index(self):
        def request(_path, params):
            payload = self._payload([{"thscode": "600001.SH", "name": "A"}])
            if params["thscode"] == "000905.SH":
                payload["data"]["timestamp"] = "2026-09-07"
            return payload
        with self.assertRaisesRegex(CandidateSeedDataError, "AFTER_AS_OF.*index_code=000905.SH"):
            HithinkCandidateSeedAdapter(request).load(as_of=AS_OF)

    def test_holiday_ready_time_uses_prior_exact_cn_session_and_keeps_timestamp(self):
        for timestamp in ("2026-10-01T23:00:00+08:00", "2026-10-02T09:00:00+08:00"):
            payload = self._payload([{"thscode": "600001.SH", "name": "A"}])
            payload["data"]["timestamp"] = timestamp
            adapter = HithinkCandidateSeedAdapter(lambda *_args: payload)
            seeds = adapter.load(as_of=date(2026, 9, 30))
            self.assertEqual(seeds[0].source_as_of, date(2026, 9, 30))
            self.assertEqual(seeds[0].source_snapshot_timestamps, (timestamp,))
            with self.assertRaisesRegex(CandidateSeedDataError, "AFTER_AS_OF"):
                adapter.load(as_of=date(2026, 9, 29))

    def test_trading_day_ready_time_is_never_rolled_back_to_previous_report(self):
        payload = self._payload([{"thscode": "600001.SH", "name": "A"}])
        payload["data"]["timestamp"] = "2026-10-08T09:00:00+08:00"
        with self.assertRaisesRegex(CandidateSeedDataError, "AFTER_AS_OF:2026-10-08"):
            HithinkCandidateSeedAdapter(lambda *_args: payload).load(as_of=date(2026, 9, 30))

    @staticmethod
    def _payload(rows):
        return {
            "code": 0,
            "data": {
                "timestamp": "2026-09-04T15:00:00+08:00",
                "item": rows,
            },
        }

    def test_adapter_unions_official_indexes_and_keeps_membership_provenance(self):
        payloads = {
            "000300.SH": self._payload([
                {"thscode": "600001.SH", "ticker": "600001", "name": "A"},
                {"thscode": "300001.SZ", "ticker": "300001", "name": "B"},
            ]),
            "000905.SH": self._payload([
                {"thscode": "600001.SH", "ticker": "600001", "name": "A"},
                {"thscode": "000001.SZ", "ticker": "000001", "name": "C"},
            ]),
        }
        calls = []

        def request(path, params):
            calls.append((path, params))
            return payloads[params["thscode"]]

        seeds = HithinkCandidateSeedAdapter(request).load(as_of=AS_OF)
        by_symbol = {seed.symbol: seed for seed in seeds}
        self.assertEqual(set(by_symbol), {"600001.SH", "300001.SZ", "000001.SZ"})
        self.assertEqual(by_symbol["600001.SH"].index_memberships, ("000300.SH", "000905.SH"))
        self.assertEqual(by_symbol["600001.SH"].source_snapshot_timestamps, ("2026-09-04T15:00:00+08:00",))
        self.assertIsNone(by_symbol["600001.SH"].sector)
        self.assertTrue(any("index_code:000905.SH" in item for item in by_symbol["600001.SH"].provenance))
        self.assertEqual(calls[0][1], {"thscode": "000300.SH"})
        self.assertEqual(calls[1][1], {"thscode": "000905.SH"})

    def test_current_only_snapshot_cannot_be_applied_to_a_future_as_of_date(self):
        payload = self._payload([
            {"thscode": "600001.SH", "name": "A"},
        ])
        adapter = HithinkCandidateSeedAdapter(
            lambda _path, _params: payload
        )
        with self.assertRaisesRegex(CandidateSeedDataError, "AFTER_AS_OF"):
            adapter.load(as_of=date(2026, 9, 3))


if __name__ == "__main__":
    unittest.main()
