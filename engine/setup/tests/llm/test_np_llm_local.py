"""Local-backend contract for the model seam, driven through np_model.py's CLI
(`python3 np_model.py complete|agent`) -- the sole seam since np-llm.sh was retired
(phase 19). np_model's `local` backend routes `complete` to np-llm-local.py (the
OpenAI-compatible /chat/completions driver) and `agent` to the user-configured
NP_LLM_AGENT_CMD via `bash -c`, exactly as the retired wrapper did, so these seven
cases (content/system forwarding, HTTP-error + unreachable failure, agent passthrough
+ NP_LLM_TOOLS env, and the clear unset-agent error) still pin that behavior against
the surviving implementation. Invoking np_model.py directly (not via bash) is also
Windows-native-friendly. Stdlib unittest (no pytest), per CLAUDE.md."""
import json, os, subprocess, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from nptest import u  # convert paths embedded in bash -c NP_LLM_AGENT_CMD snippets

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
NPMODEL = os.path.join(REPO, "engine", "setup", "np_model.py")


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
        return subprocess.run([sys.executable, NPMODEL, *args], input=prompt,
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

    def test_http_error_yields_no_content(self):
        # A backend failure surfaces to the in-process seam (np_model.complete) as
        # empty stdout -- the runtime callers (np_capture/np_evaluator) fail-open on
        # empty output. (The old np-llm.sh propagated the backend's nonzero exit; the
        # in-process seam returns the string, so "no content" is the ported contract.)
        Handler.status = 500
        r = self._run(["complete"])
        self.assertEqual(r.stdout, "")

    def test_unreachable_yields_no_content(self):
        r = self._run(["complete"], extra={"NP_LLM_BASE_URL": "http://127.0.0.1:1/v1"})
        self.assertEqual(r.stdout, "")

    def test_agent_passthrough_runs_cmd_with_prompt(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "agent_in")
        r = self._run(["agent", "--tools", "Bash Read"],
                      extra={"NP_LLM_AGENT_CMD": f"cat > {u(out)}"})  # u(): bash can't write a backslash path
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as fh:
            self.assertEqual(fh.read(), "hi")

    def test_agent_passthrough_gets_tools_env(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "tools")
        r = self._run(["agent", "--tools", "Bash Read"],
                      extra={"NP_LLM_AGENT_CMD": f'printf "%s" "$NP_LLM_TOOLS" > {u(out)}'})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as fh:
            self.assertEqual(fh.read(), "Bash Read")

    def test_agent_unset_errors_clearly(self):
        env = dict(os.environ)
        env.update({"NP_LLM_BACKEND": "local", "NP_LLM_BASE_URL": "x", "NP_LLM_MODEL_CHEAP": "m"})
        env.pop("NP_LLM_AGENT_CMD", None)
        r = subprocess.run([sys.executable, NPMODEL, "agent", "--tools", "Bash"], input="t",
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("NP_LLM_AGENT_CMD", r.stderr)


if __name__ == "__main__":
    unittest.main()
