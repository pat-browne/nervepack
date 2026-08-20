# np-test: change-spec | happy
"""Tests for np_change_spec -- the change-spec resolver shared by the
drift-guard hook and the spec-guard CI job.

The point of the module is that both gates read one matcher. A test that only
exercised the module in isolation would not catch the two drifting apart, so
the last class here asserts np-spec-guard.py's own helper agrees with it.
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_change_spec  # noqa: E402


class TestBranchSlug(unittest.TestCase):
    def test_slash_becomes_hyphen(self):
        self.assertEqual(np_change_spec.branch_slug("feat/f3-drift-guard"),
                         "feat-f3-drift-guard")

    def test_nested_slashes_all_replaced(self):
        self.assertEqual(np_change_spec.branch_slug("user/feat/thing"),
                         "user-feat-thing")

    def test_plain_branch_unchanged(self):
        self.assertEqual(np_change_spec.branch_slug("main"), "main")


class TestRadius(unittest.TestCase):
    GLOBS = ("engine/setup/tests/**", "docs/ARCHITECTURE.md", "change-specs/**")

    def test_exact_path_glob_matches(self):
        self.assertTrue(np_change_spec.in_radius("docs/ARCHITECTURE.md", self.GLOBS))

    def test_recursive_glob_matches_nested(self):
        self.assertTrue(np_change_spec.in_radius(
            "engine/setup/tests/nervepack_engine/test_x.py", self.GLOBS))

    def test_recursive_glob_matches_direct_child(self):
        self.assertTrue(np_change_spec.in_radius(
            "engine/setup/tests/run-all.sh", self.GLOBS))

    def test_undeclared_path_is_outside(self):
        self.assertFalse(np_change_spec.in_radius("engine/setup/np_toggle.py",
                                                  self.GLOBS))

    def test_sibling_prefix_is_not_a_match(self):
        """`docs/ARCHITECTURE.md` must not admit `docs/ARCHITECTURE.md.bak`."""
        self.assertFalse(np_change_spec.in_radius("docs/ARCHITECTURE.md.bak",
                                                  self.GLOBS))

    def test_empty_globs_admits_nothing(self):
        """A spec with no blast_radius declares no permission, so everything is
        outside it. Failing open here would make an empty field a wildcard."""
        self.assertFalse(np_change_spec.in_radius("anything.py", ()))

    def test_outside_radius_lists_only_offenders(self):
        files = ["docs/ARCHITECTURE.md", "engine/setup/np_toggle.py", "README.md"]
        self.assertEqual(np_change_spec.outside_radius(files, self.GLOBS),
                         ["engine/setup/np_toggle.py", "README.md"])


class TestRepoRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(self.tmp, ".git"))
        os.makedirs(os.path.join(self.tmp, "a", "b"))

    def test_finds_root_from_nested_dir(self):
        self.assertEqual(np_change_spec.repo_root(os.path.join(self.tmp, "a", "b")),
                         self.tmp)

    def test_finds_root_from_the_root_itself(self):
        self.assertEqual(np_change_spec.repo_root(self.tmp), self.tmp)

    def test_finds_root_from_a_path_that_does_not_exist_yet(self):
        """Write creates new files, so the hook routinely sees a path with no
        file and sometimes no directory behind it."""
        target = os.path.join(self.tmp, "a", "b", "new", "deeper", "file.py")
        self.assertEqual(np_change_spec.repo_root(os.path.dirname(target)), self.tmp)

    def test_returns_empty_outside_any_repo(self):
        outside = os.path.realpath(tempfile.mkdtemp())
        self.assertEqual(np_change_spec.repo_root(outside), "")


class TestCurrentBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.git = os.path.join(self.tmp, ".git")
        os.makedirs(self.git)

    def _head(self, text):
        with open(os.path.join(self.git, "HEAD"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_reads_a_symbolic_ref(self):
        self._head("ref: refs/heads/feat/f3-drift-guard\n")
        self.assertEqual(np_change_spec.current_branch(self.tmp),
                         "feat/f3-drift-guard")

    def test_detached_head_has_no_branch(self):
        self._head("9f1a2b3c4d5e6f70819a2b3c4d5e6f7081920304\n")
        self.assertEqual(np_change_spec.current_branch(self.tmp), "")

    def test_missing_head_has_no_branch(self):
        self.assertEqual(np_change_spec.current_branch(self.tmp), "")

    def test_worktree_gitdir_file_is_followed(self):
        """A linked worktree's `.git` is a FILE pointing at the real gitdir.
        Reading it as a directory is how a worktree silently loses its branch."""
        wt = os.path.realpath(tempfile.mkdtemp())
        real = os.path.join(self.git, "worktrees", "wt1")
        os.makedirs(real)
        with open(os.path.join(real, "HEAD"), "w", encoding="utf-8") as fh:
            fh.write("ref: refs/heads/feat/in-a-worktree\n")
        with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: %s\n" % real)
        self.assertEqual(np_change_spec.current_branch(wt), "feat/in-a-worktree")


class TestLoadSpec(unittest.TestCase):
    SPEC = (
        "---\n"
        "id: 0007\n"
        "status: proposed\n"
        "tier: high\n"
        "blast_radius:\n"
        "  - engine/setup/**\n"
        "  - change-specs/**\n"
        "---\n\n# 0007: a spec\n"
    )

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(self.tmp, "change-specs"))

    def _write(self, slug, text):
        with open(os.path.join(self.tmp, "change-specs", slug + ".md"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)

    def test_returns_path_and_globs(self):
        self._write("feat-x", self.SPEC)
        rel, globs = np_change_spec.load(self.tmp, "feat/x")
        self.assertEqual(rel, "change-specs/feat-x.md")
        self.assertEqual(globs, ["engine/setup/**", "change-specs/**"])

    def test_missing_spec_returns_no_path(self):
        rel, globs = np_change_spec.load(self.tmp, "feat/absent")
        self.assertEqual(rel, "")
        self.assertEqual(globs, [])

    def test_spec_without_blast_radius_returns_path_and_no_globs(self):
        """The distinction matters: a present spec with no radius is a policy
        problem spec-guard reports, not an absent spec the hook ignores."""
        self._write("feat-y", "---\nid: 0008\ntier: normal\n---\n")
        rel, globs = np_change_spec.load(self.tmp, "feat/y")
        self.assertEqual(rel, "change-specs/feat-y.md")
        self.assertEqual(globs, [])


class TestSpecGuardAgrees(unittest.TestCase):
    """The whole reason this module exists: np-spec-guard.py must not carry a
    second, independently-drifting copy of the matcher.

    Two assertions, doing different jobs. The identity test is what actually
    holds the line -- it fails the moment someone re-inlines a local copy. The
    behavioral test is the backstop for a re-inlining that also keeps the name
    bound, where identity would pass and behavior would not.
    """

    def setUp(self):
        import importlib.util
        path = os.path.join(_ENGINE_SETUP, "np-spec-guard.py")
        spec = importlib.util.spec_from_file_location("np_spec_guard_under_test", path)
        self.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.guard)

    def test_spec_guard_uses_the_shared_matcher_itself(self):
        self.assertIs(self.guard.diff_outside_blast_radius,
                      np_change_spec.outside_radius)
        self.assertIs(self.guard.branch_slug, np_change_spec.branch_slug)

    def test_same_verdict_on_the_same_inputs(self):
        globs = ["engine/setup/**", "docs/*.md"]
        files = ["engine/setup/np_toggle.py", "docs/ARCHITECTURE.md",
                 "dashboard/build.py", "README.md"]
        self.assertEqual(self.guard.diff_outside_blast_radius(files, globs),
                         np_change_spec.outside_radius(files, globs))

    def test_same_slug(self):
        self.assertEqual(self.guard.branch_slug("feat/f3-drift-guard"),
                         np_change_spec.branch_slug("feat/f3-drift-guard"))


if __name__ == "__main__":
    unittest.main()
