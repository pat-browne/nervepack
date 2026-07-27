"""#176: unit tests for np_transcripts.extract_cwd — the transcript cwd line-scan
that was byte-identical in backcapture_sweep, resume_sessionstart, resume_write."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_transcripts  # noqa: E402


class TestExtractCwd(unittest.TestCase):
    def _write(self, content):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.addCleanup(os.remove, p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def test_returns_first_cwd(self):
        p = self._write('{"type":"x"}\n{"cwd":"/home/u/proj","t":1}\n{"cwd":"/other"}\n')
        self.assertEqual(np_transcripts.extract_cwd(p), "/home/u/proj")

    def test_json_unescapes_the_value(self):
        p = self._write('{"cwd":"/tmp/a b\\u002fc"}\n')  # \\u002f == '/'
        self.assertEqual(np_transcripts.extract_cwd(p), "/tmp/a b/c")

    def test_none_when_no_cwd_line(self):
        p = self._write('{"type":"x"}\n{"foo":"bar"}\n')
        self.assertIsNone(np_transcripts.extract_cwd(p))

    def test_none_when_file_unreadable(self):
        self.assertIsNone(np_transcripts.extract_cwd("/no/such/file/xyz.jsonl"))


if __name__ == "__main__":
    unittest.main()
