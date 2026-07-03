#!/usr/bin/env python3
"""Contract test for np-graduation-detect.py (stdlib unittest, per language policy).
Black-box: builds a fake memory/lessons/ tree and asserts the emitted JSON.
The detector flags auto-distilled lessons that have proven themselves (high `seen`)
or outgrown a skill's body budget (bytes) as candidates to graduate into a
human-reviewed skill — it never acts, only surfaces. The candidate `kind` carries
the lesson's `provenance` (failure|success)."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DET = os.path.join(HERE, "..", "..", "np-graduation-detect.py")


def make_entry(root, name, *, seen=1, body_bytes=900, status="candidate", provenance="failure"):
    os.makedirs(root, exist_ok=True)
    fm = ("---\nname: %s\nkind: lesson\nprovenance: %s\nstatus: %s\nseen: %d\n---\n"
          % (name, provenance, status, seen))
    pad = "x" * max(0, body_bytes - len(fm.encode()))
    with open(os.path.join(root, name + ".md"), "w") as fh:
        fh.write(fm + pad)


def run(lessons_dir, **env):
    e = dict(os.environ)
    e.update(env)
    out = subprocess.run(["python3", DET, lessons_dir], env=e,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class TestGraduationDetect(unittest.TestCase):
    def test_flags_high_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "proven", seen=30)
            make_entry(tmp, "fresh", seen=2)
            r = run(tmp, GRADUATE_SEEN="10", GRADUATE_KB="6")
            names = [c["name"] for c in r["candidates"]]
            self.assertEqual(names, ["proven"])
            self.assertIn("seen", r["candidates"][0]["reasons"])

    def test_flags_over_budget_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "fat", seen=2, body_bytes=7000)   # > 6KB, low seen
            r = run(tmp, GRADUATE_SEEN="10", GRADUATE_KB="6")
            self.assertEqual([c["name"] for c in r["candidates"]], ["fat"])
            self.assertIn("bytes", r["candidates"][0]["reasons"])

    def test_skips_already_graduated(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "done", seen=99, status="graduated")
            make_entry(tmp, "promoted", seen=99, status="promoted")
            r = run(tmp, GRADUATE_SEEN="10")
            self.assertEqual(r["candidates"], [])

    def test_reports_kind_from_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "s1", seen=20, provenance="success")
            make_entry(tmp, "p1", seen=20, provenance="failure")
            r = run(tmp, GRADUATE_SEEN="10")
            kinds = {c["name"]: c["kind"] for c in r["candidates"]}
            self.assertEqual(kinds, {"s1": "success", "p1": "failure"})

    def test_ignores_index_and_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "real", seen=20)
            # INDEX.md / README.md are generated, not graduatable entries
            with open(os.path.join(tmp, "INDEX.md"), "w") as fh:
                fh.write("x" * 9000)
            with open(os.path.join(tmp, ".gitkeep"), "w") as fh:
                fh.write("")
            r = run(tmp, GRADUATE_SEEN="10")
            self.assertEqual([c["name"] for c in r["candidates"]], ["real"])

    def test_thresholds_are_tunable(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_entry(tmp, "mid", seen=5)
            r = run(tmp, GRADUATE_SEEN="4")  # lower the bar
            self.assertEqual([c["name"] for c in r["candidates"]], ["mid"])

    def test_missing_dir_fail_open(self):
        r = run("/nonexistent/lessons")
        self.assertEqual(r["candidates"], [])


if __name__ == "__main__":
    unittest.main()
