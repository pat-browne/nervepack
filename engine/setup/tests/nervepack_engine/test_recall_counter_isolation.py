"""#171: the episodic-recall and lesson-recall per-session counters must never
share a file. They both read EPISODIC_STATE_DIR (with different defaults), so a
shared override would previously merge them onto one bare-`sid` filename, and each
hook's increment would consume the other's recall budget — silently suppressing
recall after a single prompt. The counter filenames are now feature-namespaced."""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nervepack_engine.hooks import episodic_recall, lesson_recall  # noqa: E402


class TestRecallCounterIsolation(unittest.TestCase):
    def test_counter_paths_differ_for_same_state_dir_and_sid(self):
        state_dir, sid = "/shared/state", "abcd-1234"
        ep = episodic_recall._counter_path(state_dir, sid)
        ls = lesson_recall._counter_path(state_dir, sid)
        self.assertNotEqual(ep, ls, "episodic and lesson counters must not share a file")
        # both still live under the (shared) state dir, just under distinct names
        self.assertEqual(os.path.dirname(ep), state_dir)
        self.assertEqual(os.path.dirname(ls), state_dir)
        self.assertTrue(os.path.basename(ep).startswith("ep-"))
        self.assertTrue(os.path.basename(ls).startswith("ls-"))

    def test_slash_in_sid_still_sanitized_in_both(self):
        for mod in (episodic_recall, lesson_recall):
            self.assertNotIn("/", os.path.basename(mod._counter_path("/s", "a/b/c")))


if __name__ == "__main__":
    unittest.main()
