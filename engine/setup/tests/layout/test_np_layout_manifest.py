# np-test: layout | happy
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nervepack_engine"))
import np_layout


def _layout():
    return {
        "schema": 1,
        "routes": {
            "skill": {"path": "skills/{name}/SKILL.md"},
            "roadmap": {"path": "ROADMAP.md", "append": True},
        },
        "index": "INDEX.md",
        "links": "wikilink",
    }


class TestManifest(unittest.TestCase):
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

    def _write(self, data):
        p = np_layout.manifest_path(self.root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            if isinstance(data, str):
                fh.write(data)
            else:
                json.dump(data, fh)

    def test_manifest_path_is_dot_nervepack(self):
        self.assertEqual(np_layout.manifest_path(self.root),
                         os.path.join(self.root, ".nervepack", "layout.json"))

    def test_load_returns_none_when_absent(self):
        self.assertIsNone(np_layout.load(self.root))

    def test_load_reads_a_written_manifest(self):
        self._write(_layout())
        got = np_layout.load(self.root)
        self.assertEqual(got["routes"]["skill"]["path"], "skills/{name}/SKILL.md")

    def test_load_rejects_wrong_schema(self):
        bad = _layout()
        bad["schema"] = 99
        self._write(bad)
        with self.assertRaises(np_layout.LayoutError):
            np_layout.load(self.root)

    def test_load_rejects_non_object_routes(self):
        bad = _layout()
        bad["routes"] = ["skills"]
        self._write(bad)
        with self.assertRaises(np_layout.LayoutError):
            np_layout.load(self.root)

    def test_load_rejects_unparseable_json(self):
        self._write("{not json")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.load(self.root)

    def test_validate_rejects_absolute_route(self):
        bad = _layout()
        bad["routes"]["skill"] = {"path": "/etc/{name}"}
        with self.assertRaises(np_layout.LayoutError):
            np_layout.validate(bad)

    def test_validate_rejects_route_with_no_path(self):
        bad = _layout()
        bad["routes"]["skill"] = {"frontmatter": {"kind": "x"}}
        with self.assertRaises(np_layout.LayoutError):
            np_layout.validate(bad)

    def test_validate_rejects_bad_links_value(self):
        bad = _layout()
        bad["links"] = "hyperlink"
        with self.assertRaises(np_layout.LayoutError):
            np_layout.validate(bad)

    def test_validate_accepts_variants(self):
        ok = _layout()
        ok["routes"]["knowledge"] = {"variants": [
            {"name": "concept", "when": "r", "path": "wiki/concepts/{name}.md"}]}
        self.assertIs(np_layout.validate(ok), ok)


if __name__ == "__main__":
    unittest.main()
