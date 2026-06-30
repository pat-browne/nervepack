#!/usr/bin/env python3
"""Regression: the SessionEnd hooks must run on the `local` backend with NO `claude`
binary present. episodic-capture.sh / np-evaluator.sh historically gated on
`[[ -x "$CLAUDE" ]]` — a leftover from before the np-llm.sh seam — which made both
bail silently on a pure non-Claude host even though the local backend works. This
drives each hook with NP_LLM_BACKEND=local, CLAUDE_BIN pointed at a nonexistent path,
and a stub OpenAI-compatible server, asserting a note/record is still written.
Stdlib unittest (no pytest), per CLAUDE.md. Run: `python3 -m unittest`."""
import json, os, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from nptest import sh  # bash-invoke the .sh hooks via the right (non-WSL) bash on Windows

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SETUP = os.path.join(REPO, "engine", "setup")
CAPTURE = os.path.join(SETUP, "episodic-capture.sh")
EVAL = os.path.join(SETUP, "np-evaluator.sh")
NO_CLAUDE = "/nonexistent/np-no-claude-binary"


class Handler(BaseHTTPRequestHandler):
    content = "{}"  # the model's reply body (an OpenAI choices[].message.content string)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": Handler.content}}]}).encode())

    def log_message(self, *a):
        pass


class TestLocalBackendNoClaude(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.tmp = tempfile.mkdtemp()
        # A minimal transcript the hooks will summarize/score.
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        with open(self.transcript, "w") as fh:
            fh.write('{"message":{"content":"add validation to the signup form"}}\n')
            fh.write('{"message":{"content":[{"type":"text","text":"added a trim() check, tests pass"}]}}\n')

    def _env(self, **extra):
        env = dict(os.environ)
        env.pop("NERVEPACK_AGENT", None)  # else the re-entry guard bails immediately
        env.update({
            "NP_LLM_BACKEND": "local",
            "NP_LLM_BASE_URL": f"http://127.0.0.1:{self.port}/v1",
            "NP_LLM_MODEL_CHEAP": "m",
            "CLAUDE_BIN": NO_CLAUDE,  # the claude binary is absent
        })
        env.update(extra)
        return env

    def _payload(self, sid):
        return json.dumps({"transcript_path": self.transcript,
                           "cwd": os.path.join(self.tmp, "demo-proj"),
                           "session_id": sid})

    def test_capture_writes_note_without_claude(self):
        Handler.content = json.dumps({
            "headline": "added signup validation", "body": "added a trim() check.",
            "candidate_topics": ["forms"], "keywords": ["a", "b", "c", "d", "e"],
            "struggles": [], "strategies": []})
        inbox = os.path.join(self.tmp, "cap-inbox")
        r = sh(CAPTURE, "session-end", input=self._payload("nc-cap"),
               capture_output=True, text=True,
               env=self._env(EPISODIC_INBOX=inbox,
                             EPISODIC_SEEN_DIR=os.path.join(self.tmp, "seen")))
        self.assertEqual(r.returncode, 0, r.stderr)
        files = os.listdir(inbox) if os.path.isdir(inbox) else []
        self.assertTrue(files, f"no note written (inbox empty); stderr={r.stderr}")
        rec = json.loads(open(os.path.join(inbox, files[0])).read().strip().splitlines()[-1])
        self.assertEqual(rec["headline"], "added signup validation")

    def test_evaluator_writes_record_without_claude(self):
        Handler.content = json.dumps({
            "contribution_score": 55, "helped": ["x"], "shortfalls": [],
            "suggestions": [], "assets_used": []})
        inbox = os.path.join(self.tmp, "eval-inbox")
        r = sh(EVAL, input=self._payload("nc-eval"),
               capture_output=True, text=True,
               env=self._env(EVAL_INBOX=inbox))
        self.assertEqual(r.returncode, 0, r.stderr)
        files = os.listdir(inbox) if os.path.isdir(inbox) else []
        self.assertTrue(files, f"no record written (inbox empty); stderr={r.stderr}")
        rec = json.loads(open(os.path.join(inbox, files[0])).read().strip().splitlines()[-1])
        self.assertEqual(rec["contribution_score"], 55)


if __name__ == "__main__":
    unittest.main()
