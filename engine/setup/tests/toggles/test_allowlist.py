#!/usr/bin/env python3
"""Port of toggles/test_allowlist.sh (phase 14) — the managed allowlist permission
writes, now np_toggle.install_permissions() / remove_permissions() (90/91-*.sh
ported to stdlib json). Ports the bash remove assertions (managed entries removed,
hand-added rule preserved) and ADDS: install union (append missing, preserve order +
other settings keys) and the fail-safe on a present-but-malformed settings.json
(raise, don't clobber — the phase-13 np_hook lesson). stdlib unittest, zero-dep."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import np_toggle  # noqa: E402


class TestAllowlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.settings = os.path.join(self.tmp, "settings.json")
        self._prev = os.environ.get("CLAUDE_SETTINGS")
        os.environ["CLAUDE_SETTINGS"] = self.settings
        self.entries = np_toggle._read_allowlist()
        self.assertTrue(len(self.entries) >= 2, "allowlist-entries.txt too short for the test")

    def tearDown(self):
        self._tmp.cleanup()
        if self._prev is None:
            os.environ.pop("CLAUDE_SETTINGS", None)
        else:
            os.environ["CLAUDE_SETTINGS"] = self._prev

    def _write(self, obj):
        with open(self.settings, "w") as fh:
            json.dump(obj, fh)

    def _read(self):
        with open(self.settings) as fh:
            return json.load(fh)

    # --- ported bash remove assertions -------------------------------------
    def test_remove_drops_managed_keeps_hand_added(self):
        m1, m2 = self.entries[0], self.entries[1]
        self._write({"permissions": {"allow": [m1, m2, "Bash(my-own-tool:*)"]}})
        np_toggle.remove_permissions()
        allow = self._read()["permissions"]["allow"]
        self.assertIn("Bash(my-own-tool:*)", allow)
        self.assertNotIn(m1, allow)
        self.assertNotIn(m2, allow)

    # --- install union (new) -----------------------------------------------
    def test_install_union_preserves_order_and_other_keys(self):
        self._write({"model": "opus", "hooks": {"x": 1},
                     "permissions": {"allow": [self.entries[0], "Bash(my-own-tool:*)"]}})
        np_toggle.install_permissions()
        data = self._read()
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["hooks"], {"x": 1})
        allow = data["permissions"]["allow"]
        # existing kept in place, at the front
        self.assertEqual(allow[0], self.entries[0])
        self.assertEqual(allow[1], "Bash(my-own-tool:*)")
        # every managed entry present exactly once (union, no dup of the pre-existing one)
        for e in self.entries:
            self.assertIn(e, allow)
        self.assertEqual(allow.count(self.entries[0]), 1)

    def test_install_is_idempotent(self):
        self._write({})
        np_toggle.install_permissions()
        first = self._read()["permissions"]["allow"]
        np_toggle.install_permissions()
        self.assertEqual(self._read()["permissions"]["allow"], first)

    def test_install_creates_missing_settings(self):
        # bash 90 writes {} first; install must produce a valid file with the union.
        self.assertFalse(os.path.exists(self.settings))
        np_toggle.install_permissions()
        allow = self._read()["permissions"]["allow"]
        self.assertEqual(allow, self.entries)

    # --- fail-safe (phase-13 lesson) ---------------------------------------
    def test_install_failsafe_on_malformed_settings(self):
        with open(self.settings, "w") as fh:
            fh.write("{ this is not valid json ")
        with open(self.settings) as fh:
            before = fh.read()
        with self.assertRaises(ValueError):
            np_toggle.install_permissions()
        with open(self.settings) as fh:
            self.assertEqual(fh.read(), before, "malformed settings.json was clobbered")

    def test_remove_noop_when_settings_absent(self):
        self.assertFalse(os.path.exists(self.settings))
        np_toggle.remove_permissions()          # must not raise, must not create
        self.assertFalse(os.path.exists(self.settings))


if __name__ == "__main__":
    unittest.main()
