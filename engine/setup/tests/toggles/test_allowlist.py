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
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

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

    def test_remove_failsafe_on_malformed_settings(self):
        # Symmetric to install's fail-safe: a present-but-malformed settings.json
        # must be preserved, not clobbered (the phase-13 np_hook lesson).
        with open(self.settings, "w") as fh:
            fh.write("{ this is not valid json ")
        with open(self.settings) as fh:
            before = fh.read()
        with self.assertRaises(ValueError):
            np_toggle.remove_permissions()
        with open(self.settings) as fh:
            self.assertEqual(fh.read(), before, "malformed settings.json was clobbered by remove")

    def test_remove_noop_when_settings_absent(self):
        self.assertFalse(os.path.exists(self.settings))
        np_toggle.remove_permissions()          # must not raise, must not create
        self.assertFalse(os.path.exists(self.settings))


class TestFlipRoutesToManaged(unittest.TestCase):
    """`cli.py toggle allowlist on` must actually install the entries.

    It did not, and never had: flip() looked for "managed" in the SCOPE column
    while toggles.conf declares `allowlist|local|managed|on|` — local scope,
    managed enforcement, exactly as that file's own header documents. So
    install_permissions() had no production caller and the entries reached only
    a machine where someone ran it by hand. The tests above call it directly,
    which is why a green suite never showed the gap.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.settings = os.path.join(self.tmp, "settings.json")
        self.local = os.path.join(self.tmp, "toggles.local")
        self.conf = os.path.join(self.tmp, "toggles.conf")
        # NP_TOGGLES_CONF matters as much as NP_TOGGLES_LOCAL here. flip() on a
        # SHARED family writes set_conf_state() straight into the committed
        # toggles.conf, so a test that isolates only the local file mutates the
        # repo -- which is exactly how `focus` was flipped off in the first draft
        # of this class. Copy the real manifest so scope/enforce lookups still
        # resolve, then let every write land on the copy.
        self.real_conf = np_toggle._conf_path()
        with open(self.real_conf, encoding="utf-8") as fh:
            self.conf_before = fh.read()
        with open(self.conf, "w", encoding="utf-8") as fh:
            fh.write(self.conf_before)
        self._prev = {k: os.environ.get(k)
                      for k in ("CLAUDE_SETTINGS", "NP_TOGGLES_LOCAL",
                                "NP_TOGGLES_CONF", "NP_TOGGLES_CONTENT")}
        os.environ["CLAUDE_SETTINGS"] = self.settings
        os.environ["NP_TOGGLES_LOCAL"] = self.local
        os.environ["NP_TOGGLES_CONF"] = self.conf
        os.environ["NP_TOGGLES_CONTENT"] = ""      # pin "no content layer"
        self.entries = np_toggle._read_allowlist()

    def tearDown(self):
        with open(self.real_conf, encoding="utf-8") as fh:
            after = fh.read()
        self._tmp.cleanup()
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.assertEqual(self.conf_before, after,
                         "a test in this class wrote to the committed toggles.conf")

    def _allow(self):
        with open(self.settings) as fh:
            return json.load(fh)["permissions"]["allow"]

    def test_flip_on_installs_the_entries(self):
        np_toggle.flip("allowlist", "on")
        self.assertEqual(sorted(self._allow()), sorted(self.entries))

    def test_flip_on_still_writes_the_local_state(self):
        np_toggle.flip("allowlist", "on")
        with open(self.local) as fh:
            self.assertIn("allowlist=on", fh.read())

    def test_flip_off_removes_the_entries(self):
        np_toggle.flip("allowlist", "on")
        np_toggle.flip("allowlist", "off")
        self.assertEqual(self._allow(), [])

    def test_flip_off_keeps_a_hand_added_rule(self):
        np_toggle.flip("allowlist", "on")
        data = json.load(open(self.settings))
        data["permissions"]["allow"].append("Bash(mine *)")
        with open(self.settings, "w") as fh:
            json.dump(data, fh)
        np_toggle.flip("allowlist", "off")
        self.assertEqual(self._allow(), ["Bash(mine *)"])

    def test_a_runtime_family_does_not_touch_permissions(self):
        np_toggle.flip("focus", "off")
        self.assertFalse(os.path.exists(self.settings))


class TestSpecAndPlanPathsAreAllowlisted(unittest.TestCase):
    """The six entries that stop a spec or plan write raising a dialog. They are
    the whole of Part A of change spec 0027; a silent deletion would restore the
    prompt with nothing failing."""

    def test_every_record_directory_is_covered_for_write_and_edit(self):
        entries = set(np_toggle._read_allowlist())
        for d in ("docs/superpowers/specs", "docs/superpowers/plans",
                  "change-specs"):
            for tool in ("Write", "Edit"):
                self.assertIn("%s(~/Code/**/%s/**)" % (tool, d), entries)


if __name__ == "__main__":
    unittest.main()
