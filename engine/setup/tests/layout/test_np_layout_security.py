# np-test: layout | failure
"""A manifest arrives inside a repo, and a team overlay syncs from a remote other
people write to. Route templates and the {name}/{topic} values are therefore
attacker-reachable input to a file write. route() must refuse, never return."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nervepack_engine"))
import np_layout


def _with_route(path):
    return {"schema": 1, "routes": {"skill": {"path": path}}}


class TestSecurity(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nplayout-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_traversal_route_raises(self):
        layout = _with_route("../../../.ssh/{name}")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root,
                            values={"name": "authorized_keys"})

    def test_absolute_route_raises(self):
        layout = _with_route("/etc/{name}")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "passwd"})

    def test_traversal_in_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "../../etc"})

    def test_slash_in_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "a/b"})

    def test_dotdot_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": ".."})

    def test_dot_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "."})

    def test_empty_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": ""})

    def test_windows_backslash_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "a\\b"})

    def test_null_byte_value_raises(self):
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "a\x00b"})

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_escape_raises(self):
        outside = tempfile.mkdtemp(prefix="nplayout-out-")
        self.addCleanup(shutil.rmtree, outside, True)
        try:
            os.symlink(outside, os.path.join(self.root, "skills"))
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted here")
        layout = _with_route("skills/{name}/SKILL.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root, values={"name": "x"})

    def test_traversal_route_with_no_placeholder_raises(self):
        layout = _with_route("../escape.md")
        with self.assertRaises(np_layout.LayoutError):
            np_layout.route(layout, "skill", self.root)

    def test_safe_route_still_returns(self):
        layout = _with_route("skills/{name}/SKILL.md")
        self.assertEqual(
            np_layout.route(layout, "skill", self.root, values={"name": "ok-1.2"}),
            "skills/ok-1.2/SKILL.md")


if __name__ == "__main__":
    unittest.main()
