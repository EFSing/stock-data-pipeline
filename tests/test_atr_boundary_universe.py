import unittest

from research.atr_boundary_universe import (
    TARGET_COUNTS,
    build_universe_manifest,
    load_universe_manifest,
    symbol_list_hash,
)


class AtrBoundaryUniverseTests(unittest.TestCase):
    def test_clean_universe_is_frozen_and_excludes_all_exposed_identities(self):
        manifest = load_universe_manifest()
        self.assertEqual(manifest["counts"], TARGET_COUNTS)
        self.assertEqual(len(manifest["symbols"]), 40)
        self.assertEqual(manifest["symbol_list_sha256"], symbol_list_hash(manifest["symbols"]))
        for proof in manifest["exclusion_proofs"].values():
            self.assertEqual(proof["intersection"], [])
            self.assertTrue(proof["intersection_is_empty"])
        self.assertTrue(manifest["controls"]["selection_precedes_ohlcv"])
        self.assertFalse(manifest["controls"]["result_driven_ranking_or_replacement_allowed"])

    def test_clean_universe_selection_rebuild_is_deterministic(self):
        self.assertEqual(build_universe_manifest(), load_universe_manifest())


if __name__ == "__main__":
    unittest.main()
