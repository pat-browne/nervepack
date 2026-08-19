"""Tests for hooks.form_gate -- the PreToolUse durable-text form gate."""
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


class TestFormGatePaths(unittest.TestCase):
    def test_markdown_is_prose(self):
        self.assertTrue(form_gate._is_prose_path("/x/notes.md"))

    def test_python_is_not_prose(self):
        self.assertFalse(form_gate._is_prose_path("/x/thing.py"))

    def test_test_fixture_path_is_exempt(self):
        self.assertTrue(form_gate._is_exempt_path("/x/tests/data.md"))

    def test_voiced_prose_glob_is_exempt(self):
        globs = os.path.expanduser("~/Code/pbrowne-net/**")
        with mock.patch.object(form_gate.np_toggle, "param",
                               side_effect=lambda k, d=None:
                               globs if k == "form_gate.exempt_globs" else d):
            target = os.path.expanduser("~/Code/pbrowne-net/src/post.md")
            self.assertTrue(form_gate._is_exempt_path(target))


class TestFormGateFailOpen(unittest.TestCase):
    def _run(self, payload, enabled=True, params=None):
        params = params or {}
        with mock.patch.object(form_gate.np_toggle, "enabled", return_value=enabled), \
             mock.patch.object(form_gate.np_toggle, "param",
                               side_effect=lambda k, d=None: params.get(k, d)):
            return form_gate.run(payload)

    def test_toggle_off_returns_empty(self):
        payload = json.dumps({"tool_name": "Write",
                              "tool_input": {"file_path": "/x/a.md",
                                             "content": "a; b"}})
        self.assertEqual(self._run(payload, enabled=False), "")

    def test_malformed_payload_returns_empty(self):
        self.assertEqual(self._run("not json at all"), "")

    def test_empty_payload_returns_empty(self):
        self.assertEqual(self._run(""), "")

    def test_non_dict_payload_returns_empty(self):
        self.assertEqual(self._run("[1,2,3]"), "")

    def test_unknown_tool_returns_empty(self):
        payload = json.dumps({"tool_name": "SomeFutureTool",
                              "tool_input": {"whatever": "a; b"}})
        self.assertEqual(self._run(payload), "")


class TestExtraction(unittest.TestCase):
    def test_write_markdown_yields_content(self):
        text, label = form_gate._extract(
            "Write", {"file_path": "/x/a.md", "content": "Hello there."})
        self.assertEqual(text, "Hello there.")
        self.assertIn("a.md", label)

    def test_write_python_yields_nothing(self):
        text, _ = form_gate._extract(
            "Write", {"file_path": "/x/a.py", "content": "a = 1; b = 2"})
        self.assertIsNone(text)

    def test_edit_uses_new_string(self):
        text, _ = form_gate._extract(
            "Edit", {"file_path": "/x/a.md",
                     "old_string": "old", "new_string": "new prose"})
        self.assertEqual(text, "new prose")

    def test_artifact_reads_the_file_from_disk(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "page.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<p>Body copy here.</p>")
        text, _ = form_gate._extract("Artifact", {"file_path": path})
        self.assertIn("Body copy here", text)

    def test_artifact_missing_file_yields_nothing(self):
        text, _ = form_gate._extract(
            "Artifact", {"file_path": "/nope/absent.html"})
        self.assertIsNone(text)

    def test_bash_git_commit_double_quoted(self):
        text, _ = form_gate._extract(
            "Bash", {"command": 'git commit -m "fix: it does not work"'})
        self.assertEqual(text, "fix: it does not work")

    def test_bash_git_commit_single_quoted(self):
        text, _ = form_gate._extract(
            "Bash", {"command": "git commit -m 'chore: tidy up'"})
        self.assertEqual(text, "chore: tidy up")

    def test_bash_non_commit_yields_nothing(self):
        text, _ = form_gate._extract("Bash", {"command": "ls -la; echo hi"})
        self.assertIsNone(text)

    def test_slack_message_text(self):
        text, _ = form_gate._extract(
            "mcp__abc__slack_send_message", {"text": "Shipping now."})
        self.assertEqual(text, "Shipping now.")

    def test_pull_request_description(self):
        text, _ = form_gate._extract(
            "mcp__abc__repo_pull_request_write",
            {"description": "Adds the thing."})
        self.assertEqual(text, "Adds the thing.")


