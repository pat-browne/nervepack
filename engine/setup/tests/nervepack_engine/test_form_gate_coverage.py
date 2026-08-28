"""Tests for form_gate's delta linting and widened coverage (spec 0021).

Two changes are under test.

**Delta linting on Write.** Write replaces a whole file, so linting the whole
payload scores prose the author may never have touched. That is what produced
the 579-violation corpus reading that kept `categorical` pinned to `warn`. Edit
already lints only `new_string`; Write now matches it.

**Coverage.** The gate read four file extensions and four MCP tool suffixes.
The skill names review-thread replies as the highest-volume text a reviewer
reads, and not one of them was gated.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hooks import form_gate  # noqa: E402

DIRTY = "We have a robust solution; it is seamless."     # semicolon + 2 marketing
CLEAN = "The parser reads the file. It writes one row per record."


def _fake_lint(text, timeout_s):
    """Stand in for the overlay linter.

    The real one lives in the content overlay, which the CI runner isolates per
    test, so a test that shells to it passes alone and fails in the suite. What
    these cases are actually about is WHICH TEXT reaches the linter, so a stub
    that scores the text it is handed tests the thing and stays hermetic.
    """
    low = text.lower()
    violations = {
        "semicolon": text.count(";"),
        "em_dash": text.count("\u2014"),
        "contraction": 0,
        "marketing_adjective": sum(low.count(w) for w in ("robust", "seamless")),
    }
    words = max(len(text.split()), 1)
    return {"violations": violations,
            "total_per100w": 100.0 * sum(violations.values()) / words}


class FormGateCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, tool, tool_input, **params):
        def fake_param(key, default=None):
            return params.get(key, default)

        with mock.patch.object(form_gate.np_toggle, "enabled", return_value=True), \
             mock.patch.object(form_gate.np_toggle, "param", side_effect=fake_param), \
             mock.patch.object(form_gate.np_toggle, "signal", return_value=None), \
             mock.patch.object(form_gate, "_lint", side_effect=_fake_lint):
            return form_gate.run(json.dumps({"session_id": "s1",
                                             "tool_name": tool,
                                             "tool_input": tool_input}))

    def _decision(self, out):
        if not out:
            return None
        return json.loads(out)["hookSpecificOutput"].get("permissionDecision")

    def _reason(self, out):
        block = json.loads(out)["hookSpecificOutput"]
        return block.get("permissionDecisionReason") or block.get("additionalContext") or ""

    def _file(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    # --- ask mode ----------------------------------------------------------
    def test_categorical_ask_pauses_the_write(self):
        out = self._run("Write", {"file_path": os.path.join(self.tmp.name, "n.md"),
                                  "content": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")
        self.assertIn("semicolon", self._reason(out))

    def test_categorical_warn_still_only_warns(self):
        out = self._run("Write", {"file_path": os.path.join(self.tmp.name, "n.md"),
                                  "content": DIRTY},
                        **{"form_gate.categorical": "warn"})
        self.assertEqual(self._decision(out), "allow")

    # --- delta linting on Write -------------------------------------------
    def test_write_onto_existing_file_ignores_inherited_violations(self):
        """The change that unblocks `ask`. The legacy line is still in the
        payload, and it must not be scored against this write."""
        path = self._file("legacy.md", DIRTY + "\n")
        out = self._run("Write", {"file_path": path,
                                  "content": DIRTY + "\n" + CLEAN + "\n"},
                        **{"form_gate.categorical": "ask", "form_gate.rate": "off"})
        self.assertEqual(out, "")

    def test_write_onto_existing_file_still_catches_new_violations(self):
        path = self._file("legacy.md", CLEAN + "\n")
        out = self._run("Write", {"file_path": path,
                                  "content": CLEAN + "\n" + DIRTY + "\n"},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")

    def test_write_of_a_new_file_lints_everything(self):
        out = self._run("Write", {"file_path": os.path.join(self.tmp.name, "new.md"),
                                  "content": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")

    def test_unchanged_rewrite_is_silent(self):
        path = self._file("same.md", DIRTY + "\n")
        out = self._run("Write", {"file_path": path, "content": DIRTY + "\n"},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(out, "")

    def test_edit_is_unchanged_and_still_lints_new_string_only(self):
        out = self._run("Edit", {"file_path": os.path.join(self.tmp.name, "e.md"),
                                 "old_string": "x", "new_string": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")

    # --- extension coverage -------------------------------------------------
    def test_prose_ext_is_a_toggle_param(self):
        out = self._run("Write", {"file_path": os.path.join(self.tmp.name, "n.rst"),
                                  "content": DIRTY},
                        **{"form_gate.categorical": "ask",
                           "form_gate.prose_ext": ".rst"})
        self.assertEqual(self._decision(out), "ask")

    def test_source_files_stay_out_of_scope(self):
        out = self._run("Write", {"file_path": os.path.join(self.tmp.name, "a.py"),
                                  "content": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(out, "")

    # --- widened MCP coverage ----------------------------------------------
    def _mcp(self, suffix, payload):
        return self._run("mcp__srv__" + suffix, payload,
                         **{"form_gate.categorical": "ask"})

    def test_work_item_comment_is_gated(self):
        self.assertEqual(self._decision(self._mcp("wit_work_item_comment_write",
                                                  {"comment": DIRTY})), "ask")

    def test_pr_thread_reply_is_gated(self):
        """Named in the skill as the highest-volume text a reviewer reads."""
        self.assertEqual(self._decision(self._mcp("repo_pull_request_thread_write",
                                                  {"content": DIRTY})), "ask")

    def test_wiki_upsert_is_gated(self):
        self.assertEqual(self._decision(self._mcp("wiki_upsert_page",
                                                  {"content": DIRTY})), "ask")

    def test_notion_create_pages_is_gated(self):
        self.assertEqual(self._decision(self._mcp("notion-create-pages",
                                                  {"pages": [{"content": DIRTY}]})), "ask")

    def test_slack_draft_and_canvas_are_gated(self):
        self.assertEqual(self._decision(self._mcp("slack_send_message_draft",
                                                  {"text": DIRTY})), "ask")
        self.assertEqual(self._decision(self._mcp("slack_update_canvas",
                                                  {"markdown": DIRTY})), "ask")

    def test_mail_draft_is_gated(self):
        self.assertEqual(self._decision(self._mcp("create_draft",
                                                  {"body": DIRTY})), "ask")

    def test_unknown_mcp_tool_is_still_ignored(self):
        self.assertEqual(self._mcp("search_workitem", {"text": DIRTY}), "")

    def test_artifact_comment_reply_is_gated(self):
        out = self._run("Artifact", {"action": "reply", "url": "u",
                                     "thread_id": "t", "text": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")

    def test_send_user_file_caption_is_gated(self):
        out = self._run("SendUserFile", {"files": ["a.md"], "caption": DIRTY},
                        **{"form_gate.categorical": "ask"})
        self.assertEqual(self._decision(out), "ask")

    def test_clean_text_passes_everywhere(self):
        self.assertEqual(self._mcp("wiki_upsert_page", {"content": CLEAN}), "")
        self.assertEqual(self._run("SendUserFile", {"caption": CLEAN},
                                   **{"form_gate.categorical": "ask"}), "")


if __name__ == "__main__":
    unittest.main()
