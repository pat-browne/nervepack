# np-test: layout | happy+failure
"""Layout drift: content added after a layer's interview lands in directories no
route names. drift() finds them from frontmatter heads, add_route() records the
clear ones, and open_questions() surfaces the rest."""
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


def page(t=None, field="type"):
    return ("---\n%s: %s\n---\n\nBody.\n" % (field, t)) if t else "# No frontmatter\n"


BASE = {"schema": 1, "routes": {
    "knowledge": {"path": "docs/systems/{name}.md", "frontmatter": {"type": "system"}},
    "skill": {"path": ".claude/skills/{name}/SKILL.md"},
    "reference": {"variants": [{"name": "solution", "path": "docs/solutions/{name}.md"}]}},
    "unmapped": ["templates/"]}


class TestDrift(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="npdrift-")
        self.home = tempfile.mkdtemp(prefix="nphome-")
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(shutil.rmtree, self.home, True)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home

    def w(self, rel, text):
        write(os.path.join(self.root, rel), text)

    def layout(self):
        return json.loads(json.dumps(BASE))

    def test_clear_dir_when_every_page_shares_a_type(self):
        self.w("docs/plans/a.md", page("plan"))
        self.w("docs/plans/b.md", page("plan"))
        self.w("docs/plans/README.md", "# readme\n")
        rep = np_layout.drift(self.root, self.layout())
        self.assertEqual(rep["clear"], [{"dir": "docs/plans", "field": "type",
                                         "value": "plan", "kind": "knowledge",
                                         "pages": 2}])
        self.assertEqual(rep["ambiguous"], [])

    def test_reference_kind_value_maps_to_reference(self):
        self.w("refs/a.md", page("source", field="kind"))
        rep = np_layout.drift(self.root, self.layout())
        self.assertEqual(rep["clear"][0]["kind"], "reference")
        self.assertEqual(rep["clear"][0]["field"], "kind")

    def test_mixed_or_untyped_dir_is_ambiguous(self):
        self.w("docs/mixed/a.md", page("plan"))
        self.w("docs/mixed/b.md", page("receipt"))
        self.w("docs/bare/a.md", page())
        rep = np_layout.drift(self.root, self.layout())
        self.assertEqual(sorted(a["dir"] for a in rep["ambiguous"]),
                         ["docs/bare", "docs/mixed"])
        self.assertEqual(rep["clear"], [])

    def test_readme_only_dir_is_ignored(self):
        self.w("docs/wiki/README.md", "# readme\n")
        self.w("docs/lessons/INDEX.md", "# index\n")
        self.assertEqual(np_layout.drift(self.root, self.layout()),
                         {"clear": [], "ambiguous": []})

    def test_routes_and_unmapped_cover_their_dirs(self):
        self.w("docs/systems/a.md", page("system"))
        self.w("docs/solutions/a.md", page("solution"))
        self.w(".claude/skills/x/SKILL.md", page("skill"))
        self.w(".claude/skills/x/references/r.md", page())
        self.w("templates/t.md", page())
        self.w("templates/sub/t.md", page())
        self.assertEqual(np_layout.drift(self.root, self.layout()),
                         {"clear": [], "ambiguous": []})

    def test_flat_route_does_not_cover_its_subdirs(self):
        self.w("docs/systems/mcp/a.md", page("adr"))
        rep = np_layout.drift(self.root, self.layout())
        self.assertEqual([c["dir"] for c in rep["clear"]], ["docs/systems/mcp"])

    def test_nested_route_container_is_covered(self):
        lay = self.layout()
        lay["routes"]["knowledge"] = {"variants": [
            {"name": "conv", "path": "refs/{name}.md"},
            {"name": "model", "path": "refs/model/{name}.md"}]}
        self.w("refs/model/a.md", page())
        self.assertEqual(np_layout.drift(self.root, lay),
                         {"clear": [], "ambiguous": []})

    def test_dot_dirs_walked_only_along_routes(self):
        self.w(".claude/worktrees/x/docs/a.md", page("plan"))
        self.w(".claude/hooks/a.md", page("plan"))
        self.w(".other/a.md", page("plan"))
        self.assertEqual(np_layout.drift(self.root, self.layout()),
                         {"clear": [], "ambiguous": []})

    def test_add_route_converts_single_path_route(self):
        lay = self.layout()
        np_layout.add_route(lay, {"dir": "docs/plans", "field": "type",
                                  "value": "plan", "kind": "knowledge"})
        vs = lay["routes"]["knowledge"]["variants"]
        self.assertEqual(vs[0], {"name": "system", "path": "docs/systems/{name}.md",
                                 "frontmatter": {"type": "system"}})
        self.assertEqual(vs[1]["path"], "docs/plans/{name}.md")
        self.assertEqual(vs[1]["frontmatter"], {"type": "plan"})
        self.assertIn("added by sync", vs[1]["when"])
        np_layout.validate(lay)

    def test_add_route_appends_to_variants_and_skips_duplicates(self):
        lay = self.layout()
        item = {"dir": "docs/runbooks", "field": "type", "value": "runbook",
                "kind": "reference"}
        self.assertIsNotNone(np_layout.add_route(lay, item))
        self.assertIsNone(np_layout.add_route(lay, item))
        names = [v["name"] for v in lay["routes"]["reference"]["variants"]]
        self.assertEqual(names, ["solution", "runbook"])

    def test_add_route_creates_missing_kind(self):
        lay = {"schema": 1, "routes": {}}
        np_layout.add_route(lay, {"dir": "refs", "field": "kind",
                                  "value": "reference", "kind": "reference"})
        self.assertEqual(lay["routes"]["reference"]["variants"][0]["path"],
                         "refs/{name}.md")

    def test_apply_drift_records_clear_and_reports_ambiguous(self):
        write(np_layout.manifest_path(self.root), json.dumps(self.layout()))
        self.w("docs/plans/a.md", page("plan"))
        self.w("docs/mixed/a.md", page("plan"))
        self.w("docs/mixed/b.md", page("x"))
        changes, questions = np_layout.apply_drift(self.root)
        self.assertEqual(len(changes), 1)
        self.assertIn("docs/plans/", changes[0])
        self.assertEqual(len(questions), 1)
        self.assertIn("docs/mixed/", questions[0])
        saved = np_layout.load(self.root)
        paths = [v["path"] for v in saved["routes"]["knowledge"]["variants"]]
        self.assertIn("docs/plans/{name}.md", paths)
        self.assertEqual(np_layout.apply_drift(self.root)[0], [])

    def test_apply_drift_never_writes_an_inferred_layout(self):
        self.w("docs/plans/a.md", page("plan"))
        changes, _q = np_layout.apply_drift(self.root)
        self.assertIn("not recorded", changes[0])
        self.assertFalse(os.path.exists(np_layout.manifest_path(self.root)))

    def test_record_refuses_symlinked_nervepack_dir(self):
        outside = tempfile.mkdtemp(prefix="npout-")
        self.addCleanup(shutil.rmtree, outside, True)
        os.symlink(outside, os.path.join(self.root, ".nervepack"))
        with self.assertRaises(np_layout.LayoutError):
            np_layout.record(self.root, self.layout())
        self.assertEqual(os.listdir(outside), [])

    def test_record_refuses_symlinked_manifest(self):
        outside = tempfile.mkdtemp(prefix="npout-")
        self.addCleanup(shutil.rmtree, outside, True)
        target = os.path.join(outside, "victim.json")
        os.makedirs(os.path.join(self.root, ".nervepack"))
        os.symlink(target, np_layout.manifest_path(self.root))
        with self.assertRaises(np_layout.LayoutError):
            np_layout.record(self.root, self.layout())
        self.assertFalse(os.path.exists(target))

    def test_apply_drift_cache_only_leaves_layer_repo_alone(self):
        write(np_layout.manifest_path(self.root), json.dumps(self.layout()))
        with open(np_layout.manifest_path(self.root)) as fh:
            before = fh.read()
        self.w("docs/plans/a.md", page("plan"))
        changes, _q = np_layout.apply_drift(self.root, cache_only=True)
        self.assertEqual(len(changes), 1)
        with open(np_layout.manifest_path(self.root)) as fh:
            self.assertEqual(fh.read(), before)
        self.assertTrue(os.path.isfile(np_layout.drift_path(self.root)))
        lay = np_layout.load(self.root)
        paths = [v["path"] for v in lay["routes"]["knowledge"]["variants"]]
        self.assertIn("docs/plans/{name}.md", paths)
        self.assertEqual(np_layout.apply_drift(self.root, cache_only=True)[0], [])

    def test_corrupt_drift_entries_are_dropped(self):
        write(np_layout.manifest_path(self.root), json.dumps(self.layout()))
        write(np_layout.drift_path(self.root), json.dumps([
            {"dir": "../etc", "field": "type", "value": "x", "kind": "knowledge"},
            {"dir": "ok", "field": "type", "value": "y", "kind": "bogus"}]))
        self.assertNotIn("variants", np_layout.load(self.root)["routes"]["knowledge"])

    def test_open_questions_surface_ambiguous_subdirs(self):
        self.w("docs/systems/a.md", page("system"))
        self.w("docs/reviews/a.md", page())
        ids = [q["id"] for q in np_layout.open_questions(self.root, self.layout())]
        self.assertIn("unmapped-dir:docs/reviews", ids)
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
