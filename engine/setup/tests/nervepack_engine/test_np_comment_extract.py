"""Tests for np_comment_extract -- per-language comment extraction feeding
form_gate's comment-lint feature."""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_comment_extract as nce  # noqa: E402


class TestPython(unittest.TestCase):
    def test_hash_comment_is_extracted(self):
        text = "x = 1\n# a note about x\ny = 2\n"
        comment, _ = nce.extract_comments(text, ".py")
        self.assertIn("a note about x", comment)

    def test_leading_module_docstring_is_extracted(self):
        text = '"""Module summary."""\nimport os\n'
        comment, max_block = nce.extract_comments(text, ".py")
        self.assertIn("Module summary.", comment)
        self.assertEqual(max_block, 1)

    def test_function_docstring_is_extracted(self):
        text = 'def foo():\n    """Explains foo."""\n    return 1\n'
        comment, _ = nce.extract_comments(text, ".py")
        self.assertIn("Explains foo.", comment)

    def test_non_docstring_triple_quoted_string_is_not_extracted(self):
        text = 'x = 1\nDATA = """not a docstring, just data"""\ny = 2\n'
        comment, _ = nce.extract_comments(text, ".py")
        self.assertNotIn("not a docstring", comment)

    def test_max_block_lines_for_multiline_comment_run(self):
        text = "# one\n# two\n# three\nx = 1\n"
        _, max_block = nce.extract_comments(text, ".py")
        self.assertEqual(max_block, 3)

    def test_blank_line_breaks_a_block(self):
        text = "# one\n\n# two\n"
        _, max_block = nce.extract_comments(text, ".py")
        self.assertEqual(max_block, 1)

    def test_no_comments_yields_empty(self):
        comment, max_block = nce.extract_comments("x = 1\ny = 2\n", ".py")
        self.assertEqual(comment, "")
        self.assertEqual(max_block, 0)


class TestCLike(unittest.TestCase):
    def test_line_comment_is_extracted(self):
        comment, _ = nce.extract_comments("let x = 1; // explain x\n", ".ts")
        self.assertIn("explain x", comment)

    def test_https_in_string_is_not_treated_as_comment(self):
        text = 'const url = "https://example.com/path";\n'
        comment, _ = nce.extract_comments(text, ".js")
        self.assertEqual(comment, "")

    def test_block_comment_extracted_with_correct_span(self):
        text = "/* line one\n   line two\n   line three */\ncode();\n"
        comment, max_block = nce.extract_comments(text, ".go")
        self.assertIn("line one", comment)
        self.assertIn("line two", comment)
        self.assertEqual(max_block, 3)

    def test_consecutive_line_comments_merge_into_one_block(self):
        text = "// one\n// two\ncode();\n"
        _, max_block = nce.extract_comments(text, ".rs")
        self.assertEqual(max_block, 2)

    def test_trailing_comment_after_code_is_its_own_block(self):
        text = "code(); // trailing\nmore_code();\n"
        comment, max_block = nce.extract_comments(text, ".java")
        self.assertIn("trailing", comment)
        self.assertEqual(max_block, 1)


class TestShellSql(unittest.TestCase):
    def test_shell_hash_comment_extracted(self):
        comment, _ = nce.extract_comments("echo hi\n# a shell note\n", ".sh")
        self.assertIn("a shell note", comment)

    def test_shell_hash_inside_quotes_is_not_extracted(self):
        text = 'echo "not a # comment"\n'
        comment, _ = nce.extract_comments(text, ".bash")
        self.assertEqual(comment, "")

    def test_sql_double_dash_comment_extracted(self):
        comment, _ = nce.extract_comments("SELECT 1;\n-- a sql note\n", ".sql")
        self.assertIn("a sql note", comment)

    def test_sql_hash_is_not_a_comment_marker(self):
        # .sql uses `--`, not `#` -- a bare `#` is left alone.
        comment, _ = nce.extract_comments("SELECT 1; # not sql syntax\n", ".sql")
        self.assertEqual(comment, "")


class TestUnknownExtension(unittest.TestCase):
    def test_unrecognized_extension_yields_empty(self):
        comment, max_block = nce.extract_comments("whatever", ".xyz")
        self.assertEqual(comment, "")
        self.assertEqual(max_block, 0)

    def test_never_raises_on_none_text(self):
        comment, max_block = nce.extract_comments(None, ".py")
        self.assertEqual(comment, "")
        self.assertEqual(max_block, 0)


if __name__ == "__main__":
    unittest.main()
