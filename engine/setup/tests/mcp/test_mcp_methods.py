#!/usr/bin/env python3
# np-test: mcp toggle-set / maintain / doctor / prompts | happy
"""Tier-2 MCP method gaps with strong side-effect assertions.

Covered:
  - nervepack_toggle set (happy): writes=on + set memory=off -> the temp
    toggles.conf state column for `memory` really flips to off.
  - nervepack_maintain (happy): writes=on + job=aggregate -> 73-aggregate-metrics.sh
    really drains a planted EVAL_INBOX record into a temp METRICS file.
  - nervepack_maintain (failure): writes=off -> isError "disabled";
    unknown job value -> isError (KeyError surfaced as a tool error result).
  - nervepack_doctor (failure): a broken adapter.json makes the doctor surface a
    MISSING MUST capability in its result text (clean text result, not a crash).
  - prompts/get unknown name -> -32602 protocol error.
  - prompts/list with directive.md absent -> still returns the directive entry
    gracefully (the list is static; no file read, no crash).
"""
import json, os, shutil, subprocess, sys, tempfile, threading, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SERVER = os.path.join(REPO, "engine", "setup", "np-mcp-server.py")
SETUP = os.path.join(REPO, "engine", "setup")
FIXTURES = os.path.join(SETUP, "tests", "mcp", "fixtures")


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
        r = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "0"}})
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


def _conf_state(conf_path, feature):
    """Read the state column (4th, pipe-delimited) for a feature from a toggles.conf."""
    with open(conf_path) as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            cols = line.split("|")
            if len(cols) >= 4 and cols[0].strip() == feature:
                return cols[3].strip()
    return None


