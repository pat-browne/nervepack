"""Pure-Python port of np-suggestion-resolve.sh -- mark an evaluator
suggestion as acted-on so the metrics dashboard stops resurfacing it. Appends
the suggestion text to dashboard/data/resolved-suggestions.txt (deduped,
case/space-insensitive) with an ISO-8601 timestamp suffix, then rebuilds
metrics.js so the dashboard reflects it now. build.py's load_resolved()
strips the \\t<ts> suffix before matching.

Called in-process by np-mcp-server.py (resolve/reject action),
np-dashboard-server.py (/api/resolve), and np_implement_suggestion.py
(_default_resolve()) -- previously all three shelled out to bash.
"""
import datetime
import os
import re
import sys

import np_content


def _norm(text):
    # Mirror: strip a trailing tab+ts if present, lowercase, collapse
    # whitespace runs to single spaces, strip leading/trailing space.
    text = text.split("\t", 1)[0]
    return re.sub(r"\s+", " ", text.lower()).strip()


def default_ledger_path():
    """Resolve the resolved-suggestions ledger path: NP_RESOLVED_SUGGESTIONS
    env override, else dashboard/data/resolved-suggestions.txt under the
    content dir."""
    return os.environ.get("NP_RESOLVED_SUGGESTIONS") or os.path.join(
        np_content.content_dir(), "dashboard", "data", "resolved-suggestions.txt")


def resolve(text, ledger_path=None, no_build=None):
    """Returns (message, exit_code). exit_code 2 on empty text (matches the
    bash original's `exit 2`); 0 otherwise."""
    if not text:
        return ('usage: np-suggestion-resolve "<suggestion text>"', 2)

    if ledger_path is None:
        ledger_path = default_ledger_path()
    if no_build is None:
        no_build = os.environ.get("NP_RESOLVE_NO_BUILD") == "1"

    target = _norm(text)
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    if not os.path.exists(ledger_path):
        open(ledger_path, "a").close()

    with open(ledger_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            if _norm(line) == target:
                return ("already resolved: %s" % text, 0)

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write("%s\t%s\n" % (text, ts))

    if not no_build:
        _rebuild_dashboard()

    return ("resolved: %s" % text, 0)


def _rebuild_dashboard():
    # Best-effort, matches the bash original's `|| true` -- a rebuild failure
    # must never fail the resolve itself.
    here = os.path.dirname(os.path.abspath(__file__))
    dash = os.path.join(os.path.dirname(os.path.dirname(here)), "dashboard")
    if dash not in sys.path:
        sys.path.insert(0, dash)
    try:
        import build as _build
        _build.main([])
    except Exception:
        pass


if __name__ == "__main__":
    message, code = resolve(sys.argv[1] if len(sys.argv) > 1 else "")
    print(message)
    sys.exit(code)
