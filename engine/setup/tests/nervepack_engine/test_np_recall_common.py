"""#176: unit tests for np_recall_common — the prompt cap + PII-filter shell shared
by episodic_recall and lesson_recall (previously byte-identical in both hooks)."""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_recall_common  # noqa: E402


class TestRecallCommon(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("EPISODIC_RECALL_MAX", None)

    def test_max_prompts_default(self):
        os.environ.pop("EPISODIC_RECALL_MAX", None)
        self.assertEqual(np_recall_common.max_prompts(), 2)

    def test_max_prompts_env_override(self):
        os.environ["EPISODIC_RECALL_MAX"] = "5"
        self.assertEqual(np_recall_common.max_prompts(), 5)

    def test_max_prompts_non_int_falls_back(self):
        os.environ["EPISODIC_RECALL_MAX"] = "nope"
        self.assertEqual(np_recall_common.max_prompts(), 2)

    def test_default_pii_filter_fails_open_to_original_text(self):
        # a filter that exits nonzero (nonexistent script) -> text returned unchanged
        orig = np_recall_common.PII_FILTER_SCRIPT
        np_recall_common.PII_FILTER_SCRIPT = os.path.join(_HERE, "no-such-filter-xyz.py")
        try:
            self.assertEqual(np_recall_common.default_pii_filter("keep me"), "keep me")
        finally:
            np_recall_common.PII_FILTER_SCRIPT = orig


if __name__ == "__main__":
    unittest.main()
