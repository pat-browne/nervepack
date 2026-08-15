#!/usr/bin/env python3
"""Collect gate-verdict JSON artifacts and post/update ONE PR comment (F4/#250).

Finds an existing comment carrying MARKER (matched by substring - a fresh
checkout has no stored comment ID to remember across runs) and PATCHes it if
found, POSTs a new one otherwise. Danger's "amend, don't append" model, so a
PR carries exactly one gate-verdicts comment across every re-run rather than
a growing thread of stale ones.

Pure stdlib urllib against the GitHub REST API - no `gh` CLI dependency, no
third-party requests lib - so the HTTP call is trivially monkeypatchable in
tests (`fetch` is an injectable parameter on every function that needs one).

Fails open: a missing token or any GitHub API error is logged and exits 0.
A comment-posting problem must never fail the build - see np-flow-develop's
"fail closed on a policy violation, fail open on the mechanism's own error".

Usage:
  np-gate-verdicts-comment.py --verdicts-dir DIR --repo owner/name --pr N

Reads GITHUB_TOKEN (falling back to GH_TOKEN) from the environment only -
never as a CLI arg, so it can't appear in a process listing or CI log line.
"""
import argparse
import glob
import json
import os
import sys
import urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_github_api  # noqa: E402

MARKER = "<!-- nervepack:gate-verdicts -->"

# A machine-readable copy of the same verdicts, embedded in an HTML comment so
# it renders invisibly. F5/#251's ledger writer reads this back out rather
# than re-downloading CI artifacts or re-deriving verdicts from the table.
JSON_MARKER = "<!-- nervepack:gate-verdicts-json"

_ICON = {"PASSED": "✅", "FAILED": "❌", "SKIPPED": "⚪"}


def load_verdicts(verdicts_dir):
    """Every *.json in verdicts_dir, sorted by gate name so the rendered
    comment is deterministic across re-runs with the same result set."""
    verdicts = []
    for path in sorted(glob.glob(os.path.join(verdicts_dir, "*.json"))):
        with open(path) as f:
            verdicts.append(json.load(f))
    verdicts.sort(key=lambda v: v.get("gate", ""))
    return verdicts


def render_comment(verdicts):
    lines = [MARKER, "", "## Gate verdicts", ""]
    if not verdicts:
        lines.append("*No gate verdicts found for this run.*")
        lines.append("")
        lines.append(JSON_MARKER)
        lines.append("[]")
        lines.append("-->")
        return "\n".join(lines)
    lines.append("| Gate | Verdict | Reason | Rules |")
    lines.append("|---|---|---|---|")
    for v in verdicts:
        icon = _ICON.get(v.get("verdict"), "❔")
        rules_short = (v.get("rules_sha") or "")[:12]
        lines.append("| [%s](%s) | %s %s | %s | `%s` |" % (
            v.get("gate", "?"), v.get("evidence_ref", "#"),
            icon, v.get("verdict", "?"), v.get("reason", ""), rules_short,
        ))
    lines.append("")
    lines.append(
        "*%s — structured per-gate record. See F5 for the durable, "
        "change-keyed ledger.*" % verdicts[0].get("schema", "?")
    )
    lines.append("")
    lines.append(JSON_MARKER)
    lines.append(json.dumps(verdicts))
    lines.append("-->")
    return "\n".join(lines)


def extract_verdicts_json(comment_body):
    """The verdicts list embedded by render_comment(), or None if the body
    has no JSON block or it fails to parse (malformed/edited-by-hand)."""
    start = comment_body.find(JSON_MARKER)
    if start == -1:
        return None
    payload_start = start + len(JSON_MARKER)
    end = comment_body.find("-->", payload_start)
    if end == -1:
        return None
    raw = comment_body[payload_start:end].strip()
    try:
        return json.loads(raw)
    except ValueError:
        return None


def find_existing_comment(repo, pr, token, fetch=np_github_api.default_fetch):
    """The comment id of the prior gate-verdicts comment, or None."""
    url = "https://api.github.com/repos/%s/issues/%s/comments?per_page=100" % (repo, pr)
    for c in fetch(url, token) or []:
        if MARKER in (c.get("body") or ""):
            return c["id"]
    return None


def upsert_comment(repo, pr, token, body, fetch=np_github_api.default_fetch):
    existing = find_existing_comment(repo, pr, token, fetch)
    if existing is not None:
        url = "https://api.github.com/repos/%s/issues/comments/%s" % (repo, existing)
        fetch(url, token, method="PATCH", data={"body": body})
        return "updated", existing
    url = "https://api.github.com/repos/%s/issues/%s/comments" % (repo, pr)
    result = fetch(url, token, method="POST", data={"body": body})
    return "created", result.get("id")


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verdicts-dir", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    args = p.parse_args(argv[1:])

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.stderr.write("gate-verdicts-comment: no GITHUB_TOKEN - skipping\n")
        return 0

    verdicts = load_verdicts(args.verdicts_dir)
    body = render_comment(verdicts)
    try:
        action, comment_id = upsert_comment(args.repo, args.pr, token, body)
    except urllib.error.HTTPError as e:
        sys.stderr.write(
            "gate-verdicts-comment: GitHub API error %s - %s\n" % (e.code, e.reason)
        )
        return 0

    print("gate-verdicts-comment: %s comment %s" % (action, comment_id))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
