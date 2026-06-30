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

    def test_recall_is_bashfree(self):
        # Full recall path — keyword match (np_episodic_match) + topic-file read —
        # against an isolated content overlay, with bash unreachable.
        cd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cd, ignore_errors=True)
        os.makedirs(os.path.join(cd, "episodic"))
        with open(os.path.join(cd, "episodic", "INDEX.md"), "w", encoding="utf-8") as f:
            f.write("| topic | last_updated | keywords |\n|---|---|---|\n"
                    "| widgets | 2026-01-01 | sprocket, gizmo |\n")
        with open(os.path.join(cd, "episodic", "widgets.md"), "w", encoding="utf-8") as f:
            f.write("# widgets\nThe sprocket notes.\n")
        c = self.client({"NP_CONTENT_DIR": cd})
        c.initialize()
        r = c.tool("nervepack_recall", {"query": "sprocket gizmo", "kinds": ["episodic"], "top": 3})
        self.assertFalse(r["result"]["isError"], r["result"])
        self.assertIn("sprocket", r["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
