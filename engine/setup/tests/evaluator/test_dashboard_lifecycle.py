# np-test: dashboard-lifecycle | the COMPOSED contract — a SessionStart must
#          leave the dashboard actually reachable, not merely leave each part correct.
"""The drift guard.

The dashboard was completely dead for seven weeks and **every unit test passed
the entire time**. That is the whole lesson: `test_dashboard_server.py` spawns
the server directly and proves it serves; `test_open_dashboard.py` proved the
hook's branching. Nothing proved the hook actually *produces a reachable
dashboard*, so when the hook stopped spawning the server the suite stayed green.

Root cause on the day: open_dashboard gated the server spawn behind a
once-per-OS-boot marker. On a host that suspends instead of rebooting, boot_id
is stable for weeks, so the hook returned early every single session, nothing
listened on the port, and every Implement click POSTed into the void.

These tests assert the END-TO-END contract in exactly that condition — marker
already matching the current boot — so any future change that stops the
lifecycle from bringing the backend up fails here, regardless of which
component's internals changed. Test the composition, not just the parts.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_dashboard  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class DashboardLifecycleTest(unittest.TestCase):
    """Serve mode on + boot marker already burned == the exact 7-week drift state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.port = free_port()
        self.spawned = []

        conf = os.path.join(self.tmp, "toggles.conf")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_open=on,dashboard_serve=on,"
                     "dashboard_port=%d,suggestions_top=10,toggle_ui=on\n" % self.port)

        # The drift condition: this boot has already been marked, so the
        # once-per-boot browser guard is spent.
        self.marker = os.path.join(self.tmp, "dashboard-open-boot")
        with open(self.marker, "w", encoding="utf-8") as fh:
            fh.write(np_dashboard.boot_id())

        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_DASH_MARKER": self.marker,
            "NP_DASH_OPENER": "true",
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

        # dashboard_url() owns the spawn, so wrap Popen to keep the handles and
        # guarantee teardown never leaks a detached server onto the test host.
        real_popen = subprocess.Popen

        def _tracking_popen(*a, **kw):
            p = real_popen(*a, **kw)
            self.spawned.append(p)
            return p

        self._popen = mock.patch.object(np_dashboard.subprocess, "Popen",
                                        side_effect=_tracking_popen)
        self._popen.start()
        self.addCleanup(self._popen.stop)
        self.addCleanup(self._reap)

    def _reap(self):
        for p in self.spawned:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass

    def _run_hook(self, opener_calls=None):
        from nervepack_engine.hooks import open_dashboard
        return open_dashboard.run(
            "", aggregate_fn=lambda: None,
            opener_fn=(opener_calls.append if opener_calls is not None else (lambda u: None)))

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            c.request("GET", path, headers={"Host": "127.0.0.1:%d" % self.port})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    # --- the contract -----------------------------------------------------

    def test_session_start_leaves_the_dashboard_actually_reachable(self):
        """The one that would have failed for seven weeks."""
        opened = []
        self._run_hook(opened)
        self.assertTrue(np_dashboard.is_listening(self.port),
                        "SessionStart must leave a live backend even when the "
                        "once-per-boot browser guard is already spent")
        status, _ = self._get("/")
        self.assertEqual(status, 200)
        # ...and the browser must still NOT reopen (invariant 8 still holds).
        self.assertEqual(opened, [])

    def test_hook_hands_back_an_http_url_not_a_file_url(self):
        """dashboard_url() falls back to file:// when the backend never comes up.
        A file:// page looks fine and silently has no API — which is precisely how
        the dead Implement button presented. Assert we got the served URL."""
        self._run_hook()
        url = np_dashboard.dashboard_url()
        self.assertTrue(url.startswith("http://127.0.0.1:%d" % self.port),
                        "got %r — a file:// fallback means the backend failed to "
                        "start and every API-backed control is silently dead" % url)

    def test_api_surface_is_live_so_implement_reject_can_work(self):
        """The Implement/Reject buttons POST to this server. If the lifecycle
        does not bring it up, they fail silently in the page with no error."""
        self._run_hook()
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8")).get("ok"))
        # /api/config is what the page reads to render the Implement controls.
        status, body = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("implement_mode", json.loads(body.decode("utf-8")))

    def test_repeated_session_starts_do_not_spawn_a_second_backend(self):
        """Idempotence: SessionStart fires constantly (startup/resume/clear/
        compact). Ensuring the backend every session must not pile up servers —
        that would trade a dead dashboard for a process leak."""
        self._run_hook()
        self.assertTrue(np_dashboard.is_listening(self.port))
        before = len(self.spawned)
        self._run_hook()
        self._run_hook()
        self.assertEqual(len(self.spawned), before,
                         "an already-listening port must be reused, not re-spawned")

    def test_serve_off_still_yields_a_file_url_and_no_server(self):
        """The opt-out must keep working — this guard must not force a server on
        someone who turned serve mode off."""
        conf = os.environ["NP_TOGGLES_CONF"]
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_open=on,dashboard_serve=off,"
                     "dashboard_port=%d\n" % self.port)
        self._run_hook()
        self.assertFalse(np_dashboard.is_listening(self.port))
        self.assertTrue(np_dashboard.dashboard_url().startswith("file://"))


if __name__ == "__main__":
    unittest.main()
