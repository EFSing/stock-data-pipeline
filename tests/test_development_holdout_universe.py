import copy
import json
import unittest

from research.development_holdout_universe import (
    HOLDOUT_FIXED_SEED,
    HOLDOUT_UNIVERSE_VERSION,
    PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256,
    build_holdout_universe_manifest,
    load_holdout_universe_manifest,
    manifest_integrity_hash,
)


class DevelopmentHoldoutUniverseTests(unittest.TestCase):
    def test_frozen_manifest_is_20_plus_20_and_has_two_empty_exclusion_proofs(self):
        manifest = load_holdout_universe_manifest()
        self.assertEqual(manifest["universe_version"], HOLDOUT_UNIVERSE_VERSION)
        self.assertEqual(manifest["selection_spec"]["fixed_seed"], HOLDOUT_FIXED_SEED)
        self.assertEqual(manifest["counts"], {"CN": 20, "US": 20, "total": 40})
        self.assertEqual(manifest["exclusion_proofs"]["a1_formal_120"]["intersection"], [])
        self.assertEqual(manifest["exclusion_proofs"]["development_v1_40"]["intersection"], [])
        self.assertEqual(
            manifest["integrity"]["manifest_sha256"], PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256
        )

    def test_rebuild_from_saved_source_snapshots_is_exact(self):
        frozen = load_holdout_universe_manifest()
        rebuilt = build_holdout_universe_manifest(frozen_at=frozen["frozen_at"])
        self.assertEqual(rebuilt, frozen)

    def test_synchronized_hash_change_does_not_make_same_version_valid(self):
        manifest = load_holdout_universe_manifest()
        changed = copy.deepcopy(manifest)
        changed["symbols"][0]["source_name"] = "changed after freeze"
        changed["integrity"]["manifest_sha256"] = manifest_integrity_hash(changed)
        self.assertNotEqual(changed["integrity"]["manifest_sha256"], manifest["integrity"]["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
