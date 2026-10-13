# np-test: implement-kinds | compact-apply and graduate jobs reuse the implement queue
"""np_implement_suggestion job kinds.

The dashboard's compact-proposal Apply and graduation Graduate buttons reuse the
suggestion Implement machinery. A `kind` picks the agent prompt, routes the
content overlay first, and skips the suggestion ledger.
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


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


def _mkrepo(path, marker):
    os.makedirs(path)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    with open(os.path.join(path, marker), "w") as fh:
        fh.write("marker\n")
    _git(path, "add", marker)
    _git(path, "commit", "-qm", "init")
    return path


class TestKinds(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.status = os.path.join(d, "status")
        self.prompt = os.path.join(d, "prompt.md")
        with open(self.prompt, "w") as fh:
            fh.write("SUGGESTION TEMPLATE\n")
        os.environ["NP_RESOLVED_SUGGESTIONS"] = os.path.join(d, "resolved.txt")
        self.engine = _mkrepo(os.path.join(d, "engine"), "engine-marker.txt")
        self.content = _mkrepo(os.path.join(d, "content"), "content-marker.txt")
        os.environ["NP_CONTENT_DIR"] = self.content
        self.calls, self.resolved = [], []

    def tearDown(self):
        os.environ.pop("NP_RESOLVED_SUGGESTIONS", None)
        os.environ.pop("NP_CONTENT_DIR", None)
        self._tmp.cleanup()

    def _run(self, text, kind):
        def record(prompt, tools, cwd, timeout):
            which = "content" if os.path.exists(os.path.join(cwd, "content-marker.txt")) else "engine"
            self.calls.append((which, prompt))
            return (0, "NOT_IMPLEMENTABLE: test", "")

        return imp.implement(
            text, None, repo=self.engine, kind=kind,
            log_path=os.path.join(self._tmp.name, "log"),
            lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": self.resolved.append(t), agent_fn=record)

    def test_compact_kind_uses_its_prompt_and_overlay_first(self):
        self._run("compact-proposals/2026-09-30.md :: a vs b", "compact")
        self.assertEqual(self.calls[0][0], "content")
        self.assertIn("compact proposal", self.calls[0][1].lower())
        self.assertNotIn("SUGGESTION TEMPLATE", self.calls[0][1])

    def test_graduate_kind_uses_its_prompt(self):
        self._run("strategy:security-review", "graduate")
        self.assertIn("np-core-graduate", self.calls[0][1])

    def test_unknown_kind_falls_back_to_suggestion(self):
        self._run("Do a thing", "../../etc")
        self.assertIn("SUGGESTION TEMPLATE", self.calls[0][1])

    def test_kind_survives_the_queue(self):
        qdir = imp.queue_dir(self.status)
        self.assertTrue(imp.enqueue(qdir, self.status, "x", kind="compact"))
        self.assertEqual(imp.queue_entries(qdir)[0][1]["kind"], "compact")


if __name__ == "__main__":
    unittest.main()
