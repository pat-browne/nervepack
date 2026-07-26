"""Direct unit tests for np_dashboard.py -- the Python port of
np-dashboard-launch.sh's URL/opener resolution (consumed by
hooks/open_dashboard.py) AND open-dashboard.sh's manual open (open_manual(),
consumed by cli.py open-dashboard). Ports the scenarios from
test_dashboard_launch.sh, test_resolve_opener.sh, and test_open_dashboard_manual.sh.
Both bash scripts are retired -- np_dashboard.py is the sole implementation."""
import contextlib
import io
import os
import socket
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/evaluator -- two levels up is engine/setup
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_dashboard  # noqa: E402


class TestResolveOpener(unittest.TestCase):
    def test_1_explicit_override_wins(self):
        with mock.patch.dict(os.environ, {"NP_DASH_OPENER": "my-opener"}):
            self.assertEqual(np_dashboard.resolve_opener(), "my-opener")

    def test_2_prefers_xdg_open_when_both_present(self):
        real_which = np_dashboard.shutil.which
        def _which(name):
            return "/usr/bin/%s" % name if name in ("xdg-open", "open") else None
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(np_dashboard.shutil, "which", side_effect=_which):
            os.environ.pop("NP_DASH_OPENER", None)
            self.assertEqual(np_dashboard.resolve_opener(), "xdg-open")

    def test_3_falls_back_to_open_when_only_open_present(self):
        def _which(name):
            return "/usr/bin/open" if name == "open" else None
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(np_dashboard.shutil, "which", side_effect=_which):
            os.environ.pop("NP_DASH_OPENER", None)
            self.assertEqual(np_dashboard.resolve_opener(), "open")

    def test_4_none_available_returns_empty(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(np_dashboard.shutil, "which", return_value=None):
            os.environ.pop("NP_DASH_OPENER", None)
            self.assertEqual(np_dashboard.resolve_opener(), "")


class TestIsListening(unittest.TestCase):
    def test_5_nothing_listening_returns_false(self):
        # Bind briefly to find a free port, then release it before checking.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertFalse(np_dashboard.is_listening(port, timeout=0.2))

    def test_6_real_listener_returns_true(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(np_dashboard.is_listening(port, timeout=0.2))
        finally:
            srv.close()


class TestDashboardUrl(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_serve=off\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil as _shutil
        self.addCleanup(_shutil.rmtree, self.tmp, True)

    def test_7_serve_off_returns_file_url(self):
        url = np_dashboard.dashboard_url()
        self.assertTrue(url.startswith("file://"))
        self.assertTrue(url.endswith("dashboard/index.html"))

    def test_8_serve_on_already_listening_no_spawn(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_serve=on,dashboard_port=0\n")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with open(self.toggles_conf, "w") as fh:
                fh.write("evaluator|shared|runtime|on|dashboard_serve=on,dashboard_port=%d\n" % port)
            with mock.patch.object(np_dashboard.subprocess, "Popen") as popen:
                url = np_dashboard.dashboard_url()
                popen.assert_not_called()
            self.assertEqual(url, "http://127.0.0.1:%d/" % port)
        finally:
            srv.close()

    def test_9_serve_on_backend_never_comes_up_falls_back_to_file(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_serve=on,dashboard_port=1\n")
        with mock.patch.object(np_dashboard, "_POLL_ATTEMPTS", 1), \
             mock.patch.object(np_dashboard, "_POLL_INTERVAL", 0.01), \
             mock.patch.object(np_dashboard.subprocess, "Popen") as popen:
            url = np_dashboard.dashboard_url()
            popen.assert_called_once()
        self.assertTrue(url.startswith("file://"))


class TestBootId(unittest.TestCase):
    def test_10_linux_path_read_when_present(self):
        with mock.patch("builtins.open", mock.mock_open(read_data="abc-123\n")):
            self.assertEqual(np_dashboard.boot_id(), "abc-123")

    def test_11_macos_fallback_uses_sysctl_kern_boottime(self):
        def _open_raises(path, *a, **kw):
            raise OSError("no such file")
        fake_result = mock.Mock(returncode=0, stdout="{ sec = 123 } Wed Jan 1\n")
        with mock.patch("builtins.open", side_effect=_open_raises), \
             mock.patch.object(np_dashboard.subprocess, "run", return_value=fake_result) as run:
            got = np_dashboard.boot_id()
            run.assert_called_once()
            self.assertIn("sysctl", run.call_args[0][0])
        self.assertEqual(got, "{ sec = 123 } Wed Jan 1")

    def test_12_neither_available_returns_unknown(self):
        def _open_raises(path, *a, **kw):
            raise OSError("no such file")
        with mock.patch("builtins.open", side_effect=_open_raises), \
             mock.patch.object(np_dashboard.subprocess, "run", side_effect=OSError("no sysctl")):
            self.assertEqual(np_dashboard.boot_id(), "unknown")


class TestOpenManual(unittest.TestCase):
    """Ports test_open_dashboard_manual.sh. Host-agnostic + hermetic: serve=off
    keeps dashboard_url() on the cheap file:// path; subprocess.run is mocked so
    neither the metrics rebuild nor the opener actually execute -- the assertions
    ride the `command -v` gate (shutil.which/os.path.isfile), which is pure
    Python, so both cases run on every lane including native Windows."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        # serve=off -> deterministic file:// URL, no server spawn.
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_serve=off,dashboard_port=8787\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil as _shutil
        self.addCleanup(_shutil.rmtree, self.tmp, True)

    def test_13_happy_resolvable_opener_prints_opened_and_returns_zero(self):
        # A resolvable opener (sys.executable is always on PATH via shutil.which,
        # harmless under the mock). Assert the file:// URL is what open_manual
        # hands the opener, "opened <url>" is printed, and it returns 0.
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"NP_DASH_OPENER": sys.executable}, clear=False), \
             mock.patch.object(np_dashboard.subprocess, "run") as run, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = np_dashboard.open_manual()
        self.assertEqual(rc, 0)
        expected = "file://%s/dashboard/index.html" % np_dashboard._ENGINE
        self.assertIn("opened %s" % expected, out.getvalue())
        self.assertEqual(err.getvalue(), "")
        # Two subprocess.run calls: the metrics rebuild, then the opener with the URL.
        opener_calls = [c for c in run.call_args_list
                        if c.args and c.args[0] == [sys.executable, expected]]
        self.assertEqual(len(opener_calls), 1)

    def test_14_missing_opener_prints_no_opener_opens_nothing_returns_zero(self):
        # A bogus NP_DASH_OPENER override -> fails the command -v gate -> "no
        # opener", nothing opened, still exit 0 (fail-open). Host-agnostic: the
        # bogus path is neither on PATH nor an existing file on any OS.
        bogus = os.path.join(self.tmp, "does-not-exist-opener").replace("\\", "/")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"NP_DASH_OPENER": bogus}, clear=False), \
             mock.patch.object(np_dashboard.subprocess, "run") as run, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = np_dashboard.open_manual()
        self.assertEqual(rc, 0)
        self.assertIn("no opener", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        # Only the metrics rebuild ran; the opener was never invoked.
        opener_calls = [c for c in run.call_args_list
                        if c.args and c.args[0] and c.args[0][0] == bogus]
        self.assertEqual(opener_calls, [])


class TestOpenManualDispatch(unittest.TestCase):
    """The `cli.py open-dashboard` top-level command routes to open_manual()
    and is distinct from `cli.py hook open-dashboard` (the SessionStart hook)."""

    def test_15_cli_open_dashboard_routes_to_open_manual(self):
        _ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
        if _ENGINE_DIR not in sys.path:
            sys.path.insert(0, _ENGINE_DIR)
        from nervepack_engine import cli
        with mock.patch.object(np_dashboard, "open_manual", return_value=0) as om:
            rc = cli.main(["open-dashboard"])
        self.assertEqual(rc, 0)
        om.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
