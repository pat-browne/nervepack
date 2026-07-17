#!/usr/bin/env python3
# np-test: knowledge-capture | failure
"""Tier-1 coverage for the MCP knowledge-capture / retrieval tools.

Mirrors test_mcp_server.py's scripted-stdio client. Covers the writes-gated
lifecycle tools (capture / evaluate / flush), the recall failure path, and the
contribute / suggestions-implement durable-write happy paths. Everything is
isolated: writes land in tempdirs, the LLM seam never reaches a real `claude`,
and the contribute git commit happens in a throwaway repo (no real push).
"""
import json, os, subprocess, sys, tempfile, threading, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SERVER = os.path.join(REPO, "engine", "setup", "np-mcp-server.py")
FIXTURES = os.path.join(REPO, "engine", "setup", "tests", "mcp", "fixtures")


def _readline_timed(proc, timeout=15):
    """Read one line from proc.stdout, raising TimeoutError if the server doesn't respond.

    Uses a daemon thread so the bound applies even when Python's BufferedReader has
    already consumed OS-pipe bytes into its internal buffer (making select() on the raw
    fd appear "not ready" despite readline() having data available immediately).
    """
    result = [None]
    exc = [None]

    def _read():
        try:
            result[0] = proc.stdout.readline()
        except Exception as e:  # noqa: BLE001
            exc[0] = e

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        raise TimeoutError(f"MCP server did not respond within {timeout}s")
    if exc[0]:
        raise exc[0]
    return result[0]


