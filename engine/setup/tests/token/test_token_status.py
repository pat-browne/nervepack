#!/usr/bin/env python3
"""Contract test for np_token_status.py (stdlib unittest, per language policy).
Covers: missing file, fresh token, token inside the rotation window, and the
"token present but issued-date unknown" fail-safe (never silently report ok)."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_token_status  # noqa: E402


class TestTokenStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.token_file = os.path.join(self.tmp, "claude-oauth-token")

    def write_token(self, issued=None):
        with open(self.token_file, "w") as f:
            f.write("dummy-token-value")
        if issued is not None:
            with open(self.token_file + ".issued", "w") as f:
                f.write(issued.strftime("%Y-%m-%d"))

    def test_missing_file_reports_missing(self):
        self.assertEqual(np_token_status.status(self.token_file), "missing")

    def test_empty_file_reports_missing(self):
        open(self.token_file, "w").close()
        self.assertEqual(np_token_status.status(self.token_file), "missing")

    def test_fresh_token_reports_ok(self):
        self.write_token(issued=date.today())
        result = np_token_status.status(self.token_file, today=date.today())
        self.assertTrue(result.startswith("ok "))
        self.assertEqual(int(result.split()[1]), 365)

    def test_token_past_warn_threshold_reports_warn(self):
        # 340 days elapsed of a 365-day TTL / 30-day warn window -> 25 days left, warn.
        self.write_token(issued=date.today() - timedelta(days=340))
        result = np_token_status.status(self.token_file, today=date.today())
        self.assertTrue(result.startswith("warn "))
        self.assertEqual(int(result.split()[1]), 25)

    def test_token_without_issued_sidecar_reports_warn_zero(self):
        self.write_token(issued=None)
        self.assertEqual(np_token_status.status(self.token_file), "warn 0")

    def test_unparsable_issued_sidecar_reports_warn_zero(self):
        self.write_token(issued=None)
        with open(self.token_file + ".issued", "w") as f:
            f.write("not-a-date")
        self.assertEqual(np_token_status.status(self.token_file), "warn 0")

    def test_expired_token_reports_warn_negative(self):
        self.write_token(issued=date.today() - timedelta(days=400))
        result = np_token_status.status(self.token_file, today=date.today())
        self.assertTrue(result.startswith("warn "))
        self.assertLess(int(result.split()[1]), 0)

    def test_custom_ttl_and_warn_days(self):
        self.write_token(issued=date.today() - timedelta(days=10))
        result = np_token_status.status(self.token_file, ttl_days=20, warn_days=5, today=date.today())
        self.assertEqual(result, "ok 10")
        result2 = np_token_status.status(self.token_file, ttl_days=14, warn_days=5, today=date.today())
        self.assertEqual(result2, "warn 4")


class TestTokenStatusCli(unittest.TestCase):
    """Black-box: the CLI wires argv into status() correctly."""

    def test_cli_missing(self):
        out = subprocess.run(
            ["python3", os.path.join(_ENGINE_SETUP, "np_token_status.py"), "/no/such/file"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(out, "missing")

    def test_cli_custom_ttl_flag(self):
        tmp = tempfile.mkdtemp()
        token_file = os.path.join(tmp, "claude-oauth-token")
        with open(token_file, "w") as f:
            f.write("dummy")
        with open(token_file + ".issued", "w") as f:
            f.write((date.today() - timedelta(days=5)).strftime("%Y-%m-%d"))
        out = subprocess.run(
            ["python3", os.path.join(_ENGINE_SETUP, "np_token_status.py"), token_file,
             "--ttl-days", "10", "--warn-days", "5"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(out, "warn 5")


if __name__ == "__main__":
    unittest.main()
