#!/usr/bin/env python3
"""Leniently extract the first valid JSON object from messy model output.

Claude/Haiku reliably return a bare JSON object, but local (Ollama) models
routinely wrap it in ```json fences or surround it with prose ("Sure! Here is the
verdict: {…} Hope that helps!"). The strict `printf '%s' "$out" | jq -e .` path in
episodic-capture.sh / np-evaluator.sh rejects all of that and the session loses its
note/verdict. This helper is the shared lenient front-door: it scans for the first
*balanced, string-aware* {…} run that `json.loads` accepts and prints it compact.

Runs OFF the hot path (SessionEnd / cron), so per nervepack's harness language
policy the parsing lives here in tested Python, not an inline sed/jq monster
duplicated across two consumers. One tested extractor, both callers.

Usage:  some_model_output | np-json-extract.py
Stdout: the extracted JSON object (compact), exit 0.
Fail:   no valid JSON object found -> empty stdout, exit 1 (caller bails cleanly).
"""
import json
import sys


def _candidates(text):
    """Yield each balanced, string-aware {...} substring, in start order.

    Tracks string state so a `}` inside a JSON string value (or an escaped quote)
    never closes the object early. Nested objects are handled by brace depth.
    """
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, n):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    break
        # advance past this opening brace; the next candidate (if any) starts later
        i += 1


def extract(text):
    """Return the first {...} substring that parses as a JSON object, or None."""
    for cand in _candidates(text):
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def main():
    raw = sys.stdin.read()
    obj = extract(raw)
    if obj is None:
        return 1
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