class TestStripQuoted(unittest.TestCase):
    def test_blockquote_is_stripped(self):
        out = form_gate._strip_quoted("Mine.\n\n> Theirs; quoted.\n")
        self.assertNotIn(";", out)
        self.assertIn("Mine.", out)

    def test_heading_is_stripped(self):
        out = form_gate._strip_quoted("## A heading; with punctuation\n\nBody.")
        self.assertNotIn(";", out)
        self.assertIn("Body.", out)

    def test_html_tags_are_stripped(self):
        out = form_gate._strip_quoted('<p style="a; b">Copy.</p>')
        self.assertNotIn(";", out)
        self.assertIn("Copy.", out)


class TestChannels(unittest.TestCase):
    def _run(self, payload, params=None, lint=None):
        params = params or {}
        patches = [
            mock.patch.object(form_gate.np_toggle, "enabled", return_value=True),
            mock.patch.object(form_gate.np_toggle, "param",
                              side_effect=lambda k, d=None: params.get(k, d)),
            mock.patch.object(form_gate.np_toggle, "signal", return_value=None),
        ]
        if lint is not None:
            patches.append(mock.patch.object(form_gate, "_lint", return_value=lint))
        for p in patches:
            p.start()
        try:
            return form_gate.run(payload)
        finally:
            for p in reversed(patches):
                p.stop()

    def _write(self, content, name="a.md"):
        return json.dumps({"session_id": "s1", "tool_name": "Write",
                           "tool_input": {"file_path": "/x/" + name,
                                          "content": content}})

    def _clean(self, **over):
        v = {"em_dash": 0, "semicolon": 0, "contraction": 0,
             "marketing_adjective": 0, "passive_voice": 0}
        v.update(over)
        return {"violations": v, "total_per100w": 0.0}

    def test_semicolon_asks(self):
        out = self._run(self._write("A clause; another clause."),
                        lint=self._clean(semicolon=1))
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["permissionDecision"], "ask")
        self.assertIn("semicolon", data["permissionDecisionReason"])

    def test_clean_prose_returns_empty(self):
        out = self._run(self._write("A clean sentence."), lint=self._clean())
        self.assertEqual(out, "")

    def test_rate_only_violation_warns_and_never_asks(self):
        out = self._run(self._write("The file was read by the parser."),
                        params={"form_gate.rate_threshold": "2.5"},
                        lint={"violations": {"passive_voice": 3},
                              "total_per100w": 9.0})
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["permissionDecision"], "allow")
        self.assertIn("additionalContext", data)

    def test_rate_below_threshold_returns_empty(self):
        out = self._run(self._write("Fine prose."),
                        params={"form_gate.rate_threshold": "2.5"},
                        lint={"violations": {"passive_voice": 1},
                              "total_per100w": 1.0})
        self.assertEqual(out, "")

    def test_categorical_off_downgrades_to_warn(self):
        out = self._run(self._write("A clause; another."),
                        params={"form_gate.categorical": "warn"},
                        lint=self._clean(semicolon=1))
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["permissionDecision"], "allow")

    def test_reason_names_every_violated_rule(self):
        out = self._run(self._write("Text"),
                        lint=self._clean(semicolon=2, em_dash=1))
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("semicolon", reason)
        self.assertIn("em dash", reason)

    def test_absent_linter_allows(self):
        with mock.patch.object(form_gate, "_lint_path", return_value=None):
            out = self._run(self._write("A clause; another."))
        self.assertEqual(out, "")

    def test_linter_timeout_allows(self):
        import subprocess as sp
        with mock.patch.object(form_gate, "_lint_path", return_value="/x/lint.py"), \
             mock.patch.object(form_gate.subprocess, "run",
                               side_effect=sp.TimeoutExpired("lint", 5)):
            out = self._run(self._write("A clause; another."))
        self.assertEqual(out, "")

    def test_blockquoted_semicolon_allows(self):
        """Quoted material is stripped before the linter ever sees it."""
        captured = {}

        def fake_lint(text, timeout_s):
            captured["text"] = text
            return self._clean()

        with mock.patch.object(form_gate, "_lint", side_effect=fake_lint):
            out = self._run(self._write("Mine.\n\n> Theirs; quoted.\n"))
        self.assertEqual(out, "")
        self.assertNotIn(";", captured["text"])


if __name__ == "__main__":
    unittest.main()
