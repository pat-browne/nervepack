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
        if cmd and cmd[0] == "bash":
            base = os.path.basename(cmd[1])
            if base == "np-doctor.sh":
                return _FakeResult(self.doctor_rc)
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
    # np-doctor.sh must exist for the final verify step
    doc = os.path.join(d, "np-doctor.sh")
    if not os.path.exists(doc):
        with open(doc, "w") as fh:
            fh.write("#!/usr/bin/env bash\nexit 0\n")
    return d


class TestOnboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_runs_every_phase_in_order(self):
        setup_dir = _make_setup_dir(self.tmp, [
            "30-link-skills.sh", "35-link-dashboard-data.sh",
            "61-install-resume-hook.sh",
        ])
        rec = _Recorder()
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        self.assertEqual(rc, 0)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertIn("30-link-skills.sh", basenames)
        self.assertIn("35-link-dashboard-data.sh", basenames)
        self.assertIn("61-install-resume-hook.sh", basenames)
        self.assertIn("np-doctor.sh", basenames)
        # order: link-skills before dashboard-data before hooks before doctor
        self.assertLess(basenames.index("30-link-skills.sh"), basenames.index("35-link-dashboard-data.sh"))
        self.assertLess(basenames.index("61-install-resume-hook.sh"), basenames.index("np-doctor.sh"))

    def test_2_glob_picks_up_5x_and_6x_but_not_70(self):
        setup_dir = _make_setup_dir(self.tmp, [
            "50-install-session-hook.sh", "61-install-resume-hook.sh",
        ])
        # a stray 70-* file must NOT be picked up by the hook-installer glob
        with open(os.path.join(setup_dir, "70-install-memory-cron.sh"), "w") as fh:
            fh.write("exit 0\n")
        rec = _Recorder()
        np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertIn("50-install-session-hook.sh", basenames)
        self.assertIn("61-install-resume-hook.sh", basenames)
        self.assertNotIn("70-install-memory-cron.sh", basenames)

    def test_3_fail_soft_a_failing_step_does_not_abort_the_run(self):
        setup_dir = _make_setup_dir(self.tmp, ["30-link-skills.sh", "35-link-dashboard-data.sh"])
        rec = _Recorder(fail_scripts={"30-link-skills.sh"})
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertIn("35-link-dashboard-data.sh", basenames)
        self.assertIn("np-doctor.sh", basenames)
        self.assertEqual(rc, 0)  # doctor itself succeeded -- that's the return value

    def test_4_missing_step_script_is_skipped_not_fatal(self):
        setup_dir = _make_setup_dir(self.tmp, [])  # neither link script present
        rec = _Recorder()
        rc = np_onboard.run(run_fn=rec, uname_fn=lambda: "Linux", setup_dir=setup_dir)
        self.assertEqual(rc, 0)
        basenames = [os.path.basename(c[1]) for c in rec.calls if c[0] == "bash"]
        self.assertNotIn("30-link-skills.sh", basenames)  # never invoked -- didn't exist

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
