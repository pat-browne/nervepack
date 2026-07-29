"""Tests for nervepack_engine.hooks.open_dashboard -- the Python port of
74-open-dashboard.sh. Ports test_open_dashboard.sh's scenarios. Computes its
expected boot-id value via np_dashboard.boot_id() itself (not a hardcoded
Linux-only fallback) so it stays correct on whatever platform it runs on --
see Task 1's deliberate boot_id() behavior-change note."""
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_dashboard  # noqa: E402


class TestOpenDashboard(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_open=on,dashboard_serve=off\n")
        self.marker = os.path.join(self.tmp, "dashboard-open-boot")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_DASH_MARKER": self.marker,
            "NP_DASH_OPENER": "true",  # a real, harmless no-op binary on PATH
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, aggregate_fn=None, opener_fn=None):
        from nervepack_engine.hooks import open_dashboard
        return open_dashboard.run("", aggregate_fn=aggregate_fn, opener_fn=opener_fn)

    def test_1_fresh_boot_opens_once_writes_marker(self):
        calls = []
        real_boot = np_dashboard.boot_id()
        self._run(aggregate_fn=lambda: None, opener_fn=lambda url: calls.append(url))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("file://"))
        with open(self.marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), real_boot)

    def test_2_marker_already_matches_boot_does_not_reopen(self):
        with open(self.marker, "w", encoding="utf-8") as fh:
            fh.write(np_dashboard.boot_id())
        calls = []
        self._run(aggregate_fn=lambda: None, opener_fn=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_2b_backend_is_ensured_even_when_marker_matches(self):
        """Invariant 8's once-per-boot guard exists to stop a *browser window*
        reopening in a loop. Ensuring the local server is listening is not a GUI
        side effect and must not sit behind that guard: on a host that suspends
        instead of rebooting, boot_id is stable for weeks, so the old placement
        left the dashboard with no backend for that whole time (observed: 7
        weeks of uptime, nothing listening, every Implement click POSTing into
        the void)."""
        with open(self.marker, "w", encoding="utf-8") as fh:
            fh.write(np_dashboard.boot_id())
        opened, ensured = [], []
        with mock.patch.object(np_dashboard, "dashboard_url",
                                side_effect=lambda: ensured.append(1) or "file:///x"):
            self._run(aggregate_fn=lambda: None, opener_fn=lambda url: opened.append(url))
        self.assertEqual(opened, [], "browser must still open only once per boot")
        self.assertEqual(len(ensured), 1, "the backend must be ensured every session")

    def test_2c_metrics_refresh_runs_even_when_marker_matches(self):
        # Same reasoning: regenerating metrics.js is not a GUI side effect, and
        # gating it on boot left the rendered data refreshed only by the daily cron.
        with open(self.marker, "w", encoding="utf-8") as fh:
            fh.write(np_dashboard.boot_id())
        agg = []
        self._run(aggregate_fn=lambda: agg.append(1), opener_fn=lambda url: None)
        self.assertEqual(len(agg), 1)

    def test_2d_backend_ensured_even_with_no_opener(self):
        # A headless box (no opener) should still get a served dashboard it can
        # be port-forwarded to; the old order returned before ever spawning it.
        ensured = []
        with mock.patch.dict(os.environ, {"NP_DASH_OPENER": ""}, clear=False), \
             mock.patch.object(np_dashboard, "resolve_opener", return_value=""), \
             mock.patch.object(np_dashboard, "dashboard_url",
                                side_effect=lambda: ensured.append(1) or "file:///x"):
            self._run(aggregate_fn=lambda: None, opener_fn=lambda url: None)
        self.assertEqual(len(ensured), 1)

    def test_3_toggle_off_does_not_open(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_open=off\n")
        calls = []
        self._run(aggregate_fn=lambda: None, opener_fn=lambda url: calls.append(url))
        self.assertEqual(calls, [])
        self.assertFalse(os.path.isfile(self.marker))

    def test_4_aggregate_step_invoked_before_open(self):
        order = []
        self._run(aggregate_fn=lambda: order.append("aggregate"),
                  opener_fn=lambda url: order.append("open"))
        self.assertEqual(order, ["aggregate", "open"])

    def test_5_no_opener_available_fails_open(self):
        with mock.patch.object(np_dashboard, "resolve_opener", return_value=""):
            calls = []
            out = self._run(aggregate_fn=lambda: None, opener_fn=lambda url: calls.append(url))
        self.assertEqual(out, "")
        self.assertEqual(calls, [])

    def test_6_aggregate_step_exception_fails_open_still_opens(self):
        def _boom():
            raise RuntimeError("boom")
        calls = []
        out = self._run(aggregate_fn=_boom, opener_fn=lambda url: calls.append(url))
        self.assertEqual(out, "")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
