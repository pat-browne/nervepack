# np-test: dashboard-actions | compact proposals parse/reject and graduation dismissals
"""np_dashboard_actions: proposal parsing, one-click reject, and dismissals."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
import np_dashboard_actions as A  # noqa: E402

PROPOSAL = """# Compact proposals 2026-09-30

## Ambiguous merge candidates

### np-kb-a vs np-kb-b

Some table.

**Recommendation: keep separate, they serve different triggers.**

### np-kb-c vs np-kb-d

Recommendation: merge with rewrite.

## Split proposals

Nothing here.
"""


class TestProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        with open(os.path.join(self.d, "2026-09-30.md"), "w") as fh:
            fh.write(PROPOSAL)
        with open(os.path.join(self.d, "REJECTED.md"), "w") as fh:
            fh.write("# Rejected\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_titles_and_recommendations(self):
        files = A.load_proposals(self.d)
        self.assertEqual([f["file"] for f in files], ["2026-09-30.md"])
        props = files[0]["proposals"]
        self.assertEqual([p["title"] for p in props], ["np-kb-a vs np-kb-b", "np-kb-c vs np-kb-d"])
        self.assertTrue(props[0]["keep_separate"])
        self.assertIn("keep separate", props[0]["recommendation"])
        self.assertFalse(props[1]["keep_separate"])
        self.assertEqual(props[1]["recommendation"], "merge with rewrite")

    def test_rejected_md_is_not_a_proposal_file(self):
        self.assertNotIn("REJECTED.md", [f["file"] for f in A.load_proposals(self.d)])

    def test_reject_removes_entry_and_notes_it(self):
        self.assertTrue(A.reject_proposal(self.d, "2026-09-30.md", "np-kb-a vs np-kb-b", today="2026-10-13"))
        with open(os.path.join(self.d, "2026-09-30.md")) as fh:
            body = fh.read()
        self.assertNotIn("np-kb-a vs np-kb-b", body)
        self.assertIn("np-kb-c vs np-kb-d", body)
        self.assertIn("## Split proposals", body)
        with open(os.path.join(self.d, "REJECTED.md")) as fh:
            rej = fh.read().splitlines()
        self.assertEqual(len(rej), 2)
        self.assertIn("2026-10-13 | 2026-09-30.md | np-kb-a vs np-kb-b", rej[1])

    def test_reject_last_entry_deletes_file(self):
        A.reject_proposal(self.d, "2026-09-30.md", "np-kb-a vs np-kb-b")
        A.reject_proposal(self.d, "2026-09-30.md", "np-kb-c vs np-kb-d")
        self.assertFalse(os.path.exists(os.path.join(self.d, "2026-09-30.md")))
        self.assertEqual(A.load_proposals(self.d), [])

    def test_reject_unknown_or_unsafe_is_refused(self):
        self.assertFalse(A.reject_proposal(self.d, "2026-09-30.md", "nope"))
        self.assertFalse(A.reject_proposal(self.d, "../2026-09-30.md", "np-kb-a vs np-kb-b"))
        self.assertFalse(A.reject_proposal(self.d, "REJECTED.md", "x"))

    def test_missing_dir_is_empty(self):
        self.assertEqual(A.load_proposals(os.path.join(self.d, "absent")), [])


class TestDismissals(unittest.TestCase):
    def test_dismiss_persists_and_filters(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "graduation-dismissed.json")
            self.assertEqual(A.load_dismissed(path), [])
            A.dismiss(path, "strategy", "s1")
            A.dismiss(path, "strategy", "s1")
            self.assertEqual(A.load_dismissed(path), ["strategy:s1"])
            grad = {"candidates": [{"kind": "strategy", "name": "s1"},
                                   {"kind": "playbook", "name": "p1"}], "thresholds": {}}
            out = A.filter_candidates(grad, A.load_dismissed(path))
            self.assertEqual([c["name"] for c in out["candidates"]], ["p1"])

    def test_find_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "graduation-candidates.json")
            with open(path, "w") as fh:
                json.dump({"candidates": [{"kind": "strategy", "name": "s1"}]}, fh)
            self.assertIsNotNone(A.find_candidate(path, "strategy", "s1"))
            self.assertIsNone(A.find_candidate(path, "strategy", "nope"))
            self.assertIsNone(A.find_candidate(os.path.join(d, "absent"), "strategy", "s1"))


if __name__ == "__main__":
    unittest.main()
