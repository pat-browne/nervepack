"""Tests for np_content.layer_dir() — the single-root sibling of merge_roots(),
mirroring bash np-content-lib.sh's np_layer_dir (content_dir()/memory/<layer>)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import np_content  # noqa: E402


class TestLayerDir(unittest.TestCase):
    def test_layer_dir_is_content_dir_slash_memory_slash_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": tmp}):
                self.assertEqual(np_content.layer_dir("lessons"), os.path.join(tmp, "memory", "lessons"))

    def test_layer_dir_reflects_a_different_layer_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": tmp}):
                self.assertEqual(np_content.layer_dir("episodic"), os.path.join(tmp, "memory", "episodic"))


if __name__ == "__main__":
    unittest.main()
