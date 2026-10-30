#!/usr/bin/env python3
"""Endpoint contract tests for the dashboard action buttons (stdlib unittest).

Every job button (Implement, compact Apply, Graduate) shares one path in
np-dashboard-server.py. These tests boot the real server against a fixture
overlay and assert the structured error shape for each failure a click can hit:
a missing overlay, a stale entry, a disabled toggle, a wrong cwd, a dead job.
Dry runs prove the happy path without spawning an agent.
"""
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
SERVER = os.path.join(SETUP, "np-dashboard-server.py")

PROPOSAL = "# P\n\n### np-kb-c vs np-kb-d\n\nRecommendation: merge.\n"
CANDIDATES = {"candidates": [{"kind": "strategy", "name": "s1"}], "thresholds": {}}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com"))


def make_overlay(root, origin=True):
    """A git checkout with one proposal file and one graduation candidate."""
    overlay = os.path.join(root, "overlay")
    os.makedirs(os.path.join(overlay, "compact-proposals"))
    os.makedirs(os.path.join(overlay, "dashboard", "data"))
    with open(os.path.join(overlay, "compact-proposals", "2026-09-30.md"), "w") as fh:
        fh.write(PROPOSAL)
    with open(os.path.join(overlay, "dashboard", "data", "graduation-candidates.json"), "w") as fh:
        json.dump(CANDIDATES, fh)
    git(overlay, "init", "-q", "-b", "main")
    git(overlay, "add", "-A")
    git(overlay, "commit", "-q", "-m", "seed")
    if origin:
        bare = os.path.join(root, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True, capture_output=True)
        git(overlay, "remote", "add", "origin", bare)
        git(overlay, "push", "-q", "origin", "main")
    return overlay


