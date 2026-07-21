"""Direct unit tests for np_dashboard.py -- the new Python port of
np-dashboard-launch.sh's URL/opener resolution, consumed by the new
hooks/open_dashboard.py (Task 2). Ports the scenarios from
test_dashboard_launch.sh and test_resolve_opener.sh. np-dashboard-launch.sh
itself is NOT retired in this phase -- open-dashboard.sh (the manual open
script, out of scope) still sources it directly."""
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


if __name__ == "__main__":
    unittest.main()
