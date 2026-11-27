# np-test: transcript extractor redaction | happy
"""np-transcript-extract.py redacts provider keys before capture stores excerpts."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_EXTRACT = os.path.join(_SETUP, "np-transcript-extract.py")
sys.path.insert(0, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine")))
import np_scrub  # noqa: E402

# Built at runtime so the engine secret scanner never sees a literal key shape.
_A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
KEYS = [p + _A[:n] for p, n in (
    ("sk" + "-", 22), ("sk" + "-ant-api03-", 24), ("sk" + "-proj-", 22),
    ("sk" + "_live_", 22), ("rk" + "_test_", 22), ("gh" + "p_", 36), ("AK" + "IA", 16),
    ("AI" + "zaSy", 35), ("h" + "f_", 32), ("glp" + "at-", 20), ("xo" + "xb-1234567890-", 12))]


class TestRedact(unittest.TestCase):
    def test_scrub_covers_provider_shapes(self):
        for k in KEYS:
            with self.subTest(k=k):
                self.assertNotIn(k.encode(), np_scrub.scrub(("key " + k).encode()))

    def test_scrub_keeps_plain_prose(self):
        text = b"the task-runner skill handles hf_ prefixes and sk- flags"
        self.assertEqual(np_scrub.scrub(text), text)

    def test_extractor_output_has_no_keys(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "t.jsonl")
        with open(path, "w") as fh:
            for k in KEYS:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "1", "content": "env " + k}]}}) + "\n")
        out = subprocess.run([sys.executable, _EXTRACT, path], capture_output=True, text=True).stdout
        self.assertIn("env ", out)
        for k in KEYS:
            self.assertNotIn(k, out)


if __name__ == "__main__":
    unittest.main()
