"""Direct unit tests for np_architecture_freshness.py -- port of
np-architecture-freshness.sh. Ports the 3 cases from test_freshness.sh
(missing feature flagged, missing spec flagged, 0 gaps when fresh) and the
1 case from test_freshness_failure.sh (missing map -> advisory, no crash)."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_architecture_freshness  # noqa: E402


class TestArchitectureFreshness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.specs_dir = os.path.join(self.tmp, "specs")
        os.makedirs(self.specs_dir)
        self.toggles = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles, "w") as fh:
            fh.write("# feature|scope|enforce|state|param\n")
            fh.write("memory|shared|runtime|on|\n")
            fh.write("newthing|shared|runtime|on|\n")
        open(os.path.join(self.specs_dir, "2026-01-01-newthing-design.md"), "a").close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_1_missing_feature_and_spec_flagged(self):
        arch = os.path.join(self.tmp, "ARCH-stale.md")
        with open(arch, "w") as fh:
            fh.write("# map\nThe `memory` feature exists. See 1999-old-design.md.\n")
        lines = np_architecture_freshness.check(
            arch_file=arch, toggles_file=self.toggles, specs_dir=self.specs_dir)
        joined = "\n".join(lines)
        self.assertIn("STALE: feature 'newthing'", joined)
        self.assertIn("STALE: spec '2026-01-01-newthing-design.md'", joined)
        self.assertIn("architecture-freshness: 2 gap", joined)

    def test_2_zero_gaps_when_fresh(self):
        arch = os.path.join(self.tmp, "ARCH-fresh.md")
        with open(arch, "w") as fh:
            fh.write("# map\nFeatures: `memory`, `newthing`.\nSpecs: 2026-01-01-newthing-design.md.\n")
        lines = np_architecture_freshness.check(
            arch_file=arch, toggles_file=self.toggles, specs_dir=self.specs_dir)
        self.assertIn("architecture-freshness: 0 gap", "\n".join(lines))

    def test_3_missing_map_is_advisory_no_crash(self):
        missing = os.path.join(self.tmp, "NOPE", "ARCHITECTURE.md")
        lines = np_architecture_freshness.check(
            arch_file=missing, toggles_file=self.toggles, specs_dir=self.specs_dir)
        joined = "\n".join(lines)
        self.assertIn("ARCHITECTURE.md missing at %s" % missing, joined)
        self.assertNotIn("STALE:", joined)

    def test_4_no_specs_dir_skips_spec_check(self):
        arch = os.path.join(self.tmp, "ARCH-fresh.md")
        with open(arch, "w") as fh:
            fh.write("# map\nFeatures: `memory`, `newthing`.\n")
        lines = np_architecture_freshness.check(
            arch_file=arch, toggles_file=self.toggles, specs_dir="")
        self.assertIn("architecture-freshness: 0 gap", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
