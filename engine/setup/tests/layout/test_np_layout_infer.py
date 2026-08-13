# np-test: layout | happy
"""Inference must carry no assumption about directory NAMES. A layer that keeps
knowledge in notes/ must infer just as well as one that uses wiki/."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nervepack_engine"))
import np_layout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestInfer(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nplayout-")
        self.home = tempfile.mkdtemp(prefix="nphome-")
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_empty_layer_infers_no_routes(self):
        self.assertEqual(np_layout.infer(self.root)["routes"], {})

    def test_skills_dir_infers_skill_route(self):
        write(os.path.join(self.root, "skills", "np-kb-x", "SKILL.md"),
              "---\nname: x\n---\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["routes"]["skill"]["path"], "skills/{name}/SKILL.md")

    def test_skills_dir_without_skill_md_infers_nothing(self):
        os.makedirs(os.path.join(self.root, "skills", "empty"))
        self.assertNotIn("skill", np_layout.infer(self.root)["routes"])

    def test_frontmatter_kinds_become_knowledge_variants(self):
        write(os.path.join(self.root, "wiki", "concepts", "a.md"),
              "---\nkind: concept\n---\n")
        write(os.path.join(self.root, "wiki", "topics", "rust", "rust.md"),
              "---\nkind: topic\n---\n")
        got = np_layout.infer(self.root)
        names = sorted(v["name"] for v in got["routes"]["knowledge"]["variants"])
        self.assertEqual(names, ["concept", "topic"])

    def test_folder_owning_page_infers_a_topic_template(self):
        write(os.path.join(self.root, "wiki", "topics", "rust", "rust.md"),
              "---\nkind: topic\n---\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["routes"]["knowledge"]["path"],
                         "wiki/topics/{topic}/{topic}.md")

    def test_single_kind_infers_a_plain_route_not_variants(self):
        write(os.path.join(self.root, "wiki", "concepts", "a.md"),
              "---\nkind: concept\n---\n")
        got = np_layout.infer(self.root)
        self.assertNotIn("variants", got["routes"]["knowledge"])
        self.assertEqual(got["routes"]["knowledge"]["path"], "wiki/concepts/{name}.md")

    def test_reference_kind_routes_to_reference_not_knowledge(self):
        write(os.path.join(self.root, "wiki", "topics", "rust", "rust.md"),
              "---\nkind: topic\n---\n")
        write(os.path.join(self.root, "wiki", "topics", "rust", "spec.md"),
              "---\nkind: reference\n---\n")
        got = np_layout.infer(self.root)
        self.assertIn("reference", got["routes"])
        know = got["routes"]["knowledge"]
        names = [v["name"] for v in know.get("variants", [])] or ["topic"]
        self.assertNotIn("reference", names)

    def test_nonstandard_dir_names_infer_correctly(self):
        write(os.path.join(self.root, "notes", "a.md"), "---\nkind: note\n---\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["routes"]["knowledge"]["path"], "notes/{name}.md")

    def test_root_roadmap_infers_roadmap_route(self):
        write(os.path.join(self.root, "ROADMAP.md"), "# Roadmap\n")
        self.assertEqual(np_layout.infer(self.root)["routes"]["roadmap"]["path"],
                         "ROADMAP.md")

    def test_agents_dir_infers_prompt_route(self):
        write(os.path.join(self.root, "agents", "np-flow-x.md"), "# prompt\n")
        self.assertEqual(np_layout.infer(self.root)["routes"]["prompt"]["path"],
                         "agents/{name}.md")

    def test_index_and_links_detected(self):
        write(os.path.join(self.root, "INDEX.md"), "# index\n")
        write(os.path.join(self.root, "notes", "a.md"),
              "---\nkind: note\n---\nsee [[b]]\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["index"], "INDEX.md")
        self.assertEqual(got["links"], "wikilink")

    def test_links_defaults_to_path_without_wikilinks(self):
        write(os.path.join(self.root, "notes", "a.md"), "---\nkind: note\n---\nplain\n")
        self.assertEqual(np_layout.infer(self.root)["links"], "path")

    def test_derived_from_lists_prose_docs(self):
        write(os.path.join(self.root, "README.md"), "# r\n")
        write(os.path.join(self.root, "CONTRIBUTING.md"), "# c\n")
        write(os.path.join(self.root, "wiki", "README.md"), "# w\n")
        got = np_layout.infer(self.root)
        self.assertIn("README.md", got["derived_from"])
        self.assertIn("CONTRIBUTING.md", got["derived_from"])
        self.assertIn("wiki/README.md", got["derived_from"])

    def test_root_level_markdown_is_not_a_knowledge_tree(self):
        write(os.path.join(self.root, "stray.md"), "---\nkind: note\n---\n")
        self.assertNotIn("knowledge", np_layout.infer(self.root)["routes"])

    def test_memory_and_archive_are_skipped(self):
        write(os.path.join(self.root, "memory", "episodic", "a.md"),
              "---\nkind: episode\n---\n")
        write(os.path.join(self.root, "archive", "old.md"), "---\nkind: dead\n---\n")
        self.assertNotIn("knowledge", np_layout.infer(self.root)["routes"])

    def test_template_generalizes_over_all_pages_not_one_sample(self):
        # Regression: inferring from the first page alone baked that page's concrete
        # directory into the template (wiki/concepts/password-management/{name}.md).
        for n in ("alpha", "beta", "gamma"):
            write(os.path.join(self.root, "wiki", "concepts", n + ".md"),
                  "---\nkind: concept\n---\n")
        write(os.path.join(self.root, "wiki", "concepts", "delta", "delta.md"),
              "---\nkind: concept\n---\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["routes"]["knowledge"]["path"], "wiki/concepts/{name}.md")

    def test_co_located_reference_generalizes_its_topic_folder(self):
        # A reference sits beside the synthesis page that owns its folder, so the
        # folder name is a variable, not a constant.
        for t in ("rust", "zig"):
            write(os.path.join(self.root, "wiki", "topics", t, t + ".md"),
                  "---\nkind: topic\n---\n")
            write(os.path.join(self.root, "wiki", "topics", t, "spec.md"),
                  "---\nkind: reference\n---\n")
        got = np_layout.infer(self.root)
        self.assertEqual(got["routes"]["reference"]["path"],
                         "wiki/topics/{topic}/{name}.md")

    def test_no_majority_shape_yields_no_route(self):
        # Two pages of one kind in unrelated trees is a real ambiguity. Emit no
        # route so the interview asks, rather than guessing one of them.
        write(os.path.join(self.root, "alpha", "a.md"), "---\nkind: note\n---\n")
        write(os.path.join(self.root, "beta", "b.md"), "---\nkind: note\n---\n")
        self.assertNotIn("knowledge", np_layout.infer(self.root)["routes"])

    def test_majority_wins_over_a_stray_page(self):
        for n in ("a", "b", "c"):
            write(os.path.join(self.root, "notes", n + ".md"), "---\nkind: note\n---\n")
        write(os.path.join(self.root, "stray", "d.md"), "---\nkind: note\n---\n")
        self.assertEqual(np_layout.infer(self.root)["routes"]["knowledge"]["path"],
                         "notes/{name}.md")

    def test_infer_output_validates(self):
        write(os.path.join(self.root, "skills", "s", "SKILL.md"), "---\nname: s\n---\n")
        np_layout.validate(np_layout.infer(self.root))

    def test_resolve_prefers_manifest_over_inference(self):
        p = np_layout.manifest_path(self.root)
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "routes": {"skill": {"path": "s/{name}.md"}}}, fh)
        write(os.path.join(self.root, "skills", "x", "SKILL.md"), "---\nname: x\n---\n")
        layout, source = np_layout.resolve(self.root)
        self.assertEqual(source, "manifest")
        self.assertEqual(layout["routes"]["skill"]["path"], "s/{name}.md")

    def test_resolve_falls_back_to_inference(self):
        write(os.path.join(self.root, "skills", "x", "SKILL.md"), "---\nname: x\n---\n")
        layout, source = np_layout.resolve(self.root)
        self.assertEqual(source, "inferred")

    def test_inferred_routes_are_usable_by_route(self):
        write(os.path.join(self.root, "notes", "a.md"), "---\nkind: note\n---\n")
        layout, _ = np_layout.resolve(self.root)
        self.assertEqual(
            np_layout.route(layout, "knowledge", self.root, values={"name": "b"}),
            "notes/b.md")


if __name__ == "__main__":
    unittest.main()
