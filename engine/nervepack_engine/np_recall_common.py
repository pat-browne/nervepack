"""Shared helpers for the two recall hooks (episodic_recall, lesson_recall).

Both cap recall to a session's first N prompts and optionally scrub injected
context through the PII filter. The prompt cap, the filter script path, and the
filter subprocess were byte-identical in both hooks -- centralize them so the
recall contract can't drift between the two. The per-feature bits (state-dir
default, counter filename prefix, layer roots, header regex) stay in each hook. (#176)
"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# nervepack_engine/ -> engine/ -> setup/np-pii-filter.py
PII_FILTER_SCRIPT = os.path.normpath(os.path.join(_HERE, "..", "setup", "np-pii-filter.py"))


def max_prompts():
    """Recall fires only on a session's first N prompts (EPISODIC_RECALL_MAX, default 2)."""
    try:
        return int(os.environ.get("EPISODIC_RECALL_MAX", "2"))
    except ValueError:
        return 2


def default_pii_filter(text):
    """Scrub `text` through np-pii-filter.py (fast mode) via a Python subprocess;
    return it unchanged on any failure (fail-open)."""
    try:
        result = subprocess.run(
            [sys.executable, PII_FILTER_SCRIPT, "--mode", "fast"],
            input=text, capture_output=True, text=True,
        )
        return result.stdout if result.returncode == 0 else text
    except OSError:
        return text
