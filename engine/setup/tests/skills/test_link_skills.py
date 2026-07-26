#!/usr/bin/env python3
# np-test: link-skills | happy
"""np_link_skills.link(): symlink refresh (prune broken, repoint overridden, skip
external) + in-process INDEX regen. The actual-symlink assertions are skipped on
Windows (symlink creation is privilege-gated on the CI lane); the INDEX-regen half
is host-agnostic and always asserted."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_link_skills  # noqa: E402


class LinkSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(_rmtree, self.tmp)
        self.eng = os.path.join(self.tmp, "engine")
        self.ov = os.path.join(self.tmp, "overlay")
        self.dst = os.path.join(self.tmp, "dst")
        for name, root, desc in (("np-eng-a", self.eng, "engine a"),
                                 ("np-kb-b", self.ov, "overlay b")):
            d = os.path.join(root, "skills", name)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w") as fh:
                fh.write("---\nname: %s\ndescription: %s\n---\n" % (name, desc))
        os.makedirs(self.dst)
        self.env = dict(os.environ)
        os.environ["NP_DIR"] = self.eng
        os.environ["NP_CONTENT_DIR"] = self.ov
        os.environ["NP_SKILLS_DST"] = self.dst
        os.environ["HOME"] = self.tmp
        os.environ.pop("NP_TEAM_DIR", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self.env)

    def _out(self):
        import io
        return io.StringIO()

    def test_index_regen_is_host_agnostic(self):
        # The INDEX regen runs regardless of symlink support.
        rc = np_link_skills.link(out=self._out())
        self.assertEqual(rc, 0)
        eng_index = os.path.join(self.eng, "INDEX.md")
        ov_index = os.path.join(self.ov, "INDEX.md")
        self.assertTrue(os.path.isfile(eng_index))
        with open(eng_index) as fh:
            body = fh.read()
        self.assertIn("np-eng-a", body)
        self.assertNotIn("np-kb-b", body)          # engine index stays engine-only
        with open(ov_index) as fh:
            merged = fh.read()
        self.assertIn("np-eng-a", merged)
        self.assertIn("np-kb-b", merged)           # overlay index is merged

    @unittest.skipIf(os.name == "nt", "symlink creation privilege-gated on Windows")
    def test_symlinks_created(self):
        np_link_skills.link(out=self._out())
        a = os.path.join(self.dst, "np-eng-a")
        b = os.path.join(self.dst, "np-kb-b")
        self.assertTrue(os.path.islink(a))
        self.assertTrue(os.path.islink(b))
        self.assertEqual(os.readlink(a), os.path.join(self.eng, "skills", "np-eng-a"))

    @unittest.skipIf(os.name == "nt", "symlink creation privilege-gated on Windows")
    def test_prunes_broken_managed_link(self):
        # A dangling symlink whose target is under a managed base is pruned.
        gone = os.path.join(self.eng, "skills", "np-eng-gone")
        broken = os.path.join(self.dst, "np-eng-gone")
        os.symlink(gone, broken)                    # target does not exist
        self.assertTrue(os.path.islink(broken))
        np_link_skills.link(out=self._out())
        self.assertFalse(os.path.lexists(broken))

    @unittest.skipIf(os.name == "nt", "symlink creation privilege-gated on Windows")
    def test_external_symlink_left_alone(self):
        # A symlink to an unmanaged target is never touched.
        ext_target = os.path.join(self.tmp, "somewhere-else")
        os.makedirs(ext_target)
        ext_link = os.path.join(self.dst, "np-eng-a")   # same name as a managed skill
        os.symlink(ext_target, ext_link)
        np_link_skills.link(out=self._out())
        self.assertEqual(os.readlink(ext_link), ext_target)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
