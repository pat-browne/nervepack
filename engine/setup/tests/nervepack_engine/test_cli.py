"""Tests for the nervepack CLI dispatcher (engine/nervepack_engine/cli.py).
Stdlib unittest only, run via engine/setup/tests/run-all.sh."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
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
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(os.environ, {"NERVEPACK_CLI_LOG": os.path.join(tmp_dir, "cli.log")}), \
                 mock.patch.object(sys, "stdin", io.StringIO("{}")):
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

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(cli._HOOKS, {"fake": _boom}), \
                 mock.patch.dict(os.environ, {"NERVEPACK_CLI_LOG": os.path.join(tmp_dir, "cli.log")}, clear=False), \
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


class TestBackcaptureSweepEndToEnd(unittest.TestCase):
    """Real subprocess invocation of cli.py — proves the full settings.json
    dispatch shape (`python3 cli.py hook backcapture-sweep` with a JSON stdin
    payload) actually reaches the ported hook and writes a real inbox record,
    using the real np_capture/np_evaluator (stubbed CLAUDE_BIN, matching the
    bash test's fake-claude approach for this one true integration check)."""

    @unittest.skipIf(
        sys.platform == "win32",
        "the claude_stub below is a shebang script exec'd directly as a "
        "subprocess argv[0]; native Windows Python can't CreateProcess a "
        "shebang script (WinError 193) — same constraint documented in "
        "tests/mcp/parity/test_model_parity.sh. Windows gets functional "
        "coverage once capture/evaluate land their own Windows-safe stub.",
    )
    def test_full_dispatch_captures_a_settled_session(self):
        cli_path = os.path.join(_ENGINE_DIR, "engine", "nervepack_engine", "cli.py")
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = os.path.join(tmp, "projects")
            proj = os.path.join(projects_dir, "proj")
            os.makedirs(proj)
            sid = "e2e-11111111"
            tpath = os.path.join(proj, sid + ".jsonl")
            with open(tpath, "w") as fh:
                fh.write(json.dumps({"type": "user", "cwd": "/home/test/proj",
                                      "message": {"role": "user", "content": "hi"}}) + "\n")
            old = time.time() - 600
            os.utime(tpath, (old, old))

            toggles_conf = os.path.join(tmp, "toggles.conf")
            with open(toggles_conf, "w") as fh:
                fh.write("memory|shared|runtime|on|\nevaluator|shared|runtime|on|\n")

            claude_stub = os.path.join(tmp, "claude")
            with open(claude_stub, "w") as fh:
                fh.write("#!/usr/bin/env bash\ncat >/dev/null\n"
                         'printf %s \'{"headline":"h","body":"b","candidate_topics":["p"],'
                         '"keywords":["a"],"struggles":[],"strategies":[],'
                         '"contribution_score":70,"helped":[],"shortfalls":[],'
                         '"suggestions":[],"assets_used":[]}\'\n')
            os.chmod(claude_stub, 0o755)

            env = dict(os.environ)
            env.update({
                "NP_TOGGLES_CONF": toggles_conf,
                "NP_TOGGLES_LOCAL": os.path.join(tmp, "local"),
                "CLAUDE_PROJECTS_DIR": projects_dir,
                "BACKCAPTURE_SEEN_DIR": os.path.join(tmp, "seen"),
                "BACKCAPTURE_QUEUE_DIR": os.path.join(tmp, "queue"),
                "BACKCAPTURE_METRICS": os.path.join(tmp, "metrics.jsonl"),
                "BACKCAPTURE_MIN_AGE_SEC": "120",
                "BACKCAPTURE_LOG": os.path.join(tmp, "bc.log"),
                "EPISODIC_INBOX": os.path.join(tmp, "ep-inbox"),
                "EPISODIC_SEEN_DIR": os.path.join(tmp, "ep-seen"),
                "EVAL_INBOX": os.path.join(tmp, "eval-inbox"),
                "NP_SIGNAL_DIR": os.path.join(tmp, "sig"),
                "CLAUDE_BIN": claude_stub,
            })
            env.pop("NERVEPACK_AGENT", None)

            result = subprocess.run(
                [sys.executable, cli_path, "hook", "backcapture-sweep"],
                input=json.dumps({"session_id": "current"}),
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)

            eval_inbox = os.path.join(tmp, "eval-inbox")
            self.assertTrue(os.path.isdir(eval_inbox))
            lines = []
            for fname in os.listdir(eval_inbox):
                with open(os.path.join(eval_inbox, fname)) as fh:
                    lines.extend(fh.readlines())
            self.assertEqual(len(lines), 1)
            self.assertIn(sid, lines[0])


if __name__ == "__main__":
    unittest.main()
