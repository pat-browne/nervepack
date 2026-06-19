#!/usr/bin/env python3
"""Contract test for setup/np-dashboard-server.py (stdlib unittest). Starts the
server in an isolated temp root on a free port, stubs the LLM seam via CLAUDE_BIN,
and asserts: static serving, /api/health, resolve/clear/review routes, and that a
path-traversal request is rejected (the one security-critical behavior)."""
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "..", "..")
SERVER = os.path.join(SETUP, "np-dashboard-server.py")

FIXTURE = (
    '{"session_id":"s1","ts":"2026-06-01T10:00:00Z","suggestions":['
    '{"text":"Do alpha","confidence":0.9,"target":"hooks","auto_safe":true},'
    '{"text":"Do beta","confidence":0.5,"target":"skills"}]}\n'
)
STUB_CLAUDE = '#!/usr/bin/env bash\ncat >/dev/null\necho \'[{"i":0,"decision":"implement","reason":"ok"}]\'\n'


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.root = os.path.join(d, "dashboard"); os.makedirs(cls.root)
        with open(os.path.join(cls.root, "index.html"), "w") as fh:
            fh.write("<html>NERVEPACK-DASH-OK</html>")
        # Mirror the engine/content split: dashboard/data is a SYMLINK out of the
        # static root into the content overlay. Files under it must still serve.
        cls.ext_data = os.path.join(d, "content-dashboard-data"); os.makedirs(cls.ext_data)
        with open(os.path.join(cls.ext_data, "metrics.js"), "w") as fh:
            fh.write("window.METRICS=[];window.LEARNED={};")
        os.symlink(cls.ext_data, os.path.join(cls.root, "data"))
        cls.metrics = os.path.join(d, "metrics.jsonl")
        with open(cls.metrics, "w") as fh:
            fh.write(FIXTURE)
        cls.resolved = os.path.join(d, "resolved.txt")
        # stub the implement job so /api/implement can be tested without an agent:
        # it just records the suggestion text it was spawned with.
        cls.impl_sentinel = os.path.join(d, "impl-ran.txt")
        impl = os.path.join(d, "implement-stub.sh")
        with open(impl, "w") as fh:
            fh.write(f'#!/usr/bin/env bash\nprintf "%s\\n" "$1" >> "{cls.impl_sentinel}"\n')
        os.chmod(impl, 0o755)
        cls.impl = impl
        cls.status_dir = os.path.join(d, "implement-status"); os.makedirs(cls.status_dir)
        claude = os.path.join(d, "claude-stub.sh")
        with open(claude, "w") as fh:
            fh.write(STUB_CLAUDE)
        os.chmod(claude, 0o755)
        # isolated toggle files so /api/config + /api/implement-mode don't touch the real ones
        cls.toggles_local = os.path.join(d, "toggles.local")
        cls.toggles_conf = os.path.join(d, "toggles.conf")
        with open(cls.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|implement=on,implement_mode=pr\n")
        cls.port = free_port()
        env = dict(os.environ)
        env.update({
            "NP_DASH_PORT": str(cls.port), "NP_DASH_ROOT": cls.root,
            "NP_METRICS": cls.metrics, "NP_RESOLVED_SUGGESTIONS": cls.resolved,
            "NP_RESOLVE_NO_BUILD": "1", "NP_SUGGESTIONS_TOP": "5", "CLAUDE_BIN": claude,
            "NP_IMPLEMENT": impl, "NP_IMPLEMENT_STATUS_DIR": cls.status_dir,
            "NP_TOGGLES_LOCAL": cls.toggles_local, "NP_TOGGLES_CONF": cls.toggles_conf,
        })
        cls.proc = subprocess.Popen(["python3", SERVER], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # wait for health
        for _ in range(50):
            try:
                if cls._get("/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try: cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired: cls.proc.kill()
        cls.tmp.cleanup()

    def setUp(self):
        # Fresh resolved ledger before each test — the server reads it per request,
        # so this fully isolates tests that share the one class-level server.
        with open(self.resolved, "w") as fh:
            fh.write("# test ledger\n")
        with open(self.toggles_local, "w") as fh:  # reset per-machine override
            fh.write("")

    @classmethod
    def _conn(cls):
        return http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)

    @classmethod
    def _get(cls, path):
        c = cls._conn(); c.request("GET", path); r = c.getresponse()
        body = r.read().decode(); c.close(); return r.status, body

    def _post(self, path, obj, headers=None):
        c = self._conn()
        h = {"Content-Type": "application/json", "X-Requested-With": "nervepack"}
        if headers is not None:
            h = headers
        c.request("POST", path, json.dumps(obj), h)
        r = c.getresponse(); body = r.read().decode(); c.close()
        return r.status, body

    def test_serves_index(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("NERVEPACK-DASH-OK", body)

    def test_health(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_path_traversal_rejected(self):
        """Raw socket so the client can't normalize away the ../ — the server's
        _safe_path must refuse anything outside the dashboard root."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"GET /../../np-suggestions-review.py HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            resp += chunk
        s.close()
        self.assertIn(b"404", resp.split(b"\r\n", 1)[0])
        self.assertNotIn(b"np-suggestions-review", resp.split(b"\r\n\r\n", 1)[-1])

    def test_serves_symlinked_data_dir(self):
        """After the engine/content split, dashboard/data is a symlink into the
        content overlay, so its realpath is outside DASH. The guard must still serve
        files under the canonical data root (else the charts get no metrics.js)."""
        status, body = self._get("/data/metrics.js")
        self.assertEqual(status, 200)
        self.assertIn("window.METRICS", body)

    def test_traversal_through_data_symlink_rejected(self):
        """Escaping the symlinked data dir with ../ must still be refused — the
        canonical-data allowance must not become a traversal hole."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"GET /data/../../content-dashboard-data/../np-dashboard-server.py "
                  b"HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            resp += chunk
        s.close()
        self.assertIn(b"404", resp.split(b"\r\n", 1)[0])

    def test_resolve_writes_ledger(self):
        status, body = self._post("/api/resolve", {"text": "Do beta"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        with open(self.resolved) as fh:
            self.assertIn("Do beta", fh.read())

    def test_review_returns_rows_with_verdicts(self):
        status, body = self._post("/api/review", {})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["degraded"])                # stub LLM responded
        self.assertTrue(data["rows"])
        self.assertEqual(data["rows"][0]["verdict"]["decision"], "implement")

    def test_resolve_missing_text_is_400(self):
        status, _ = self._post("/api/resolve", {})
        self.assertEqual(status, 400)

    def test_post_without_csrf_header_is_forbidden(self):
        """A state-changing POST lacking X-Requested-With is rejected (CSRF guard),
        and the action does not run."""
        status, _ = self._post("/api/clear", {}, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_post_with_foreign_origin_is_forbidden(self):
        status, _ = self._post("/api/clear", {}, headers={
            "Content-Type": "application/json", "X-Requested-With": "nervepack",
            "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_clear_reports_count(self):
        status, body = self._post("/api/clear", {})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertIn("count", json.loads(body))

    def test_implement_spawns_job(self):
        # remove any prior sentinel so we assert on THIS spawn
        try: os.remove(self.impl_sentinel)
        except OSError: pass
        status, body = self._post("/api/implement", {"text": "Do gamma"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("started"))
        for _ in range(60):  # detached job — wait briefly for the stub to record it
            if os.path.exists(self.impl_sentinel) and "Do gamma" in open(self.impl_sentinel).read():
                return
            time.sleep(0.05)
        self.fail("implement job was not spawned")

    def test_implement_missing_text_is_400(self):
        status, _ = self._post("/api/implement", {})
        self.assertEqual(status, 400)

    def test_implement_without_csrf_header_is_forbidden(self):
        status, _ = self._post("/api/implement", {"text": "x"},
                               headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_config_returns_default_mode(self):
        status, body = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["implement_mode"], "pr")  # conf default

    def test_set_mode_writes_override_and_get_reflects_it(self):
        status, body = self._post("/api/implement-mode", {"mode": "direct"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "direct")
        with open(self.toggles_local) as fh:
            self.assertIn("evaluator.implement_mode=direct", fh.read())
        # the resolver now reports direct
        _, cfg = self._get("/api/config")
        self.assertEqual(json.loads(cfg)["implement_mode"], "direct")

    def test_set_mode_rejects_invalid(self):
        status, _ = self._post("/api/implement-mode", {"mode": "yolo"})
        self.assertEqual(status, 400)

    def test_set_mode_without_csrf_is_forbidden(self):
        status, _ = self._post("/api/implement-mode", {"mode": "direct"},
                               headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_implement_status_reflects_job_file(self):
        import hashlib as _h
        text = "Add a gamma helper"
        key = _h.sha256(text.encode()).hexdigest()[:16]
        with open(os.path.join(self.status_dir, key + ".json"), "w") as fh:
            json.dump({"state": "done", "ref": "https://example/pr/9"}, fh)
        from urllib.parse import quote
        status, body = self._get("/api/implement-status?text=" + quote(text))
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["state"], "done")
        self.assertEqual(data["ref"], "https://example/pr/9")

    def test_implement_status_none_when_absent(self):
        from urllib.parse import quote
        _, body = self._get("/api/implement-status?text=" + quote("never ran this one"))
        self.assertEqual(json.loads(body)["state"], "none")


if __name__ == "__main__":
    unittest.main()