class Booted:
    """One server process with its own temp root. Use as a context manager."""

    def __init__(self, overlay=True, origin=True, env=None, cwd=None, git_repo=True):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.root = root
        self.overlay = make_overlay(root, origin) if overlay else os.path.join(root, "missing")
        if overlay and not git_repo:
            subprocess.run(["rm", "-rf", os.path.join(self.overlay, ".git")], check=True)
        self.job_log = os.path.join(root, "jobs.log")
        self.status_dir = os.path.join(root, "status")
        self.toggles_local = os.path.join(root, "toggles.local")
        self.applied = os.path.join(root, "applied.json")
        self.port = free_port()
        full = dict(os.environ)
        full.pop("NERVEPACK_AGENT", None)
        full.update({
            "NP_DASH_PORT": str(self.port), "NP_CONTENT_DIR": self.overlay,
            "NP_DASH_JOB_LOG": self.job_log, "NP_IMPLEMENT_STATUS_DIR": self.status_dir,
            "NP_TOGGLES_LOCAL": self.toggles_local, "NP_TOGGLE_NO_COMMIT": "1",
            "NP_COMPACT_APPLIED": self.applied, "NP_RESOLVE_NO_BUILD": "1",
            "NP_COMPACT_PROPOSALS_DIR": "", "NP_GRADUATION_CANDIDATES": "",
            "NP_GRADUATION_DISMISSED": "", "NP_IMPLEMENT": "",
        })
        full.update(env or {})
        self.proc = subprocess.Popen(["python3", SERVER], env=full, cwd=cwd or root,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                if self.get("/api/health")[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        self.close()
        raise RuntimeError("server did not come up")

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, json.loads(body or "{}")

    def post(self, path, obj):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", path, json.dumps(obj),
                  {"Content-Type": "application/json", "X-Requested-With": "nervepack"})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, json.loads(body or "{}")

    def jobs_log(self):
        try:
            with open(self.job_log) as fh:
                return fh.read()
        except OSError:
            return ""

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


APPLY = ("/api/compact/apply", {"file": "2026-09-30.md", "title": "np-kb-c vs np-kb-d", "dry_run": True})
GRADUATE = ("/api/graduation/graduate", {"kind": "strategy", "name": "s1", "dry_run": True})


class TestErrorShape(unittest.TestCase):
    def assert_structured(self, body, code):
        self.assertIs(body.get("ok"), False)
        self.assertEqual(body.get("code"), code)
        self.assertTrue(body.get("error"), "error text must not be empty")
        self.assertIn("hint", body)

    def test_unknown_entries_are_stale_not_silent(self):
        with Booted() as s:
            for route, body in (("/api/compact/apply", {"file": "2000-01-01.md", "title": "x"}),
                                ("/api/compact/reject", {"file": "2000-01-01.md", "title": "x"}),
                                ("/api/compact/apply", {}),
                                ("/api/graduation/graduate", {"kind": "strategy", "name": "nope"}),
                                ("/api/graduation/dismiss", {})):
                status, out = s.post(route, body)
                self.assertEqual(status, 404, route)
                self.assert_structured(out, "stale")

    def test_missing_overlay_is_stale_with_a_hint(self):
        with Booted(overlay=False) as s:
            status, out = s.post(*APPLY)
            self.assertEqual(status, 404)
            self.assert_structured(out, "stale")
            self.assertIn("Reload", out["hint"])

    def test_implement_without_text_is_bad_request(self):
        with Booted() as s:
            status, out = s.post("/api/implement", {})
            self.assertEqual(status, 400)
            self.assert_structured(out, "bad_request")

    def test_applied_marker_makes_the_proposal_stale(self):
        with Booted() as s:
            with open(s.applied, "w") as fh:
                json.dump(["2026-09-30.md :: np-kb-c vs np-kb-d"], fh)
            status, out = s.post(*APPLY)
            self.assertEqual(status, 404)
            self.assert_structured(out, "stale")


class TestPreflight(unittest.TestCase):
    def assert_refused(self, s, route, body, needle):
        status, out = s.post(route, body)
        self.assertEqual(status, 409, out)
        self.assertEqual(out["code"], "preflight_failed")
        self.assertIn(needle, out["error"])
        self.assertTrue(out["hint"] or needle == "evaluator.implement")
        self.assertTrue(any(not c["ok"] for c in out["checks"]))
        self.assertNotIn("spawn", s.jobs_log(), "a refused click must not spawn a job")

    def test_overlay_that_is_not_a_repository(self):
        with Booted(git_repo=False) as s:
            self.assert_refused(s, *APPLY, "not a repository")

    def test_overlay_without_origin(self):
        with Booted(origin=False) as s:
            self.assert_refused(s, *GRADUATE, "no origin remote")

    def test_overlay_that_is_the_engine_repo(self):
        repo_root = os.path.normpath(os.path.join(SETUP, "..", ".."))
        with Booted(env={"NP_CONTENT_DIR": repo_root, "NP_COMPACT_PROPOSALS_DIR": os.path.join(
                repo_root, "compact-proposals")}) as s:
            status, out = s.post("/api/compact/apply", {"file": "x.md", "title": "x", "dry_run": True})
            self.assertIn(status, (404, 409))
            self.assertIs(out["ok"], False)

    def test_implement_toggle_off(self):
        with Booted() as s:
            with open(s.toggles_local, "w") as fh:
                fh.write("evaluator.implement=off\n")
            self.assert_refused(s, *APPLY, "evaluator.implement")

    def test_agent_reentry_guard_in_server_env(self):
        with Booted(env={"NERVEPACK_AGENT": "1"}) as s:
            self.assert_refused(s, *GRADUATE, "NERVEPACK_AGENT")


class TestHappyPath(unittest.TestCase):
    def test_dry_run_apply_and_graduate_pass_every_check_and_spawn_nothing(self):
        with Booted() as s:
            for route, body in (APPLY, GRADUATE):
                status, out = s.post(route, body)
                self.assertEqual(status, 200, out)
                self.assertTrue(out["ok"] and out["dry_run"])
                self.assertTrue(all(c["ok"] for c in out["checks"]), out["checks"])
            self.assertNotIn("spawn", s.jobs_log())

    def test_dry_run_dismiss_and_reject_change_nothing(self):
        with Booted() as s:
            status, out = s.post("/api/graduation/dismiss", {"kind": "strategy", "name": "s1", "dry_run": True})
            self.assertEqual(status, 200)
            self.assertTrue(out["dry_run"])
            status, out = s.post("/api/compact/reject", {"file": "2026-09-30.md", "title": "np-kb-c vs np-kb-d",
                                                         "dry_run": True})
            self.assertEqual(status, 200)
            self.assertTrue(out["dry_run"])
            self.assertTrue(os.path.exists(os.path.join(s.overlay, "compact-proposals", "2026-09-30.md")))
            status, out = s.post(*GRADUATE)
            self.assertEqual(status, 200, "a dry-run dismiss must not hide the candidate")

    def test_server_started_from_another_cwd_still_finds_the_overlay(self):
        elsewhere = tempfile.mkdtemp()
        try:
            with Booted(cwd=elsewhere) as s:
                status, out = s.post(*APPLY)
                self.assertEqual(status, 200, out)
        finally:
            os.rmdir(elsewhere)

    def test_health_and_doctor_report_the_api_version(self):
        with Booted() as s:
            self.assertEqual(s.get("/api/health")[1]["api"], 2)
            status, out = s.get("/api/doctor")
            self.assertEqual(status, 200)
            self.assertTrue(out["ok"], out["checks"])
            ids = {c["id"] for c in out["checks"]}
            self.assertTrue({"implement-toggle", "agent-env", "overlay", "job-files", "status-dir"} <= ids)

    def test_doctor_names_a_broken_overlay(self):
        with Booted(origin=False) as s:
            status, out = s.get("/api/doctor")
            self.assertFalse(out["ok"])
            bad = [c for c in out["checks"] if not c["ok"]]
            self.assertEqual(bad[0]["id"], "overlay")
            self.assertTrue(bad[0]["hint"])


class TestPageContract(unittest.TestCase):
    PAGE = os.path.join(SETUP, "..", "..", "dashboard", "index.html")

    def test_failures_use_the_banner_not_a_native_alert(self):
        # Embedded browsers suppress alert(), which made a failed click look like a no-op.
        with open(self.PAGE, encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("alert(", html)
        self.assertIn('id="action-banner"', html)
        self.assertIn("function notify(", html)

    def test_page_and_server_agree_on_the_api_version(self):
        sys_path = os.path.join(SETUP)
        import sys
        sys.path.insert(0, sys_path)
        import np_dashboard_actions
        with open(self.PAGE, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("const EXPECT_API = %d;" % np_dashboard_actions.API_VERSION, html)


class TestDeadJob(unittest.TestCase):
    def test_a_job_that_exits_without_a_status_reports_failed(self):
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "die.sh")
            with open(stub, "w") as fh:
                fh.write('#!/usr/bin/env bash\necho "boom: agent missing" >&2\nexit 3\n')
            os.chmod(stub, 0o755)
            with Booted(env={"NP_IMPLEMENT": stub}) as s:
                status, out = s.post("/api/implement", {"text": "Do the thing"})
                self.assertEqual(status, 200, out)
                state = {}
                for _ in range(50):
                    state = s.get("/api/implement-status?text=Do%20the%20thing")[1]
                    if state.get("state") == "failed":
                        break
                    time.sleep(0.1)
                self.assertEqual(state.get("state"), "failed", state)
                self.assertIn("exited without reporting", state.get("ref", ""))
                self.assertIn("boom", state["ref"])


if __name__ == "__main__":
    unittest.main()
