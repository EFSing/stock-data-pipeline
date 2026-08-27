import ast
from collections import Counter
import copy
import json
import random
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.development_validation_symbol_manifest import (
    INFORMATION_CUTOFF,
    MANIFEST_PATH,
    MANIFEST_STATUS,
    MANIFEST_VERSION,
    MIN_ACTIVE_SYMBOLS_PER_MARKET,
    MIN_ACTIVE_SYMBOLS_TOTAL,
    PINNED_MANIFEST_SHA256_BY_VERSION,
    PRIMARY_SYMBOLS_PER_MARKET,
    RESERVE_SYMBOLS_PER_MARKET,
    SECTOR_CAP,
    TARGET_SYMBOLS_PER_MARKET,
    VALIDATION_MARKETS,
    build_manifest,
    build_manifest_from_provider,
    load_manifest,
    manifest_integrity_hash,
)
from research.structural_validation_protocol import load_protocol


def metadata_rows():
    sectors = (
        "Sector-A",
        "Sector-A",
        "Sector-B",
        "Sector-B",
        "Sector-C",
        "Sector-C",
        "Sector-D",
        "Sector-D",
        "Sector-E",
        "Sector-E",
        "Sector-F",
        "Sector-F",
        "Sector-G",
        "Sector-G",
    )
    rows = []
    for market in VALIDATION_MARKETS:
        for rank, sector in enumerate(sectors, start=1):
            rows.append(
                {
                    "market": market,
                    "symbol": f"{market}-{rank:02d}",
                    "issuer_id": f"{market}-ISSUER-{rank:02d}",
                    "exchange": f"{market}-EXCHANGE",
                    "security_type": "COMMON_STOCK",
                    "primary_listing": True,
                    "listing_date": "2020-01-02",
                    "active_status": "ACTIVE",
                    "liquidity_rank": rank,
                    "history_length": 5000 - rank,
                    "broad_sector": sector,
                    "provider_metadata_available": True,
                    "share_class": "COMMON",
                    "is_adr": False,
                    "special_trading_status": "NORMAL",
                }
            )
    return rows


