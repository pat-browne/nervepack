"""Tests for np_bootstrap -- the Python port of the one-time toolchain-baseline
bootstrap scripts (phase 7 of the bash->Python migration): install-apt-baseline,
install-brew-baseline, install-rustup, install-claude-plugins, prewarm-serena,
install-pii-deps, install-vscode-extensions. The bash originals had no dedicated
tests (only a syntax/portability scan) -- this is new coverage, not a port of
existing cases, verified via the injectable run_fn/which_fn seams so no real
apt/brew/rustup/claude/code/pip installation is ever touched.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_bootstrap  # noqa: E402


class _FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class _Recorder:
    """Fake run_fn: records every invocation, returns a canned/queued result."""

    def __init__(self, default_returncode=0):
        self.calls = []
        self.default_returncode = default_returncode
        self._returns = {}

    def fail(self, cmd0, returncode=1):
        self._returns[cmd0] = returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        rc = self._returns.get(cmd[0] if cmd else None, self.default_returncode)
        return _FakeResult(returncode=rc, stdout="1.2.3\n")


class TestInstallAptBaseline(unittest.TestCase):
    def test_1_no_sudo_fails_open_with_nonzero(self):
        rc = np_bootstrap.install_apt_baseline(which_fn=lambda n: None)
        self.assertEqual(rc, 1)

    def test_2_installs_the_full_package_list(self):
        rec = _Recorder()
        rc = np_bootstrap.install_apt_baseline(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        self.assertEqual(rc, 0)
        install_call = next(c for c in rec.calls if c[:3] == ["sudo", "apt", "install"])
        for pkg in ("git", "gh", "jq", "nodejs", "npm", "golang-go", "build-essential", "cron"):
            self.assertIn(pkg, install_call)

    def test_3_runs_apt_update_before_install(self):
        rec = _Recorder()
        np_bootstrap.install_apt_baseline(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        update_idx = rec.calls.index(["sudo", "apt", "update"])
        install_idx = next(i for i, c in enumerate(rec.calls) if c[:3] == ["sudo", "apt", "install"])
        self.assertLess(update_idx, install_idx)


class TestInstallBrewBaseline(unittest.TestCase):
    def test_1_no_brew_fails_open_with_nonzero(self):
        rc = np_bootstrap.install_brew_baseline(which_fn=lambda n: None)
        self.assertEqual(rc, 1)

    def test_2_installs_expected_formulas_and_uv_python(self):
        rec = _Recorder()
        rc = np_bootstrap.install_brew_baseline(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        self.assertEqual(rc, 0)
        brew_call = next(c for c in rec.calls if c[:2] == ["brew", "install"])
        for formula in ("gh", "jq", "node", "go", "uv"):
            self.assertIn(formula, brew_call)
        self.assertIn(["uv", "python", "install"], rec.calls)
        # python is deliberately NOT brewed
        self.assertNotIn("python", brew_call)
        self.assertNotIn("python3", brew_call)

    def test_3_missing_git_triggers_xcode_select(self):
        rec = _Recorder()
        which = {"brew": "/opt/homebrew/bin/brew"}
        np_bootstrap.install_brew_baseline(run_fn=rec, which_fn=lambda n: which.get(n))
        self.assertIn(["xcode-select", "--install"], rec.calls)

    def test_4_git_present_skips_xcode_select(self):
        rec = _Recorder()
        np_bootstrap.install_brew_baseline(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        self.assertNotIn(["xcode-select", "--install"], rec.calls)


class TestInstallRustup(unittest.TestCase):
    def test_1_already_installed_is_idempotent_no_op(self):
        rec = _Recorder()
        install_calls = []
        rc = np_bootstrap.install_rustup(
            run_fn=rec, which_fn=lambda n: "/usr/bin/rustup" if n == "rustup" else None,
            install_fn=lambda: install_calls.append(True))
        self.assertEqual(rc, 0)
        self.assertEqual(install_calls, [])

    def test_2_absent_invokes_install_fn_then_checks_versions(self):
        rec = _Recorder()
        install_calls = []
        rc = np_bootstrap.install_rustup(
            run_fn=rec, which_fn=lambda n: None,
            install_fn=lambda: install_calls.append(True))
        self.assertEqual(rc, 0)
        self.assertEqual(len(install_calls), 1)
        self.assertIn(["rustc", "--version"], rec.calls)
        self.assertIn(["cargo", "--version"], rec.calls)


class TestInstallClaudePlugins(unittest.TestCase):
    def test_1_no_claude_cli_fails_open(self):
        rc = np_bootstrap.install_claude_plugins(which_fn=lambda n: "/usr/bin/git" if n == "git" else None)
        self.assertEqual(rc, 1)

    def test_2_no_git_fails_open(self):
        rc = np_bootstrap.install_claude_plugins(which_fn=lambda n: "/usr/bin/claude" if n == "claude" else None)
        self.assertEqual(rc, 1)

    def test_3_installs_every_plugin_and_disables_default_off(self):
        rec = _Recorder()
        rc = np_bootstrap.install_claude_plugins(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        self.assertEqual(rc, 0)
        installs = [c for c in rec.calls if c[1:3] == ["plugin", "install"]]
        self.assertTrue(any("superpowers@claude-plugins-official" in c for c in installs))
        self.assertTrue(any("serena@claude-plugins-official" in c for c in installs))
        disables = [c for c in rec.calls if c[1:3] == ["plugin", "disable"]]
        self.assertTrue(any("serena@claude-plugins-official" in c for c in disables))

    def test_4_a_failed_install_is_reported_nonzero(self):
        rec = _Recorder()
        rec.fail("claude", returncode=1)
        rc = np_bootstrap.install_claude_plugins(run_fn=rec, which_fn=lambda n: "/usr/bin/" + n)
        self.assertEqual(rc, 1)


class TestPrewarmSerena(unittest.TestCase):
    def test_1_no_uvx_fails_open(self):
        rc = np_bootstrap.prewarm_serena(which_fn=lambda n: None)
        self.assertEqual(rc, 1)

    def test_2_invokes_the_exact_serena_source(self):
        rec = _Recorder()
        rc = np_bootstrap.prewarm_serena(run_fn=rec, which_fn=lambda n: "/usr/bin/uvx")
        self.assertEqual(rc, 0)
        self.assertIn(["uvx", "--from", "git+https://github.com/oraios/serena", "serena", "--help"], rec.calls)

    def test_2b_success_message_is_spelled_correctly(self):
        buf = io.StringIO()
        rec = _Recorder()
        with contextlib.redirect_stdout(buf):
            np_bootstrap.prewarm_serena(run_fn=rec, which_fn=lambda n: "/usr/bin/uvx")
        self.assertIn("Serena pre-warmed", buf.getvalue())

    def test_3_uvx_failure_reported_nonzero(self):
        rec = _Recorder(default_returncode=1)
        rc = np_bootstrap.prewarm_serena(run_fn=rec, which_fn=lambda n: "/usr/bin/uvx")
        self.assertEqual(rc, 1)


class TestInstallPiiDeps(unittest.TestCase):
    def test_1_installs_presidio_then_spacy_model(self):
        rec = _Recorder()
        rc = np_bootstrap.install_pii_deps(run_fn=rec)
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[1:4] == ["-m", "pip", "install"] and "presidio-analyzer" in c for c in rec.calls))
        self.assertTrue(any(c[1:4] == ["-m", "spacy", "download"] and "en_core_web_lg" in c for c in rec.calls))

    def test_2_pip_failure_short_circuits_nonzero(self):
        rec = _Recorder()
        rec.fail(sys.executable, returncode=1)
        rc = np_bootstrap.install_pii_deps(run_fn=rec)
        self.assertEqual(rc, 1)
        # spacy download must not run if pip install already failed
        self.assertFalse(any("spacy" in c for c in rec.calls))


class TestInstallVscodeExtensions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.settings_path = os.path.join(self.tmp, "Code", "User", "settings.json")

    def test_1_no_code_cli_fails_open(self):
        rc = np_bootstrap.install_vscode_extensions(which_fn=lambda n: None)
        self.assertEqual(rc, 1)

    def test_2_installs_every_extension(self):
        rec = _Recorder()
        rc = np_bootstrap.install_vscode_extensions(
            run_fn=rec, which_fn=lambda n: "/usr/bin/code", settings_path=self.settings_path)
        self.assertEqual(rc, 0)
        exts = [c[2] for c in rec.calls if c[:2] == ["code", "--install-extension"]]
        for e in ("anthropic.claude-code", "ms-python.python", "rust-lang.rust-analyzer"):
            self.assertIn(e, exts)

    def test_3_writes_settings_json_when_missing(self):
        rec = _Recorder()
        np_bootstrap.install_vscode_extensions(
            run_fn=rec, which_fn=lambda n: "/usr/bin/code", settings_path=self.settings_path)
        self.assertTrue(os.path.isfile(self.settings_path))
        with open(self.settings_path) as fh:
            content = fh.read()
        self.assertIn('"editor.formatOnSave": true', content)

    def test_4_does_not_clobber_existing_settings_json(self):
        os.makedirs(os.path.dirname(self.settings_path))
        with open(self.settings_path, "w") as fh:
            fh.write('{"my.custom.setting": true}')
        rec = _Recorder()
        np_bootstrap.install_vscode_extensions(
            run_fn=rec, which_fn=lambda n: "/usr/bin/code", settings_path=self.settings_path)
        with open(self.settings_path) as fh:
            self.assertIn("my.custom.setting", fh.read())

    def test_5_a_failed_extension_install_is_reported_nonzero(self):
        rec = _Recorder()
        rec.fail("code", returncode=1)
        rc = np_bootstrap.install_vscode_extensions(
            run_fn=rec, which_fn=lambda n: "/usr/bin/code", settings_path=self.settings_path)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
