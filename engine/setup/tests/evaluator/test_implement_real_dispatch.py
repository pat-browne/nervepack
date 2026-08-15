# np-test: implement-real-dispatch | the server's /api/implement route must
#          actually reach np_implement_suggestion.py THROUGH cli.py, not just
#          through a test stub.
"""Every other implement test stubs the job entirely: test_dashboard_server.py's
NP_IMPLEMENT override and the e2e Playwright suite's stub-implement.sh both
replace IMPLEMENT_ARGV with a script that never calls np_implement_suggestion.py.
test_implement_verdict.py/test_implement_modify.py call imp._attempt_repo()/
imp.implement() directly in-process, bypassing the server and cli.py entirely.

So nothing proves the actual chain the dashboard depends on: HTTP POST
/api/implement -> server Popen()s the REAL IMPLEMENT_ARGV (python3 cli.py
implement-suggestion <text>) -> cli.py's dispatch -> np_implement_suggestion.
implement() -> a verified agent commit -> the status file the dashboard polls.
A break in cli.py's own dispatch (a renamed subcommand, an import that only
fails when run as `__main__`, an argv off-by-one) would pass every existing
test and still leave the Implement button posting into a job that silently
does nothing -- the same failure class as the seven-week-dead dashboard
incident in ARCHITECTURE.md invariant 6, just one seam further down the chain.
Only the agent call itself is stubbed here (via the documented IMPLEMENT_LLM
override); everything else -- server, cli.py, np_implement_suggestion.py,
git worktree isolation, commit verification, status write -- is the real code.
"""
import http.client
import json
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "..", "..")
SERVER = os.path.join(SETUP, "np-dashboard-server.py")

# The dashboard server spawns the implement job as its OWN child, inheriting
# the server process's environment -- there is no per-request env override.
# So one stub agent handles both scenarios, branching on the untrusted
# suggestion text piped to it on stdin (the same text np_implement_suggestion.
# _build_prompt() wraps in data markers), rather than needing two server
# instances with two different IMPLEMENT_LLM values.
STUB_AGENT = (
    "#!/usr/bin/env bash\n"
    "prompt=$(cat)\n"
    "if [[ \"$prompt\" == *alpha* ]]; then\n"
    "  echo 'NOT_IMPLEMENTABLE: real-dispatch test stub, not a code change'\n"
    "else\n"
    "  echo 'change' >> NOTES.md\n"
    "  git add NOTES.md\n"
    "  git commit -qm 'test: real-dispatch stub commit'\n"
    "  echo committed\n"
    "fi\n"
)


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestImplementRealDispatch(unittest.TestCase):
    """Drives the server's real IMPLEMENT_ARGV (no NP_IMPLEMENT override) so the
    request actually flows through cli.py's implement-suggestion dispatch."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name

        cls.root = os.path.join(d, "dashboard")
        os.makedirs(cls.root)
        with open(os.path.join(cls.root, "index.html"), "w") as fh:
            fh.write("<html>ok</html>")

        cls.repo = os.path.join(d, "repo")
        os.makedirs(cls.repo)
        _git(cls.repo, "init", "-q", "-b", "main")
        _git(cls.repo, "config", "user.email", "t@t")
        _git(cls.repo, "config", "user.name", "t")
        with open(os.path.join(cls.repo, "seed.txt"), "w") as fh:
            fh.write("seed\n")
        _git(cls.repo, "add", "seed.txt")
        _git(cls.repo, "commit", "-qm", "init")

        cls.status_dir = os.path.join(d, "implement-status")
        os.makedirs(cls.status_dir)

        cls.toggles_conf = os.path.join(d, "toggles.conf")
        with open(cls.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|implement=on,implement_mode=pr,"
                     "dashboard_open=on,dashboard_serve=on\n")
        cls.toggles_local = os.path.join(d, "toggles.local")
        with open(cls.toggles_local, "w"):
            pass

        cls.stub_agent = os.path.join(d, "agent-stub.sh")
        with open(cls.stub_agent, "w") as fh:
            fh.write(STUB_AGENT)
        os.chmod(cls.stub_agent, 0o755)

        cls.port = free_port()
        cls.env = dict(os.environ)
        cls.env.update({
            "NP_DASH_PORT": str(cls.port), "NP_DASH_ROOT": cls.root,
            "NP_METRICS": os.path.join(d, "metrics.jsonl"),
            "NP_RESOLVED_SUGGESTIONS": os.path.join(d, "resolved.txt"),
            "NP_RESOLVE_NO_BUILD": "1",
            "NP_TOGGLES_LOCAL": cls.toggles_local, "NP_TOGGLES_CONF": cls.toggles_conf,
            # Deliberately NOT setting NP_IMPLEMENT: IMPLEMENT_ARGV stays the real
            # default (python3 cli.py implement-suggestion), so this test exercises
            # the actual dispatch, not a stand-in.
            "IMPLEMENT_REPO": cls.repo,
            "IMPLEMENT_LOG": os.path.join(d, "implement.log"),
            "IMPLEMENT_LOCK": os.path.join(d, "implement.lock"),
            "IMPLEMENT_STATUS_DIR": cls.status_dir,
            "NP_IMPLEMENT_STATUS_DIR": cls.status_dir,
            "IMPLEMENT_LLM": cls.stub_agent,
        })
        with open(os.path.join(d, "metrics.jsonl"), "w"):
            pass
        with open(os.path.join(d, "resolved.txt"), "w"):
            pass

        cls.proc = subprocess.Popen(["python3", SERVER], env=cls.env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                if cls._get("/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.tmp.cleanup()

    @classmethod
    def _conn(cls):
        return http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)

    @classmethod
    def _get(cls, path):
        c = cls._conn()
        c.request("GET", path)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def _post(self, path, obj):
        c = self._conn()
        c.request("POST", path, json.dumps(obj),
                  {"Content-Type": "application/json", "X-Requested-With": "nervepack"})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def _poll_status(self, text, timeout=15):
        """Poll /api/implement-status the way the dashboard's own JS does.
        implement_status() returns {"state": "none"} until the job writes its
        file, then the real state (busy|running|done|not_implementable|failed)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = self._get("/api/implement-status?text=" + text.replace(" ", "%20"))
            data = json.loads(body)
            if data.get("state") not in ("none", "running", "busy"):
                return data
            time.sleep(0.2)
        self.fail("implement-status never reached a terminal state for %r" % text)

    def test_not_implementable_reflected_through_the_real_cli_dispatch(self):
        text = "real dispatch test alpha, not a code change"
        status, body = self._post("/api/implement", {"text": text})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("started"))
        result = self._poll_status(text)
        self.assertEqual(result.get("state"), "not_implementable", result)

    def test_implemented_lands_a_verified_commit_through_the_real_cli_dispatch(self):
        text = "real dispatch test beta, please add a note"
        status, body = self._post("/api/implement", {"text": text})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("started"))
        result = self._poll_status(text)
        self.assertEqual(result.get("state"), "done", result)
        branches = _git(self.repo, "branch", "--list", "np-suggest/*").stdout
        self.assertIn("np-suggest/", branches)
        log = _git(self.repo, "log", "--all", "--oneline").stdout
        self.assertIn("real-dispatch stub commit", log)


if __name__ == "__main__":
    unittest.main()
