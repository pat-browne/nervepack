"""Direct unit tests for np_instruction_block.py -- port of
np-instruction-block.sh. Ports the 6 scenarios from test_instruction_block.sh,
plus 2 new cases (exact blank-line behavior) added during the port -- see
the phase-11 plan."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_instruction_block  # noqa: E402


class TestInstructionBlock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.directive_path = "/opt/np/nervepack-session-directive.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self, path):
        with open(path) as fh:
            return fh.read()

    def test_1_install_preserves_content_and_adds_one_block(self):
        f = os.path.join(self.tmp, "CLAUDE.md")
        with open(f, "w") as fh:
            fh.write("# My project rules\n\nUse tabs.\n")
        np_instruction_block.install(f, directive_path=self.directive_path)
        content = self._read(f)
        self.assertIn("Use tabs.", content)
        self.assertEqual(content.count("nervepack:begin"), 1)
        self.assertIn("@" + self.directive_path, content)
        # Exact bash semantics: [[ -s "$file" ]] && printf '\n' is
        # UNCONDITIONAL on non-empty size, not on missing trailing newline --
        # a file already ending in "\n" still gets a second blank line
        # before the block. Locks this down explicitly (grep-based bash
        # assertions never caught this; a prior draft of this port got it
        # wrong in exactly this spot).
        self.assertEqual(
            content,
            "# My project rules\n\nUse tabs.\n\n"
            + np_instruction_block.BEGIN + "\n"
            + "@" + self.directive_path + "\n"
            + np_instruction_block.END + "\n")

    def test_1b_install_on_empty_file_has_no_leading_blank_line(self):
        f = os.path.join(self.tmp, "empty.md")
        open(f, "w").close()
        np_instruction_block.install(f, directive_path=self.directive_path)
        content = self._read(f)
        self.assertEqual(
            content,
            np_instruction_block.BEGIN + "\n"
            + "@" + self.directive_path + "\n"
            + np_instruction_block.END + "\n")

    def test_2_install_idempotent(self):
        f = os.path.join(self.tmp, "CLAUDE.md")
        with open(f, "w") as fh:
            fh.write("# My project rules\n\nUse tabs.\n")
        np_instruction_block.install(f, directive_path=self.directive_path)
        np_instruction_block.install(f, directive_path=self.directive_path)
        content = self._read(f)
        self.assertEqual(content.count("nervepack:begin"), 1)
        self.assertIn("Use tabs.", content)

    def test_3_remove_strips_block_preserves_content(self):
        f = os.path.join(self.tmp, "CLAUDE.md")
        with open(f, "w") as fh:
            fh.write("# My project rules\n\nUse tabs.\n")
        np_instruction_block.install(f, directive_path=self.directive_path)
        np_instruction_block.remove(f)
        content = self._read(f)
        self.assertEqual(content.count("nervepack:begin"), 0)
        self.assertIn("Use tabs.", content)
        self.assertNotIn("nervepack:", content)

    def test_4_install_creates_missing_target(self):
        g = os.path.join(self.tmp, "sub", "AGENTS.md")
        np_instruction_block.install(g, directive_path=self.directive_path)
        self.assertTrue(os.path.isfile(g))
        self.assertEqual(self._read(g).count("nervepack:begin"), 1)

    def test_5_remove_preserves_trailing_content_added_after_install(self):
        h = os.path.join(self.tmp, "CLAUDE_with_trailing.md")
        with open(h, "w") as fh:
            fh.write("# My instructions\n\nInitial content.\n")
        np_instruction_block.install(h, directive_path=self.directive_path)
        with open(h, "a") as fh:
            fh.write("TRAILING user line\n")
        np_instruction_block.remove(h)
        content = self._read(h)
        self.assertIn("TRAILING user line", content)
        self.assertNotIn("nervepack:", content)

    def test_6_remove_handles_lone_begin_marker(self):
        i = os.path.join(self.tmp, "CLAUDE_lone_begin.md")
        begin = "<!-- nervepack:begin (managed — do not edit; remove via np-instruction-block.sh remove) -->"
        with open(i, "w") as fh:
            fh.write(begin + "\nORPHAN user content\n")
        np_instruction_block.remove(i)
        content = self._read(i)
        self.assertIn("ORPHAN user content", content)

    def test_7_empty_file_path_raises(self):
        with self.assertRaises(ValueError):
            np_instruction_block.install("")
        with self.assertRaises(ValueError):
            np_instruction_block.remove("")


if __name__ == "__main__":
    unittest.main()
