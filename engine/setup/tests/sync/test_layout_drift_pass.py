#!/usr/bin/env python3
# np-test: sync | happy+failure
"""np_sync runs np_layout.apply_drift on every content layer after the validity
check: a clear new directory gets a route recorded and a stderr line, a mixed one
prints a layout question, and sync.layout_drift=off skips the pass."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_PY = os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine", "np_sync.py"))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class LayoutDriftPass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.team = os.path.join(self.tmp, "team")
        os.makedirs(os.path.join(self.home, ".config", "nervepack"))
        os.makedirs(os.path.join(self.tmp, "notgit"))
        self.local = os.path.join(self.home, ".config", "nervepack", "toggles.local")
        _write(self.local, "team=on\n")
        _write(os.path.join(self.team, ".nervepack", "layout.json"), json.dumps(
            {"schema": 1, "routes": {"knowledge": {"path": "docs/systems/{name}.md"}}}))
        _write(os.path.join(self.team, "docs", "plans", "a.md"), "---\ntype: plan\n---\n")
        _write(os.path.join(self.team, "docs", "mixed", "a.md"), "---\ntype: a\n---\n")
        _write(os.path.join(self.team, "docs", "mixed", "b.md"), "---\ntype: b\n---\n")

    def _run(self):
        env = dict(os.environ, HOME=self.home,
                   NP_TOGGLES_CONF=os.path.join(_SETUP, "toggles.conf"),
                   NP_TOGGLES_LOCAL=self.local, NP_TEAM_DIR=self.team,
                   NP_SYNC_TARGET=os.path.join(self.tmp, "notgit"),
                   NP_SYNC_STATUS=os.path.join(self.tmp, "status"),
                   NP_SYNC_STAMP=os.path.join(self.tmp, "stamp"))
        return subprocess.run(["python3", _PY, "exit"], capture_output=True,
                              text=True, env=env)

    def _layout(self):
        with open(os.path.join(self.team, ".nervepack", "layout.json")) as fh:
            return json.load(fh)

    def test_records_clear_dir_and_reports_mixed(self):
        res = self._run()
        self.assertIn("layout drift:", res.stderr)
        self.assertIn("docs/plans/", res.stderr)
        self.assertIn("layout question:", res.stderr)
        self.assertIn("docs/mixed/", res.stderr)
        paths = [v["path"] for v in self._layout()["routes"]["knowledge"]["variants"]]
        self.assertIn("docs/plans/{name}.md", paths)

    def test_param_off_skips_the_pass(self):
        with open(self.local, "a") as fh:
            fh.write("sync.layout_drift=off\n")
        res = self._run()
        self.assertNotIn("layout drift:", res.stderr)
        self.assertNotIn("variants", self._layout()["routes"]["knowledge"])


if __name__ == "__main__":
    unittest.main()
