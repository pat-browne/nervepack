# np-test: compact-scan | Jaccard pairs, propose band, split criterion vs skill budget, proposals dir
"""np_compact_scan feeds the weekly compact agent. Its thresholds must be
reachable. The old prompt asked for Jaccard >= 0.4 and SKILL.md files over 300
lines. skill-maintain keeps every SKILL.md under 8 KB, so no split could fire,
and no real pair scored above 0.31, so no proposal was ever written."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (SETUP, os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_compact_scan  # noqa: E402


def _skill(root, name, desc, heads, pad=0, refs=0):
    d = os.path.join(root, "skills", name)
    os.makedirs(d, exist_ok=True)
    body = "---\nname: %s\ndescription: %s\n---\n\n# T\n\n" % (name, desc)
    body += "".join("## %s\n\ntext\n\n" % h for h in heads)
    body += "x" * pad
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(body)
    if refs:
        os.makedirs(os.path.join(d, "references"), exist_ok=True)
        with open(os.path.join(d, "references", "more.md"), "w", encoding="utf-8") as fh:
            fh.write("y" * refs)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.content = tempfile.mkdtemp()

    def _scan(self):
        return np_compact_scan.scan([self.root], propose_min=0.3, split_total_kb=40,
                                    content_dir=self.content)

    def test_pair_in_lowered_band_is_proposed(self):
        _skill(self.root, "site-a", "deploy the alpha static site to pages", ["Deploy", "DNS", "Cache"])
        _skill(self.root, "site-b", "deploy the beta static site to pages", ["Deploy", "DNS", "Forms"])
        _skill(self.root, "other", "query sql server tables", ["Joins"])
        names = [(p["a"], p["b"], p["band"]) for p in self._scan()["pairs"]]
        self.assertIn(("site-a", "site-b", "propose"), names)
        self.assertFalse(any("other" in (a, b) for a, b, _ in names))

    def test_identical_pair_is_auto_merge(self):
        _skill(self.root, "x1", "same words here", ["A"])
        _skill(self.root, "x2", "same words here", ["A"])
        self.assertEqual(self._scan()["pairs"][0]["band"], "auto-merge")

    def test_split_counts_references_not_lines(self):
        # A 7 KB SKILL.md on few lines plus 40 KB in references/: under 300
        # lines and under split_kb, but over the 40 KB total.
        _skill(self.root, "big", "big skill", ["A", "B"], pad=7 * 1024, refs=40 * 1024)
        _skill(self.root, "small", "small skill", ["A"], pad=7 * 1024)
        self.assertEqual([s["name"] for s in self._scan()["oversized"]], ["big"])

    def test_rejected_pair_is_skipped(self):
        _skill(self.root, "x1", "same words here", ["A"])
        _skill(self.root, "x2", "same words here", ["A"])
        os.makedirs(os.path.join(self.content, "compact-proposals"))
        with open(os.path.join(self.content, "compact-proposals", "REJECTED.md"), "w") as fh:
            fh.write("- x1 vs x2 -- keep separate\n")
        self.assertEqual(self._scan()["pairs"], [])

    def test_proposals_dir_is_the_content_overlay(self):
        self.assertEqual(self._scan()["proposals_dir"],
                         os.path.join(self.content, "compact-proposals"))

    def test_main_prints_json(self):
        _skill(self.root, "a", "alpha", ["A"])
        buf = io.StringIO()
        with mock.patch.object(np_compact_scan, "_roots", return_value=[self.root]), \
                mock.patch.object(np_compact_scan, "_content_dir", return_value=self.content), \
                mock.patch("sys.stdout", buf):
            self.assertEqual(np_compact_scan.main([]), 0)
        self.assertIn("pairs", json.loads(buf.getvalue()))


class PromptTest(unittest.TestCase):
    def test_prompt_uses_scanner_and_current_paths(self):
        path = os.path.join(SETUP, "..", "..", "agents", "np-flow-weekly-compact.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("skills setup INDEX.md", text)
        self.assertIn("engine/setup", text)
        self.assertIn("np_compact_scan.py", text)
        self.assertNotIn("300 lines", text)


if __name__ == "__main__":
    unittest.main()