class TestMethods(unittest.TestCase):
    def setUp(self):
        self._tmp = []

    def tearDown(self):
        for d in self._tmp:
            shutil.rmtree(d, ignore_errors=True)

    def _mktmp(self):
        d = tempfile.mkdtemp()
        self._tmp.append(d)
        return d

    def _client(self, extra_env=None):
        c = MCPClient(extra_env=extra_env)
        self.addCleanup(c.close)
        c.initialize()
        return c

    # --- toggle set happy -----------------------------------------------
    def test_toggle_set_flips_conf_state(self):
        tmp = self._mktmp()
        conf = os.path.join(tmp, "toggles.conf")
        shutil.copy(os.path.join(SETUP, "toggles.conf"), conf)
        self.assertEqual(_conf_state(conf, "memory"), "on", "fixture precondition: memory starts on")
        local = os.path.join(tmp, "writes-on.local")
        with open(local, "w") as fh:
            fh.write("mcp.writes=on\n")
        env = {
            "NP_TOGGLES_CONF": conf,            # the toggle CLI mutates THIS copy
            "NP_TOGGLES_LOCAL": local,          # mcp.writes=on (gate open)
            "NP_TOGGLE_NO_COMMIT": "1",         # no git commit/push
            "NP_TOGGLE_NO_MANAGED": "1",        # no install/remove-permissions side effects
        }
        c = self._client(env)
        r = c.tool("nervepack_toggle", {"action": "set", "feature": "memory", "state": "off"})
        self.assertFalse(r["result"]["isError"], r["result"])
        # Real side effect: memory's state column flipped to off in the temp conf.
        self.assertEqual(_conf_state(conf, "memory"), "off",
                         "memory state was not flipped to off in toggles.conf")

    # --- maintain happy -------------------------------------------------
    def test_maintain_aggregate_drains_inbox(self):
        tmp = self._mktmp()
        local = os.path.join(tmp, "writes-on.local")
        with open(local, "w") as fh:
            fh.write("mcp.writes=on\n")
        eval_inbox = os.path.join(tmp, "evaluator-inbox")
        os.makedirs(eval_inbox)
        rec = os.path.join(eval_inbox, "rec.jsonl")
        with open(rec, "w") as fh:
            fh.write(json.dumps({"session_id": "s1", "contribution_score": 50}) + "\n")
        metrics = os.path.join(tmp, "metrics.jsonl")
        content = os.path.join(tmp, "content")   # isolate dashboard rebuild target
        os.makedirs(content)
        env = {
            "NP_TOGGLES_LOCAL": local,
            "EVAL_INBOX": eval_inbox,
            "METRICS_FILE": metrics,
            "NP_CONTENT_DIR": content,
            "NP_AGG_NO_COMMIT": "1",            # no git
        }
        c = self._client(env)
        r = c.tool("nervepack_maintain", {"job": "aggregate"})
        self.assertFalse(r["result"]["isError"], r["result"])
        # Real side effects: record appended to METRICS, inbox file removed.
        self.assertTrue(os.path.exists(metrics), "73-aggregate did not create metrics file")
        with open(metrics) as fh:
            body = fh.read()
        self.assertIn('"session_id": "s1"', body, f"record not appended to metrics: {body!r}")
        self.assertFalse(os.path.exists(rec), "inbox record was not drained")

    # --- maintain failures ----------------------------------------------
    def test_maintain_blocked_when_writes_off(self):
        c = self._client({"NP_TOGGLES_LOCAL": os.path.join(FIXTURES, "writes-off.local")})
        r = c.tool("nervepack_maintain", {"job": "aggregate"})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("disabled", r["result"]["content"][0]["text"].lower())

    def test_maintain_unknown_job_is_error(self):
        local = os.path.join(self._mktmp(), "writes-on.local")
        with open(local, "w") as fh:
            fh.write("mcp.writes=on\n")
        c = self._client({"NP_TOGGLES_LOCAL": local})
        r = c.tool("nervepack_maintain", {"job": "not-a-job"})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("error", r["result"]["content"][0]["text"].lower())

    # --- doctor failure -------------------------------------------------
    def test_doctor_surfaces_missing_must_capability(self):
        tmp = self._mktmp()
        # A bad adapter: omit the `knowledge` MUST capability -> doctor reports MISSING
        # and exits non-zero; _tool_doctor surfaces that in the result text (clean,
        # not a protocol crash).
        adapter = os.path.join(tmp, "bad-adapter.json")
        with open(adapter, "w") as fh:
            json.dump({"host": "test",
                       "capabilities": {"session-start": {"status": "wired", "verify": "true"}}}, fh)
        c = self._client({"NP_ADAPTER": adapter})
        r = c.tool("nervepack_doctor", {})
        text = r["result"]["content"][0]["text"]
        # Result is a clean text envelope (no protocol error) that names the failure.
        self.assertFalse(r["result"]["isError"])
        self.assertIn("missing", text.lower(),
                      f"doctor failure not surfaced in result text: {text!r}")
        self.assertIn("knowledge", text.lower())

    # --- prompts/get unknown -------------------------------------------
    def test_prompts_get_unknown_name_is_invalid_params(self):
        c = self._client()
        r = c.call("prompts/get", {"name": "does-not-exist"})
        self.assertIn("error", r)
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("does-not-exist", r["error"]["message"])

    # --- prompts/get missing directive.md → clean protocol error ------
    def test_prompts_get_missing_directive_md_is_clean_error(self):
        # prompts/get calls _directive_text() which does open(); if the md is absent
        # handle_prompt_get catches OSError and must return a JSON-RPC error
        # (code -32603) — not an unhandled crash / dropped connection.
        # Verify: (a) the response is a JSON-RPC error with code -32603,
        #         (b) the server is still alive (answers a subsequent ping).
        tmp = self._mktmp()
        stage = os.path.join(tmp, "setup")
        shutil.copytree(SETUP, stage, ignore=shutil.ignore_patterns("tests"))
        os.remove(os.path.join(stage, "nervepack-session-directive.md"))
        staged_repo = self._mktmp()
        os.makedirs(os.path.join(staged_repo, "engine"))
        shutil.move(stage, os.path.join(staged_repo, "engine", "setup"))
        shutil.copytree(os.path.join(REPO, "engine", "bin"), os.path.join(staged_repo, "engine", "bin"))
        shutil.copytree(os.path.join(REPO, "dashboard"), os.path.join(staged_repo, "dashboard"))
        shutil.copy(os.path.join(REPO, "INDEX.md"), os.path.join(staged_repo, "INDEX.md"))
        staged_server = os.path.join(staged_repo, "engine", "setup", "np-mcp-server.py")
        p = subprocess.Popen([sys.executable, staged_server], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                             env=dict(os.environ))
        try:
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},  # notification
                {"jsonrpc": "2.0", "id": 2, "method": "prompts/get",
                 "params": {"name": "nervepack-directive"}},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            ]
            for m in msgs:
                p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()
            resps = {}
            want = {1, 2, 3}
            while want - set(resps):
                try:
                    line = _readline_timed(p, timeout=15)
                except TimeoutError as e:
                    self.fail(str(e))
                if not line:
                    self.fail(
                        "server closed before all responses; got={}, stderr:\n{}".format(
                            resps, p.stderr.read()))
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in msg:
                    resps[msg["id"]] = msg
            # (a) prompts/get must return a JSON-RPC error, not a result
            r = resps[2]
            self.assertIn("error", r,
                          f"expected JSON-RPC error for missing directive md, got: {r}")
            self.assertNotIn("result", r)
            self.assertEqual(r["error"]["code"], -32603,
                             f"expected -32603 (internal error), got: {r['error']}")
            self.assertIn("directive", r["error"]["message"].lower(),
                          f"error message should mention 'directive': {r['error']}")
            # (b) server still alive: ping returned a result, not a closed pipe
            ping = resps[3]
            self.assertIn("result", ping, f"server did not respond to ping after error: {ping}")
        finally:
            for s in (p.stdin, p.stdout, p.stderr):
                try:
                    s.close()
                except Exception:
                    pass
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    # --- prompts/list missing directive.md -----------------------------
    def test_prompts_list_graceful_when_directive_md_missing(self):
        # Run the server from a copied SETUP that LACKS nervepack-session-directive.md.
        # prompts/list is static (no file read) so it must still return the directive
        # entry without crashing — graceful, not isError.
        tmp = self._mktmp()
        stage = os.path.join(tmp, "setup")
        shutil.copytree(SETUP, stage, ignore=shutil.ignore_patterns("tests"))
        os.remove(os.path.join(stage, "nervepack-session-directive.md"))
        # Recreate the engine/bin sibling tree so REPO resolution & np-mcp-server imports hold.
        staged_repo = self._mktmp()
        os.makedirs(os.path.join(staged_repo, "engine"))
        shutil.move(stage, os.path.join(staged_repo, "engine", "setup"))
        shutil.copytree(os.path.join(REPO, "engine", "bin"), os.path.join(staged_repo, "engine", "bin"))
        shutil.copytree(os.path.join(REPO, "dashboard"), os.path.join(staged_repo, "dashboard"))
        shutil.copy(os.path.join(REPO, "INDEX.md"), os.path.join(staged_repo, "INDEX.md"))
        staged_server = os.path.join(staged_repo, "engine", "setup", "np-mcp-server.py")
        p = subprocess.Popen([sys.executable, staged_server], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                             env=dict(os.environ))
        try:
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                 "clientInfo": {"name": "t", "version": "0"}}}) + "\n")
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"}) + "\n")
            p.stdin.flush()
            resps = {}
            while 2 not in resps:
                try:
                    line = _readline_timed(p, timeout=15)
                except TimeoutError as e:
                    self.fail(str(e))
                if not line:
                    self.fail("server closed before prompts/list; stderr:\n" + p.stderr.read())
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in m:
                    resps[m["id"]] = m
            r = resps[2]
            self.assertNotIn("error", r, f"prompts/list errored with md missing: {r}")
            names = [pr["name"] for pr in r["result"]["prompts"]]
            self.assertIn("nervepack-directive", names)
        finally:
            for s in (p.stdin, p.stdout, p.stderr):
                try:
                    s.close()
                except Exception:
                    pass
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    unittest.main()
