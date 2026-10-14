"""Regression guard: the engine working tree must be scan-clean.

Personal content now lives in a separate overlay repo (NP_CONTENT_DIR), so the
engine repo's whole tree IS the publishable surface. This test runs the real PII
guard (publish/np-publish-scan.py) against the engine repo root and asserts it
exits 0 — i.e. no secrets/PII (beyond the vetted fake-token allowlist) have
crept into a tracked engine file. It is the local mirror of the CI PII guard.
"""
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
# Scan the actual working tree under test (the branch checked out HERE), so this local
# mirror catches PII on THIS branch — not some other checkout. --show-toplevel gives the
# worktree root; the scanner skips a `.git` pointer file the same as a `.git` dir, so a
# worktree root scans cleanly without the /home/... false positive.
REPO = subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], cwd=_HERE, text=True
).strip()
SCAN = os.path.join(REPO, "publish", "np-publish-scan.py")


class TestNoEnginePII(unittest.TestCase):
    def test_engine_tree_is_scan_clean(self):
        r = subprocess.run([sys.executable, SCAN, REPO], capture_output=True, text=True)
        self.assertEqual(
            r.returncode, 0,
            f"PII guard found secrets/PII in the engine tree:\n{r.stdout}\n{r.stderr}",
        )

    def test_no_tracked_venv(self):
        # The scanner skips .venv, so a force-added venv must fail here instead.
        files = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).splitlines()
        tracked = [f for f in files if ".venv" in f.split("/")]
        self.assertEqual(tracked, [], "a .venv path is tracked; the PII scan skips it")

    def test_scan_skips_venv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".venv", "bin"))
            with open(os.path.join(d, ".venv", "bin", "activate"), "w") as f:
                f.write("# maintainer someone.real@gmail.com\n")
            r = subprocess.run([sys.executable, SCAN, d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