class DevelopmentValidationSymbolManifestTests(unittest.TestCase):
    def test_frozen_manifest_is_complete_and_not_fetched(self):
        manifest = load_manifest()
        self.assertEqual(manifest["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(manifest["status"], MANIFEST_STATUS)
        self.assertEqual(manifest["markets"], list(VALIDATION_MARKETS))
        self.assertEqual(manifest["information_cutoff"], INFORMATION_CUTOFF.isoformat())
        self.assertEqual(manifest["validation_window"], {
            "start": "2018-01-01",
            "end": "2026-08-26",
        })
        self.assertEqual(manifest["phase5k_controls"], {
            "historical_ohlcv_fetched": False,
            "setup03_evaluated": False,
            "validation_started": False,
            "final_oos_accessed": False,
            "manifest_is_authoritative_before_acquisition": True,
        })
        self.assertEqual(
            manifest["integrity"]["symbol_manifest_sha256"],
            PINNED_MANIFEST_SHA256_BY_VERSION[MANIFEST_VERSION],
        )

    def test_metadata_input_order_does_not_change_manifest_or_hash(self):
        rows = metadata_rows()
        first = build_manifest(rows)
        shuffled = list(rows)
        random.Random(17).shuffle(shuffled)
        second = build_manifest(shuffled)
        self.assertEqual(first, second)
        self.assertEqual(
            first["integrity"]["symbol_manifest_sha256"],
            manifest_integrity_hash(first),
        )

    def test_market_set_counts_and_primary_reserve_split_are_exact(self):
        manifest = build_manifest(metadata_rows())
        self.assertEqual(set(manifest["markets"]), set(VALIDATION_MARKETS))
        self.assertEqual(len(manifest["symbols"]), 70)
        for market in VALIDATION_MARKETS:
            rows = [row for row in manifest["symbols"] if row["market"] == market]
            self.assertEqual(len(rows), TARGET_SYMBOLS_PER_MARKET)
            self.assertEqual(
                sum(row["intended_role"] == "PRIMARY" for row in rows),
                PRIMARY_SYMBOLS_PER_MARKET,
            )
            self.assertEqual(
                sum(row["intended_role"] == "RESERVE" for row in rows),
                RESERVE_SYMBOLS_PER_MARKET,
            )
            self.assertEqual(
                [row["manifest_rank"] for row in rows],
                list(range(1, TARGET_SYMBOLS_PER_MARKET + 1)),
            )
        self.assertEqual(
            manifest["counts"]["future_hard_minimum_active_per_market"],
            MIN_ACTIVE_SYMBOLS_PER_MARKET,
        )
        self.assertEqual(
            manifest["counts"]["future_hard_minimum_active_total"],
            MIN_ACTIVE_SYMBOLS_TOTAL,
        )

    def test_eligibility_filters_age_security_type_listing_status_and_adr_st(self):
        rows = metadata_rows()
        invalid = {
            "market": "CN",
            "symbol": "CN-INVALID",
            "issuer_id": "CN-INVALID-ISSUER",
            "exchange": "CN-EXCHANGE",
            "primary_listing": True,
            "listing_date": "2020-01-02",
            "active_status": "ACTIVE",
            "liquidity_rank": 0,
            "history_length": 9999,
            "broad_sector": "Sector-Z",
            "provider_metadata_available": True,
            "share_class": "COMMON",
            "is_adr": False,
            "special_trading_status": "NORMAL",
        }
        rejected = []
        for index, change in enumerate((
            {"symbol": "CN-TOO-NEW", "listing_date": "2022-08-27"},
            {"symbol": "CN-ETF", "security_type": "ETF"},
            {"symbol": "CN-BOND", "security_type": "BOND"},
            {"symbol": "CN-ADR", "is_adr": True},
            {"symbol": "CN-ST", "special_trading_status": "ST"},
            {"symbol": "CN-ST-NAME", "name": "*ST Example"},
            {"symbol": "CN-INACTIVE", "active_status": "INACTIVE"},
            {"symbol": "CN-NOT-PRIMARY", "primary_listing": False},
            {"symbol": "CN-NO-METADATA", "provider_metadata_available": False},
        ), start=1):
            row = dict(invalid)
            row.update(change)
            row["liquidity_rank"] = 100 + index
            row["security_type"] = row.get("security_type", "COMMON_STOCK")
            rejected.append(row)
        rows.extend(rejected)
        manifest = build_manifest(rows)
        selected = {row["symbol"] for row in manifest["symbols"]}
        self.assertTrue(selected.isdisjoint({row["symbol"] for row in rejected}))

    def test_issuer_share_class_conflict_uses_deterministic_rank_winner(self):
        rows = [row for row in metadata_rows() if not (
            row["market"] == "CN" and row["liquidity_rank"] == 14
        )]
        rows.extend([
            {
                "market": "CN", "symbol": "CN-DUP-B", "issuer_id": "CN-DUP",
                "exchange": "CN-EXCHANGE", "security_type": "COMMON_STOCK",
                "primary_listing": True, "listing_date": "2020-01-02",
                "active_status": "ACTIVE", "liquidity_rank": 1,
                "history_length": 100, "broad_sector": "Sector-Z",
                "provider_metadata_available": True, "share_class": "B",
                "is_adr": False, "special_trading_status": "NORMAL",
            },
            {
                "market": "CN", "symbol": "CN-DUP-A", "issuer_id": "CN-DUP",
                "exchange": "CN-EXCHANGE", "security_type": "COMMON_STOCK",
                "primary_listing": True, "listing_date": "2020-01-02",
                "active_status": "ACTIVE", "liquidity_rank": 2,
                "history_length": 9999, "broad_sector": "Sector-Z",
                "provider_metadata_available": True, "share_class": "A",
                "is_adr": False, "special_trading_status": "NORMAL",
            },
        ])
        manifest = build_manifest(rows)
        cn = [row for row in manifest["symbols"] if row["market"] == "CN"]
        self.assertIn("CN-DUP-B", {row["symbol"] for row in cn})
        self.assertNotIn("CN-DUP-A", {row["symbol"] for row in cn})
        self.assertEqual(len({row["issuer_id"] for row in cn}), 14)

    def test_sector_cap_is_applied_before_final_rank_assignment(self):
        rows = metadata_rows()
        extra = dict(rows[0])
        extra.update({
            "symbol": "CN-CAP-THIRD",
            "issuer_id": "CN-CAP-THIRD",
            "liquidity_rank": 1,
            "broad_sector": "Sector-A",
        })
        rows.append(extra)
        manifest = build_manifest(rows)
        cn = [row for row in manifest["symbols"] if row["market"] == "CN"]
        self.assertLessEqual(
            max(Counter(row["broad_sector"] for row in cn).values()), SECTOR_CAP
        )
        self.assertIn("CN-CAP-THIRD", {row["symbol"] for row in cn})
        self.assertNotIn("CN-02", {row["symbol"] for row in cn})

    def test_selection_rejects_signal_and_result_fields(self):
        rows = metadata_rows()
        rows[0]["confirmed_count"] = 1
        with self.assertRaisesRegex(ValueError, "forbidden signal/result"):
            build_manifest(rows)

    def test_metadata_provider_is_used_without_bar_access(self):
        rows = metadata_rows()

        class MetadataOnlyProvider:
            def __init__(self):
                self.cutoff = None

            def list_security_metadata(self, *, information_cutoff):
                self.cutoff = information_cutoff
                return rows

            def fetch_historical_ohlcv(self, *args, **kwargs):
                raise AssertionError("manifest builder must not request bars")

        provider = MetadataOnlyProvider()
        manifest = build_manifest_from_provider(provider)
        self.assertEqual(provider.cutoff, INFORMATION_CUTOFF)
        self.assertEqual(len(manifest["symbols"]), 70)

    def test_reserve_rank_is_deterministic(self):
        manifest = build_manifest(metadata_rows())
        for market in VALIDATION_MARKETS:
            reserve = [row for row in manifest["symbols"] if (
                row["market"] == market and row["intended_role"] == "RESERVE"
            )]
            self.assertEqual([row["manifest_rank"] for row in reserve], [11, 12, 13, 14])

    def test_manifest_version_and_hash_pinning_rejects_recomputed_same_version_drift(self):
        manifest = load_manifest()
        changed = copy.deepcopy(manifest)
        changed["counts"]["target_per_market"] = 15
        changed["integrity"]["symbol_manifest_sha256"] = manifest_integrity_hash(changed)
        self.assertNotEqual(
            changed["integrity"]["symbol_manifest_sha256"],
            PINNED_MANIFEST_SHA256_BY_VERSION[MANIFEST_VERSION],
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "same-version-drift.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bound to a different canonical hash"):
                load_manifest(path)

    def test_manifest_hash_pinning_rejects_unsynchronized_content(self):
        manifest = load_manifest()
        changed = copy.deepcopy(manifest)
        changed["selection_policy"]["ranking"].reverse()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unsynchronized.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                load_manifest(path)

    def test_parent_phase5j_version_and_hash_are_validated(self):
        protocol = load_protocol()
        changed = copy.deepcopy(protocol)
        changed["protocol_version"] = "changed"
        with self.assertRaisesRegex(ValueError, "parent Phase 5J protocol version"):
            build_manifest(metadata_rows(), parent_protocol=changed)
        changed = copy.deepcopy(protocol)
        changed["integrity"]["protocol_sha256"] = "sha256:changed"
        with self.assertRaisesRegex(ValueError, "parent Phase 5J protocol hash"):
            build_manifest(metadata_rows(), parent_protocol=changed)

    def test_builder_source_has_no_setup_or_historical_data_dependencies(self):
        source_path = Path("research/development_validation_symbol_manifest.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "core", "trading"}))
        self.assertNotIn("replay_setup03_history", source)
        self.assertNotIn("evaluate_setup03", source)


if __name__ == "__main__":
    unittest.main()
