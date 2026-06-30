#!/usr/bin/env python3
# np-test: mcp-bashfree | failure
"""Prove the MCP server's PORTED surface works with NO bash reachable.

Slice 2 of the git-for-windows-free MCP work (#38). The long-running server now
resolves toggles + content in-process (np_toggle / np_content), so its protocol
handshake, listing, resource reads, prompt reads, and toggle GATING must all
function with bash unavailable. We make bash unreachable for the server child
(NP_BASH -> a path that does not exist), so any accidental ["bash", ...] shell-out
raises instead of silently working, and assert the read/gate surface still answers.

Tools that still shell out to bash (doctor / recall / capture / evaluate / flush /
toggle-set / maintain / contribute / dashboard summary) are intentionally NOT
exercised here — porting them is a later slice. The one tool checked is
nervepack_dashboard view=metrics, which is a pure file read.

Runs on every lane as a portable proof; the dedicated windows-no-bash CI lane runs
this same test with Git-bash stripped from PATH for the real-world proof.
"""
import os
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
        self.c = MCPClient(extra_env=self.env)

    def tearDown(self):
        self.c.close()

    def test_initialize_and_gating(self):
        # The server only serves if np_enabled("mcp") passes — resolved in-process
        # by np_toggle. A successful handshake IS the bash-free gating proof.
        r = self.c.initialize()
        self.assertIn("result", r, r)
        self.assertEqual(r["result"]["serverInfo"]["name"], "nervepack")

    def test_tools_list(self):
        self.c.initialize()
        r = self.c.call("tools/list")
        names = [t["name"] for t in r["result"]["tools"]]
        self.assertIn("nervepack_doctor", names)  # static listing, bash-free

    def test_resources_list_and_read(self):
        self.c.initialize()
        lst = self.c.call("resources/list")
        uris = [x["uri"] for x in lst["result"]["resources"]]
        self.assertIn("nervepack://index", uris)  # list_resources() calls content_dir()
        # Reading the index resolves the content/engine roots and reads a file — the
        # proof that content resolution + a resource read need no bash.
        rd = self.c.call("resources/read", {"uri": "nervepack://index"})
        contents = rd["result"]["contents"]
        self.assertTrue(contents and contents[0]["text"].strip(), rd)

    def test_prompts(self):
        self.c.initialize()
        lst = self.c.call("prompts/list")
        self.assertIn("nervepack-directive", [p["name"] for p in lst["result"]["prompts"]])
        g = self.c.call("prompts/get", {"name": "nervepack-directive"})
        self.assertIn("messages", g["result"], g)

    def test_dashboard_metrics_is_bashfree(self):
        # view=metrics is a pure file read (view=summary would shell out to bash);
        # it must not fail with a bash error even though bash is unreachable.
        self.c.initialize()
        r = self.c.tool("nervepack_dashboard", {"view": "metrics"})
        self.assertFalse(r["result"]["isError"], r["result"])


if __name__ == "__main__":
    unittest.main()
