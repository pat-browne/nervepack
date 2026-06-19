import json, os, subprocess, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
NPLLM = os.path.join(REPO, "engine", "setup", "np-llm.sh")


class Handler(BaseHTTPRequestHandler):
    last_body = None
    status = 200
    content = "PONG"

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        Handler.last_body = json.loads(self.rfile.read(n) or b"{}")
        if Handler.status != 200:
            self.send_response(Handler.status); self.end_headers(); self.wfile.write(b"err"); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": Handler.content}}]}).encode())

    def log_message(self, *a):
        pass


class TestLocalBackend(unittest.TestCase):
    def setUp(self):
        Handler.last_body = None; Handler.status = 200; Handler.content = "PONG"
        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def _run(self, args, prompt="hi", extra=None):
        env = dict(os.environ)
        env.update({"NP_LLM_BACKEND": "local",
                    "NP_LLM_BASE_URL": f"http://127.0.0.1:{self.port}/v1",
                    "NP_LLM_MODEL_CHEAP": "m"})
        if extra:
            env.update(extra)
        return subprocess.run(["bash", NPLLM] + args, input=prompt,
                              capture_output=True, text=True, env=env)

    def test_complete_returns_content(self):
        r = self._run(["complete"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "PONG")
        self.assertEqual(Handler.last_body["model"], "m")
        self.assertEqual(Handler.last_body["messages"][-1], {"role": "user", "content": "hi"})

    def test_system_message_forwarded(self):
        self._run(["complete", "--system", "SYS"])
        self.assertEqual(Handler.last_body["messages"][0], {"role": "system", "content": "SYS"})

    def test_http_error_is_nonzero(self):
        Handler.status = 500
        r = self._run(["complete"])
        self.assertNotEqual(r.returncode, 0)

    def test_unreachable_is_nonzero(self):
        r = self._run(["complete"], extra={"NP_LLM_BASE_URL": "http://127.0.0.1:1/v1"})
        self.assertNotEqual(r.returncode, 0)

    def test_agent_passthrough_runs_cmd_with_prompt(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "agent_in")
        r = self._run(["agent", "--tools", "Bash Read"],
                      extra={"NP_LLM_AGENT_CMD": f"cat > {out}"})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as fh:
            self.assertEqual(fh.read(), "hi")

    def test_agent_passthrough_gets_tools_env(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "tools")
        r = self._run(["agent", "--tools", "Bash Read"],
                      extra={"NP_LLM_AGENT_CMD": f'printf "%s" "$NP_LLM_TOOLS" > {out}'})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as fh:
            self.assertEqual(fh.read(), "Bash Read")

    def test_agent_unset_errors_clearly(self):
        env = dict(os.environ)
        env.update({"NP_LLM_BACKEND": "local", "NP_LLM_BASE_URL": "x", "NP_LLM_MODEL_CHEAP": "m"})
        env.pop("NP_LLM_AGENT_CMD", None)
        r = subprocess.run(["bash", NPLLM, "agent", "--tools", "Bash"], input="t",
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("NP_LLM_AGENT_CMD", r.stderr)


if __name__ == "__main__":
    unittest.main()
