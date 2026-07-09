#!/usr/bin/env python3
"""Unit tests for np_toggle_schema.py (stdlib unittest, direct import). Schema
loading and per-type validation are pure functions — no server/subprocess needed."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "..", "..")
sys.path.insert(0, SETUP)
import np_toggle_schema  # noqa: E402


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "toggle-schema.json")
        with open(self.path, "w") as fh:
            json.dump({
                "evaluator.dashboard_port": {"type": "number", "min": 1024, "max": 65535, "description": "x"},
                "evaluator.implement_mode": {"type": "enum", "options": ["pr", "direct"], "description": "x"},
                "lessons.enforce": {"type": "bool", "description": "x"},
                "team.merge": {"type": "enum", "options": ["override", "concatenate", "team-only"], "description": "x"},
            }, fh)
        self._prev = os.environ.get("NP_TOGGLE_SCHEMA")
        os.environ["NP_TOGGLE_SCHEMA"] = self.path

    def tearDown(self):
        self.tmp.cleanup()
        if self._prev is None:
            os.environ.pop("NP_TOGGLE_SCHEMA", None)
        else:
            os.environ["NP_TOGGLE_SCHEMA"] = self._prev

    def test_load_returns_parsed_dict(self):
        schema = np_toggle_schema.load()
        self.assertEqual(schema["lessons.enforce"]["type"], "bool")

    def test_load_missing_file_is_empty_not_a_crash(self):
        os.environ["NP_TOGGLE_SCHEMA"] = os.path.join(self.tmp.name, "nope.json")
        self.assertEqual(np_toggle_schema.load(), {})

    def test_validate_no_schema_entry(self):
        valid, coerced, error = np_toggle_schema.validate("memory.cap_bytes", "48000")
        self.assertFalse(valid)
        self.assertIsNone(coerced)
        self.assertEqual(error, "no schema entry")

    def test_validate_bool_ok(self):
        valid, coerced, error = np_toggle_schema.validate("lessons.enforce", "on")
        self.assertTrue(valid)
        self.assertIs(coerced, True)
        self.assertIsNone(error)

    def test_validate_bool_rejects_non_on_off(self):
        valid, coerced, error = np_toggle_schema.validate("lessons.enforce", "yes")
        self.assertFalse(valid)
        self.assertIn("on/off", error)

    def test_validate_number_ok(self):
        valid, coerced, error = np_toggle_schema.validate("evaluator.dashboard_port", "8787")
        self.assertTrue(valid)
        self.assertEqual(coerced, 8787)

    def test_validate_number_rejects_non_numeric(self):
        valid, coerced, error = np_toggle_schema.validate("evaluator.dashboard_port", "abc")
        self.assertFalse(valid)
        self.assertIn("number", error)

    def test_validate_number_enforces_min(self):
        valid, coerced, error = np_toggle_schema.validate("evaluator.dashboard_port", "80")
        self.assertFalse(valid)
        self.assertIn("min", error)

    def test_validate_number_enforces_max(self):
        valid, coerced, error = np_toggle_schema.validate("evaluator.dashboard_port", "70000")
        self.assertFalse(valid)
        self.assertIn("max", error)

    def test_validate_enum_ok(self):
        valid, coerced, error = np_toggle_schema.validate("evaluator.implement_mode", "direct")
        self.assertTrue(valid)
        self.assertEqual(coerced, "direct")

    def test_validate_enum_rejects_out_of_range(self):
        valid, coerced, error = np_toggle_schema.validate("team.merge", "clobber")
        self.assertFalse(valid)
        self.assertIn("one of", error)


if __name__ == "__main__":
    unittest.main()
