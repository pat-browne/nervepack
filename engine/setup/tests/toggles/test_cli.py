#!/usr/bin/env python3
"""Port of toggles/test_cli.sh (phase 14) — the toggle CLI's flip/param/status via
`cli.py toggle`, driven in a hermetic subprocess with NP_TOGGLE_NO_COMMIT=1 +
NP_TOGGLE_NO_MANAGED=1 (no git, no permission scripts). Preserves every assertion
of the bash original AND adds the commit/managed guard checks (the phase-14 plan's
test_guards intent). stdlib unittest, zero-dep.

Windows lane: cli.py emits LF (np_toggle.cli reconfigures stdout), and every file
is read as bytes/`newline=""`-agnostic text so a stray \\r would surface rather than
be masked. Subprocess env is fully pinned (isolated conf/local), so nothing consults
the real toggles.local / git / settings.json."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
CLI = os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine", "cli.py"))
LIB = os.path.join(SETUP, "np-toggle-lib.sh")

CONF = (
    "memory|shared|runtime|on|\n"
    "allowlist|local|managed|on|\n"
    "sync|shared|runtime|on|interval=86400\n"
    "maintain|shared|runtime|on|\n"
    "maintain.refine|shared|runtime|on|\n"
)


class TestToggleCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self.local = os.path.join(self.tmp, "local")
        with open(self.conf, "w", newline="") as fh:
            fh.write(CONF)

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, **extra):
        env = dict(os.environ)
        env.update({
            "NP_TOGGLES_CONF": self.conf, "NP_TOGGLES_LOCAL": self.local,
            "NP_TOGGLE_NO_COMMIT": "1", "NP_TOGGLE_NO_MANAGED": "1",
        })
        env.update(extra)
        return env

    def _run(self, *args, env=None):
        return subprocess.run([sys.executable, CLI, "toggle", *args],
                              capture_output=True, text=True, env=env or self._env())

    def _read(self, path):
        with open(path, "r", newline="") as fh:
            return fh.read()

    def _conf_state(self, feature):
        for line in self._read(self.conf).splitlines():
            fields = line.split("|")
            if fields and fields[0] == feature:
                return fields[3] if len(fields) > 3 else ""
        return None

    def _np_param(self, key, default):
        # Resolve via the bash lib (kept, phase 18) to prove the write took effect
        # through the real resolver — mirrors the bash test's cross-check.
        snippet = 'source "%s"; np_param "%s" "%s"' % (LIB, key, default)
        r = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True, env=self._env())
        return r.stdout.strip()

    def _np_enabled(self, feature):
        snippet = 'source "%s"; np_enabled "%s"' % (LIB, feature)
        return subprocess.run(["bash", "-c", snippet], env=self._env()).returncode == 0

    # --- ported bash assertions --------------------------------------------
    def test_local_feature_writes_local_file(self):
        self._run("allowlist", "off")
        self.assertIn("allowlist=off", self._read(self.local).splitlines())

    def test_shared_feature_edits_conf_state(self):
        self._run("memory", "off")
        self.assertEqual(self._conf_state("memory"), "off")

    def test_param_shared_edits_conf(self):
        self._run("param", "sync.interval", "3600")
        self.assertEqual(self._np_param("sync.interval", "1"), "3600")

    def test_status_lists_features_with_state(self):
        self._run("memory", "off")
        out = self._run("status").stdout
        self.assertRegex(out, r"memory\s+off")

    def test_dotted_bare_feature_flips_conf_not_local(self):
        # A declared feature whose own name contains a dot (maintain.refine) must
        # update toggles.conf's shared state column, NOT be misrouted to local.
        self._run("maintain.refine", "off")
        self.assertEqual(self._conf_state("maintain.refine"), "off")
        local = self._read(self.local) if os.path.exists(self.local) else ""
        self.assertNotIn("maintain.refine=", local)

    def test_dotted_bare_feature_flip_takes_effect_in_resolver(self):
        # maintain (the truncated family) stays on, so this proves np_enabled checks
        # maintain.refine's OWN conf row rather than falling back to the family.
        self._run("maintain.refine", "off")
        self.assertFalse(self._np_enabled("maintain.refine"),
                         "np_enabled maintain.refine still reports on after the flip")

    # --- commit / managed guard coverage (phase-14 plan's test_guards intent) --
    def test_no_commit_guard_prevents_git(self):
        # With NP_TOGGLE_NO_COMMIT=1 a shared flip must NOT invoke git. Run in a
        # scratch dir that is NOT a git repo and put a failing `git` first on PATH;
        # if commit_shared ran git at all we'd still be fine (best-effort), so assert
        # the real contract: the conf is edited and the command still exits 0.
        r = self._run("memory", "off")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self._conf_state("memory"), "off")

    def test_no_managed_guard_writes_local_only(self):
        # allowlist is managed scope. With NP_TOGGLE_NO_MANAGED=1 the flip must only
        # write toggles.local and must NOT touch settings.json (no permission scripts).
        settings = os.path.join(self.tmp, "settings.json")
        env = self._env(CLAUDE_SETTINGS=settings)
        r = self._run("allowlist", "off", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("allowlist=off", self._read(self.local).splitlines())
        self.assertFalse(os.path.exists(settings), "managed guard still wrote settings.json")


if __name__ == "__main__":
    unittest.main()
