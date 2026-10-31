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

    def test_quoted_and_odd_values(self):
        for cmd in ('x --password="abc def" y', "x --token 'abc def' y",
                    'x --password abc"def y', "x --secret=abc'def y"):
            out = s(cmd)
            self.assertNotIn("abc", out, cmd)
            self.assertNotIn("def", out.replace("[REDACTED-SECRET]", ""), cmd)

    def test_chained_commands_do_not_hide_a_second_secret(self):
        # An unquoted value ends at a shell separator, so the next flag is still seen.
        for cmd in ("x --password aaa1;--token bbb2", "x --password aaa1&&curl --token bbb2",
                    "x --password aaa1|tee --secret bbb2"):
            out = s(cmd)
            self.assertNotIn("aaa1", out, cmd)
            self.assertNotIn("bbb2", out, cmd)

    def test_value_may_start_with_or_contain_a_separator(self):
        # Only a separator that precedes another flag ends the value.
        for cmd, secret in (("x --password &hunter2", "hunter2"), ("x --password ;hunter2", "hunter2"),
                            ("x --password |hunter2", "hunter2"), ("x --password a;b9z", "b9z"),
                            ("x --password p\\&ss9", "ss9"), ("x --password ab|cd9", "cd9")):
            out = s(cmd)
            self.assertNotIn(secret, out, cmd)
            self.assertEqual(out.replace("[REDACTED-SECRET]", "").strip(), "x --password", cmd)

    def test_escaped_quotes_inside_quoted_values(self):
        for cmd in ('x --password="abc\\"def9z" y', "x --token 'abc\\'def9z' y"):
            out = s(cmd)
            self.assertNotIn("def9z", out, cmd)
            self.assertNotIn("abc", out, cmd)

    def test_basic_header_equals_form_keeps_case_and_needs_word_boundary(self):
        # The "Authorization:" colon form is redacted by an earlier rule. This rule adds "=".
        self.assertIn("authorization=basic [REDACTED-SECRET]", s("authorization=basic Ym9iOmh1bnRlcjI="))
        self.assertIn("Authorization=Basic [REDACTED-SECRET]", s("Authorization=Basic Ym9iOmh1bnRlcjI="))
        self.assertIn("Ym9iOmh1bnRlcjI", s("NotAuthorization=Basic Ym9iOmh1bnRlcjI="))
        self.assertNotIn("Ym9iOmh1bnRlcjI", s("Authorization: Basic Ym9iOmh1bnRlcjI="))

    def test_user_flag_stops_before_a_following_flag(self):
        out = s("curl -u bob:aaa1;--token bbb2 x")
        self.assertNotIn("aaa1", out)
        self.assertNotIn("bbb2", out)

    def test_double_quoted_escape_does_not_hide_a_second_secret(self):
        # In a shell, "pw\\" --token "s3cretValue" is one word, so both parts are the value.
        out = s('deploy --password "pw\\" --token "s3cretValue"')
        self.assertNotIn("s3cretValue", out)
        self.assertNotIn("pw", out.replace("password", ""))

    def test_single_quotes_are_literal(self):
        # A backslash does not escape inside single quotes: the first value ends at the second quote.
        out = s("x --password 'a\\' --token 'b9zValue'")
        self.assertNotIn("b9zValue", out)

    def test_separator_dash_inside_a_password_is_not_a_flag(self):
        for cmd, secret in (("curl -u bob:pa;-ss9z x", "ss9z"), ("x --password a;-b9z y", "b9z")):
            self.assertNotIn(secret, s(cmd), cmd)

    def test_prefixed_authorization_names(self):
        for cmd in ("http_authorization=basic Ym9iOmh1bnRlcjI=", "HTTP_AUTHORIZATION=Basic Ym9iOmh1bnRlcjI=",
                    "proxy-authorization=Basic Ym9iOmh1bnRlcjI="):
            self.assertNotIn("Ym9iOmh1bnRlcjI", s(cmd), cmd)

    def test_similar_flags_untouched(self):
        for cmd in ("x --token-file /tmp/t", "docker login --password-stdin", "x --port 8080"):
            self.assertEqual(s(cmd), cmd)

    def test_user_flag(self):
        self.assertNotIn("hunter2", s("curl -u bob:hunter2 https://host/x"))
        self.assertNotIn("hunter2", s("curl --user=bob:hunter2 https://host/x"))
        self.assertEqual(s("ssh -u bob host"), "ssh -u bob host")

    def test_basic_auth_header(self):
        self.assertNotIn("Ym9iOmh1bnRlcjI", s("Authorization: Basic Ym9iOmh1bnRlcjI="))

    def test_basic_prose_untouched(self):
        for text in ("basic configuration", "Basic understanding of auth"):
            self.assertEqual(s(text), text)
        self.assertNotIn("Ym9iOmh1bnRlcjI", s("curl -H 'Authorization: Basic Ym9iOmh1bnRlcjI=' x"))

    def test_quoted_value_with_space(self):
        out = s('x --token "abc def" y')
        self.assertNotIn("def", out)
        self.assertTrue(out.endswith(" y"))

    def test_existing_rules_still_apply(self):
        self.assertIn("REDACTED", s("token=abcdefghijk"))


if __name__ == "__main__":
    unittest.main()
