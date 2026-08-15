"""#176: unit tests for the shared frontmatter/env helpers extracted from
np_skill_budget / np_skill_validate / np_graduation_detect."""
import os
import sys
import unittest

_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import np_frontmatter  # noqa: E402


class TestIntEnv(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("NP_FM_TEST", None)

    def test_missing_returns_default(self):
        os.environ.pop("NP_FM_TEST", None)
        self.assertEqual(np_frontmatter.int_env("NP_FM_TEST", 7), 7)

    def test_valid_int_parsed(self):
        os.environ["NP_FM_TEST"] = "42"
        self.assertEqual(np_frontmatter.int_env("NP_FM_TEST", 7), 42)

    def test_non_integer_falls_back(self):
        os.environ["NP_FM_TEST"] = "notint"
        self.assertEqual(np_frontmatter.int_env("NP_FM_TEST", 7), 7)


class TestField(unittest.TestCase):
    DOC = "---\nname: demo\ndescription: a demo skill\n---\nbody\n"

    def test_reads_field_stripped(self):
        self.assertEqual(np_frontmatter.field(self.DOC, "description"), "a demo skill")
        self.assertEqual(np_frontmatter.field(self.DOC, "name"), "demo")

    def test_absent_field_returns_default(self):
        self.assertIsNone(np_frontmatter.field(self.DOC, "missing"))       # default None
        self.assertEqual(np_frontmatter.field(self.DOC, "missing", ""), "")  # default ""

    def test_no_frontmatter_block_returns_default(self):
        self.assertIsNone(np_frontmatter.field("no frontmatter here", "name"))
        self.assertEqual(np_frontmatter.field("plain text", "name", ""), "")

    def test_unterminated_frontmatter_returns_default(self):
        self.assertEqual(np_frontmatter.field("---\nname: x\nno close", "name", ""), "")


class TestListField(unittest.TestCase):
    DOC = (
        "---\n"
        "id: 0001\n"
        "blast_radius:\n"
        "  - change-specs/**\n"
        "  - AGENTS.md\n"
        "---\n"
        "body\n"
    )

    def test_reads_block_list_items_stripped(self):
        self.assertEqual(
            np_frontmatter.list_field(self.DOC, "blast_radius"),
            ["change-specs/**", "AGENTS.md"],
        )

    def test_absent_field_returns_empty_list(self):
        self.assertEqual(np_frontmatter.list_field(self.DOC, "missing"), [])

    def test_inline_scalar_form_returns_empty_list(self):
        doc = "---\nblast_radius: not-a-list\n---\nbody\n"
        self.assertEqual(np_frontmatter.list_field(doc, "blast_radius"), [])

    def test_empty_block_returns_empty_list(self):
        doc = "---\nblast_radius:\nid: 1\n---\nbody\n"
        self.assertEqual(np_frontmatter.list_field(doc, "blast_radius"), [])

    def test_no_frontmatter_block_returns_empty_list(self):
        self.assertEqual(np_frontmatter.list_field("no frontmatter", "blast_radius"), [])

    def test_last_field_in_block_reads_to_end(self):
        doc = "---\nid: 1\nblast_radius:\n  - a/**\n  - b/**\n---\nbody\n"
        self.assertEqual(np_frontmatter.list_field(doc, "blast_radius"), ["a/**", "b/**"])


if __name__ == "__main__":
    unittest.main()
