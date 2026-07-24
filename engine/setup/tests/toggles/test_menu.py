#!/usr/bin/env python3
"""Port of toggles/test_menu.sh + test_menu_invalid.sh (phase 14) — the interactive
picker, now `cli.py toggle menu`, driven by feeding stdin. Happy path: number flips
that feature in-process; 's'/'q' quit. Failure path: invalid / out-of-range / empty
input is ignored (loop continues) and flips nothing. Preserves every assertion of
both bash originals. stdlib unittest, zero-dep."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
CLI = os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine", "cli.py"))

CONF = "memory|shared|runtime|on|\nplaybooks|shared|runtime|on|\n"


class TestToggleMenu(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self.local = os.path.join(self.tmp, "local")
        with open(self.conf, "w", newline="") as fh:
            fh.write(CONF)

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        env = dict(os.environ)
        env.update({"NP_TOGGLES_CONF": self.conf, "NP_TOGGLES_LOCAL": self.local,
                    "NP_TOGGLE_NO_COMMIT": "1"})
        return env

    def _feed(self, stdin):
        return subprocess.run([sys.executable, CLI, "toggle", "menu"], input=stdin,
                              capture_output=True, text=True, env=self._env())

    def _read(self, path):
        with open(path, "r", newline="") as fh:
            return fh.read()

    def _conf_state(self, feature):
        for line in self._read(self.conf).splitlines():
            fields = line.split("|")
            if fields and fields[0] == feature:
                return fields[3] if len(fields) > 3 else ""
        return None

    def test_number_flips_feature_then_save(self):
        # toggle item 1 (memory), then save+quit
        self._feed("1\ns\n")
        self.assertEqual(self._conf_state("memory"), "off")

    def test_invalid_input_flips_nothing(self):
        before = self._read(self.conf)
        # 'x' (non-numeric), '99' (out of range), '0' (index -1), empty line, then 'q'
        self._feed("x\n99\n0\n\nq\n")
        self.assertEqual(self._read(self.conf), before, "invalid input mutated toggles.conf")
        self.assertEqual(self._conf_state("memory"), "on")
        self.assertEqual(self._conf_state("playbooks"), "on")
        # No local override should have been created for an invalid choice.
        self.assertFalse(os.path.exists(self.local) and os.path.getsize(self.local) > 0,
                         "a local override was written for an invalid choice")


if __name__ == "__main__":
    unittest.main()
