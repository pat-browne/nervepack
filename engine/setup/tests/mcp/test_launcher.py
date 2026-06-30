#!/usr/bin/env python3
# np-test: nervepack-mcp launcher | happy
"""Cover engine/bin/nervepack-mcp — the stable spawn command for the MCP server.

Happy: launching the launcher (not the server directly) starts the stdio server,
which answers a real `ping` with the `{}` result envelope and an `initialize` with
serverInfo.name == "nervepack".
Failure: with the mcp toggle OFF, main() logs "mcp feature disabled; exiting" and
returns 0 immediately — the process exits 0 and emits NO JSON-RPC response even
though we sent a well-formed request (proves the gate, not a crash/hang).
"""
import json, os, subprocess, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from nptest import sh  # bash-invoke the launcher cross-platform (it's a bash script)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
LAUNCHER = os.path.join(REPO, "engine", "bin", "nervepack-mcp")
FIXTURES = os.path.join(REPO, "engine", "setup", "tests", "mcp", "fixtures")


def _run_launcher(stdin_text, extra_env=None, timeout=15):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    # The launcher is a bash script; exec'ing it directly raises WinError 193 on
    # Windows, so run it through bash (nptest.sh). On Linux this is equivalent.
    return sh(LAUNCHER, input=stdin_text, capture_output=True,
              text=True, env=env, timeout=timeout)


def _responses(stdout):
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


class TestLauncher(unittest.TestCase):
    def test_launcher_starts_server_and_answers_ping(self):
        msgs = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "0"}}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n"
        )
        p = _run_launcher(msgs)
        self.assertEqual(p.returncode, 0, f"launcher exit={p.returncode}; stderr={p.stderr}")
        resps = {r.get("id"): r for r in _responses(p.stdout)}
        self.assertIn(1, resps, f"no initialize response; stdout={p.stdout!r} stderr={p.stderr!r}")
        self.assertEqual(resps[1]["result"]["serverInfo"]["name"], "nervepack")
        self.assertIn(2, resps, "no ping response — launcher did not start the server")
        self.assertEqual(resps[2]["result"], {})

    def test_launcher_exits_clean_when_mcp_toggle_off(self):
        # mcp=off -> main() returns 0 before the stdin loop; well-formed ping gets
        # NO response, and the process exits 0 (clean gate, not a crash).
        ping = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        p = _run_launcher(ping, extra_env={"NP_TOGGLES_LOCAL": os.path.join(FIXTURES, "mcp-off.local")})
        self.assertEqual(p.returncode, 0, f"launcher exit={p.returncode}; stderr={p.stderr}")
        resps = _responses(p.stdout)
        self.assertEqual(resps, [], f"expected no JSON-RPC output when mcp off, got {resps!r}")
        self.assertIn("disabled", p.stderr.lower())


if __name__ == "__main__":
    unittest.main()
