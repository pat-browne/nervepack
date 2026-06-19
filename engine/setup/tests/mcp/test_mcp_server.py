import json, os, subprocess, sys, threading, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SERVER = os.path.join(REPO, "engine", "setup", "np-mcp-server.py")


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
    """Minimal scripted MCP client over the server's stdio pipe."""
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


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.c = MCPClient()
        self.addCleanup(self.c.close)

    def test_initialize_reports_capabilities(self):
        r = self.c.initialize()
        res = r["result"]
        self.assertEqual(res["serverInfo"]["name"], "nervepack")
        for cap in ("tools", "resources", "prompts"):
            self.assertIn(cap, res["capabilities"])

    def test_ping(self):
        self.c.initialize()
        r = self.c.call("ping")
        self.assertEqual(r["result"], {})

    def test_unknown_method_is_method_not_found(self):
        self.c.initialize()
        r = self.c.call("does/not/exist")
        self.assertEqual(r["error"]["code"], -32601)

    def test_tools_list_includes_doctor(self):
        self.c.initialize()
        names = [t["name"] for t in self.c.call("tools/list")["result"]["tools"]]
        self.assertIn("nervepack_doctor", names)

    def test_doctor_call_returns_text_content(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_doctor", "arguments": {}})
        content = r["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(len(content[0]["text"]) > 0)

    def test_resources_list_includes_index(self):
        self.c.initialize()
        uris = [r["uri"] for r in self.c.call("resources/list")["result"]["resources"]]
        self.assertIn("nervepack://index", uris)

    def test_resources_read_index_returns_text(self):
        self.c.initialize()
        r = self.c.call("resources/read", {"uri": "nervepack://index"})
        c = r["result"]["contents"][0]
        self.assertEqual(c["uri"], "nervepack://index")
        self.assertIn("skill", c["text"].lower())

    def test_resources_read_rejects_traversal(self):
        self.c.initialize()
        r = self.c.call("resources/read", {"uri": "nervepack://skills/../../etc/passwd"})
        self.assertIn("error", r)
        msg = r["error"]["message"].lower()
        self.assertTrue("reject" in msg or "escape" in msg, f"weak/incorrect error: {msg}")

    def test_resources_read_rejects_absolute_uri(self):
        # No '..' so the first guard doesn't fire; _safe_path's realpath backstop must catch it.
        self.c.initialize()
        r = self.c.call("resources/read", {"uri": "nervepack:////etc/passwd"})
        self.assertIn("error", r)
        self.assertIn("escape", r["error"]["message"].lower())

    def test_prompts_list_includes_directive(self):
        self.c.initialize()
        names = [p["name"] for p in self.c.call("prompts/list")["result"]["prompts"]]
        self.assertIn("nervepack-directive", names)

    def test_prompts_get_directive_returns_messages(self):
        self.c.initialize()
        r = self.c.call("prompts/get", {"name": "nervepack-directive"})
        msgs = r["result"]["messages"]
        self.assertEqual(msgs[0]["role"], "user")
        self.assertIn("nervepack", msgs[0]["content"]["text"].lower())

    def test_writes_gate_blocks_when_off(self):
        # mcp.writes=off must make a write tool refuse; reads still work.
        c = MCPClient(extra_env={"NP_TOGGLES_LOCAL": os.path.join(REPO, "engine/setup/tests/mcp/fixtures/writes-off.local")})
        self.addCleanup(c.close)
        c.initialize()
        r = c.call("tools/call", {"name": "nervepack_toggle",
                                  "arguments": {"action": "set", "feature": "memory", "state": "on"}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    def test_toggle_get_status(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_toggle", "arguments": {"action": "get"}})
        self.assertFalse(r["result"]["isError"])
        self.assertIn("mcp", r["result"]["content"][0]["text"])

    def test_recall_runs_without_error(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_recall",
                                       "arguments": {"query": "mcp server design"}})
        self.assertFalse(r["result"]["isError"])  # may be "(no matches)" — that's fine

    def test_dashboard_summary(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_dashboard",
                                       "arguments": {"view": "summary"}})
        self.assertFalse(r["result"]["isError"])
        self.assertIn("sessions", r["result"]["content"][0]["text"].lower())


    def test_lifecycle_write_tools_listed(self):
        self.c.initialize()
        names = [t["name"] for t in self.c.call("tools/list")["result"]["tools"]]
        for n in ("nervepack_capture", "nervepack_evaluate", "nervepack_flush", "nervepack_sync"):
            self.assertIn(n, names)

    def test_sync_blocked_when_writes_off(self):
        c = MCPClient(extra_env={"NP_TOGGLES_LOCAL": os.path.join(REPO, "engine/setup/tests/mcp/fixtures/writes-off.local")})
        self.addCleanup(c.close)
        c.initialize()
        r = c.call("tools/call", {"name": "nervepack_sync", "arguments": {}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    def test_suggestions_list(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_suggestions",
                                       "arguments": {"action": "list", "top": 5}})
        self.assertFalse(r["result"]["isError"])

    def test_suggestions_implement_blocked_by_default(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_suggestions",
                                       "arguments": {"action": "implement", "text": "x"}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("contribute is disabled", r["result"]["content"][0]["text"].lower())

    def test_contribute_blocked_by_default(self):
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_contribute",
                                       "arguments": {"kind": "source", "name": "x", "topic": "misc", "body": "hi"}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("contribute is disabled", r["result"]["content"][0]["text"].lower())

    def test_maintain_and_contribute_listed(self):
        self.c.initialize()
        names = [t["name"] for t in self.c.call("tools/list")["result"]["tools"]]
        self.assertIn("nervepack_maintain", names)
        self.assertIn("nervepack_contribute", names)

    def test_dashboard_summary_no_metrics_returns_zero_sessions(self):
        # np-test: mcp-dashboard | failure
        # Failure path: point NP_CONTENT_DIR at an EMPTY overlay so the content
        # metrics.jsonl does not exist. _tool_dashboard's summary reuses build.
        # load_records(), which swallows FileNotFoundError and returns []. The
        # tool must return a normal (non-error) JSON result with sessions=0 — NOT
        # an isError / crash. Guards a regression that lets a fresh box (no
        # metrics yet) error out of the dashboard tool.
        import tempfile, os as _os, json as _json
        with tempfile.TemporaryDirectory() as overlay:
            self.assertFalse(_os.path.exists(_os.path.join(overlay, "dashboard", "data", "metrics.jsonl")))
            c = MCPClient(extra_env={"NP_CONTENT_DIR": overlay})
            self.addCleanup(c.close)
            c.initialize()
            r = c.call("tools/call", {"name": "nervepack_dashboard",
                                      "arguments": {"view": "summary"}})
            self.assertFalse(r["result"]["isError"], r["result"])
            payload = _json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(payload["sessions"], 0)

    def test_dashboard_metrics_view_no_file_returns_empty_array(self):
        # np-test: mcp-dashboard | failure
        # Companion: view=metrics on an overlay with no metrics.jsonl returns the
        # literal "[]" (the documented missing-file fallback), not isError.
        import tempfile
        with tempfile.TemporaryDirectory() as overlay:
            c = MCPClient(extra_env={"NP_CONTENT_DIR": overlay})
            self.addCleanup(c.close)
            c.initialize()
            r = c.call("tools/call", {"name": "nervepack_dashboard",
                                      "arguments": {"view": "metrics"}})
            self.assertFalse(r["result"]["isError"], r["result"])
            self.assertEqual(r["result"]["content"][0]["text"].strip(), "[]")

    def test_suggestions_unknown_action_is_error_result(self):
        # np-test: mcp-suggestions | failure
        # Failure path: an action the handler doesn't recognise. _tool_suggestions
        # falls through to `raise ValueError("unknown suggestions action: ...")`,
        # which handle_tool_call turns into a result with isError=True (a tool
        # error, NOT a protocol error / dropped connection). Assert isError + the
        # specific message naming the bad action, then prove the server is still
        # alive by issuing a follow-up ping.
        self.c.initialize()
        r = self.c.call("tools/call", {"name": "nervepack_suggestions",
                                       "arguments": {"action": "frobnicate"}})
        self.assertTrue(r["result"]["isError"], r["result"])
        txt = r["result"]["content"][0]["text"].lower()
        self.assertIn("unknown suggestions action", txt)
        self.assertIn("frobnicate", txt)
        # server survives the tool error:
        self.assertEqual(self.c.call("ping")["result"], {})

    def test_resources_list_empty_overlay_no_crash_no_overlay_uris(self):
        # np-test: mcp-resources-list | failure
        # Failure path: NP_CONTENT_DIR points at an EMPTY dir (no skills/sources/
        # wiki/... subtrees). resources/list must NOT raise — it returns a clean
        # list containing the static singletons (and the engine's own skills,
        # which live under REPO regardless of the overlay) but NO overlay-sourced
        # content URIs. Guards a regression where globbing an absent overlay subdir
        # throws instead of yielding nothing.
        import tempfile
        with tempfile.TemporaryDirectory() as overlay:
            c = MCPClient(extra_env={"NP_CONTENT_DIR": overlay})
            self.addCleanup(c.close)
            c.initialize()
            r = c.call("resources/list")
            self.assertNotIn("error", r, r)
            uris = [x["uri"] for x in r["result"]["resources"]]
            # Static singletons always present (no overlay needed):
            self.assertIn("nervepack://index", uris)
            # Engine skills still surface (they live under REPO, not the overlay):
            self.assertTrue(any(u.startswith("nervepack://skills/") for u in uris),
                            f"engine skills missing from list: {uris}")
            # But the empty overlay contributed no sources/wiki/playbooks/etc URIs.
            overlay_only = [u for u in uris
                            if u.startswith(("nervepack://sources/", "nervepack://wiki/",
                                             "nervepack://playbooks/", "nervepack://strategies/",
                                             "nervepack://episodic/"))]
            self.assertEqual(overlay_only, [], f"empty overlay leaked content URIs: {overlay_only}")

    def test_resources_reflect_content_overlay(self):
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as overlay:
            sk = _os.path.join(overlay, "skills", "np-kb-demo"); _os.makedirs(sk)
            with open(_os.path.join(sk, "SKILL.md"), "w") as fh:
                fh.write("---\nname: np-kb-demo\ndescription: d\n---\n# demo\n")
            c = MCPClient(extra_env={"NP_CONTENT_DIR": overlay})
            self.addCleanup(c.close)
            c.initialize()
            uris = [r["uri"] for r in c.call("resources/list")["result"]["resources"]]
            self.assertIn("nervepack://skills/np-kb-demo", uris)


if __name__ == "__main__":
    unittest.main()
