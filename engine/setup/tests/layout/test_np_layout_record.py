# np-test: layout | happy
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nervepack_engine"))
import np_layout

LAYOUT = {"schema": 1, "routes": {"skill": {"path": "skills/{name}/SKILL.md"}}}


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nplayout-")
        self.home = tempfile.mkdtemp(prefix="nphome-")
        self._old_home = os.environ.get("HOME")
        # HOME alone no longer isolates state: np_dirs honours XDG_CACHE_HOME
        # and XDG_CONFIG_HOME (#299), and the shell harness exports both. Point
        # them at the new HOME so this stays hermetic.
        os.environ["HOME"] = self.home
        for _v in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            os.environ.pop(_v, None)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        os.chmod(self.root, stat.S_IRWXU)
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_record_writes_manifest_and_round_trips(self):
        written = np_layout.record(self.root, LAYOUT)
        self.assertEqual(written, np_layout.manifest_path(self.root))
        self.assertEqual(np_layout.load(self.root)["routes"]["skill"]["path"],
                         "skills/{name}/SKILL.md")

    def test_record_strips_internal_source_marker(self):
        layout = dict(LAYOUT)
        layout["_source"] = "inferred"
        np_layout.record(self.root, layout)
        with open(np_layout.manifest_path(self.root), encoding="utf-8") as fh:
            self.assertNotIn("_source", json.load(fh))

    def test_record_rejects_an_invalid_layout(self):
        with self.assertRaises(np_layout.LayoutError):
            np_layout.record(self.root, {"schema": 99, "routes": {}})

    def test_record_leaves_no_temp_file(self):
        np_layout.record(self.root, LAYOUT)
        leftovers = [f for f in os.listdir(os.path.join(self.root, ".nervepack"))
                     if f != "layout.json"]
        self.assertEqual(leftovers, [])

    def test_record_is_idempotent(self):
        first = np_layout.record(self.root, LAYOUT)
        with open(first, encoding="utf-8") as fh:
            a = fh.read()
        np_layout.record(self.root, LAYOUT)
        with open(first, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), a)

    def test_record_output_is_stable_and_sorted(self):
        np_layout.record(self.root, LAYOUT)
        with open(np_layout.manifest_path(self.root), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.endswith("\n"))
        self.assertIn('"schema": 1', text)

    def _block_manifest_dir(self):
        """Make <root>/.nervepack/ impossible to create, on every OS.

        A chmod'd directory is NOT portable for this: Windows ignores POSIX mode
        bits on directories, so the layer stays writable under Git-bash and the
        fallback never fires (caught by the Windows CI lane). Occupying the path
        with a regular file makes os.makedirs raise FileExistsError everywhere."""
        with open(os.path.join(self.root, ".nervepack"), "w") as fh:
            fh.write("not a directory\n")

    def test_unwritable_layer_falls_back_to_cache(self):
        self._block_manifest_dir()
        written = np_layout.record(self.root, LAYOUT)
        self.assertTrue(written.startswith(os.path.join(self.home, ".config",
                                                        "nervepack", "layouts")),
                        written)
        self.assertTrue(os.path.isfile(written))

    def test_load_reads_the_cache_when_layer_has_no_manifest(self):
        self._block_manifest_dir()
        np_layout.record(self.root, LAYOUT)
        self.assertEqual(np_layout.load(self.root)["routes"]["skill"]["path"],
                         "skills/{name}/SKILL.md")

    @unittest.skipUnless(os.name == "posix", "Windows ignores directory mode bits")
    @unittest.skipIf(os.geteuid() == 0 if hasattr(os, "geteuid") else False,
                     "root bypasses directory mode bits")
    def test_readonly_layer_dir_falls_back_to_cache(self):
        # The real-world shape of the same failure: a read-only checkout.
        os.chmod(self.root, stat.S_IRUSR | stat.S_IXUSR)
        written = np_layout.record(self.root, LAYOUT)
        self.assertTrue(written.startswith(os.path.join(self.home, ".config",
                                                        "nervepack", "layouts")),
                        written)

    def test_cache_path_is_stable_for_a_root(self):
        self.assertEqual(np_layout.cache_path(self.root),
                         np_layout.cache_path(self.root))

    def test_cache_path_differs_for_same_basename_in_different_trees(self):
        a = os.path.join(self.home, "one", "content")
        b = os.path.join(self.home, "two", "content")
        os.makedirs(a)
        os.makedirs(b)
        self.assertNotEqual(np_layout.cache_path(a), np_layout.cache_path(b))

    def test_layer_manifest_wins_over_a_stale_cache(self):
        np_layout.record(self.root, LAYOUT)                 # writes the layer file
        cache = np_layout.cache_path(self.root)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "routes": {"skill": {"path": "STALE/{name}.md"}}}, fh)
        self.assertEqual(np_layout.load(self.root)["routes"]["skill"]["path"],
                         "skills/{name}/SKILL.md")


if __name__ == "__main__":
    unittest.main()
