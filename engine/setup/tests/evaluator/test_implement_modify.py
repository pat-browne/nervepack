"""np_implement_suggestion: the Modify path and the cross-machine guard.

Modify lets the dashboard rewrite a suggestion before implementing it: the AGENT
gets the edit, but the ORIGINAL is what keys the status file the dashboard polls
and what gets resolved off the ledger (the edit was never an evaluator
suggestion, so resolving it would match nothing).

The guard covers the multi-machine setup: several machines share one content
overlay, so a suggestion another machine already implemented arrives resolved on
the next sync and must not earn a second agent pass.
"""
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_implement_suggestion as imp        # noqa: E402
import np_suggestion_resolve as res          # noqa: E402

def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


ORIGINAL = "Add a playbook for security reviews"
EDITED = "Add a lesson (not a playbook) for security reviews, advisory only"


class TestUnresolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, "resolved.txt")

    def tearDown(self):
        self._tmp.cleanup()

    def test_1_removes_a_resolved_entry(self):
        res.resolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        self.assertTrue(res.is_resolved(ORIGINAL, ledger_path=self.ledger))
        msg, code = res.unresolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        self.assertEqual(code, 0)
        self.assertFalse(res.is_resolved(ORIGINAL, ledger_path=self.ledger))

    def test_2_is_idempotent(self):
        """Every machine may run the same recovery against the same synced ledger."""
        res.resolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        res.unresolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        msg, code = res.unresolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", msg)

    def test_3_keeps_the_other_entries(self):
        res.resolve("keep me", ledger_path=self.ledger, no_build=True)
        res.resolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        res.resolve("keep me too", ledger_path=self.ledger, no_build=True)
        res.unresolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        self.assertTrue(res.is_resolved("keep me", ledger_path=self.ledger))
        self.assertTrue(res.is_resolved("keep me too", ledger_path=self.ledger))
        self.assertFalse(res.is_resolved(ORIGINAL, ledger_path=self.ledger))

    def test_4_note_is_recorded_without_breaking_matching(self):
        res.resolve(ORIGINAL, ledger_path=self.ledger, no_build=True, note="implemented as: " + EDITED)
        with open(self.ledger) as fh:
            line = fh.read().strip()
        self.assertIn(EDITED, line)
        self.assertTrue(res.is_resolved(ORIGINAL, ledger_path=self.ledger),
                        "a 3rd tab field must not break normalized matching")


class TestImplementModify(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.ledger = os.path.join(d, "resolved.txt")
        self.log = os.path.join(d, "implement.log")
        self.status = os.path.join(d, "status")
        self.prompt = os.path.join(d, "prompt.md")
        with open(self.prompt, "w") as fh:
            fh.write("PROMPT TEMPLATE\n")
        # Hermetic: without both of these the job resolves the developer's REAL
        # content overlay and runs its content-repo attempt against it.
        os.environ["NP_RESOLVED_SUGGESTIONS"] = self.ledger
        os.environ["NP_CONTENT_DIR"] = os.path.join(d, "content")
        os.makedirs(os.environ["NP_CONTENT_DIR"])

        self.repo = os.path.join(d, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "seed.txt"), "w") as fh:
            fh.write("seed\n")
        _git(self.repo, "add", "seed.txt")
        _git(self.repo, "commit", "-qm", "init")

        self.seen = []
        self.resolved = []

    def tearDown(self):
        os.environ.pop("NP_RESOLVED_SUGGESTIONS", None)
        os.environ.pop("NP_CONTENT_DIR", None)
        self._tmp.cleanup()

    def _run(self, text, edited=None, agent_fn=None):
        def record(prompt, tools, cwd, timeout):
            self.seen.append(prompt)
            return (0, "", "")

        return imp.implement(
            text, edited, repo=self.repo,
            log_path=self.log, lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": self.resolved.append((t, note)),
            agent_fn=agent_fn or record)

    def test_1_agent_receives_the_edited_text(self):
        self._run(ORIGINAL, EDITED)
        self.assertTrue(self.seen)
        self.assertIn(EDITED, self.seen[0])
        self.assertNotIn(ORIGINAL, self.seen[0])

    def test_2_status_is_keyed_by_the_original(self):
        """The dashboard polls with the text it rendered, so the key must not move."""
        self._run(ORIGINAL, EDITED)
        expected = imp._status_key(ORIGINAL) + ".json"
        self.assertIn(expected, os.listdir(self.status))

    def test_3_already_resolved_skips_the_agent(self):
        res.resolve(ORIGINAL, ledger_path=self.ledger, no_build=True)
        self._run(ORIGINAL)
        self.assertEqual(self.seen, [], "no agent pass for work another machine already did")
        with open(os.path.join(self.status, imp._status_key(ORIGINAL) + ".json")) as fh:
            self.assertIn("already_resolved", fh.read())

    def test_4_no_edit_sends_the_original(self):
        self._run(ORIGINAL)
        self.assertIn(ORIGINAL, self.seen[0])


if __name__ == "__main__":
    unittest.main()
