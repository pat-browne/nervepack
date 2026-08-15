#!/usr/bin/env python3
"""Contract test for np-gate-verdict.py (stdlib unittest, per language policy).
F4 in the AI-native compliance epic (#250)."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-gate-verdict.py"))

_spec = importlib.util.spec_from_file_location("gate_verdict", CHK)
gate_verdict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_verdict)


class TestToVerdict(unittest.TestCase):
    def test_success_is_passed(self):
        self.assertEqual(gate_verdict.to_verdict("success"), "PASSED")

    def test_failure_is_failed(self):
        self.assertEqual(gate_verdict.to_verdict("failure"), "FAILED")

    def test_cancelled_is_skipped(self):
        self.assertEqual(gate_verdict.to_verdict("cancelled"), "SKIPPED")

    def test_unknown_status_is_skipped(self):
        self.assertEqual(gate_verdict.to_verdict("something-new"), "SKIPPED")


class TestBuild(unittest.TestCase):
    def test_shape_has_all_five_required_fields_plus_schema(self):
        v = gate_verdict.build("regression", "success", "146 passed", "http://x", "abc123")
        self.assertEqual(v["schema"], gate_verdict.SCHEMA)
        self.assertEqual(v["gate"], "regression")
        self.assertEqual(v["verdict"], "PASSED")
        self.assertEqual(v["reason"], "146 passed")
        self.assertEqual(v["evidence_ref"], "http://x")
        self.assertEqual(v["rules_sha"], "abc123")

    def test_schema_is_versioned_string(self):
        self.assertRegex(gate_verdict.SCHEMA, r"^nervepack\.gate-verdict/\d+$")


class TestCliWritesJson(unittest.TestCase):
    def test_writes_valid_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "verdict.json")
            rc = subprocess.run(
                [sys.executable, CHK,
                 "--gate", "syntax", "--status", "success",
                 "--reason", "clean", "--evidence-ref", "http://run",
                 "--rules-sha", "deadbeef", "--out", out],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            with open(out) as f:
                data = json.load(f)
            self.assertEqual(data["gate"], "syntax")
            self.assertEqual(data["verdict"], "PASSED")

    def test_failure_status_writes_failed_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "verdict.json")
            subprocess.run(
                [sys.executable, CHK,
                 "--gate", "regression", "--status", "failure",
                 "--reason", "3 failed", "--evidence-ref", "http://run",
                 "--rules-sha", "deadbeef", "--out", out],
                check=True,
            )
            with open(out) as f:
                data = json.load(f)
            self.assertEqual(data["verdict"], "FAILED")


if __name__ == "__main__":
    unittest.main()
