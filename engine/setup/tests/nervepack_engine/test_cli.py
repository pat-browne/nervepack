"""Tests for the nervepack CLI dispatcher (engine/nervepack_engine/cli.py).
Stdlib unittest only, run via engine/setup/tests/run-all.sh."""
import io
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestPackageSkeleton(unittest.TestCase):
    def test_package_importable(self):
        import nervepack_engine
        self.assertTrue(hasattr(nervepack_engine, "__version__"))


class TestDispatch(unittest.TestCase):
    def test_unknown_hook_name_fails_open(self):
        from nervepack_engine import cli
        with mock.patch.object(sys, "stdin", io.StringIO("{}")):
            rc = cli.main(["hook", "does-not-exist"])
        self.assertEqual(rc, 0)

    def test_nervepack_agent_guard_skips_dispatch(self):
        from nervepack_engine import cli
        calls = []
        with mock.patch.dict(cli._HOOKS, {"fake": lambda text: calls.append(text)}), \
             mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}), \
             mock.patch.object(sys, "stdin", io.StringIO("{}")):
            rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_dispatch_calls_hook_with_stdin_text(self):
        from nervepack_engine import cli
        calls = []
        with mock.patch.dict(cli._HOOKS, {"fake": lambda text: calls.append(text)}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO('{"session_id":"s1"}')):
            os.environ.pop("NERVEPACK_AGENT", None)
            rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ['{"session_id":"s1"}'])

    def test_hook_exception_fails_open(self):
        from nervepack_engine import cli

        def _boom(_text):
            raise RuntimeError("boom")

        with mock.patch.dict(cli._HOOKS, {"fake": _boom}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO("{}")):
            os.environ.pop("NERVEPACK_AGENT", None)
            rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)

    def test_malformed_argv_fails_open(self):
        from nervepack_engine import cli
        rc = cli.main([])
        self.assertEqual(rc, 0)
        rc = cli.main(["not-a-group"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
