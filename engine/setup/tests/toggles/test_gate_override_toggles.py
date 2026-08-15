#!/usr/bin/env python3
"""Unit tests for the gate-override toggle family (#259/F12): three params on a
new `gates` feature — spec_guard.enforce, drift_guard.enforce, tier_guard.enforce
— resolved by the existing np_toggle.param()/toggle-schema.json machinery, the
same shape lessons.enforce already uses (lesson_guard.py). Mirrors
test_np_toggle_params.py's hermetic env-var-override pattern.

Scope: this only proves the toggles resolve correctly and are dashboard-editable
(schema present). No hook consumes them yet - #249 (drift-guard) and #254
(tier-guard) wire the actual block-vs-warn-plus-log behavior when built, reading
these same keys the way lesson_guard.py already reads lessons.enforce."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)


def _load_np_toggle():
    spec = importlib.util.spec_from_file_location(
        "np_toggle", os.path.join(SETUP, "..", "nervepack_engine", "np_toggle.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


np_toggle = _load_np_toggle()

GATE_KEYS = (
    "gates.spec_guard.enforce",
    "gates.drift_guard.enforce",
    "gates.tier_guard.enforce",
)


class TestGateOverrideResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.tmp.name, "toggles.conf")
        self.local = os.path.join(self.tmp.name, "toggles.local")
        with open(self.conf, "w", newline="") as fh:
            fh.write(
                "gates|shared|runtime|on|"
                "spec_guard.enforce=on,drift_guard.enforce=on,tier_guard.enforce=on\n"
            )
        self._prev_conf = os.environ.get("NP_TOGGLES_CONF")
        self._prev_local = os.environ.get("NP_TOGGLES_LOCAL")
        os.environ["NP_TOGGLES_CONF"] = self.conf
        os.environ["NP_TOGGLES_LOCAL"] = self.local

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in (("NP_TOGGLES_CONF", self._prev_conf), ("NP_TOGGLES_LOCAL", self._prev_local)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_defaults_to_on_from_conf(self):
        for key in GATE_KEYS:
            self.assertEqual(np_toggle.param(key, "on"), "on")

    def test_local_override_flips_one_gate_to_off(self):
        with open(self.local, "w", newline="") as fh:
            fh.write("gates.drift_guard.enforce=off\n")
        self.assertEqual(np_toggle.param("gates.drift_guard.enforce", "on"), "off")
        # the other two gates are unaffected by an override on one
        self.assertEqual(np_toggle.param("gates.spec_guard.enforce", "on"), "on")
        self.assertEqual(np_toggle.param("gates.tier_guard.enforce", "on"), "on")

    def test_missing_conf_row_falls_back_to_default_arg(self):
        with open(self.conf, "w", newline="") as fh:
            fh.write("directive|shared|runtime|on|\n")
        self.assertEqual(np_toggle.param("gates.spec_guard.enforce", "on"), "on")


class TestGateOverrideSchema(unittest.TestCase):
    """The dashboard settings panel renders a control for a key only when
    toggle-schema.json has an entry for it (np_toggle_schema.load()) - a param
    with no schema entry renders read-only. These three must be editable."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(SETUP, "toggle-schema.json")
        with open(path) as fh:
            cls.schema = json.load(fh)

    def test_all_three_gate_keys_have_a_schema_entry(self):
        for key in GATE_KEYS:
            self.assertIn(key, self.schema, "%s missing from toggle-schema.json" % key)

    def test_schema_entries_are_bool_with_a_description(self):
        for key in GATE_KEYS:
            entry = self.schema[key]
            self.assertEqual(entry.get("type"), "bool")
            self.assertTrue(entry.get("description"), "%s has no description" % key)


if __name__ == "__main__":
    unittest.main()
