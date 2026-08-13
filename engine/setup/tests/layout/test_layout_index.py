# np-test: layout | happy
"""The index is what makes directory structure stop being the lookup path. It must
follow the layer's DECLARED routes, so a layer that uses notes/ indexes the same as
one that uses wiki/. Hermetic: temp NP_DIR + NP_CONTENT_DIR, never the real repos."""
import io
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
# np_generate_index lives in engine/setup; the library modules it imports live in
# engine/nervepack_engine. Both go on the path, as the other suites do.
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..",
                                                 "nervepack_engine")))
import np_generate_index


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestKnowledgeIndex(unittest.TestCase):
    def setUp(self):
        self.engine = tempfile.mkdtemp(prefix="npidx-eng-")
        self.overlay = tempfile.mkdtemp(prefix="npidx-ovl-")
        self.home = tempfile.mkdtemp(prefix="npidx-home-")
        self._saved = {k: os.environ.get(k)
                       for k in ("NP_DIR", "NP_CONTENT_DIR", "NP_TEAM_DIR", "HOME")}
        os.environ["NP_DIR"] = self.engine
        os.environ["NP_CONTENT_DIR"] = self.overlay
        os.environ["HOME"] = self.home
        os.environ.pop("NP_TEAM_DIR", None)
        write(os.path.join(self.engine, "skills", "np-core-x", "SKILL.md"),
              "---\nname: np-core-x\ndescription: engine skill\n---\n")

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for d in (self.engine, self.overlay, self.home):
            shutil.rmtree(d, ignore_errors=True)

    def _index(self):
        np_generate_index.generate(np_dir=self.engine, out=io.StringIO())
        with open(os.path.join(self.overlay, "INDEX.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_knowledge_pages_are_listed(self):
        write(os.path.join(self.overlay, "wiki", "concepts", "widgets.md"),
              "---\nkind: concept\ndescription: what a widget is\n---\n")
        text = self._index()
        self.assertIn("## Knowledge", text)
        self.assertIn("widgets", text)
        self.assertIn("what a widget is", text)

    def test_nonstandard_tree_is_listed_too(self):
        write(os.path.join(self.overlay, "notes", "gadgets.md"),
              "---\nkind: note\ndescription: about gadgets\n---\n")
        text = self._index()
        self.assertIn("gadgets", text)
        self.assertIn("notes/gadgets.md", text)

    def test_reference_pages_are_listed(self):
        write(os.path.join(self.overlay, "wiki", "topics", "rust", "rust.md"),
              "---\nkind: topic\ndescription: rust\n---\n")
        write(os.path.join(self.overlay, "wiki", "topics", "rust", "spec.md"),
              "---\nkind: reference\ndescription: the spec\n---\n")
        text = self._index()
        self.assertIn("the spec", text)

    def test_engine_index_has_no_knowledge_section(self):
        write(os.path.join(self.overlay, "wiki", "concepts", "widgets.md"),
              "---\nkind: concept\ndescription: d\n---\n")
        self._index()
        with open(os.path.join(self.engine, "INDEX.md"), encoding="utf-8") as fh:
            self.assertNotIn("## Knowledge", fh.read())

    def test_no_knowledge_route_yields_no_section(self):
        self.assertNotIn("## Knowledge", self._index())

    def test_skills_section_still_present(self):
        write(os.path.join(self.overlay, "wiki", "concepts", "w.md"),
              "---\nkind: concept\ndescription: d\n---\n")
        self.assertIn("np-core-x", self._index())

    def test_page_without_frontmatter_kind_is_skipped(self):
        write(os.path.join(self.overlay, "notes", "real.md"),
              "---\nkind: note\ndescription: d\n---\n")
        write(os.path.join(self.overlay, "notes", "stray.md"), "no frontmatter\n")
        text = self._index()
        self.assertIn("real", text)
        self.assertNotIn("stray", text)

    def test_readme_is_not_indexed_as_a_page(self):
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\ndescription: d\n---\n")
        write(os.path.join(self.overlay, "notes", "README.md"),
              "---\nkind: note\ndescription: nope\n---\n")
        self.assertNotIn("nope", self._index())

    def test_pipe_in_description_is_escaped(self):
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\ndescription: a | b\n---\n")
        self.assertIn("a \\| b", self._index())

    def test_description_falls_back_to_a_body_excerpt(self):
        # Real wiki pages carry name/kind/last_updated but no description:, so a
        # description-only column reads "_(no description)_" for every row.
        write(os.path.join(self.overlay, "wiki", "topics", "aws", "aws.md"),
              "---\nname: aws\nkind: topic\n---\n\n# AWS\n\n"
              "Synthesis page. What this nervepack knows about AWS.\n")
        text = self._index()
        self.assertIn("Synthesis page. What this nervepack knows about AWS.", text)

    def test_frontmatter_description_wins_over_the_excerpt(self):
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\ndescription: the declared one\n---\n\n"
              "# A\n\nthe body line\n")
        text = self._index()
        self.assertIn("the declared one", text)
        self.assertNotIn("the body line", text)

    def test_excerpt_skips_headings_and_blank_lines(self):
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\n---\n\n# Heading\n\n## Sub\n\nreal prose here\n")
        self.assertIn("real prose here", self._index())

    def test_excerpt_is_truncated(self):
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\n---\n\n" + ("word " * 80) + "\n")
        row = [ln for ln in self._index().splitlines() if "notes/a.md" in ln][0]
        self.assertLess(len(row), 400)

    def test_page_with_no_body_still_lists(self):
        write(os.path.join(self.overlay, "notes", "a.md"), "---\nkind: note\n---\n")
        self.assertIn("notes/a.md", self._index())

    def test_index_is_deterministic(self):
        write(os.path.join(self.overlay, "notes", "b.md"),
              "---\nkind: note\ndescription: d2\n---\n")
        write(os.path.join(self.overlay, "notes", "a.md"),
              "---\nkind: note\ndescription: d1\n---\n")
        self.assertEqual(self._index(), self._index())


if __name__ == "__main__":
    unittest.main()
