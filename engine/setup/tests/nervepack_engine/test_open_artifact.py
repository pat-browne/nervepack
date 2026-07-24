"""Tests for nervepack_engine.hooks.open_artifact -- the PostToolUse hook that
opens a spec/plan doc when a Write call creates one under
docs/superpowers/{specs,plans}/*.md. See
docs/superpowers/specs/2026-07-21-open-artifact-on-write-design.md.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_dashboard  # noqa: E402
from nervepack_engine.hooks import open_artifact  # noqa: E402


class TestOpenArtifact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("focus|shared|runtime|on|\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_DASH_OPENER": "true",  # a real, harmless no-op binary on PATH
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def _spec_path(self, name="2026-07-21-thing-design.md"):
        d = os.path.join(self.tmp, "docs", "superpowers", "specs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "w") as fh:
            fh.write("# spec\n")
        return p

    def _plan_path(self, name="2026-07-21-thing.md"):
        d = os.path.join(self.tmp, "docs", "superpowers", "plans")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "w") as fh:
            fh.write("# plan\n")
        return p

    def _payload(self, file_path, tool_name="Write"):
        return json.dumps({
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path, "content": "x"},
            "cwd": self.tmp,
        })

    def test_1_spec_write_opens(self):
        p = self._spec_path()
        calls = []
        out = open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(out, "")
        self.assertEqual(calls, [p])

    def test_2_plan_write_opens(self):
        p = self._plan_path()
        calls = []
        open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [p])

    def test_3_non_matching_doc_does_not_open(self):
        d = os.path.join(self.tmp, "docs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "README.md")
        with open(p, "w") as fh:
            fh.write("# readme\n")
        calls = []
        open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [])

    def test_4_non_write_tool_does_not_open(self):
        p = self._spec_path()
        calls = []
        open_artifact.run(self._payload(p, tool_name="Edit"), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [])

    def test_5_toggle_off_does_not_open(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("focus|shared|runtime|off|\n")
        p = self._spec_path()
        calls = []
        open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [])

    def test_6_missing_file_on_disk_does_not_open(self):
        p = os.path.join(self.tmp, "docs", "superpowers", "specs", "ghost.md")
        calls = []
        open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [])

    def test_7_no_opener_available_fails_open(self):
        p = self._spec_path()
        with mock.patch.object(np_dashboard, "resolve_opener", return_value=""):
            calls = []
            out = open_artifact.run(self._payload(p), opener_fn=lambda path: calls.append(path))
        self.assertEqual(out, "")
        self.assertEqual(calls, [])

    def test_8_relative_file_path_resolved_against_cwd(self):
        p = self._spec_path()
        rel = os.path.relpath(p, self.tmp)
        calls = []
        open_artifact.run(self._payload(rel), opener_fn=lambda path: calls.append(path))
        self.assertEqual(calls, [p])

    def test_9_bad_json_fails_open(self):
        calls = []
        out = open_artifact.run("not json", opener_fn=lambda path: calls.append(path))
        self.assertEqual(out, "")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
