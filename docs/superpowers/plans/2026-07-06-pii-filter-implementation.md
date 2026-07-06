# PII Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `pii_filter` toggle that scrubs PII (emails, phones, IPs, paths, tokens, and optionally names via Presidio NER) from nervepack memory content both at storage time and at LLM injection time.

**Architecture:** A new `np-pii-filter.py` stdin→stdout script provides two modes: `--mode fast` (regex-only, <1ms) for the injection-time critical path and `--mode full` (regex + Presidio NER) for storage time. The `episodic-scrub.sh` storage hook and both recall hooks (`episodic-recall.sh`, `lesson-recall.sh`) gate on the `pii_filter` toggle to pipe content through the filter. The MCP server's Python capture path (`np_scrub.py`) adds matching PII regex rules gated on `NP_PII_FILTER=1`.

**Tech Stack:** Bash, Python 3 (stdlib + optional `presidio-analyzer`, `presidio-anonymizer`, `spacy en_core_web_lg`), `np-toggle-lib.sh` for toggle gating, stdlib `unittest` for tests.

## Global Constraints

- All scripts fail-open: any filter error passes input through unchanged, exits 0.
- `pii_filter` toggle default is **off** — behavior change is opt-in.
- Do not use `pyodbc` or `pip` (project policy); Presidio install script uses `pip` only because it is a stand-alone optional setup script, not part of the main project stack.
- Byte-level processing throughout — never choke on invalid UTF-8 (match `np_scrub.py`'s `scrub_line` contract).
- `NER` runs storage-time only — never on the injection-time path (latency constraint).
- The `episodic-scrub.sh` / `np_scrub.py` parity test (`tests/mcp/parity/test_scrub_parity.sh`) must continue to pass — the parity test does not set `NP_PII_FILTER=1` or enable the toggle, so the guard conditions on both sides must be off-by-default.
- No LLM attribution in code, commits, or PRs.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `engine/setup/np-pii-filter.py` | Stdin→stdout PII filter; `--mode fast\|full` |
| Create | `engine/setup/25-install-pii-deps.sh` | Optional Presidio + spaCy install |
| Modify | `engine/setup/toggles.conf` | Add `pii_filter\|shared\|runtime\|off\|` row |
| Modify | `engine/setup/np-doctor.sh` | Add `pii_filter_full` case to `core_check()` |
| Modify | `engine/onboard/capabilities.json` | Add `pii_filter_full` capability entry |
| Modify | `engine/setup/episodic-scrub.sh` | Restructure to wrap sed in function; pipe to full-mode filter when toggle on |
| Modify | `engine/setup/np_scrub.py` | Add PII regex rules in `scrub_line`; gate on `NP_PII_FILTER=1` |
| Modify | `engine/setup/np-mcp-server.py` | Set `NP_PII_FILTER=1` at startup when `pii_filter` toggle on |
| Modify | `engine/setup/episodic-recall.sh` | Pipe assembled `ctx` through fast-mode filter when toggle on |
| Modify | `engine/setup/lesson-recall.sh` | Same as episodic-recall.sh |
| Create | `engine/setup/tests/pii/test_pii_filter.py` | Unit tests for np-pii-filter.py |
| Create | `engine/setup/tests/pii/test_pii_hooks.sh` | Integration tests for recall hooks |
| Modify | `docs/ARCHITECTURE.md` | Add row to Feature catalog table |

---

## Task 1: Toggle + install stub + doctor capability

**Files:**
- Modify: `engine/setup/toggles.conf`
- Create: `engine/setup/25-install-pii-deps.sh`
- Modify: `engine/setup/np-doctor.sh` (add `pii_filter_full` case at line ~90, before `*) echo SKIP ;;`)
- Modify: `engine/onboard/capabilities.json` (add entry before the closing `]`)

**Interfaces:**
- Produces: `np_enabled pii_filter` returns false by default; `np-doctor.sh` reports `pii_filter_full` as `FAIL` when Presidio absent

- [ ] **Step 1: Add toggle row to `toggles.conf`**

Open `engine/setup/toggles.conf`. After the `maintain.compact` line, add:

```
pii_filter|shared|runtime|off|
```

- [ ] **Step 2: Verify toggle is off by default**

```bash
cd /path/to/nervepack
source engine/setup/np-toggle-lib.sh
np_enabled pii_filter && echo "BUG: on" || echo "PASS: off (expected)"
```
Expected output: `PASS: off (expected)`

- [ ] **Step 3: Create `25-install-pii-deps.sh`**

Create `engine/setup/25-install-pii-deps.sh` (executable: `chmod +x`):

```bash
#!/usr/bin/env bash
# Optional: install Presidio + spaCy for np-pii-filter --mode full.
# Safe to skip — filter degrades gracefully to regex-only without these.
set -euo pipefail
pip install presidio-analyzer presidio-anonymizer
python -m spacy download en_core_web_lg
```

- [ ] **Step 4: Add `pii_filter_full` to `np-doctor.sh` `core_check()`**

In `engine/setup/np-doctor.sh`, inside the `core_check()` case statement, add the new case just before the `*) echo SKIP ;;` fallback at the bottom:

```bash
    pii_filter_full)
      python3 -c "import presidio_analyzer" >/dev/null 2>&1 \
        && echo PASS \
        || echo "FAIL (run engine/setup/25-install-pii-deps.sh to install Presidio + spaCy)" ;;
```

- [ ] **Step 5: Add `pii_filter_full` capability to `capabilities.json`**

Open `engine/onboard/capabilities.json`. Append a new entry to the `capabilities` array (before the closing `]`). Add a comma to the previous last entry, then add:

```json
{
  "id": "pii_filter_full",
  "tier": "SHOULD",
  "check": "core",
  "title": "Presidio NER available for pii_filter --mode full",
  "why": "Enables name/org/location scrubbing at storage time. Without it, pii_filter falls back to regex-only (structural PII only).",
  "accept": "python3 -c 'import presidio_analyzer' succeeds.",
  "hints": {
    "generic": "Run engine/setup/25-install-pii-deps.sh to install Presidio + spaCy en_core_web_lg."
  }
}
```

- [ ] **Step 6: Run doctor to verify it shows the new capability**

```bash
bash engine/setup/np-doctor.sh 2>&1 | grep pii_filter_full
```
Expected: a line containing `pii_filter_full` and either `PASS` (if Presidio installed) or `FAIL (run…)`.

- [ ] **Step 7: Commit**

```bash
git add engine/setup/toggles.conf engine/setup/25-install-pii-deps.sh engine/setup/np-doctor.sh engine/onboard/capabilities.json
git commit -m "feat(pii-filter): add pii_filter toggle, install stub, doctor capability"
```

---

## Task 2: `np-pii-filter.py` + unit tests

**Files:**
- Create: `engine/setup/np-pii-filter.py`
- Create: `engine/setup/tests/pii/test_pii_filter.py`

**Interfaces:**
- Produces: `np-pii-filter.py --mode fast` and `--mode fast` callable via `python3 engine/setup/np-pii-filter.py --mode fast|full`
- Produces: `_apply_fast(data: bytes) -> bytes` and `_apply_full(data: bytes) -> bytes` importable for unit testing

- [ ] **Step 1: Create the test directory and write failing tests**

```bash
mkdir -p engine/setup/tests/pii
```

Create `engine/setup/tests/pii/test_pii_filter.py`:

```python
#!/usr/bin/env python3
"""Unit tests for np-pii-filter.py — stdlib unittest, no external deps."""
import importlib.util
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILTER = os.path.join(HERE, "..", "..", "np-pii-filter.py")


def _run(text: str, mode: str = "fast") -> tuple:
    result = subprocess.run(
        [sys.executable, FILTER, "--mode", mode],
        input=text.encode(),
        capture_output=True,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def _load_filter():
    spec = importlib.util.spec_from_file_location("np_pii_filter", FILTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFastModeRegex(unittest.TestCase):
    def test_email(self):
        out, _, rc = _run("contact user@example.com today")
        self.assertEqual(rc, 0)
        self.assertIn("[EMAIL]", out)
        self.assertNotIn("user@example.com", out)

    def test_phone_us(self):
        out, _, _ = _run("call 415-555-1234 now")
        self.assertIn("[PHONE]", out)
        self.assertNotIn("415-555-1234", out)

    def test_ssn(self):
        out, _, _ = _run("ssn is 123-45-6789")
        self.assertIn("[SSN]", out)
        self.assertNotIn("123-45-6789", out)

    def test_private_ip_192(self):
        out, _, _ = _run("server 192.168.1.100 is down")
        self.assertIn("[IP]", out)
        self.assertNotIn("192.168.1.100", out)

    def test_private_ip_10(self):
        out, _, _ = _run("host 10.0.0.1")
        self.assertIn("[IP]", out)
        self.assertNotIn("10.0.0.1", out)

    def test_private_ip_172(self):
        out, _, _ = _run("host 172.16.0.5")
        self.assertIn("[IP]", out)
        self.assertNotIn("172.16.0.5", out)

    def test_public_ip_not_redacted(self):
        out, _, _ = _run("server 8.8.8.8")
        self.assertNotIn("[IP]", out)
        self.assertIn("8.8.8.8", out)

    def test_unix_path_users(self):
        out, _, _ = _run("file at /Users/alice/code/proj/main.py")
        self.assertIn("[PATH]", out)
        self.assertNotIn("/Users/alice/", out)

    def test_unix_path_home(self):
        out, _, _ = _run("config in /home/bob/.bashrc")
        self.assertIn("[PATH]", out)
        self.assertNotIn("/home/bob/", out)

    def test_api_token_sk(self):
        out, _, _ = _run("key sk-ABCDEFGHIJKLMNOPQRSTUVWX end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("sk-ABCDEFG", out)

    def test_bearer_token(self):
        out, _, _ = _run("header Bearer abcdef123456ghijklmno end")
        self.assertIn("[TOKEN]", out)
        self.assertNotIn("abcdef123456ghijklmno", out)

    def test_clean_text_unchanged(self):
        out, _, _ = _run("just normal text about oauth flow")
        self.assertEqual(out, "just normal text about oauth flow")

    def test_placeholder_not_re_replaced(self):
        # Already-substituted placeholders must not be mangled
        text = "[EMAIL] is safe [PHONE] and [IP] too"
        out, _, _ = _run(text)
        self.assertEqual(out, text)

    def test_exits_zero(self):
        _, _, rc = _run("any text")
        self.assertEqual(rc, 0)


class TestFullModeNoPrecidio(unittest.TestCase):
    """Full mode without Presidio installed falls back to regex-only and warns."""

    def test_regex_still_runs_on_full_mode(self):
        # Even if Presidio is absent, fast-mode regex must fire in full mode
        out, stderr, rc = _run("contact user@example.com", mode="full")
        self.assertEqual(rc, 0)
        self.assertIn("[EMAIL]", out)
        # If Presidio was missing, stderr should mention it OR be empty (if installed)
        # Either way, the output must have [EMAIL]

    def test_full_mode_missing_presidio_warns(self):
        mod = _load_filter()
        import builtins
        import io
        import sys as _sys
        import unittest.mock as mock

        _real_import = builtins.__import__

        def _no_presidio(name, *args, **kwargs):
            if name.startswith("presidio"):
                raise ImportError("mocked unavailable")
            return _real_import(name, *args, **kwargs)

        old_stderr = _sys.stderr
        _sys.stderr = io.StringIO()
        try:
            with mock.patch("builtins.__import__", side_effect=_no_presidio):
                result = mod._apply_full(b"email user@example.com here")
            stderr_out = _sys.stderr.getvalue()
        finally:
            _sys.stderr = old_stderr

        self.assertIn("[EMAIL]", result.decode())
        self.assertIn("presidio unavailable", stderr_out)


class TestExceptionSafety(unittest.TestCase):
    def test_invalid_utf8_fast_mode(self):
        # Binary data not valid UTF-8 must pass through unchanged in fast mode
        result = subprocess.run(
            [sys.executable, FILTER, "--mode", "fast"],
            input=b"\xff\xfe binary garbage",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"\xff\xfe binary garbage")

    def test_fast_mode_does_not_import_presidio(self):
        # --mode fast must not trigger a Presidio import
        mod = _load_filter()
        import unittest.mock as mock

        imported = []
        _real = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        with mock.patch("builtins.__import__", side_effect=lambda n, *a, **k: (imported.append(n), _real(n, *a, **k))[1]):
            mod._apply_fast(b"test user@example.com")

        presidio_imports = [n for n in imported if "presidio" in n]
        self.assertEqual(presidio_imports, [], "fast mode must not import presidio")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/nervepack
python3 engine/setup/tests/pii/test_pii_filter.py 2>&1 | head -20
```
Expected: errors like `FileNotFoundError` or `No such file` (np-pii-filter.py doesn't exist yet).

- [ ] **Step 3: Create `np-pii-filter.py`**

Create `engine/setup/np-pii-filter.py` (mark executable: `chmod +x`):

```python
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
```

Then make it executable:
```bash
chmod +x engine/setup/np-pii-filter.py
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 engine/setup/tests/pii/test_pii_filter.py -v 2>&1
```
Expected: all tests PASS (tests that mock missing Presidio will pass regardless of whether Presidio is installed; test for `_apply_full` with real Presidio only fails if something is structurally wrong).

- [ ] **Step 5: Verify fail-open on bad input**

```bash
printf '\xff\xfe bad bytes' | python3 engine/setup/np-pii-filter.py --mode fast | xxd | head -2
```
Expected: `ff fe 20 62 61 64 20 62 79 74 65 73` — bytes pass through unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/setup/np-pii-filter.py engine/setup/tests/pii/test_pii_filter.py
git commit -m "feat(pii-filter): add np-pii-filter.py with fast/full modes and unit tests"
```

---

## Task 3: Storage-time wiring — `episodic-scrub.sh`, `np_scrub.py`, MCP server startup

**Files:**
- Modify: `engine/setup/episodic-scrub.sh`
- Modify: `engine/setup/np_scrub.py`
- Modify: `engine/setup/np-mcp-server.py`

**Interfaces:**
- Consumes: `np-pii-filter.py --mode full` (Task 2), `np_enabled pii_filter` (Task 1), `NP_PII_FILTER=1` env var
- The scrub parity test (`tests/mcp/parity/test_scrub_parity.sh`) must still pass — when pii_filter toggle is off (default) and `NP_PII_FILTER` is unset, both scripts produce byte-identical output as before.

- [ ] **Step 1: Restructure `episodic-scrub.sh` to wrap sed in a function**

Replace the entire contents of `engine/setup/episodic-scrub.sh` with:

```bash
#!/usr/bin/env bash
# Redact secret-shaped substrings from stdin → stdout. Defense-in-depth on top
# of the summarizer's "no secrets" instruction. Conservative by design: catches
# known token shapes, does not attempt to be exhaustive.
# When pii_filter toggle is on, also pipes through np-pii-filter.py --mode full.
set -euo pipefail
# Byte-process (C locale): a redactor must never choke on binary / invalid-UTF-8
# input. Without this, BSD sed (macOS) aborts with "RE error: illegal byte sequence"
# on non-UTF-8 bytes, defeating the fail-open contract.
export LC_ALL=C
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-toggle-lib.sh" 2>/dev/null || true

_scrub_secrets() {
  sed -E \
    -e 's/sk-[A-Za-z0-9]{16,}/[REDACTED-SECRET]/g' \
    -e 's/github_pat_[A-Za-z0-9_]{20,}/[REDACTED-SECRET]/g' \
    -e 's/gh[opusr]_[A-Za-z0-9]{20,}/[REDACTED-SECRET]/g' \
    -e 's/AKIA[0-9A-Z]{16}/[REDACTED-SECRET]/g' \
    -e 's/xox[baprs]-[A-Za-z0-9-]{10,}/[REDACTED-SECRET]/g' \
    -e 's/(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9\/+]{40}/\1=[REDACTED-SECRET]/g' \
    -e 's/[Bb]earer[[:space:]]+[A-Za-z0-9._-]{12,}/Bearer [REDACTED-SECRET]/g' \
    -e 's/([Pp]assword|[Pp]asswd|[Ss]ecret|[Tt]oken|[Aa]pi[_-]?[Kk]ey)("?[[:space:]]*[:=][[:space:]]*"?)[^[:space:]"]{6,}/\1\2[REDACTED-SECRET]/g' \
    -e 's/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/[REDACTED-JWT]/g' \
    -e 's/-----BEGIN[ A-Z]*PRIVATE KEY-----/[REDACTED-KEY]/g'
}

if np_enabled pii_filter 2>/dev/null && command -v python3 >/dev/null 2>&1 && [[ -x "$HERE/np-pii-filter.py" ]]; then
  _scrub_secrets | python3 "$HERE/np-pii-filter.py" --mode full
else
  _scrub_secrets
fi
```

- [ ] **Step 2: Verify scrub parity test still passes**

```bash
bash engine/setup/tests/mcp/parity/test_scrub_parity.sh
```
Expected: PASS (pii_filter is off by default, so `_scrub_secrets` runs alone — identical output to original).

- [ ] **Step 3: Add PII rules to `np_scrub.py`**

Open `engine/setup/np_scrub.py`. Add `import os` after the module docstring, then add a `_PII_RULES` list after `_COMPILED`, and update `scrub_line` to apply them when `NP_PII_FILTER=1`.

Replace the existing file with the following (all existing rules preserved):

```python
"""Bash-free byte-exact port of episodic-scrub.sh — redact secret-shaped
substrings from stdin -> stdout. Defense-in-depth before an episodic note is
written to the inbox; conservative (known token shapes), fail-open.

Parity-locked to episodic-scrub.sh by tests/mcp/parity/test_scrub_parity.sh
(byte-identical output). Operates on BYTES, per line (like sed under LC_ALL=C),
so it never chokes on invalid-UTF-8 input. stdlib only. Used by the ported
capture pipeline (np_capture) on a bash-free host. Slice 4 of #38.

When NP_PII_FILTER=1, also applies structural PII regex rules (email, phone,
SSN, private IP, path, token) matching np-pii-filter.py --mode fast.
"""
import os
import re
import sys

# The sed -E rules, in order. \s in a bytes pattern is exactly POSIX [[:space:]]
# under LC_ALL=C ([ \t\n\r\f\v]); processing per-line means \n never appears within
# a segment, matching sed's line-at-a-time behavior.
_RULES = [
    (rb'sk-[A-Za-z0-9]{16,}', rb'[REDACTED-SECRET]'),
    (rb'github_pat_[A-Za-z0-9_]{20,}', rb'[REDACTED-SECRET]'),
    (rb'gh[opusr]_[A-Za-z0-9]{20,}', rb'[REDACTED-SECRET]'),
    (rb'AKIA[0-9A-Z]{16}', rb'[REDACTED-SECRET]'),
    (rb'xox[baprs]-[A-Za-z0-9-]{10,}', rb'[REDACTED-SECRET]'),
    (rb'(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*[A-Za-z0-9/+]{40}',
     rb'\1=[REDACTED-SECRET]'),
    (rb'[Bb]earer\s+[A-Za-z0-9._-]{12,}', rb'Bearer [REDACTED-SECRET]'),
    (rb'([Pp]assword|[Pp]asswd|[Ss]ecret|[Tt]oken|[Aa]pi[_-]?[Kk]ey)("?\s*[:=]\s*"?)[^\s"]{6,}',
     rb'\1\2[REDACTED-SECRET]'),
    (rb'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}', rb'[REDACTED-JWT]'),
    (rb'-----BEGIN[ A-Z]*PRIVATE KEY-----', rb'[REDACTED-KEY]'),
]
_COMPILED = [(re.compile(p), r) for p, r in _RULES]

# Structural PII rules (email, phone, SSN, private IP, path, token) — applied only
# when NP_PII_FILTER=1. Matches np-pii-filter.py --mode fast patterns exactly.
_PII_RULES = [
    (re.compile(rb"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), b"[EMAIL]"),
    (re.compile(rb"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"), b"[PHONE]"),
    (re.compile(rb"\d{3}-\d{2}-\d{4}"), b"[SSN]"),
    (re.compile(
        rb"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        rb"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        rb"|192\.168\.\d{1,3}\.\d{1,3})"
    ), b"[IP]"),
    (re.compile(rb"/(?:home|Users)/[A-Za-z][A-Za-z0-9_\-]*/"), b"[PATH]/"),
    (re.compile(rb"sk-[A-Za-z0-9]{16,}"), b"[TOKEN]"),
    (re.compile(rb"gh[opusr]_[A-Za-z0-9]{20,}"), b"[TOKEN]"),
    (re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"), b"[TOKEN]"),
    (re.compile(rb"AKIA[0-9A-Z]{16}"), b"[TOKEN]"),
    (re.compile(rb"xox[baprs]-[A-Za-z0-9\-]{10,}"), b"[TOKEN]"),
    (re.compile(rb"[Bb]earer\s+[A-Za-z0-9._\-]{12,}"), b"Bearer [TOKEN]"),
]


def scrub_line(line: bytes) -> bytes:
    for pat, repl in _COMPILED:
        line = pat.sub(repl, line)
    if os.environ.get("NP_PII_FILTER") == "1":
        for pat, repl in _PII_RULES:
            line = pat.sub(repl, line)
    return line


def scrub(data: bytes) -> bytes:
    """Redact `data` (bytes) per line; preserves the exact newline structure."""
    return b"\n".join(scrub_line(seg) for seg in data.split(b"\n"))


def main() -> None:
    sys.stdout.buffer.write(scrub(sys.stdin.buffer.read()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run scrub parity test again to confirm NP_PII_FILTER=0 (unset) preserves parity**

```bash
bash engine/setup/tests/mcp/parity/test_scrub_parity.sh
```
Expected: PASS (NP_PII_FILTER is unset in the parity test — no PII rules fire, bytes identical).

- [ ] **Step 5: Verify PII rules fire when NP_PII_FILTER=1**

```bash
printf 'send to user@example.com from 192.168.1.1' | NP_PII_FILTER=1 python3 engine/setup/np_scrub.py
```
Expected output contains `[EMAIL]` and `[IP]`, no raw email or IP.

- [ ] **Step 6: Set `NP_PII_FILTER=1` in MCP server startup**

Open `engine/setup/np-mcp-server.py`. In the `main()` function, after the `if not np_enabled("mcp"):` guard, add:

```python
def main():
    if not np_enabled("mcp"):
        log("mcp feature disabled; exiting")
        return 0
    if np_enabled("pii_filter"):
        os.environ["NP_PII_FILTER"] = "1"
    for line in sys.stdin:
        ...
```

(Replace `...` with the existing loop body — only insert the two new lines shown; leave everything else unchanged.)

- [ ] **Step 7: Commit**

```bash
git add engine/setup/episodic-scrub.sh engine/setup/np_scrub.py engine/setup/np-mcp-server.py
git commit -m "feat(pii-filter): wire storage-time PII scrub (episodic-scrub.sh, np_scrub.py, MCP startup)"
```

---

## Task 4: Injection-time wiring + integration tests

**Files:**
- Modify: `engine/setup/episodic-recall.sh`
- Modify: `engine/setup/lesson-recall.sh`
- Create: `engine/setup/tests/pii/test_pii_hooks.sh`

**Interfaces:**
- Consumes: `np-pii-filter.py --mode fast` (Task 2), `np_enabled pii_filter` (Task 1)
- The piped filter runs after `ctx` is assembled, before `jq` emits `additionalContext`.

- [ ] **Step 1: Write failing integration test**

Create `engine/setup/tests/pii/test_pii_hooks.sh`:

```bash
#!/usr/bin/env bash
# Integration tests: episodic-recall.sh and lesson-recall.sh filter PII from
# injected context when pii_filter toggle is on; pass through unchanged when off.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- shared toggle env ---
ON_CONF="$tmp/toggles_on.conf"
OFF_CONF="$tmp/toggles_off.conf"
printf 'memory|shared|runtime|on|\npii_filter|shared|runtime|on|\n'  > "$ON_CONF"
printf 'memory|shared|runtime|on|\npii_filter|shared|runtime|off|\n' > "$OFF_CONF"

# --- episodic fixture with PII in body ---
mkdir -p "$tmp/episodic"
cat > "$tmp/episodic/INDEX.md" <<'IDX'
| topic | last_updated | keywords | lines |
|---|---|---|---:|
| pii-topic | 2026-07-01 | pii, auth | 5 |
IDX
cat > "$tmp/episodic/pii-topic.md" <<'TOP'
---
name: pii-topic
kind: episodic
---
# PII topic
Contact admin@example.com at 192.168.1.5 for access.
TOP

ep_payload="$(jq -nc '{session_id:"s1", prompt:"fix the pii auth bug"}')"
ep_run() {
  printf '%s' "$ep_payload" | \
    NP_TOGGLES_CONF="$1" EPISODIC_DIR="$tmp/episodic" EPISODIC_STATE_DIR="$tmp/state-$2" \
    bash "$S/episodic-recall.sh"
}

# --- episodic: pii_filter ON → email and IP scrubbed ---
out_on="$(ep_run "$ON_CONF" on)"
echo "$out_on" | jq -e '.hookSpecificOutput.additionalContext | test("pii-topic")' >/dev/null \
  || { echo "FAIL: episodic pii=on: topic not injected: $out_on"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'admin@example.com' \
  && { echo "FAIL: episodic pii=on: raw email leaked"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '192\.168\.1\.5' \
  && { echo "FAIL: episodic pii=on: raw IP leaked"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '\[EMAIL\]' \
  || { echo "FAIL: episodic pii=on: [EMAIL] placeholder missing"; exit 1; }

# --- episodic: pii_filter OFF → raw content unchanged ---
out_off="$(ep_run "$OFF_CONF" off)"
echo "$out_off" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'admin@example.com' \
  || { echo "FAIL: episodic pii=off: email was unexpectedly filtered"; exit 1; }

# --- lesson fixture with PII in body ---
mkdir -p "$tmp/lessons"
cat > "$tmp/lessons/INDEX.md" <<'IDX'
| topic | last_updated | tier | gate | triggers | notes |
|---|---|---|---|---|---|
| pii-lesson | 2026-07-01 | SHOULD | off | pii,auth | |
IDX
cat > "$tmp/lessons/pii-lesson.md" <<'LESSON'
---
provenance: failure
---
**Symptom:** user@secret.org called 10.0.0.1
**Why:** PII in lessons
**Do:** redact before storing
LESSON

ls_payload="$(jq -nc '{session_id:"s2", prompt:"fix pii auth issue"}')"
ls_run() {
  printf '%s' "$ls_payload" | \
    NP_TOGGLES_CONF="$1" EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/ls-state-$2" \
    bash "$S/lesson-recall.sh"
}

# --- lesson: pii_filter ON → email and IP scrubbed ---
out_ls_on="$(ls_run "$ON_CONF" on)"
echo "$out_ls_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'user@secret.org' \
  && { echo "FAIL: lesson pii=on: raw email leaked"; exit 1; }
echo "$out_ls_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '10\.0\.0\.1' \
  && { echo "FAIL: lesson pii=on: raw IP leaked"; exit 1; }

# --- lesson: pii_filter OFF → raw content unchanged ---
out_ls_off="$(ls_run "$OFF_CONF" off)"
echo "$out_ls_off" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'user@secret.org' \
  || { echo "FAIL: lesson pii=off: content was unexpectedly filtered"; exit 1; }

echo "PASS test_pii_hooks"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
bash engine/setup/tests/pii/test_pii_hooks.sh
```
Expected: FAIL — the PII filter is not yet wired into episodic-recall.sh / lesson-recall.sh.

- [ ] **Step 3: Wire PII filter into `episodic-recall.sh`**

In `engine/setup/episodic-recall.sh`, find the block where `ctx` is assembled (lines ~32-43 in the current file) and the final `jq` call (last line before `exit 0`). Insert the following three lines **immediately before** the `np_signal` call (which is just before the `jq` line):

```bash
if np_enabled pii_filter 2>/dev/null && command -v python3 >/dev/null 2>&1 && [[ -x "$HERE/np-pii-filter.py" ]]; then
  ctx="$(printf '%s' "$ctx" | python3 "$HERE/np-pii-filter.py" --mode fast)"
fi
```

The modified tail of the file should look like:

```bash
[[ "$_hit_any" == 1 ]] || exit 0

if np_enabled pii_filter 2>/dev/null && command -v python3 >/dev/null 2>&1 && [[ -x "$HERE/np-pii-filter.py" ]]; then
  ctx="$(printf '%s' "$ctx" | python3 "$HERE/np-pii-filter.py" --mode fast)"
fi

np_signal "$sid" "episodic-recall"
jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit", additionalContext:$c}}'
exit 0
```

- [ ] **Step 4: Wire PII filter into `lesson-recall.sh`**

In `engine/setup/lesson-recall.sh`, find where `ctx` is finalized (lines ~97-100). Insert the same three-line block **immediately before** the `np_signal` call:

```bash
[[ -z "$ctx" ]] && exit 0

if np_enabled pii_filter 2>/dev/null && command -v python3 >/dev/null 2>&1 && [[ -x "$HERE/np-pii-filter.py" ]]; then
  ctx="$(printf '%s' "$ctx" | python3 "$HERE/np-pii-filter.py" --mode fast)"
fi

np_signal "$sid" "lesson-recall"
jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
```

- [ ] **Step 5: Run integration tests**

```bash
bash engine/setup/tests/pii/test_pii_hooks.sh
```
Expected: `PASS test_pii_hooks`

- [ ] **Step 6: Run existing recall tests to verify no regression**

```bash
bash engine/setup/tests/episodic/test_recall.sh
bash engine/setup/tests/lessons/test_recall.sh 2>/dev/null || echo "(no lesson recall test)"
```
Expected: both PASS (pii_filter is off in the unmodified test environments).

- [ ] **Step 7: Commit**

```bash
git add engine/setup/episodic-recall.sh engine/setup/lesson-recall.sh engine/setup/tests/pii/test_pii_hooks.sh
git commit -m "feat(pii-filter): wire injection-time fast-mode filter into recall hooks"
```

---

## Task 5: ARCHITECTURE.md documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add PII filter row to Feature catalog table**

In `docs/ARCHITECTURE.md`, locate the Feature catalog table (around the lines that list "Episodic memory", "Lessons", "Dashboard", etc.). Find the last feature row and append the following new row after it:

```markdown
| **PII filter** (context-window and storage-time scrub) | `pii_filter` (default off) | `np-pii-filter.py`, `episodic-scrub.sh` (extended), `episodic-recall.sh` (extended), `lesson-recall.sh` (extended), `np_scrub.py` (extended, `NP_PII_FILTER=1`), `25-install-pii-deps.sh` | `specs/2026-07-06-pii-filter-design.md` |
```

- [ ] **Step 2: Verify the table renders correctly**

```bash
grep -A2 "PII filter" docs/ARCHITECTURE.md
```
Expected: the new row appears with the correct `|`-delimited columns.

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs(pii-filter): add PII filter row to ARCHITECTURE.md feature catalog"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| `np-pii-filter.py` with `--mode fast\|full` | Task 2 |
| Regex rules: email, phone, SSN, private IP, path, token | Task 2 |
| NER rules via Presidio (full mode) | Task 2 |
| Fail-open: exit 0 always, missing Presidio → regex-only + stderr | Task 2 |
| Storage-time: `episodic-scrub.sh` calls filter after sed | Task 3 |
| `np_scrub.py` PII pass gated on `NP_PII_FILTER=1` | Task 3 |
| MCP server sets `NP_PII_FILTER=1` at startup when toggle on | Task 3 |
| Injection-time: `episodic-recall.sh` pipes ctx through fast mode | Task 4 |
| Injection-time: `lesson-recall.sh` pipes ctx through fast mode | Task 4 |
| `pii_filter` toggle in `toggles.conf`, default off | Task 1 |
| `25-install-pii-deps.sh` optional setup script | Task 1 |
| Doctor check: `pii_filter_full` → `import presidio_analyzer` | Task 1 |
| Unit tests: each regex rule, no double-processing, fast≠NER, degradation, exception safety | Task 2 |
| Integration tests: recall hooks on/off pair for episodic + lesson | Task 4 |
| Scrub parity test continues to pass (toggle off = unchanged behavior) | Task 3 |
| `ARCHITECTURE.md` feature catalog row | Task 5 |
| Limitations documented (NER not at injection time, retroactive re-scrub not in scope) | Spec doc (pre-existing) |
