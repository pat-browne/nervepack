#!/usr/bin/env python3
"""Append one change-keyed record to the durable ledger (F5/#251).

Run manually after merging a PR (this is a local, post-merge step - not a CI
job; see "Why this runs locally, not in CI" below). Reads the merged PR's
spec (change-specs/<slug>.md, if one exists) and the gate-verdicts comment
F4/#250 posted, and appends one line to
$NP_CONTENT_DIR/dashboard/data/ledger.jsonl:

  {"change_id": "...", "spec": "change-specs/...", "tier": "normal",
   "diff_sha": "...", "gates": [{"name": "...", "verdict": "...",
   "rules_sha": "..."}], "merge_sha": "...", "ts": "..."}

Lives beside dashboard/data/metrics.jsonl (session-keyed) - this is the
change-keyed half. Keep both; they answer different questions.

Retention: indefinite. Unlike metrics.jsonl (evaluator.retain_days, default
90 - ephemeral session telemetry), this IS the durable record F4's schema
was built toward. Nothing prunes it.

Why this runs locally, not in CI: dashboard/data/ lives in the private
content overlay, which a public-repo GitHub Actions job has no write access
to (and should not be given any - see AGENTS.md's engine/overlay split).
metrics.jsonl is populated the same way, by a local aggregator
(np_aggregate.py), not from CI. This script is that pattern's F5 counterpart.

Usage:
  np-ledger-append.py --repo owner/name --pr N
    [--repo-root DIR] [--content-dir DIR] [--spec PATH] [--tier T]
    [--merge-sha SHA]

--repo-root defaults to "." (where change-specs/ lives - the engine checkout
  you're running this from).
--content-dir defaults to $NP_CONTENT_DIR (where the overlay's
  dashboard/data/ lives). Required - errors clearly if neither is set.

A missing change-specs/<slug>.md is NOT an error: standard-tier and
spike-path changes may legitimately have none (see change-specs/README.md's
skip rule) - the ledger simply gets no entry for that merge.

GITHUB_TOKEN (or GH_TOKEN) is read from the environment, never a CLI arg.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_frontmatter  # noqa: E402
import np_github_api  # noqa: E402

JSON_MARKER = "<!-- nervepack:gate-verdicts-json"


def extract_verdicts_json(comment_body):
    """Mirrors np-gate-verdicts-comment.py's function of the same name.
    Deliberately duplicated rather than imported - see this module's own
    docstring on why hyphenated `np-*.py` scripts don't import each other;
    np_github_api.py (a real shared module) is the DRY line drawn instead."""
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


def gates_from_verdicts(verdicts):
    return [
        {"name": v.get("gate"), "verdict": v.get("verdict"), "rules_sha": v.get("rules_sha")}
        for v in verdicts
    ]


def build_entry(change_id, spec, tier, diff_sha, gates, merge_sha, ts):
    return {
        "change_id": change_id,
        "spec": spec,
        "tier": tier,
        "diff_sha": diff_sha,
        "gates": gates,
        "merge_sha": merge_sha,
        "ts": ts,
    }


def append_entry(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def fetch_pr_meta(repo, pr, token, fetch=np_github_api.default_fetch):
    data = fetch("https://api.github.com/repos/%s/pulls/%s" % (repo, pr), token)
    return {
        "head_sha": data["head"]["sha"],
        "head_ref": data["head"]["ref"],
        "merge_sha": data.get("merge_commit_sha"),
    }


def find_gate_verdicts_comment_body(repo, pr, token, fetch=np_github_api.default_fetch):
    url = "https://api.github.com/repos/%s/issues/%s/comments?per_page=100" % (repo, pr)
    for c in fetch(url, token) or []:
        body = c.get("body") or ""
        if JSON_MARKER in body:
            return body
    return None


def main(argv, fetch=np_github_api.default_fetch):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--content-dir", default=os.environ.get("NP_CONTENT_DIR", ""))
    p.add_argument("--spec")
    p.add_argument("--tier")
    p.add_argument("--merge-sha")
    args = p.parse_args(argv[1:])

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.stderr.write("ledger-append: no GITHUB_TOKEN - aborting (this is the durable "
                          "record; a silent no-op here would be worse than a loud failure)\n")
        return 1

    if not args.content_dir:
        sys.stderr.write("ledger-append: no --content-dir and $NP_CONTENT_DIR is unset\n")
        return 1

    try:
        meta = fetch_pr_meta(args.repo, args.pr, token, fetch=fetch)
    except urllib.error.HTTPError as e:
        sys.stderr.write("ledger-append: GitHub API error fetching PR - %s %s\n" % (e.code, e.reason))
        return 1

    slug = meta["head_ref"].replace("/", "-")
    spec_rel = args.spec or ("change-specs/%s.md" % slug)
    spec_path = os.path.join(args.repo_root, spec_rel)

    if not os.path.isfile(spec_path):
        print("ledger-append: no %s - standard-tier/spike change, no ledger entry needed"
              % spec_rel)
        return 0

    with open(spec_path) as f:
        spec_text = f.read()
    tier = args.tier or np_frontmatter.field(spec_text, "tier", "normal")

    try:
        comment_body = find_gate_verdicts_comment_body(args.repo, args.pr, token, fetch=fetch)
    except urllib.error.HTTPError as e:
        sys.stderr.write(
            "ledger-append: GitHub API error fetching comments - %s %s (continuing "
            "with an empty gate list)\n" % (e.code, e.reason)
        )
        comment_body = None

    verdicts = extract_verdicts_json(comment_body) if comment_body else []
    if comment_body is None:
        sys.stderr.write(
            "ledger-append: no gate-verdicts comment found on PR #%s - recording "
            "an empty gate list\n" % args.pr
        )
    gates = gates_from_verdicts(verdicts)

    entry = build_entry(
        change_id=slug,
        spec=spec_rel,
        tier=tier,
        diff_sha=meta["head_sha"],
        gates=gates,
        merge_sha=args.merge_sha or meta["merge_sha"],
        ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )

    ledger_path = os.path.join(args.content_dir, "dashboard", "data", "ledger.jsonl")
    append_entry(ledger_path, entry)
    print("ledger-append: appended %s to %s" % (entry["change_id"], ledger_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
