#!/usr/bin/env python3
"""Stdin → stdout PII filter. --mode fast: regex only. --mode full: regex + Presidio NER.
Fail-open: any exception passes input through unchanged, exits 0.
Byte-level processing per line — never chokes on invalid UTF-8 (same contract as np_scrub.py).
"""
import re
import sys

# Both modes apply these rules. Order matters: more-specific patterns first.
_FAST_RULES = [
    (re.compile(rb"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), b"[EMAIL]"),
    (re.compile(rb"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"), b"[PHONE]"),
    (re.compile(rb"\d{3}-\d{2}-\d{4}"), b"[SSN]"),
    # RFC1918 private IPs only
    (re.compile(
        rb"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        rb"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        rb"|192\.168\.\d{1,3}\.\d{1,3})"
    ), b"[IP]"),
    # Username component of Unix paths (/home/alice/ or /Users/Alice/)
    (re.compile(rb"/(?:home|Users)/[A-Za-z][A-Za-z0-9_\-]*/"), b"[PATH]/"),
    # API tokens — same shapes as episodic-scrub.sh
    (re.compile(rb"sk-[A-Za-z0-9]{16,}"), b"[TOKEN]"),
    (re.compile(rb"gh[opusr]_[A-Za-z0-9]{20,}"), b"[TOKEN]"),
    (re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"), b"[TOKEN]"),
    (re.compile(rb"AKIA[0-9A-Z]{16}"), b"[TOKEN]"),
    (re.compile(rb"xox[baprs]-[A-Za-z0-9\-]{10,}"), b"[TOKEN]"),
    (re.compile(rb"[Bb]earer\s+[A-Za-z0-9._\-]{12,}"), b"Bearer [TOKEN]"),
]

_NER_ENTITIES = ["PERSON", "ORGANIZATION", "LOCATION", "PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN"]
_NER_PLACEHOLDERS = {
    "PERSON": "[PERSON]",
    "ORGANIZATION": "[ORG]",
    "LOCATION": "[LOCATION]",
    "PHONE_NUMBER": "[PHONE]",
    "EMAIL_ADDRESS": "[EMAIL]",
    "US_SSN": "[SSN]",
}


def _apply_fast(data: bytes) -> bytes:
    for pat, repl in _FAST_RULES:
        data = pat.sub(repl, data)
    return data


def _apply_full(data: bytes) -> bytes:
    data = _apply_fast(data)
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig
    except ImportError:
        print("[np-pii] presidio unavailable, regex-only", file=sys.stderr)
        return data
    text = data.decode("utf-8", errors="replace")
    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    results = analyzer.analyze(text=text, language="en", entities=_NER_ENTITIES)
    operators = {
        entity: OperatorConfig("replace", {"new_value": placeholder})
        for entity, placeholder in _NER_PLACEHOLDERS.items()
    }
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
    return anonymized.text.encode("utf-8")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="PII filter: stdin → stdout.")
    ap.add_argument("--mode", choices=["fast", "full"], default="fast")
    args = ap.parse_args()
    data = b""
    try:
        data = sys.stdin.buffer.read()
        result = _apply_full(data) if args.mode == "full" else _apply_fast(data)
        sys.stdout.buffer.write(result)
    except Exception as exc:
        print(f"[np-pii] filter error: {exc}", file=sys.stderr)
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
