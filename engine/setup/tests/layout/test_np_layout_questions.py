# np-test: layout | happy
"""nervepack#234: "after each answer, evaluate if that solves the pending questions
about any additional organization confusion, only ask another question after this
has been reprocessed." open_questions() is a pure function of (disk, layout), so
the interview re-runs it after every answer and never asks a settled question."""
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


class TestQuestions(unittest.TestCase):
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

    def test_no_knowledge_route_asks_about_knowledge(self):
        qs = np_layout.open_questions(self.root)
        self.assertIn("missing-kind:knowledge", [q["id"] for q in qs])

    def test_unexplained_markdown_dir_is_asked_about(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain, no frontmatter\n")
        qs = np_layout.open_questions(self.root)
        self.assertIn("unmapped-dir:notes", [q["id"] for q in qs])

    def test_routed_dir_is_not_asked_about(self):
        write(os.path.join(self.root, "notes", "a.md"), "---\nkind: note\n---\n")
        qs = np_layout.open_questions(self.root)
        self.assertNotIn("unmapped-dir:notes", [q["id"] for q in qs])

    def test_dir_listed_unmapped_is_not_asked_about(self):
        write(os.path.join(self.root, "brand", "a.md"), "plain\n")
        layout = np_layout.infer(self.root)
        layout["unmapped"] = ["brand/"]
        qs = np_layout.open_questions(self.root, layout)
        self.assertNotIn("unmapped-dir:brand", [q["id"] for q in qs])

    def test_dir_with_no_markdown_is_not_asked_about(self):
        os.makedirs(os.path.join(self.root, "assets"))
        write(os.path.join(self.root, "assets", "logo.svg"), "<svg/>")
        qs = np_layout.open_questions(self.root)
        self.assertNotIn("unmapped-dir:assets", [q["id"] for q in qs])

    def test_skipped_dirs_are_never_asked_about(self):
        write(os.path.join(self.root, "memory", "episodic", "a.md"), "x\n")
        write(os.path.join(self.root, "archive", "b.md"), "x\n")
        ids = [q["id"] for q in np_layout.open_questions(self.root)]
        self.assertNotIn("unmapped-dir:memory", ids)
        self.assertNotIn("unmapped-dir:archive", ids)

    def test_question_carries_evidence(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        q = [q for q in np_layout.open_questions(self.root)
             if q["id"] == "unmapped-dir:notes"][0]
        self.assertIn("notes/a.md", q["evidence"])

    def test_every_question_has_id_question_and_evidence(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        for q in np_layout.open_questions(self.root):
            self.assertEqual(sorted(q), ["evidence", "id", "question"])
            self.assertTrue(q["question"].strip())

    def test_one_answer_can_resolve_several_questions(self):
        # THE reprocessing requirement. Two unexplained dirs plus a missing
        # knowledge route = 3+ questions. One answer that routes both dirs must
        # leave zero, so the interview asks 1 question, not 3.
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        write(os.path.join(self.root, "refs", "b.md"), "plain\n")
        write(os.path.join(self.root, "ROADMAP.md"), "# r\n")
        write(os.path.join(self.root, "skills", "s", "SKILL.md"), "---\nname: s\n---\n")
        before = np_layout.open_questions(self.root)
        self.assertGreaterEqual(len(before), 3)

        answered = np_layout.infer(self.root)
        answered["routes"]["knowledge"] = {"path": "notes/{name}.md"}
        answered["routes"]["reference"] = {"path": "refs/{name}.md"}
        after = np_layout.open_questions(self.root, answered)
        self.assertEqual(after, [])

    def test_partial_answer_leaves_the_rest(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        write(os.path.join(self.root, "refs", "b.md"), "plain\n")
        write(os.path.join(self.root, "ROADMAP.md"), "# r\n")
        write(os.path.join(self.root, "skills", "s", "SKILL.md"), "---\nname: s\n---\n")
        answered = np_layout.infer(self.root)
        answered["routes"]["knowledge"] = {"path": "notes/{name}.md"}
        ids = [q["id"] for q in np_layout.open_questions(self.root, answered)]
        self.assertEqual(ids, ["unmapped-dir:refs"])

    def test_fully_described_layer_has_no_questions(self):
        write(os.path.join(self.root, "skills", "s", "SKILL.md"), "---\nname: s\n---\n")
        write(os.path.join(self.root, "wiki", "concepts", "a.md"),
              "---\nkind: concept\n---\n")
        write(os.path.join(self.root, "ROADMAP.md"), "# r\n")
        self.assertEqual(np_layout.open_questions(self.root), [])

    def test_questions_are_stable_across_runs(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        self.assertEqual([q["id"] for q in np_layout.open_questions(self.root)],
                         [q["id"] for q in np_layout.open_questions(self.root)])

    def test_recorded_manifest_silences_the_questions(self):
        write(os.path.join(self.root, "notes", "a.md"), "plain\n")
        np_layout.record(self.root, {
            "schema": 1,
            "routes": {"knowledge": {"path": "notes/{name}.md"},
                       "skill": {"path": "skills/{name}/SKILL.md"},
                       "roadmap": {"path": "ROADMAP.md"}}})
        layout, source = np_layout.resolve(self.root)
        self.assertEqual(source, "manifest")
        self.assertEqual(np_layout.open_questions(self.root, layout), [])


if __name__ == "__main__":
    unittest.main()
