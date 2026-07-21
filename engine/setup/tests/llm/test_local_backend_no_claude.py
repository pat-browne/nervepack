#!/usr/bin/env python3
"""Regression: the SessionEnd hooks must run on the `local` backend with NO `claude`
binary present. episodic-capture.sh / np-evaluator.sh historically gated on
`[[ -x "$CLAUDE" ]]` — a leftover from before the np-llm.sh seam — which made both
bail silently on a pure non-Claude host even though the local backend works. This
drives each hook with NP_LLM_BACKEND=local, CLAUDE_BIN pointed at a nonexistent path,
and a stub OpenAI-compatible server, asserting a note/record is still written.
Both episodic-capture.sh and np-evaluator.sh are retired (Phase 6) -- both tests
now call their in-process Python ports directly (np_capture.capture() /
np_evaluator.evaluate()), same as the cli.py-dispatched hook wrappers and the MCP
server do.
Stdlib unittest (no pytest), per CLAUDE.md. Run: `python3 -m unittest`."""
import json, os, sys, tempfile, threading, unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SETUP = os.path.join(REPO, "engine", "setup")
NO_CLAUDE = "/nonexistent/np-no-claude-binary"

if SETUP not in sys.path:
    sys.path.insert(0, SETUP)
import np_capture  # noqa: E402
import np_evaluator  # noqa: E402


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
        env = self._env(EPISODIC_INBOX=inbox, EPISODIC_SEEN_DIR=os.path.join(self.tmp, "seen"))
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("NERVEPACK_AGENT", None)
            status = np_capture.capture(json.loads(self._payload("nc-cap")), mode="session-end")
        self.assertEqual(status, "captured")
        files = os.listdir(inbox) if os.path.isdir(inbox) else []
        self.assertTrue(files, "no note written (inbox empty)")
        rec = json.loads(open(os.path.join(inbox, files[0])).read().strip().splitlines()[-1])
        self.assertEqual(rec["headline"], "added signup validation")

    def test_evaluator_writes_record_without_claude(self):
        Handler.content = json.dumps({
            "contribution_score": 55, "helped": ["x"], "shortfalls": [],
            "suggestions": [], "assets_used": []})
        inbox = os.path.join(self.tmp, "eval-inbox")
        env = self._env(EVAL_INBOX=inbox)
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("NERVEPACK_AGENT", None)
            status = np_evaluator.evaluate(json.loads(self._payload("nc-eval")))
        self.assertEqual(status, "evaluated")
        files = os.listdir(inbox) if os.path.isdir(inbox) else []
        self.assertTrue(files, "no record written (inbox empty)")
        rec = json.loads(open(os.path.join(inbox, files[0])).read().strip().splitlines()[-1])
        self.assertEqual(rec["contribution_score"], 55)


if __name__ == "__main__":
    unittest.main()
