#!/usr/bin/env python3
# np-test: mcp-bashfree | failure
"""Prove the MCP server's PORTED surface works with NO bash reachable.

Slice 2+ of the git-for-windows-free MCP work (#38). The long-running server now
resolves toggles + content AND matches recall in-process (np_toggle / np_content /
np_episodic_match), so its protocol handshake, listing, resource reads, prompt
reads, toggle GATING, and nervepack_recall must all function with bash unavailable.
We make bash unreachable for the server child (NP_BASH -> a path that does not
exist) so any accidental ["bash", ...] shell-out fails loudly, and assert the
read/gate/recall surface still answers.

Tools that still shell out to bash (doctor / toggle-set / capture / evaluate /
flush / maintain / contribute / dashboard summary) are intentionally NOT exercised
here — porting them is a later slice.

Runs on every lane as a portable proof; the dedicated windows-no-bash CI lane runs
this same test with Git-bash stripped from PATH for the real-world proof.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_mcp_lifecycle import MCPClient  # noqa: E402  reuse the scripted-stdio client


class BashFreeReadSurface(unittest.TestCase):
    def setUp(self):
        # A bogus NP_BASH routes any ["bash", ...] through np_bashlib.argv to a
        # non-existent interpreter, so an accidental shell-out fails loudly rather
        # than silently working. NP_MCP_PURE_PYTHON=1 is the default but explicit.
        self.env = {
            "NP_BASH": os.path.join(tempfile.gettempdir(), "nervepack-no-such-bash-xyz"),
            "NP_MCP_PURE_PYTHON": "1",
        }
        self._clients = []

    def tearDown(self):
        for c in self._clients:
            c.close()

    def client(self, extra=None):
        c = MCPClient(extra_env={**self.env, **(extra or {})})
        self._clients.append(c)
        return c

    def test_initialize_and_gating(self):
        # The server only serves if np_enabled("mcp") passes — resolved in-process
        # by np_toggle. A successful handshake IS the bash-free gating proof.
        r = self.client().initialize()
        self.assertIn("result", r, r)
        self.assertEqual(r["result"]["serverInfo"]["name"], "nervepack")

    def test_tools_list(self):
        c = self.client()
        c.initialize()
        names = [t["name"] for t in c.call("tools/list")["result"]["tools"]]
        self.assertIn("nervepack_doctor", names)  # static listing, bash-free

    def test_resources_list_and_read(self):
        c = self.client()
        c.initialize()
        uris = [x["uri"] for x in c.call("resources/list")["result"]["resources"]]
        self.assertIn("nervepack://index", uris)  # list_resources() calls content_dir()
        # Reading the index resolves the content/engine roots and reads a file — the
        # proof that content resolution + a resource read need no bash.
        rd = c.call("resources/read", {"uri": "nervepack://index"})
        contents = rd["result"]["contents"]
        self.assertTrue(contents and contents[0]["text"].strip(), rd)

    def test_prompts(self):
        c = self.client()
        c.initialize()
        self.assertIn("nervepack-directive", [p["name"] for p in c.call("prompts/list")["result"]["prompts"]])
        g = c.call("prompts/get", {"name": "nervepack-directive"})
        self.assertIn("messages", g["result"], g)

    def test_dashboard_metrics_is_bashfree(self):
        # view=metrics is a pure file read (view=summary would shell out to bash);
        # it must not fail with a bash error even though bash is unreachable.
        c = self.client()
        c.initialize()
        r = c.tool("nervepack_dashboard", {"view": "metrics"})
        self.assertFalse(r["result"]["isError"], r["result"])

    def test_doctor_is_bashfree(self):
        # With bash unreachable, nervepack_doctor falls back to the Python core-check
        # doctor (np_doctor) instead of shelling np-doctor.sh. It must return a report
        # (not a tool error), with the deterministic core checks resolved in Python.
        c = self.client()
        c.initialize()
        r = c.tool("nervepack_doctor", {})
        self.assertFalse(r["result"]["isError"], r["result"])
        text = r["result"]["content"][0]["text"]
        self.assertIn("toggles", text)
        self.assertRegex(text, r"toggles\s+PASS")   # toggles check needs no bash/git
        self.assertIn("doctor:", text)

    def test_toggle_get_and_local_set_bashfree(self):
        # Status table (read) + a local-scoped feature write — both in-process via
        # np_toggle, with bash unreachable. (Shared writes still need bash and aren't
        # exercised here.)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        conf, local = os.path.join(d, "toggles.conf"), os.path.join(d, "toggles.local")
        with open(conf, "w", encoding="utf-8") as f:
            f.write("memory|shared|runtime|on|\nmylocal|local|runtime|on|\n")
        open(local, "w", encoding="utf-8").close()
        c = self.client({"NP_TOGGLES_CONF": conf, "NP_TOGGLES_LOCAL": local})
        c.initialize()
        g = c.tool("nervepack_toggle", {"action": "get"})
        self.assertFalse(g["result"]["isError"], g["result"])
        self.assertIn("FEATURE", g["result"]["content"][0]["text"])
        s = c.tool("nervepack_toggle", {"action": "set", "feature": "mylocal", "state": "off"})
        self.assertFalse(s["result"]["isError"], s["result"])
        with open(local, encoding="utf-8") as f:
            self.assertIn("mylocal=off", f.read())   # the write actually landed, bash-free

    def test_sync_dryrun_is_bashfree(self):
        # With bash unreachable, nervepack_sync falls back to np_sync (native git).
        # Dry-run so no real repo is touched; an isolated stamp avoids the real one.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        c = self.client({"NP_SYNC_DRYRUN": "1", "NP_SYNC_STAMP": os.path.join(d, "stamp")})
        c.initialize()
        r = c.tool("nervepack_sync", {})
        self.assertFalse(r["result"]["isError"], r["result"])
        self.assertIn("would sync now", r["result"]["content"][0]["text"])

    def test_capture_is_bashfree(self):
        # The capture pipeline (gate -> transcript extract -> model -> scrub -> inbox)
        # must run with no bash. Use the local backend with no endpoint so the model
        # call fails: the pipeline still runs bash-free through extract + the model
        # seam and fail-opens with a logged bail — a real side effect (non-tautological).
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        tpath = os.path.join(d, "transcript.jsonl")
        with open(tpath, "w", encoding="utf-8") as f:
            f.write('{"type":"user","message":{"role":"user","content":"hi"}}\n')
        log = os.path.join(d, "capture.log")
        c = self.client({
            "NP_LLM_BACKEND": "local",          # skips the claude-binary check; reaches the model seam
            "EPISODIC_CAPTURE_LOG": log,
            "EPISODIC_INBOX": os.path.join(d, "inbox"),
            "EPISODIC_SEEN_DIR": os.path.join(d, "seen"),
        })
        c.initialize()
        r = c.tool("nervepack_capture", {"transcript_path": tpath, "cwd": "/p", "session_id": "s1"})
        self.assertFalse(r["result"]["isError"], r["result"])
        with open(log, encoding="utf-8") as f:
            self.assertIn("summarizer invocation failed", f.read())  # ran bash-free, bailed at the model

    def test_evaluate_is_bashfree(self):
        # The evaluator pipeline (gate -> signals -> transcript extract -> model ->
        # scrub -> inbox) must run with no bash. Local backend, no endpoint -> the
        # model call fails after the pipeline ran bash-free; fail-opens with a logged
        # bail (a real side effect — non-tautological).
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        tpath = os.path.join(d, "transcript.jsonl")
        with open(tpath, "w", encoding="utf-8") as f:
            f.write('{"type":"user","message":{"role":"user","content":"hi"}}\n')
        log = os.path.join(d, "eval.log")
        c = self.client({
            "NP_LLM_BACKEND": "local",
            "EVAL_JUDGE_LOG": log,
            "EVAL_INBOX": os.path.join(d, "inbox"),
        })
        c.initialize()
        r = c.tool("nervepack_evaluate", {"transcript_path": tpath, "cwd": "/p", "session_id": "s1"})
        self.assertFalse(r["result"]["isError"], r["result"])
        with open(log, encoding="utf-8") as f:
            self.assertIn("judge invocation failed", f.read())

    def test_flush_maintain_refuse_cleanly_bashfree(self):
        # flush/maintain drive agent-mode crons (out of scope) — on a bash-free host
        # they must refuse cleanly, not emit a raw subprocess error. job="promote"
        # (not "aggregate") -- aggregate is now np_aggregate.py, called in-process,
        # so it no longer needs bash and must NOT be refused on a bash-free host;
        # "promote" still shells to the (still-bash) 71-run-memory-promote.sh, so
        # it's the representative job left in this refuse-cleanly gate.
        c = self.client()
        c.initialize()
        for tool, arg in (("nervepack_flush", {}), ("nervepack_maintain", {"job": "promote"})):
            r = c.tool(tool, arg)
            self.assertTrue(r["result"]["isError"], (tool, r["result"]))
            self.assertIn("needs bash", r["result"]["content"][0]["text"], (tool, r["result"]))

    def test_maintain_aggregate_is_bashfree(self):
        # np_aggregate.py (73-aggregate-metrics.sh's replacement) is called
        # in-process by _tool_maintain's "aggregate" job -- unlike the other
        # maintain jobs (see test_flush_maintain_refuse_cleanly_bashfree above),
        # it must succeed with bash unreachable, and really drain a planted
        # EVAL_INBOX record into METRICS_FILE (a real side effect, not a
        # tautological "no error" check).
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        inbox = os.path.join(d, "inbox")
        os.makedirs(inbox)
        with open(os.path.join(inbox, "rec.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"session_id": "s1", "contribution_score": 50}) + "\n")
        metrics = os.path.join(d, "metrics.jsonl")
        c = self.client({
            "EVAL_INBOX": inbox,
            "METRICS_FILE": metrics,
            "NP_CONTENT_DIR": d,
            "NP_AGG_NO_COMMIT": "1",
        })
        c.initialize()
        r = c.tool("nervepack_maintain", {"job": "aggregate"})
        self.assertFalse(r["result"]["isError"], r["result"])
        with open(metrics, encoding="utf-8") as f:
            self.assertIn('"session_id": "s1"', f.read())

    def test_recall_is_bashfree(self):
        # Full recall path — keyword match (np_episodic_match) + topic-file read —
        # against an isolated content overlay, with bash unreachable.
        cd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cd, ignore_errors=True)
        os.makedirs(os.path.join(cd, "memory", "episodic"))
        with open(os.path.join(cd, "memory", "episodic", "INDEX.md"), "w", encoding="utf-8") as f:
            f.write("| topic | last_updated | keywords |\n|---|---|---|\n"
                    "| widgets | 2026-01-01 | sprocket, gizmo |\n")
        with open(os.path.join(cd, "memory", "episodic", "widgets.md"), "w", encoding="utf-8") as f:
            f.write("# widgets\nThe sprocket notes.\n")
        c = self.client({"NP_CONTENT_DIR": cd})
        c.initialize()
        r = c.tool("nervepack_recall", {"query": "sprocket gizmo", "kinds": ["episodic"], "top": 3})
        self.assertFalse(r["result"]["isError"], r["result"])
        self.assertIn("sprocket", r["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
