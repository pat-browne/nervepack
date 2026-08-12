"""Tests for np_turn_parse -- the pure transcript-turn extractor behind the
turn-completion gate. Fixtures are built inline as JSONL so the tests stay
hermetic and readable."""
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_turn_parse  # noqa: E402


def _user(text, typed=True):
    rec = {"type": "user", "message": {"content": text}}
    if typed:
        rec["promptSource"] = "typed"
    return rec


def _tool_use(name, inp):
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _tool_result_image():
    return {"type": "user",
            "message": {"content": [{"type": "tool_result",
                                     "content": [{"type": "image", "source": {}}]}]}}


def _assistant_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class TestTurnParse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, records):
        path = os.path.join(self.tmp, "t.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def test_ui_edit_without_delivery(self):
        p = self._write([_user("change the button"),
                         _tool_use("Edit", {"file_path": "/app/Button.tsx"})])
        turn = np_turn_parse.parse(p)
        self.assertEqual(turn.edits, ["/app/Button.tsx"])
        self.assertEqual(turn.delivery, [])

    def test_tool_result_image_counts_as_delivery(self):
        p = self._write([_user("change it"),
                         _tool_use("Edit", {"file_path": "/app/a.css"}),
                         _tool_result_image()])
        self.assertTrue(np_turn_parse.parse(p).delivery)

    def test_send_user_file_counts_as_delivery(self):
        p = self._write([_user("go"),
                         _tool_use("SendUserFile", {"files": ["/tmp/shot.png"]})])
        self.assertTrue(np_turn_parse.parse(p).delivery)

    def test_read_of_image_counts_as_delivery(self):
        p = self._write([_user("go"),
                         _tool_use("Read", {"file_path": "/tmp/shot.png"})])
        self.assertTrue(np_turn_parse.parse(p).delivery)

    def test_browser_open_counts_as_delivery(self):
        p = self._write([_user("go"),
                         _tool_use("Bash", {"command": "xdg-open http://localhost:3000"})])
        self.assertTrue(np_turn_parse.parse(p).delivery)

    def test_np_md_diff_bash_call_counts_as_diff_delivery(self):
        p = self._write([_user("go"),
                         _tool_use("Bash", {"command": "python3 np-md-diff.py FILE.md --out /tmp"})])
        self.assertTrue(any("np-md-diff" in d for d in np_turn_parse.parse(p).delivery))

    def test_screenshot_mcp_counts_as_delivery(self):
        p = self._write([_user("go"),
                         _tool_use("mcp__Claude_Browser__computer",
                                   {"action": "screenshot"})])
        self.assertTrue(np_turn_parse.parse(p).delivery)

    def test_only_the_last_turn_is_considered(self):
        p = self._write([_user("first"),
                         _tool_use("Edit", {"file_path": "/app/old.tsx"}),
                         _user("second"),
                         _tool_use("Edit", {"file_path": "/app/new.tsx"})])
        self.assertEqual(np_turn_parse.parse(p).edits, ["/app/new.tsx"])

    def test_tool_result_user_record_is_not_a_turn_boundary(self):
        # A tool_result arrives as type:"user" with no promptSource. If it were
        # treated as the boundary, the edit before it would be invisible.
        p = self._write([_user("go"),
                         _tool_use("Edit", {"file_path": "/app/a.tsx"}),
                         {"type": "user",
                          "message": {"content": [{"type": "tool_result", "content": "ok"}]}}])
        self.assertEqual(np_turn_parse.parse(p).edits, ["/app/a.tsx"])

    def test_final_text_is_the_last_assistant_text(self):
        p = self._write([_user("go"), _assistant_text("first"), _assistant_text("last")])
        self.assertEqual(np_turn_parse.parse(p).final_text, "last")

    def test_malformed_line_is_skipped_not_fatal(self):
        path = os.path.join(self.tmp, "bad.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_user("go")) + "\n")
            fh.write("{not json\n")
            fh.write(json.dumps(_tool_use("Edit", {"file_path": "/a.tsx"})) + "\n")
        self.assertEqual(np_turn_parse.parse(path).edits, ["/a.tsx"])

    def test_missing_file_returns_empty_turn(self):
        turn = np_turn_parse.parse(os.path.join(self.tmp, "nope.jsonl"))
        self.assertEqual(turn.edits, [])
        self.assertEqual(turn.delivery, [])
        self.assertEqual(turn.final_text, "")

    def test_no_typed_user_message_scans_whole_file(self):
        # A transcript with no typed prompt still yields its edits rather than
        # silently returning empty, so the gate degrades to conservative.
        p = self._write([_tool_use("Edit", {"file_path": "/a.tsx"})])
        self.assertEqual(np_turn_parse.parse(p).edits, ["/a.tsx"])


if __name__ == "__main__":
    unittest.main()
