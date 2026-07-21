"""Tests for np_scheduler_install -- the Python port of
70-install-memory-{cron,launchd,schtasks}.sh (phase 6 of the bash->Python
migration). Translates every case the five retired bash tests covered
(test_cron_install.sh, test_cron_install_failure.sh, test_install_idempotency.sh,
test_skill_cron_install.sh, test_resume_install.sh's cron-installer assertions,
test_install_memory_launchd.sh, test_install_memory_schtasks.sh) 1:1, plus a
from-scratch suite for install_cron's happy path (which had no dedicated bash
test beyond the failure case -- a real coverage gap this port closes) and a
np_token_lib parity check against the bash original's np_claude_token_env_prefix.
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_scheduler_install  # noqa: E402
import np_token_lib  # noqa: E402

_JOB_NAMES = ["memory-promote", "episodic-maintain", "aggregate-metrics",
              "skill-maintain", "refine", "compact"]


class TestTokenLibParity(unittest.TestCase):
    """np_token_lib.claude_token_env_prefix isn't byte-identical to np-token-lib.sh's
    np_claude_token_env_prefix (shlex.quote vs bash's printf %q use different, both
    valid, quote styles), so parity is checked BEHAVIORALLY: eval either snippet
    (bash's original, then the Python port's output) against the same token file and
    confirm both actually export the right token -- including a path with a space,
    where the two quoting styles diverge most visibly."""

    def _write_token(self, token_file, content):
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, "w") as fh:
            fh.write(content)

    def _bash_prefix(self, token_file):
        lib = os.path.join(_ENGINE_SETUP, "np-token-lib.sh")
        result = subprocess.run(
            ["bash", "-c", 'source "%s"; np_claude_token_env_prefix' % lib],
            env=dict(os.environ, NP_CLAUDE_TOKEN_FILE=token_file),
            capture_output=True, text=True, check=True)
        return result.stdout

    def _eval_and_get_token(self, prefix_snippet):
        result = subprocess.run(
            ["bash", "-c", "%secho \"$CLAUDE_CODE_OAUTH_TOKEN\"" % prefix_snippet],
            capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _assert_both_export_correctly(self, token_file, token_value):
        self._write_token(token_file, token_value)
        py_prefix = np_token_lib.claude_token_env_prefix()
        bash_prefix = self._bash_prefix(token_file)
        self.assertEqual(self._eval_and_get_token(py_prefix), token_value)
        self.assertEqual(self._eval_and_get_token(bash_prefix), token_value)

    def test_1_default_path_both_export_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = os.path.join(tmp, "plain-token")
            with mock.patch.dict(os.environ, {"NP_CLAUDE_TOKEN_FILE": token_file}, clear=False):
                self._assert_both_export_correctly(token_file, "sk-test-token-abc")

    def test_2_path_with_space_both_export_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = os.path.join(tmp, "a b", "token")
            with mock.patch.dict(os.environ, {"NP_CLAUDE_TOKEN_FILE": token_file}, clear=False):
                self._assert_both_export_correctly(token_file, "sk-test-token-xyz")

    def test_3_missing_token_file_is_a_silent_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = os.path.join(tmp, "does-not-exist")
            with mock.patch.dict(os.environ, {"NP_CLAUDE_TOKEN_FILE": token_file}, clear=False):
                py_prefix = np_token_lib.claude_token_env_prefix()
            self.assertEqual(self._eval_and_get_token(py_prefix), "")


class TestInstallCron(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("resume|shared|runtime|on|cron=off,cron_min=5\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.crontab = [""]

    def _list(self):
        return self.crontab[0]

    def _set(self, text):
        self.crontab[0] = text

    def _run(self, **kwargs):
        kwargs.setdefault("crontab_list_fn", self._list)
        kwargs.setdefault("crontab_set_fn", self._set)
        kwargs.setdefault("token_prefix_fn", lambda: "")
        kwargs.setdefault("have_crontab_fn", lambda: True)
        kwargs.setdefault("nervepack_root", "/opt/nervepack")
        return np_scheduler_install.install_cron(**kwargs)

    def test_1_installs_all_six_authoritative_jobs(self):
        rc = self._run()
        self.assertEqual(rc, 0)
        for marker in ("nervepack-memory-promote", "nervepack-episodic-maintain",
                        "nervepack-aggregate-metrics", "nervepack-skill-maintain",
                        "nervepack-refine", "nervepack-compact"):
            self.assertIn(marker, self._list())

    def test_2_refine_and_compact_present(self):
        # ported from test_install_idempotency.sh's specific assertion
        self._run()
        self.assertIn("nervepack-refine", self._list())
        self.assertIn("nervepack-compact", self._list())
        self.assertIn("cron refine", self._list())
        self.assertIn("cron compact", self._list())

    def test_3_correct_schedule_lines(self):
        self._run()
        text = self._list()
        self.assertIn("0 8 * * *", text)   # memory-promote
        self.assertIn("30 8 * * *", text)  # episodic-maintain
        self.assertIn("15 9 * * *", text)  # skill-maintain
        self.assertIn("30 9 * * 0", text)  # refine (weekly Sun)
        self.assertIn("0 10 * * 3", text)  # compact (weekly Wed)

    def test_4_idempotent_replaces_not_duplicates(self):
        self._run()
        self._run()
        text = self._list()
        self.assertEqual(text.count("nervepack-memory-promote"), 1)
        self.assertEqual(text.count("nervepack-compact"), 1)

    def test_5_preserves_unrelated_existing_lines(self):
        self.crontab[0] = "0 0 * * * /usr/bin/some-other-job\n"
        self._run()
        self.assertIn("/usr/bin/some-other-job", self._list())

    def test_6_token_prefix_included_in_each_job_line(self):
        rc = self._run(token_prefix_fn=lambda: "f=/x; export Y; ")
        self.assertEqual(rc, 0)
        self.assertIn("f=/x; export Y; python3", self._list())

    def test_7_resume_cron_off_by_default_no_entry(self):
        self._run()
        self.assertNotIn("nervepack-resume-cron", self._list())

    def test_8_resume_cron_on_adds_entry_with_configured_interval(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("resume|shared|runtime|on|cron=on,cron_min=7\n")
        self._run()
        self.assertIn("*/7 * * * *", self._list())
        self.assertIn("nervepack-resume-cron", self._list())

    def test_9_resume_cron_flipped_off_removes_stale_entry(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("resume|shared|runtime|on|cron=on,cron_min=5\n")
        self._run()
        self.assertIn("nervepack-resume-cron", self._list())
        with open(self.toggles_conf, "w") as fh:
            fh.write("resume|shared|runtime|on|cron=off,cron_min=5\n")
        self._run()
        self.assertNotIn("nervepack-resume-cron", self._list())

    def test_10_no_crontab_binary_fails_open_with_nonzero(self):
        rc = self._run(have_crontab_fn=lambda: False)
        self.assertEqual(rc, 1)

    def test_11_no_crontab_binary_prints_the_documented_message_and_installs_nothing(self):
        # ported from test_cron_install_failure.sh: the exact "crontab not
        # available" message, and proof it bailed at the guard (no "Installed
        # cron entry" line, no crontab_set_fn call).
        buf = io.StringIO()
        set_calls = []
        with contextlib.redirect_stdout(buf):
            rc = self._run(have_crontab_fn=lambda: False, crontab_set_fn=lambda t: set_calls.append(t))
        self.assertEqual(rc, 1)
        self.assertIn("crontab not available", buf.getvalue())
        self.assertNotIn("Installed cron entry", buf.getvalue())
        self.assertEqual(set_calls, [])

    def test_12_exact_line_format_per_job(self):
        # ported from test_install_idempotency.sh / test_skill_cron_install.sh's
        # precise per-job line-format assertions (schedule + cli.py dispatch +
        # cron name + trailing marker, all in the SAME line).
        self._run()
        text = self._list()
        expectations = [
            (r"0 8 \* \* \* .*cli\.py cron memory-promote # nervepack-memory-promote", ),
            (r"30 8 \* \* \* .*cli\.py cron episodic-maintain # nervepack-episodic-maintain", ),
            (r"0 9 \* \* \* .*cli\.py cron aggregate-metrics # nervepack-aggregate-metrics", ),
            (r"15 9 \* \* \* .*cli\.py cron skill-maintain # nervepack-skill-maintain", ),
            (r"30 9 \* \* 0 .*cli\.py cron refine # nervepack-refine", ),
            (r"0 10 \* \* 3 .*cli\.py cron compact # nervepack-compact", ),
        ]
        for (pattern,) in expectations:
            self.assertTrue(re.search(pattern, text), "missing/malformed line for %r in:\n%s" % (pattern, text))


class TestInstallLaunchd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.la_dir = os.path.join(self.tmp, "LaunchAgents")
        self.log_dir = os.path.join(self.tmp, "logs")
        self.calls = []

    def _run(self, uname="Darwin", **kwargs):
        kwargs.setdefault("la_dir", self.la_dir)
        kwargs.setdefault("log_dir", self.log_dir)
        kwargs.setdefault("setup_dir", "/opt/nervepack/engine/setup")
        kwargs.setdefault("token_prefix_fn", lambda: "")
        kwargs.setdefault("uname_fn", lambda: uname)
        kwargs.setdefault("launchctl_fn", lambda p: self.calls.append(p))
        return np_scheduler_install.install_launchd(**kwargs)

    def test_1_writes_six_plists(self):
        rc = self._run()
        self.assertEqual(rc, 0)
        for j in _JOB_NAMES:
            self.assertTrue(os.path.isfile(os.path.join(self.la_dir, "com.nervepack.%s.plist" % j)))

    def test_2_each_plist_is_well_formed_xml(self):
        self._run()
        for j in _JOB_NAMES:
            xml.dom.minidom.parse(os.path.join(self.la_dir, "com.nervepack.%s.plist" % j))

    def test_3_label_hour_minute_and_target_correct(self):
        self._run()
        with open(os.path.join(self.la_dir, "com.nervepack.skill-maintain.plist")) as fh:
            content = fh.read()
        self.assertIn("<string>com.nervepack.skill-maintain</string>", content)
        self.assertIn("<key>Hour</key><integer>9</integer>", content)
        self.assertIn("<key>Minute</key><integer>15</integer>", content)
        self.assertIn("cron skill-maintain", content)
        with open(os.path.join(self.la_dir, "com.nervepack.memory-promote.plist")) as fh:
            self.assertIn("<key>Hour</key><integer>8</integer>", fh.read())

    def test_4_launchctl_invoked_once_per_agent(self):
        self._run()
        self.assertEqual(len(self.calls), 6)

    def test_5_idempotent_second_run_still_six_plists(self):
        self._run()
        self._run()
        self.assertEqual(len(os.listdir(self.la_dir)), 6)

    def test_6_refuses_on_non_darwin_without_force(self):
        out_dir = os.path.join(self.tmp, "LA2")
        rc = self._run(uname="Linux", la_dir=out_dir)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.isdir(out_dir))

    def test_7_force_env_bypasses_os_check(self):
        with mock.patch.dict(os.environ, {"NP_LAUNCHD_FORCE": "1"}, clear=False):
            rc = self._run(uname="Linux", force=None)
        self.assertEqual(rc, 0)

    def test_8_token_prefix_embedded_and_xml_escaped(self):
        self._run(token_prefix_fn=lambda: 'f=/x && export Y; ')
        with open(os.path.join(self.la_dir, "com.nervepack.memory-promote.plist")) as fh:
            content = fh.read()
        self.assertIn("f=/x &amp;&amp; export Y", content)


class TestInstallSchtasks(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _run(self, uname="MINGW64_NT", **kwargs):
        kwargs.setdefault("setup_dir", "/opt/nervepack/engine/setup")
        kwargs.setdefault("uname_fn", lambda: uname)
        kwargs.setdefault("schtasks_fn", lambda args: self.calls.append(args))
        kwargs.setdefault("bash_path_fn", lambda: "/usr/bin/bash")
        kwargs.setdefault("cygpath_fn", lambda p: "C:\\Program Files\\Git\\usr\\bin\\bash.exe")
        return np_scheduler_install.install_schtasks(**kwargs)

    def test_1_creates_six_tasks(self):
        rc = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 6)

    def test_2_task_names_namespaced(self):
        self._run()
        joined = [" ".join(c) for c in self.calls]
        for j in _JOB_NAMES:
            self.assertTrue(any("nervepack\\%s" % j in line for line in joined))

    def test_3_schedules_correct(self):
        self._run()
        joined = {c[2]: c for c in self.calls}  # TN is args[2]
        promote = joined["nervepack\\memory-promote"]
        self.assertIn("DAILY", promote)
        self.assertIn("08:00", promote)
        refine = joined["nervepack\\refine"]
        self.assertIn("WEEKLY", refine)
        self.assertIn("SUN", refine)
        self.assertIn("09:30", refine)
        compact = joined["nervepack\\compact"]
        self.assertIn("WEEKLY", compact)
        self.assertIn("WED", compact)
        self.assertIn("10:00", compact)

    def test_4_task_action_uses_bash_and_cli_dispatch(self):
        self._run()
        tr = self.calls[0][self.calls[0].index("//TR") + 1]
        self.assertIn("bash.exe", tr)
        self.assertIn("cli.py cron memory-promote", tr)

    def test_5_force_flag_present_for_replace(self):
        self._run()
        for args in self.calls:
            self.assertIn("//F", args)

    def test_6_refuses_on_non_windows_without_force(self):
        rc = self._run(uname="Linux")
        self.assertEqual(rc, 1)
        self.assertEqual(self.calls, [])

    def test_7_force_env_bypasses_os_check(self):
        with mock.patch.dict(os.environ, {"NP_SCHTASKS_FORCE": "1"}, clear=False):
            rc = self._run(uname="Linux")
        self.assertEqual(rc, 0)

    def test_8_cygpath_missing_falls_back_to_bare_bash(self):
        rc = self._run(cygpath_fn=lambda p: "")
        self.assertEqual(rc, 0)
        tr = self.calls[0][self.calls[0].index("//TR") + 1]
        self.assertIn("/usr/bin/bash", tr)

    def test_9_no_scheduled_auth_token_prefix_deliberately_unwired(self):
        # Unlike install_cron/install_launchd: the token snippet's embedded
        # quotes are an unverified collision risk against schtasks' own nested
        # //TR "..." quoting (docs/ARCHITECTURE.md). Every task's action must be
        # exactly "exec python3 <cli> cron <name>" -- no token-file read/export.
        self._run()
        for args in self.calls:
            tr = args[args.index("//TR") + 1]
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", tr)


if __name__ == "__main__":
    unittest.main()
