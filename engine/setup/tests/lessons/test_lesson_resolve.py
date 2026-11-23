# np-test: lesson resolved state | happy
"""np_lesson_resolve: a lesson linked to a GitHub issue or PR turns resolved once it closes or merges."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine"))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import np_lesson_resolve as res  # noqa: E402

FAIL = ("---\nname: t\nkind: lesson\nprovenance: failure\nstatus: candidate\n"
        "resolved_by: https://github.com/o/r/pull/7\n---\n## X\n- DO y\n")
SUCC = "---\nname: t\nkind: lesson\nprovenance: success\nstatus: candidate\n---\n## Z\n- DO w\n"


def _runner(outputs):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = outputs.get(cmd[1] if cmd[:2] != ["gh", "api"] else cmd[2], "")
        if isinstance(out, Exception):
            raise out
        return subprocess.CompletedProcess(cmd, 0 if out is not None else 1, out or "", "")
    run.calls = calls
    return run


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = os.path.join(self.tmp, "t.md")
        with open(self.f, "w") as fh:
            fh.write(FAIL + SUCC)

    def test_parse_ref(self):
        self.assertEqual(res.parse_ref("https://github.com/o/r/pull/7"), ("o", "r", "7"))
        self.assertEqual(res.parse_ref("https://github.com/o/r/issues/12"), ("o", "r", "12"))
        self.assertEqual(res.parse_ref("o/r#3"), ("o", "r", "3"))
        self.assertIsNone(res.parse_ref("https://evil.example/o/r/pull/7"))
        self.assertIsNone(res.parse_ref("o/r#3; rm -rf /"))

    def test_resolved_provenances(self):
        self.assertEqual(res.resolved_provenances(self.f), set())
        with open(self.f, "w") as fh:
            fh.write(FAIL.replace("status: candidate", "status: resolved") + SUCC)
        self.assertEqual(res.resolved_provenances(self.f), {"failure"})
        self.assertTrue(res.is_resolved(self.f, "failure"))
        self.assertFalse(res.is_resolved(self.f, "success"))
        self.assertEqual(res.resolved_provenances(os.path.join(self.tmp, "none.md")), set())

    def test_sweep_marks_merged_pr_block_only(self):
        run = _runner({"auth": "", "repos/o/r/issues/7": "closed\t2026-11-20T00:00:00Z\tcompleted"})
        done = res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh", today="2026-11-23")
        self.assertEqual(done, ["t"])
        text = open(self.f).read()
        self.assertIn("status: resolved\nresolved_on: 2026-11-23\nresolved_by:", text)
        self.assertEqual(text.count("status: resolved"), 1)
        self.assertIn("provenance: success\nstatus: candidate", text)

    def test_open_issue_or_closed_unmerged_pr_stays(self):
        for out in ("open\t\t", "closed\t\tcompleted"):
            with self.subTest(out=out):
                run = _runner({"auth": "", "repos/o/r/issues/7": out})
                self.assertEqual(res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh"), [])
        self.assertNotIn("status: resolved", open(self.f).read())

    def test_closed_issue_resolves(self):
        with open(self.f, "w") as fh:
            fh.write(FAIL.replace("pull/7", "issues/7"))
        run = _runner({"auth": "", "repos/o/r/issues/7": "closed\t\tcompleted"})
        self.assertEqual(res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh"), ["t"])

    def test_fail_open_without_gh_or_login(self):
        self.assertEqual(res.sweep([self.tmp], runner=_runner({}), which=lambda _: None), [])
        run = _runner({"auth": None})
        self.assertEqual(res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh"), [])
        self.assertEqual(len(run.calls), 1)
        run = _runner({"auth": "", "repos/o/r/issues/7": OSError("boom")})
        self.assertEqual(res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh"), [])
        self.assertNotIn("status: resolved", open(self.f).read())


    def test_dot_segments_rejected(self):
        self.assertIsNone(res.parse_ref("https://github.com/../r/pull/7"))
        self.assertIsNone(res.parse_ref("./r#7"))

    def test_issue_closed_not_planned_stays_open(self):
        with open(self.f, "w") as fh:
            fh.write(FAIL.replace("pull/7", "issues/7"))
        run = _runner({"auth": "", "repos/o/r/issues/7": "closed\t\tnot_planned"})
        self.assertEqual(res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh"), [])

    def test_any_open_failure_block_keeps_gate(self):
        with open(self.f, "w") as fh:
            fh.write(FAIL.replace("status: candidate", "status: resolved") + FAIL)
        self.assertFalse(res.is_resolved(self.f, "failure"))


    def test_owner_outside_allowlist_ignored_and_logged(self):
        logged = []
        run = _runner({"auth": "", "repos/o/r/issues/7": "closed\t2026-11-20T00:00:00Z\t"})
        out = res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh",
                        owners={"demo-user"}, log=logged.append)
        self.assertEqual(out, [])
        self.assertEqual(len(run.calls), 1)
        self.assertIn("o/r#7", logged[0])
        out = res.sweep([self.tmp], runner=run, which=lambda _: "/bin/gh", owners={"O"})
        self.assertEqual(out, ["t"])

    def test_default_owners_from_remotes(self):
        def run(cmd, **kw):
            url = {"a": "https://github.com/demo-user/nervepack\n",
                   "b": "git@github.com:Acme-Org/x.git\n", "c": ""}[cmd[2]]
            return subprocess.CompletedProcess(cmd, 0 if url else 1, url, "")
        self.assertEqual(res.default_owners(["a", "b", "c"], runner=run), {"demo-user", "acme-org"})

    def test_parse_owners_param(self):
        self.assertEqual(res.parse_owners("demo-user + Acme-Org"), {"demo-user", "acme-org"})
        self.assertEqual(res.parse_owners(""), set())


if __name__ == "__main__":
    unittest.main()
