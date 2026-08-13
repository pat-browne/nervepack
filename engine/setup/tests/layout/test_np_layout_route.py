# np-test: layout | happy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nervepack_engine"))
import np_layout

LAYOUT = {
    "schema": 1,
    "routes": {
        "skill": {"path": "skills/{name}/SKILL.md"},
        "roadmap": {"path": "ROADMAP.md"},
        "knowledge": {"variants": [
            {"name": "concept", "when": "source-free synthesis",
             "path": "wiki/concepts/{name}.md", "frontmatter": {"kind": "concept"}},
            {"name": "topic", "when": "synthesis that owns sources",
             "path": "wiki/topics/{topic}/{topic}.md", "frontmatter": {"kind": "topic"}},
        ]},
    },
}


class TestRoute(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nplayout-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_simple_substitution(self):
        got = np_layout.route(LAYOUT, "skill", self.root, values={"name": "np-kb-x"})
        self.assertEqual(got, "skills/np-kb-x/SKILL.md")

    def test_route_with_no_variables(self):
        self.assertEqual(np_layout.route(LAYOUT, "roadmap", self.root), "ROADMAP.md")

    def test_variant_selection(self):
        got = np_layout.route(LAYOUT, "knowledge", self.root,
                              variant="topic", values={"topic": "rust"})
        self.assertEqual(got, "wiki/topics/rust/rust.md")

    def test_missing_variant_raises_and_lists_choices(self):
        with self.assertRaises(np_layout.LayoutError) as ctx:
            np_layout.route(LAYOUT, "knowledge", self.root, values={"name": "x"})
        msg = str(ctx.exception)
        self.assertIn("concept", msg)
        self.assertIn("source-free synthesis", msg)

    def test_unknown_variant_raises(self):
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(LAYOUT, "knowledge", self.root, variant="nope",
                            values={"name": "x"})

    def test_unrouted_kind_raises(self):
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(LAYOUT, "reference", self.root, values={"name": "x"})

    def test_unrouted_kind_message_lists_declared_kinds(self):
        with self.assertRaises(np_layout.LayoutError) as ctx:
            np_layout.route(LAYOUT, "reference", self.root, values={"name": "x"})
        self.assertIn("skill", str(ctx.exception))

    def test_missing_variable_raises(self):
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(LAYOUT, "skill", self.root, values={})

    def test_variant_on_a_plain_route_raises(self):
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(LAYOUT, "skill", self.root, variant="concept",
                            values={"name": "x"})

    def test_variants_helper_returns_when_strings(self):
        vs = np_layout.variants(LAYOUT, "knowledge")
        self.assertEqual([v["name"] for v in vs], ["concept", "topic"])

    def test_variants_helper_empty_for_plain_route(self):
        self.assertEqual(np_layout.variants(LAYOUT, "skill"), [])

    def test_frontmatter_returns_declared_fields(self):
        self.assertEqual(np_layout.frontmatter(LAYOUT, "knowledge", "topic"),
                         {"kind": "topic"})

    def test_frontmatter_empty_when_none_declared(self):
        self.assertEqual(np_layout.frontmatter(LAYOUT, "skill"), {})

    def test_frontmatter_empty_for_unrouted_kind(self):
        self.assertEqual(np_layout.frontmatter(LAYOUT, "reference"), {})


if __name__ == "__main__":
    unittest.main()
