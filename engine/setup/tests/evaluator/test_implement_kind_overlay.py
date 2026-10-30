# np-test: implement-kind-overlay | compact/graduate jobs run in the overlay only and push there direct
"""Kind jobs (compact Apply, graduation Graduate) are overlay content.

Compact proposals, lessons and np-kb-*/np-env-* skills live in the content
overlay. A kind job must never spend an agent pass in the engine, so a dead end
never reads "engine: wrong repo". It bases on the overlay's origin default
branch and pushes there direct. A "keep separate" compact Apply records the
pair in REJECTED.md with no agent pass. A finished graduation drops off the
dashboard.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

# Never read or write the real per-machine applied marker.
os.environ["NP_COMPACT_APPLIED"] = os.path.join(tempfile.mkdtemp(), "applied.json")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_dashboard_actions as acts          # noqa: E402
import np_implement_suggestion as imp        # noqa: E402

PROPOSAL = """# Compact proposals

### np-kb-a vs np-kb-b
Overlap is small.
**Recommendation:** keep separate

### np-kb-c vs np-kb-d
**Recommendation:** merge into np-kb-c
"""


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


def _overlay(root):
    """A bare origin plus a clone on main with one proposal file."""
    origin = os.path.join(root, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    clone = os.path.join(root, "content")
    subprocess.run(["git", "clone", "-q", origin, clone], check=True, capture_output=True)
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-q", "-b", "main")
    os.makedirs(os.path.join(clone, "compact-proposals"))
    with open(os.path.join(clone, "compact-proposals", "2026-10-15.md"), "w") as fh:
        fh.write(PROPOSAL)
    os.makedirs(os.path.join(clone, "memory", "lessons"))
    for name in ("ado-session-sync", "y", "z"):
        with open(os.path.join(clone, "memory", "lessons", name + ".md"), "w") as fh:
            fh.write("---\nstatus: active\n---\nbody\n")
    with open(os.path.join(clone, "content-marker.txt"), "w") as fh:
        fh.write("m\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "init")
    _git(clone, "push", "-q", "-u", "origin", "main")
    return origin, clone


def _engine(root):
    p = os.path.join(root, "engine")
    os.makedirs(p)
    _git(p, "init", "-q", "-b", "main")
    _git(p, "config", "user.email", "t@t")
    _git(p, "config", "user.name", "t")
    with open(os.path.join(p, "engine-marker.txt"), "w") as fh:
        fh.write("m\n")
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "init")
    return p


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.status = os.path.join(self.d, "status")
        self.engine = _engine(self.d)
        self.origin, self.content = _overlay(self.d)
        os.environ["NP_CONTENT_DIR"] = self.content
        self.dismissed = os.path.join(self.d, "dismissed.json")
        os.environ["NP_GRADUATION_DISMISSED"] = self.dismissed
        self.calls = []

    def tearDown(self):
        for k in ("NP_CONTENT_DIR", "NP_GRADUATION_DISMISSED"):
            os.environ.pop(k, None)
        self._tmp.cleanup()

    def run_job(self, text, kind, agent=None):
        def default(prompt, tools, cwd, timeout):
            which = "content" if os.path.exists(os.path.join(cwd, "content-marker.txt")) else "engine"
            self.calls.append((which, prompt))
            return (0, "NOT_IMPLEMENTABLE: test", "")

        imp.implement(text, None, repo=self.engine, kind=kind,
                      log_path=os.path.join(self.d, "log"),
                      lock_path=os.path.join(self.d, "lock"),
                      status_dir=self.status,
                      resolve_fn=lambda t, note="": None, agent_fn=agent or default,
                      gh_pr_create_fn=lambda *a: "")
        with open(os.path.join(self.status, imp._status_key(text) + ".json")) as fh:
            return json.load(fh)

    def origin_file(self, path):
        r = subprocess.run(["git", "--git-dir", self.origin, "show", "main:" + path],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None


class TestRouting(_Base):
    def test_kind_repos_is_overlay_only(self):
        for kind in ("compact", "graduate"):
            self.assertEqual(imp._kind_repos(kind), ("content",))
        self.assertEqual(imp._kind_repos(""), None)

    def test_kind_job_never_tries_the_engine(self):
        st = self.run_job("2026-10-15.md :: np-kb-c vs np-kb-d", "compact")
        self.assertEqual([c[0] for c in self.calls], ["content"])
        self.assertNotIn("engine", st["ref"])
        self.assertNotIn("wrong repo", st["ref"])

    def test_no_overlay_fails_clearly_without_engine_pass(self):
        os.environ["NP_CONTENT_DIR"] = self.engine
        st = self.run_job("failure:x", "graduate")
        self.assertEqual(self.calls, [])
        self.assertEqual(st["state"], "failed")
        self.assertIn("no content overlay", st["ref"])


class TestCompactKeepSeparate(_Base):
    def test_apply_keep_separate_records_rejected_without_agent(self):
        st = self.run_job("2026-10-15.md :: np-kb-a vs np-kb-b", "compact")
        self.assertEqual(self.calls, [])
        self.assertEqual(st["state"], "done")
        rejected = self.origin_file("compact-proposals/REJECTED.md")
        self.assertIn("np-kb-a vs np-kb-b", rejected)
        self.assertIn("kept separate", rejected)
        left = self.origin_file("compact-proposals/2026-10-15.md")
        self.assertNotIn("np-kb-a vs np-kb-b", left)
        self.assertIn("np-kb-c vs np-kb-d", left)
        # The checkout the dashboard reads is clean and current.
        self.assertEqual(_git(self.content, "status", "--porcelain").stdout.strip(), "")
        self.assertIsNone(acts.find_proposal(os.path.join(self.content, "compact-proposals"),
                                             "2026-10-15.md", "np-kb-a vs np-kb-b"))

    def test_apply_that_raises_lands_nothing(self):
        def boom(*a, **k):
            raise OSError("disk full")
        orig = imp.np_dashboard_actions.reject_proposal
        imp.np_dashboard_actions.reject_proposal = boom
        self.addCleanup(setattr, imp.np_dashboard_actions, "reject_proposal", orig)
        st = self.run_job("2026-10-15.md :: np-kb-a vs np-kb-b", "compact")
        self.assertEqual(st["state"], "failed")
        self.assertIn("disk full", st["ref"])
        self.assertIsNone(self.origin_file("compact-proposals/REJECTED.md"))

    def test_reject_note_names_the_action(self):
        pdir = os.path.join(self.content, "compact-proposals")
        self.assertTrue(acts.reject_proposal(pdir, "2026-10-15.md", "np-kb-a vs np-kb-b",
                                             today="2026-10-16", action="kept separate"))
        with open(os.path.join(pdir, "REJECTED.md")) as fh:
            self.assertIn("| kept separate", fh.read())


class TestLanding(_Base):
    def _edit(self, prompt, tools, cwd, timeout):
        self.calls.append(("content", prompt))
        with open(os.path.join(cwd, "graduated.md"), "w") as fh:
            fh.write("x\n")
        return (0, "done", "")

    def test_graduate_pushes_overlay_main_direct_and_dismisses(self):
        st = self.run_job("failure:ado-session-sync", "graduate", agent=self._edit)
        self.assertEqual(st["state"], "done")
        self.assertEqual(self.origin_file("graduated.md"), "x\n")
        with open(self.dismissed) as fh:
            self.assertIn("failure:ado-session-sync", json.load(fh))

    def test_drifted_checkout_still_bases_on_origin_main(self):
        _git(self.content, "checkout", "-q", "-b", "feature")
        with open(os.path.join(self.content, "wip.md"), "w") as fh:
            fh.write("wip\n")
        _git(self.content, "add", "wip.md")
        _git(self.content, "commit", "-qm", "wip")
        feat = _git(self.content, "rev-parse", "feature").stdout
        self.run_job("failure:y", "graduate", agent=self._edit)
        self.assertEqual(self.origin_file("graduated.md"), "x\n")
        self.assertIsNone(self.origin_file("wip.md"))
        self.assertEqual(_git(self.content, "rev-parse", "feature").stdout, feat)

    def test_graduate_prompt_is_lesson_to_skill(self):
        self.run_job("failure:z", "graduate")
        prompt = self.calls[0][1]
        self.assertIn("failure", prompt)
        self.assertIn("status: promoted", prompt)
        self.assertNotIn("Read\n`skills/np-core-graduate/SKILL.md`", prompt)


if __name__ == "__main__":
    unittest.main()
