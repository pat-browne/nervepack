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

    def test_dispatch_prints_hook_return_value_to_stdout(self):
        from nervepack_engine import cli
        import io as _io
        from contextlib import redirect_stdout

        with mock.patch.dict(cli._HOOKS, {"fake": lambda text: "hello from hook"}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO("{}")):
            os.environ.pop("NERVEPACK_AGENT", None)
            buf = _io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "hello from hook")

    def test_dispatch_prints_nothing_when_hook_returns_empty(self):
        from nervepack_engine import cli
        import io as _io
        from contextlib import redirect_stdout

        with mock.patch.dict(cli._HOOKS, {"fake": lambda text: ""}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO("{}")):
            os.environ.pop("NERVEPACK_AGENT", None)
            buf = _io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_dispatch_forwards_extra_argv_to_hook(self):
        from nervepack_engine import cli
        calls = []
        with mock.patch.dict(cli._HOOKS, {"fake": lambda text, mode=None: calls.append((text, mode))}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO('{"a":1}')):
            os.environ.pop("NERVEPACK_AGENT", None)
            rc = cli.main(["hook", "fake", "checkpoint"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [('{"a":1}', "checkpoint")])

    def test_dispatch_with_no_extra_argv_unchanged(self):
        from nervepack_engine import cli
        calls = []
        with mock.patch.dict(cli._HOOKS, {"fake": lambda text: calls.append(text)}), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(sys, "stdin", io.StringIO("{}")):
            os.environ.pop("NERVEPACK_AGENT", None)
            rc = cli.main(["hook", "fake"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["{}"])


class TestResumeWriteDispatch(unittest.TestCase):
    """Covers cli.py's `resume-write` dispatch branch itself. All 10
    scenarios in test_resume_write.py call resume_write.write() directly,
    bypassing cli.py entirely -- these tests exercise the dispatch shape
    (argv parsing, the NERVEPACK_AGENT guard, and the fail-open exception
    wrapper) that only cli.main() implements."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.pointer = os.path.join(self.tmp_dir, "pointer.json")
        self.stamp = os.path.join(self.tmp_dir, "last-write")
        self.toggles_conf = os.path.join(self.tmp_dir, "toggles.conf")
        open(self.toggles_conf, "w").close()
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp_dir, "local-none"),
            "NP_RESUME_POINTER": self.pointer,
            "NP_RESUME_STAMP": self.stamp,
            "NP_RESUME_LOG": os.path.join(self.tmp_dir, "resume.log"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)

    def test_successful_dispatch_writes_a_real_pointer_file(self):
        from nervepack_engine import cli
        os.environ.pop("NERVEPACK_AGENT", None)
        rc = cli.main(["resume-write", "--session", "s1", "--cwd", self.tmp_dir])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self.pointer))
        with open(self.pointer, encoding="utf-8") as fh:
            record = json.load(fh)
        self.assertEqual(record["session_id"], "s1")
        self.assertEqual(record["cwd"], self.tmp_dir)

    def test_nervepack_agent_guard_skips_dispatch_no_pointer_written(self):
        from nervepack_engine import cli
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            rc = cli.main(["resume-write", "--session", "s1", "--cwd", self.tmp_dir])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isfile(self.pointer))

    def test_write_exception_is_caught_and_does_not_propagate(self):
        from nervepack_engine import cli
        os.environ.pop("NERVEPACK_AGENT", None)
        with mock.patch.object(cli.resume_write, "write", side_effect=RuntimeError("boom")):
            rc = cli.main(["resume-write", "--session", "s1", "--cwd", self.tmp_dir])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isfile(self.pointer))


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
