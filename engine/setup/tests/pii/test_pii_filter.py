#!/usr/bin/env python3
"""Unit tests for np-pii-filter.py — stdlib unittest, no external deps."""
import importlib.util
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILTER = os.path.join(HERE, "..", "..", "np-pii-filter.py")


def _run(text: str, mode: str = "fast") -> tuple:
    result = subprocess.run(
        [sys.executable, FILTER, "--mode", mode],
        input=text.encode(),
        capture_output=True,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def _load_filter():
    spec = importlib.util.spec_from_file_location("np_pii_filter", FILTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFastModeRegex(unittest.TestCase):
    def test_email(self):
        out, _, rc = _run("contact user@example.com today")
        self.assertEqual(rc, 0)
        self.assertIn("[EMAIL]", out)
        self.assertNotIn("user@example.com", out)

    def test_phone_us(self):
        out, _, _ = _run("call 415-555-1234 now")
        self.assertIn("[PHONE]", out)
        self.assertNotIn("415-555-1234", out)

    def test_phone_us_parenthesized(self):
        out, _, _ = _run("call (415) 555-1234 now")
        self.assertIn("[PHONE]", out)
        self.assertNotIn("(415) 555-1234", out)

    def test_ssn(self):
        out, _, _ = _run("ssn is 123-45-6789")
        self.assertIn("[SSN]", out)
        self.assertNotIn("123-45-6789", out)

    def test_private_ip_192(self):
        out, _, _ = _run("server 192.168.1.100 is down")
        self.assertIn("[IP]", out)
        self.assertNotIn("192.168.1.100", out)

    def test_private_ip_10(self):
        out, _, _ = _run("host 10.0.0.1")
        self.assertIn("[IP]", out)
        self.assertNotIn("10.0.0.1", out)

    def test_private_ip_172(self):
        out, _, _ = _run("host 172.16.0.5")
        self.assertIn("[IP]", out)
        self.assertNotIn("172.16.0.5", out)

    def test_public_ip_not_redacted(self):
        out, _, _ = _run("server 8.8.8.8")
        self.assertNotIn("[IP]", out)
        self.assertIn("8.8.8.8", out)

    def test_unix_path_users(self):
        out, _, _ = _run("file at /Users/alice/code/proj/main.py")
        self.assertIn("[PATH]", out)
        self.assertNotIn("/Users/alice/", out)

    def test_unix_path_home(self):
        out, _, _ = _run("config in /home/bob/.bashrc")
        self.assertIn("[PATH]", out)
        self.assertNotIn("/home/bob/", out)

    def test_api_token_sk(self):
        out, _, _ = _run("key sk-ABCDEFGHIJKLMNOPQRSTUVWX end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("sk-ABCDEFG", out)

    def test_bearer_token(self):
        out, _, _ = _run("header Bearer abcdef123456ghijklmno end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("abcdef123456ghijklmno", out)

    def test_api_token_github(self):
        out, _, _ = _run("key " + "ghp_" + "ABCDEFGHIJKLMNOPQRSTU" + " end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("ghp_ABCDEFG", out)

    def test_api_token_github_pat(self):
        out, _, _ = _run("key " + "github_pat_" + "0123456789ABCDEFGHIJklmnopqrstuvwx" + " end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("github_pat_0123", out)

    def test_api_token_aws(self):
        out, _, _ = _run("key " + "AKIA" + "0123456789ABCDEF" + " end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("AKIA0123", out)

    def test_api_token_slack(self):
        out, _, _ = _run("key " + "xoxb-" + "abcdefghij-klmnopqrstu" + " end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("xoxb-abcdefghij", out)

    def test_clean_text_unchanged(self):
        out, _, _ = _run("just normal text about oauth flow")
        self.assertEqual(out, "just normal text about oauth flow")

    def test_placeholder_not_re_replaced(self):
        # Already-substituted placeholders must not be mangled
        text = "[EMAIL] is safe [PHONE] and [IP] too"
        out, _, _ = _run(text)
        self.assertEqual(out, text)

    def test_exits_zero(self):
        _, _, rc = _run("any text")
        self.assertEqual(rc, 0)


class TestFullModeNoPrecidio(unittest.TestCase):
    """Full mode without Presidio installed falls back to regex-only and warns."""

    def test_regex_still_runs_on_full_mode(self):
        # Even if Presidio is absent, fast-mode regex must fire in full mode
        out, stderr, rc = _run("contact user@example.com", mode="full")
        self.assertEqual(rc, 0)
        self.assertIn("[EMAIL]", out)
        # If Presidio was missing, stderr should mention it OR be empty (if installed)
        # Either way, the output must have [EMAIL]

    def test_full_mode_missing_presidio_warns(self):
        mod = _load_filter()
        import builtins
        import io
        import sys as _sys
        import unittest.mock as mock

        _real_import = builtins.__import__

        def _no_presidio(name, *args, **kwargs):
            if name.startswith("presidio"):
                raise ImportError("mocked unavailable")
            return _real_import(name, *args, **kwargs)

        old_stderr = _sys.stderr
        _sys.stderr = io.StringIO()
        try:
            with mock.patch("builtins.__import__", side_effect=_no_presidio):
                result = mod._apply_full(b"email user@example.com here")
            stderr_out = _sys.stderr.getvalue()
        finally:
            _sys.stderr = old_stderr

        self.assertIn("[EMAIL]", result.decode())
        self.assertIn("presidio error", stderr_out)
        self.assertIn("regex-only", stderr_out)


class TestExceptionSafety(unittest.TestCase):
    def test_invalid_utf8_fast_mode(self):
        # Binary data not valid UTF-8 must pass through unchanged in fast mode
        result = subprocess.run(
            [sys.executable, FILTER, "--mode", "fast"],
            input=b"\xff\xfe binary garbage",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"\xff\xfe binary garbage")

    def test_fast_mode_does_not_import_presidio(self):
        # --mode fast must not trigger a Presidio import
        mod = _load_filter()
        import unittest.mock as mock

        imported = []
        _real = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        with mock.patch("builtins.__import__", side_effect=lambda n, *a, **k: (imported.append(n), _real(n, *a, **k))[1]):
            mod._apply_fast(b"test user@example.com")

        presidio_imports = [n for n in imported if "presidio" in n]
        self.assertEqual(presidio_imports, [], "fast mode must not import presidio")


if __name__ == "__main__":
    unittest.main()
