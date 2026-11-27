"""Evaluator suggestions can target any nervepack asset, content included.

Before: the judge saw only the transcript and a skill count, its target enum
had no content slot, and its skill rule turned every keyword-hook nudge into an
"invoke X" miss. A third of all suggestions ended up as security reminders."""
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
for _p in (_SETUP, os.path.join(_SETUP, "..", "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, os.path.normpath(_p))

import np_evaluator  # noqa: E402
import np_implement_suggestion as imp  # noqa: E402


def _skill(root, name, desc):
    d = os.path.join(root, "skills", name)
    os.makedirs(d)
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write("---\nname: %s\ndescription: %s\n---\nbody\n" % (name, desc))


class TestAssetIndex(unittest.TestCase):
    def setUp(self):
        self.eng = tempfile.mkdtemp()
        self.con = tempfile.mkdtemp()
        _skill(self.eng, "np-core-sync", "Sync nervepack with origin.")
        _skill(self.con, "np-kb-sqlserver", "SQL Server gotchas.")
        os.makedirs(os.path.join(self.eng, "engine", "nervepack_engine", "hooks"))
        open(os.path.join(self.eng, "engine", "nervepack_engine", "hooks", "security_recall.py"), "w").close()
        os.makedirs(os.path.join(self.eng, "agents"))
        open(os.path.join(self.eng, "agents", "np-flow-weekly-compact.md"), "w").close()
        os.makedirs(os.path.join(self.con, "wiki", "topics", "home-nas"))
        os.makedirs(os.path.join(self.con, "memory", "lessons"))
        open(os.path.join(self.con, "memory", "lessons", "git-gotcha.md"), "w").close()

    def _index(self):
        with mock.patch.dict(os.environ, {"NP_ENGINE_DIR": self.eng, "NP_CONTENT_DIR": self.con}):
            return np_evaluator.asset_index()

    def test_lists_every_asset_kind(self):
        idx = self._index()
        for needle in ("np-core-sync", "Sync nervepack", "np-kb-sqlserver", "security_recall",
                       "np-flow-weekly-compact", "home-nas", "git-gotcha"):
            self.assertIn(needle, idx, needle)

    def test_capped(self):
        for i in range(400):
            _skill(self.con, "np-kb-x%03d" % i, "d" * 80)
        self.assertLessEqual(len(self._index()), np_evaluator.ASSET_INDEX_CAP)

    def test_missing_roots_fail_open(self):
        with mock.patch.dict(os.environ, {"NP_ENGINE_DIR": "/nope", "NP_CONTENT_DIR": "/nope2"}):
            self.assertEqual(np_evaluator.asset_index(), "")


class TestPrompt(unittest.TestCase):
    def test_prompt_carries_index_and_new_targets(self):
        tail = np_evaluator._prompt_tail("{}", "ASSET-LIST-HERE")
        self.assertIn("ASSET-LIST-HERE", tail)
        for t in ("content", "agents", "harness"):
            self.assertIn(t, tail)
        self.assertIn('asset (the asset name', tail)

    def test_hook_nudge_is_not_a_miss(self):
        tail = np_evaluator._prompt_tail("{}", "")
        self.assertIn("keyword hook", tail)


class TestRouting(unittest.TestCase):
    def test_new_targets_route(self):
        self.assertEqual(imp._attempt_order("content"), ("content", "engine"))
        self.assertEqual(imp._attempt_order("agents"), ("engine", "content"))
        self.assertEqual(imp._attempt_order("harness"), ("engine", "content"))


if __name__ == "__main__":
    unittest.main()
