"""Tests for np_onboard -- the Python port of np-onboard.sh, the full-onboard
orchestrator (phase 7 of the bash->Python migration). Translates every case
the retired test_np_onboard.sh covered: reaches every phase, is fail-soft (a
failing step doesn't abort the run), the doctor's exit code is the return
value, and dispatches the right OS-specific scheduler step.
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_onboard  # noqa: E402


class _FakeResult:
    def __init__(self, returncode=0):
        self.returncode = returncode


class _Recorder:
    def __init__(self, doctor_rc=0, fail_scripts=()):
        self.calls = []
        self.doctor_rc = doctor_rc
        self.fail_scripts = set(fail_scripts)

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        # The final verify step is now the in-process Python doctor via
        # `cli.py doctor` (phase 15; np-doctor.sh retired), not a bash script.
        if cmd and cmd[-1] == "doctor":
            return _FakeResult(self.doctor_rc)
        if cmd and cmd[0] == "bash":
            base = os.path.basename(cmd[1])
            if base in self.fail_scripts:
                return _FakeResult(1)
        return _FakeResult(0)


def _make_setup_dir(tmp, scripts):
    d = os.path.join(tmp, "setup")
    os.makedirs(d, exist_ok=True)
    for name in scripts:
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\nexit 0\n")
        os.chmod(path, 0o755)
    # The final verify step is `cli.py doctor` (in-process Python), no script needed.
    return d


class TestOnboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_runs_every_phase_in_order(self):
        # 58-install-mcp.sh is a REMAINING non-hook installer picked up by the
        # step-2b glob; the lifecycle hooks are a single `cli.py setup install-hooks`
        # dispatch (phase 13), and link-skills is now `cli.py setup link-skills`
        # (phase 17: 30-link-skills.sh retired), not per-installer bash scripts.
        setup_dir = _make_setup_dir(self.tmp, [
            "58-install-mcp.sh",
        ])
        rec = _Recorder()
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        self.assertEqual(rc, 0)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertIn("58-install-mcp.sh", basenames)
        # link-skills + link-dashboard-data + install-hooks + doctor are cli.py
        # dispatches, not bash scripts.
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("link-skills" in c for c in cli_calls))
        self.assertTrue(any("link-dashboard-data" in c for c in cli_calls))
        self.assertTrue(any("install-hooks" in c for c in cli_calls))
        self.assertTrue(any(c[-1] == "doctor" for c in cli_calls))

        def _idx(pred):
            return next(i for i, c in enumerate(rec.calls) if pred(c))

        link_skills_idx = _idx(lambda c: c[0] != "bash" and "link-skills" in c)
        dashboard_idx = _idx(lambda c: c[0] != "bash" and "link-dashboard-data" in c)
        hooks_idx = _idx(lambda c: c[0] != "bash" and "install-hooks" in c)
        doctor_idx = _idx(lambda c: c[-1] == "doctor")
        # order: link-skills < dashboard-data < install-hooks < doctor
        self.assertLess(link_skills_idx, dashboard_idx)
        self.assertLess(dashboard_idx, hooks_idx)
        self.assertLess(hooks_idx, doctor_idx)

    def test_2_glob_picks_up_remaining_non_hook_installers_but_not_70(self):
        # Post-phase-13 the step-2b glob covers only the REMAINING non-hook 5x/6x
        # installers (58-install-mcp.sh, 62-install-scheduled-auth-token.sh); it
        # must still exclude the platform-specific 70-install-memory-* installers.
        setup_dir = _make_setup_dir(self.tmp, [
            "58-install-mcp.sh", "62-install-scheduled-auth-token.sh",
        ])
        with open(os.path.join(setup_dir, "70-install-memory-cron.sh"), "w") as fh:
            fh.write("exit 0\n")
        rec = _Recorder()
        np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertIn("58-install-mcp.sh", basenames)
        self.assertIn("62-install-scheduled-auth-token.sh", basenames)
        self.assertNotIn("70-install-memory-cron.sh", basenames)
        # hooks come via the cli dispatch, not the glob
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("install-hooks" in c for c in cli_calls))

    def test_3_fail_soft_a_failing_step_does_not_abort_the_run(self):
        # A failing bash installer (58-install-mcp.sh, picked up by the step-2b glob)
        # must warn-and-continue, not abort the run.
        setup_dir = _make_setup_dir(self.tmp, ["58-install-mcp.sh"])
        rec = _Recorder(fail_scripts={"58-install-mcp.sh"})
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("link-dashboard-data" in c for c in cli_calls))
        self.assertTrue(any(c[-1] == "doctor" for c in cli_calls))
        self.assertEqual(rc, 0)  # doctor itself succeeded -- that's the return value

    def test_4_missing_step_script_is_skipped_not_fatal(self):
        setup_dir = _make_setup_dir(self.tmp, [])  # no bash installer scripts present
        rec = _Recorder()
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        self.assertEqual(rc, 0)
        # link-skills is a cli.py dispatch (phase 17), always run — never a bash script.
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("link-skills" in c for c in cli_calls))
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertNotIn("30-link-skills.sh", basenames)  # retired -- never a bash step

    def test_5_doctor_exit_code_is_the_return_value(self):
        setup_dir = _make_setup_dir(self.tmp, [])
        rec = _Recorder(doctor_rc=1)
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        self.assertEqual(rc, 1)

    def test_6_darwin_dispatches_launchd_step(self):
        setup_dir = _make_setup_dir(self.tmp, [])
        rec = _Recorder()
        np_onboard.run(run_fn=rec, uname_fn=lambda: "Darwin", setup_dir=setup_dir)
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("install-memory-launchd" in c for c in cli_calls))

    def test_7_windows_kernel_dispatches_schtasks_step(self):
        setup_dir = _make_setup_dir(self.tmp, [])
        rec = _Recorder()
        np_onboard.run(run_fn=rec, uname_fn=lambda: "MINGW64_NT-10.0", setup_dir=setup_dir)
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("install-memory-schtasks" in c for c in cli_calls))

    def test_8_linux_dispatches_cron_step(self):
        setup_dir = _make_setup_dir(self.tmp, [])
        rec = _Recorder()
        np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        cli_calls = [c for c in rec.calls if c[0] != "bash"]
        self.assertTrue(any("install-memory-cron" in c for c in cli_calls))


if __name__ == "__main__":
    unittest.main()
