import copy
import unittest

from research.metadata_provenance import (
    FINAL_UNAVAILABLE,
    REQUIRED_CANONICAL_FIELDS,
    SnapshotIntegrityError,
    ProvenanceError,
    canonical_records_hash,
    canonicalize_security_metadata,
    freeze_metadata_snapshot,
    load_source_registry,
    ready_for_manifest_freeze,
    reproduce_canonical_records,
    sha256_hex,
)


class MetadataProvenanceTests(unittest.TestCase):
    @staticmethod
    def _field_provenance(manual=False):
        raw_hash = sha256_hex({"source": "unit-test-metadata-only"})
        return {
            field: {
                "source_id": "TEST-METADATA-SOURCE",
                "provider_source_name": "Unit-test metadata source",
                "raw_snapshot_sha256": raw_hash,
                "retrieved_at": "2026-08-27T00:00:00+08:00",
                "as_of": "2026-08-27",
                "as_of_semantics": "current-source-record",
                "derivation": "direct",
                "manual": manual,
            }
            for field in REQUIRED_CANONICAL_FIELDS
        }

    @staticmethod
    def _raw_record():
        return {
            "security_identity": {
                "canonical_id": "TEST:EXCHANGE:0001",
                "local_symbol": "0001",
                "issuer_name": "Source supplied test issuer",
            },
            "exchange": {"mic": "XTEST", "name": "Test Exchange"},
            "security_type": "COMMON_STOCK",
            "primary_listing": {"is_primary": True, "venue": "XTEST"},
            "listing_date": "2020-01-02",
            "active_status": "ACTIVE",
            "issuer_share_class_identity": {
                "issuer_id": "TEST-ISSUER-1",
                "share_class_id": "TEST-CLASS-A",
            },
            "sector": "Technology",
            "industry": "Software",
            "provider_availability": [
                {"provider": "provider-b", "available": False},
                {"provider": "provider-a", "available": True},
            ],
        }

    def test_registry_is_frozen_as_an_audit_record_and_fail_closed(self):
        registry = load_source_registry()
        self.assertEqual(registry["final_conclusion"], FINAL_UNAVAILABLE)
        self.assertFalse(ready_for_manifest_freeze(registry))
        self.assertFalse(registry["scope"]["historical_ohlcv_accessed"])
        self.assertFalse(registry["scope"]["setup03_output_accessed"])
        self.assertFalse(registry["scope"]["final_oos_accessed"])
        self.assertFalse(registry["scope"]["formal_symbol_manifest_generated"])

    def test_canonical_records_are_deterministic_and_sorted_by_identity(self):
        raw = self._raw_record()
        first = canonicalize_security_metadata(raw, self._field_provenance())
        second = canonicalize_security_metadata(
            copy.deepcopy(raw), self._field_provenance()
        )
        self.assertEqual(first, second)
        self.assertEqual(canonical_records_hash([first]), canonical_records_hash([second]))
        self.assertEqual(first["listing_date"], "2020-01-02")
        self.assertEqual(
            [row["provider"] for row in first["provider_availability"]],
            ["provider-a", "provider-b"],
        )

    def test_frozen_snapshot_reproduces_identical_canonical_records(self):
        raw = self._raw_record()
        frozen = freeze_metadata_snapshot(
            {
                "source_id": "TEST-METADATA-SOURCE",
                "source_version": "unit-test-v1",
                "retrieved_at": "2026-08-27T00:00:00+08:00",
                "as_of": "2026-08-27",
                "raw_payload": {"security_records": [raw]},
            },
            [{"raw_record": raw, "field_provenance": self._field_provenance()}],
        )
        regenerated = reproduce_canonical_records(frozen)
        self.assertEqual(regenerated, frozen["canonical_records"])
        self.assertEqual(
            frozen["integrity"]["canonical_records_sha256"],
            canonical_records_hash(regenerated),
        )

    def test_frozen_snapshot_detects_tampering(self):
        raw = self._raw_record()
        frozen = freeze_metadata_snapshot(
            {"source_id": "TEST", "raw_payload": {"records": [raw]}},
            [{"raw_record": raw, "field_provenance": self._field_provenance()}],
        )
        tampered = copy.deepcopy(frozen)
        tampered["canonical_records"][0]["sector"] = "Manual replacement"
        with self.assertRaises(SnapshotIntegrityError):
            reproduce_canonical_records(tampered)

    def test_manual_selection_driving_value_is_rejected(self):
        provenance = self._field_provenance(manual=True)
        with self.assertRaises(ProvenanceError):
            canonicalize_security_metadata(self._raw_record(), provenance)

    def test_ohlcv_or_history_input_is_rejected(self):
        raw = self._raw_record()
        raw["history_length"] = 1000
        with self.assertRaises(ProvenanceError):
            canonicalize_security_metadata(raw, self._field_provenance())

        raw = self._raw_record()
        raw["liquidity_metadata"] = {"liquidity_rank": 1}
        provenance = self._field_provenance()
        provenance["liquidity_metadata"] = provenance["security_identity"]
        with self.assertRaises(ProvenanceError):
            canonicalize_security_metadata(raw, provenance)


if __name__ == "__main__":
    unittest.main()
