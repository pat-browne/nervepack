"""np_generate_index.py --help prints usage and writes nothing."""
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.normpath(os.path.join(_HERE, "..", "..", "np_generate_index.py"))


def _snapshot(root):
    return sorted((p, os.stat(os.path.join(p)).st_mtime_ns)
                  for p in (os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs))


class HelpFlag(unittest.TestCase):
    def _run(self, flag):
        with tempfile.TemporaryDirectory() as d:
            skills = os.path.join(d, "skills", "np-core-demo")
            os.makedirs(skills)
            with open(os.path.join(skills, "SKILL.md"), "w") as fh:
                fh.write("---\nname: np-core-demo\ndescription: Demo skill.\n---\n# Demo\n")
            before = _snapshot(d)
            env = dict(os.environ, NP_DIR=d, NP_CONTENT_DIR=d,
                       HOME=d, XDG_CONFIG_HOME=os.path.join(d, "cfg"))
            r = subprocess.run([sys.executable, _SCRIPT, flag], capture_output=True,
                               text=True, env=env, cwd=d)
            self.assertEqual(_snapshot(d), before)
            self.assertFalse(os.path.exists(os.path.join(d, "INDEX.md")))
            return r

    def test_long_flag(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage:", r.stdout)
        self.assertNotIn("wrote", r.stdout)

    def test_short_flag(self):
        r = self._run("-h")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage:", r.stdout)


if __name__ == "__main__":
    unittest.main()
