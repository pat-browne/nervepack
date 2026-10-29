"""Credential shapes in command lines and URLs (security review of stack_facts evidence)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "nervepack_engine"))
import np_scrub  # noqa: E402


def s(text):
    return np_scrub.scrub(text.encode()).decode()


class TestScrubCredentials(unittest.TestCase):
    def test_url_userinfo(self):
        self.assertNotIn("hunter2", s("git clone https://bob:hunter2@host.example/r.git"))
        self.assertNotIn("TOKEN123", s("git remote add o https://TOKEN123@github.com/a/b"))
        self.assertIn("host.example", s("https://bob:hunter2@host.example/x"))

    def test_password_flags(self):
        for cmd in ("mysql --password hunter2 db", "mysql --password=hunter2 db",
                    'x --token "hunter2"', "x --api-key hunter2", "x --client-secret=hunter2"):
            self.assertNotIn("hunter2", s(cmd), cmd)

    def test_similar_flags_untouched(self):
        for cmd in ("x --token-file /tmp/t", "docker login --password-stdin", "x --port 8080"):
            self.assertEqual(s(cmd), cmd)

    def test_user_flag(self):
        self.assertNotIn("hunter2", s("curl -u bob:hunter2 https://host/x"))
        self.assertNotIn("hunter2", s("curl --user=bob:hunter2 https://host/x"))
        self.assertEqual(s("ssh -u bob host"), "ssh -u bob host")

    def test_basic_auth_header(self):
        self.assertNotIn("Ym9iOmh1bnRlcjI", s("Authorization: Basic Ym9iOmh1bnRlcjI="))

    def test_existing_rules_still_apply(self):
        self.assertIn("REDACTED", s("token=abcdefghijk"))


if __name__ == "__main__":
    unittest.main()
