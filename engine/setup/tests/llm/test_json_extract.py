#!/usr/bin/env python3
"""Contract test for np-json-extract.py (stdlib unittest — no pytest, per the
harness language policy in CLAUDE.md). Black-box: pipes raw model output to the
script's stdin and asserts on its stdout JSON + exit code. This guards the lenient
extraction that the local (non-Claude) backend needs — local models routinely wrap
their JSON in ```json fences or surround it with prose, which the strict `jq -e .`
path in episodic-capture.sh / np-evaluator.sh rejects outright.
Run: `python3 test_json_extract.py` (or `python3 -m unittest`)."""
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.join(HERE, "..", "..", "np-json-extract.py")


def run(stdin):
    """Pipe stdin to the extractor; return (exit_code, stdout_str)."""
    p = subprocess.run(
        ["python3", EXTRACT],
        input=stdin.encode("utf-8"),
        capture_output=True,
    )
    return p.returncode, p.stdout.decode("utf-8")


class TestJsonExtract(unittest.TestCase):
    def test_pure_json_passes_through(self):
        code, out = run('{"score": 7, "helped": true}')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"score": 7, "helped": True})

    def test_strips_json_code_fence(self):
        code, out = run('```json\n{"score": 7}\n```')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"score": 7})

    def test_strips_bare_code_fence(self):
        code, out = run('```\n{"score": 7}\n```')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"score": 7})

    def test_tolerates_leading_prose(self):
        code, out = run('Sure! Here is the verdict:\n{"score": 7, "helped": false}')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"score": 7, "helped": False})

    def test_tolerates_trailing_prose(self):
        code, out = run('{"score": 7}\nHope that helps! Let me know.')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"score": 7})

    def test_prose_and_fences_together(self):
        raw = 'Here you go:\n\n```json\n{"summary": "did stuff", "score": 5}\n```\n\nThanks!'
        code, out = run(raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"summary": "did stuff", "score": 5})

    def test_brace_inside_string_value(self):
        # A closing brace inside a string must NOT end the object early.
        raw = 'Result: {"note": "use the } char carefully", "n": 1} done'
        code, out = run(raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"note": "use the } char carefully", "n": 1})

    def test_escaped_quote_inside_string(self):
        raw = '{"note": "she said \\"hi\\" and left", "n": 2}'
        code, out = run(raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"note": 'she said "hi" and left', "n": 2})

    def test_nested_object(self):
        raw = 'ok:\n{"a": {"b": {"c": 1}}, "d": 2}'
        code, out = run(raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"a": {"b": {"c": 1}}, "d": 2})

    def test_returns_first_valid_object(self):
        raw = 'noise {"first": 1} then {"second": 2}'
        code, out = run(raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"first": 1})

    def test_no_json_object_fails(self):
        code, out = run("I could not produce a verdict, sorry.")
        self.assertNotEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_empty_input_fails(self):
        code, out = run("")
        self.assertNotEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_unbalanced_braces_fail(self):
        # An opening brace with prose-y junk that never forms valid JSON.
        code, out = run('{"score": 7 and some words but never closed')
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
