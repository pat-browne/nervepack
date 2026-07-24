"""Direct unit tests for np_suggestion_resolve.py -- port of
np-suggestion-resolve.sh. Ports the 4 cases from test_suggestion_resolve.sh:
append, dedup (case/space-insensitive), distinct-suggestion-added,
empty-arg-errors."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_suggestion_resolve  # noqa: E402


class TestSuggestionResolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, "resolved.txt")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, text):
        return np_suggestion_resolve.resolve(text, ledger_path=self.ledger, no_build=True)

    def test_1_appends_suggestion(self):
        msg, code = self._run("Promote auto-push rule")
        self.assertEqual(code, 0)
        with open(self.ledger) as fh:
            content = fh.read()
        self.assertTrue(content.startswith("Promote auto-push rule\t"))

    def test_2_dedup_case_and_space_insensitive(self):
        self._run("Promote auto-push rule")
        msg, code = self._run("promote   AUTO-push rule")
        self.assertEqual(code, 0)
        with open(self.ledger) as fh:
            lines = [ln for ln in fh.read().splitlines() if ln and not ln.startswith("#")]
        self.assertEqual(len(lines), 1)

    def test_3_distinct_suggestion_appended(self):
        self._run("Promote auto-push rule")
        self._run("Strengthen the directive")
        with open(self.ledger) as fh:
            lines = [ln for ln in fh.read().splitlines() if ln and not ln.startswith("#")]
        self.assertEqual(len(lines), 2)

    def test_4_empty_arg_errors(self):
        msg, code = self._run("")
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.ledger) and os.path.getsize(self.ledger) > 0)


if __name__ == "__main__":
    unittest.main()