class MCPClient:
    def __init__(self, extra_env=None):
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        self.p = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self._id = 0

    def _send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        mid = None
        if not notify:
            self._id += 1
            mid = self._id
            msg["id"] = mid
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        return mid

    def call(self, method, params=None, timeout=15):
        # doctor shells out to np-doctor.sh which can take ~9.5 s; give it extra room.
        if method == "tools/call" and isinstance(params, dict):
            if params.get("name") == "nervepack_doctor":
                timeout = 30
        mid = self._send(method, params)
        while True:
            line = _readline_timed(self.p, timeout=timeout)
            if not line:
                raise RuntimeError("server closed; stderr:\n" + self.p.stderr.read())
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == mid:
                return resp

    def initialize(self):
        r = self.call("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        })
        self._send("notifications/initialized", notify=True)
        return r

    def tool(self, name, arguments):
        return self.call("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        for stream in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                stream.close()
            except Exception:
                pass
        try:
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def _fix(name):
    return os.path.join(FIXTURES, name)


def _make_claude_stub(stub_dir, canned_json):
    """Write a CLAUDE_BIN stub that reads stdin, emits canned_json on stdout.

    The stub ignores all CLI args — np_capture / np_evaluator pass the prompt
    via stdin (np_model.complete() pipes it) so the stub just needs to drain
    stdin and emit the canned response, exactly as test_capture_invocation.sh
    does.
    """
    stub = os.path.join(stub_dir, "claude")
    with open(stub, "w") as fh:
        fh.write("#!/usr/bin/env bash\n")
        fh.write("cat >/dev/null 2>&1 || true\n")  # drain stdin; ignore args
        fh.write("printf '%s' " + repr(canned_json) + "\n")
    os.chmod(stub, 0o755)
    return stub


class TestLifecycle(unittest.TestCase):
    def _hermetic_env(self, extra=None):
        """A fresh isolated HOME so writes never touch the real machine."""
        home = tempfile.mkdtemp()
        self._homes.append(home)
        env = {
            "HOME": home,
            "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "CLAUDE_BIN": "/bin/false",          # default: any `claude -p` call fails -> fail-open bail
            "NP_LLM_BACKEND": "claude",
            "NP_FLUSH_NODETACH": "1",            # keep flush in the foreground
        }
        if extra:
            env.update(extra)
        return env

    def _client(self, extra_env=None):
        c = MCPClient(extra_env=self._hermetic_env(extra_env))
        self.addCleanup(c.close)
        c.initialize()
        return c

    def setUp(self):
        self._homes = []

        def _cleanup_homes():
            import shutil
            for h in self._homes:
                shutil.rmtree(h, ignore_errors=True)
        self.addCleanup(_cleanup_homes)

    def _transcript(self, dirpath):
        """Write a minimal valid transcript.jsonl into dirpath and return its path."""
        tp = os.path.join(dirpath, "transcript.jsonl")
        with open(tp, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
        return tp

    # --- capture --------------------------------------------------------
    def test_capture_happy_writes_on(self):
        # Install a CLAUDE_BIN stub that emits a valid canned capture summary so
        # np_capture.capture() (episodic-capture.sh's retired logic, now the MCP
        # server's only capture implementation) completes its real pipeline and
        # writes an inbox note.
        inbox = tempfile.mkdtemp()
        self._homes.append(inbox)
        home = tempfile.mkdtemp()
        self._homes.append(home)
        stub = _make_claude_stub(
            home,
            '{"headline":"did the thing","body":"worked on tests","candidate_topics":["misc"],'
            '"keywords":["test","python"],"struggles":[],"strategies":[]}'
        )
        env = {
            "NP_TOGGLES_LOCAL": _fix("writes-on.local"),
            "EPISODIC_INBOX": inbox,
            "EPISODIC_SEEN_DIR": os.path.join(home, "capture-seen"),
            "CLAUDE_BIN": stub,
            "HOME": home,
        }
        c = self._client(env)
        tp = self._transcript(home)
        r = c.tool("nervepack_capture", {"transcript_path": tp, "cwd": home, "session_id": "s1"})
        self.assertFalse(r["result"]["isError"])
        # Real side effect: np_capture.capture() wrote at least one .jsonl note into inbox.
        inbox_files = [f for f in os.listdir(inbox) if f.endswith(".jsonl")]
        self.assertTrue(
            len(inbox_files) > 0,
            f"inbox is empty — capture did not write a note (fallback literal returned). inbox={inbox!r}",
        )

    def test_capture_failure_writes_off(self):
        # Use a valid transcript so the only variable is the writes=off toggle.
        home = self._hermetic_env()["HOME"]
        tp = self._transcript(home)
        c = self._client({"NP_TOGGLES_LOCAL": _fix("writes-off.local"), "HOME": home})
        r = c.tool("nervepack_capture", {"transcript_path": tp, "cwd": home, "session_id": "s1"})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    # --- evaluate -------------------------------------------------------
    def test_evaluate_happy_writes_on(self):
        # Install a CLAUDE_BIN stub that emits a valid canned evaluator verdict so
        # np_evaluator.evaluate() (np-evaluator.sh's retired logic, now the MCP
        # server's only evaluate implementation) completes its real pipeline and
        # writes an inbox record.
        eval_inbox = tempfile.mkdtemp()
        self._homes.append(eval_inbox)
        home = tempfile.mkdtemp()
        self._homes.append(home)
        stub = _make_claude_stub(
            home,
            '{"contribution_score":75,"helped":["recall"],"shortfalls":[],"suggestions":[],"assets_used":[]}'
        )
        env = {
            "NP_TOGGLES_LOCAL": _fix("writes-on.local"),
            "EVAL_INBOX": eval_inbox,
            "CLAUDE_BIN": stub,
            "HOME": home,
        }
        c = self._client(env)
        tp = self._transcript(home)
        r = c.tool("nervepack_evaluate", {"transcript_path": tp, "cwd": home, "session_id": "s1"})
        self.assertFalse(r["result"]["isError"])
        # Real side effect: np_evaluator.evaluate() wrote at least one .jsonl record into eval_inbox.
        inbox_files = [f for f in os.listdir(eval_inbox) if f.endswith(".jsonl")]
        self.assertTrue(
            len(inbox_files) > 0,
            f"eval inbox is empty — evaluator did not write a record (fallback literal returned). inbox={eval_inbox!r}",
        )

    def test_evaluate_failure_writes_off(self):
        # Use a valid transcript so the only variable is the writes=off toggle.
        home = self._hermetic_env()["HOME"]
        tp = self._transcript(home)
        c = self._client({"NP_TOGGLES_LOCAL": _fix("writes-off.local"), "HOME": home})
        r = c.tool("nervepack_evaluate", {"transcript_path": tp, "cwd": home, "session_id": "s1"})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    # --- flush ----------------------------------------------------------
    def test_flush_writes_gate_passthrough(self):
        # np-session-flush.sh routes all output to SESSION_FLUSH_LOG; the sub-steps
        # (aggregate-metrics, episodic-maintain) are each gated by their own toggles
        # (evaluator.aggregate, memory.maintain) and produce no further observable
        # file side effect in isolation.  This test covers the writes-gate passthrough:
        # when mcp.writes=on, the flush script is invoked, runs both sub-steps
        # (idempotent no-ops with empty inboxes), and logs "flush start"/"flush done".
        home = tempfile.mkdtemp()
        self._homes.append(home)
        flush_log = os.path.join(home, "session-flush.log")
        env = {
            "NP_TOGGLES_LOCAL": _fix("writes-on.local"),
            "SESSION_FLUSH_LOG": flush_log,
            "HOME": home,
        }
        c = self._client(env)
        r = c.tool("nervepack_flush", {})
        self.assertFalse(r["result"]["isError"])
        # Real side effect: np-session-flush.sh logged its start and completion.
        self.assertTrue(
            os.path.exists(flush_log),
            "flush log was not created — np-session-flush.sh did not run",
        )
        with open(flush_log) as fh:
            log_content = fh.read()
        self.assertIn("flush start", log_content, f"'flush start' missing from log: {log_content!r}")
        self.assertIn("flush done", log_content, f"'flush done' missing from log: {log_content!r}")

    def test_flush_failure_writes_off(self):
        c = self._client({"NP_TOGGLES_LOCAL": _fix("writes-off.local")})
        r = c.tool("nervepack_flush", {})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    # --- recall failure -------------------------------------------------
    def test_recall_no_index_no_matches_not_error(self):
        # No INDEX.md anywhere in the content dir -> clean "(no matches)" regardless of query.
        empty = tempfile.mkdtemp()
        self._homes.append(empty)
        c = self._client({"NP_CONTENT_DIR": empty})
        r = c.tool("nervepack_recall", {"query": "some real-looking query about auth"})
        self.assertFalse(r["result"]["isError"])
        self.assertEqual(r["result"]["content"][0]["text"].strip(), "(no matches)")

    def test_recall_empty_query_with_index_no_matches_not_error(self):
        # Plant a minimal episodic/INDEX.md so the no-index short-circuit is bypassed.
        # An empty/whitespace query scores 0 against every topic -> episodic-match.sh
        # prints nothing -> _tool_recall still returns "(no matches)" cleanly.
        content = tempfile.mkdtemp()
        self._homes.append(content)
        ep_dir = os.path.join(content, "memory", "episodic")
        os.makedirs(ep_dir)
        with open(os.path.join(ep_dir, "INDEX.md"), "w") as fh:
            fh.write("| topic | last_updated | sessions | keywords |\n")
            fh.write("|-------|-------------|---------|----------|\n")
            fh.write("| auth-patterns | 2026-01-01 | 1 | oauth, login, token |\n")
        c = self._client({"NP_CONTENT_DIR": content})
        r = c.tool("nervepack_recall", {"query": ""})
        self.assertFalse(r["result"]["isError"])
        # Empty query scores 0 against all topics; episodic-match.sh emits nothing.
        self.assertEqual(r["result"]["content"][0]["text"].strip(), "(no matches)")

    # --- contribute happy ----------------------------------------------
    def test_contribute_happy_writes_file_and_commits(self):
        # Throwaway git content dir so nothing real is touched / pushed.
        cd = tempfile.mkdtemp()
        subprocess.run(["git", "-C", cd, "init", "-q"], check=True)
        subprocess.run(["git", "-C", cd, "config", "user.email", "t@example.test"], check=True)
        subprocess.run(["git", "-C", cd, "config", "user.name", "test"], check=True)
        c = self._client({"NP_TOGGLES_LOCAL": _fix("contribute-on.local"),
                          "NP_CONTENT_DIR": cd})
        r = c.tool("nervepack_contribute",
                   {"kind": "source", "name": "np-kb-test", "topic": "misc", "body": "# x"})
        self.assertFalse(r["result"]["isError"])
        text = r["result"]["content"][0]["text"]
        self.assertIn("committed", text.lower())
        self.assertIn("sources/misc/np-kb-test.md", text)
        # File really landed, and the commit is real (sha resolves).
        self.assertTrue(os.path.exists(os.path.join(cd, "sources", "misc", "np-kb-test.md")))
        log = subprocess.run(["git", "-C", cd, "log", "--oneline"], capture_output=True, text=True)
        self.assertIn("np-kb-test", log.stdout)

    # --- suggestions implement happy -----------------------------------
    def test_suggestions_implement_started_when_contribute_on(self):
        # contribute=on unblocks the spawn; evaluator.implement=off makes the
        # detached job a no-op so no real agent / git push runs. We assert only
        # the envelope (job accepted / started), not any side effect.
        c = self._client({"NP_TOGGLES_LOCAL": _fix("contribute-on-implement-off.local")})
        r = c.tool("nervepack_suggestions", {"action": "implement", "text": "tighten the recall ranking"})
        self.assertFalse(r["result"]["isError"])
        self.assertIn("started", r["result"]["content"][0]["text"].lower())


if __name__ == "__main__":
    unittest.main()
