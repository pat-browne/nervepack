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

  np-ledger-append.py --repo owner/name --backfill [--limit N]
    Append every recently merged pull request the ledger is missing, skipping
    the ones already there. Added for F9/#255: an auto-merged pull request has
    no human in the loop to run the single-PR form, and CI cannot run either
    form for the reason below. The durable record catches up locally instead of
    being written at merge time. Idempotent, so running it twice is a no-op.

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


def existing_change_ids(ledger_path):
    """Every change_id already recorded, so a backfill is idempotent.

    A malformed line is skipped rather than fatal. The ledger is append-only and
    indefinitely retained, so one bad line written years ago must not stop today
    from being recorded -- but it must not be silently treated as "this change is
    already present" either, which is why the id is taken only from lines that
    parse.
    """
    ids = set()
    if not os.path.isfile(ledger_path):
        return ids
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                sys.stderr.write("ledger-append: skipping an unparseable ledger line\n")
                continue
            if isinstance(entry, dict) and entry.get("change_id"):
                ids.add(entry["change_id"])
    return ids


def merged_pull_requests(repo, token, limit, fetch=np_github_api.default_fetch):
    """[(number, head_ref)] for recently merged pull requests, newest first.

    Sorted by `updated` because GitHub offers no "sort by merged date"; a
    reopened-and-remerged pull request would otherwise be missed. Unmerged closed
    ones are filtered out here rather than in the query, since `state=closed`
    covers both.
    """
    url = ("https://api.github.com/repos/%s/pulls?state=closed&sort=updated"
           "&direction=desc&per_page=%d" % (repo, min(limit, 100)))
    out = []
    for pr in fetch(url, token) or []:
        if pr.get("merged_at"):
            out.append((pr["number"], pr["head"]["ref"]))
    return out


def backfill(args, token, fetch=np_github_api.default_fetch):
    """Append every merged pull request the ledger is missing.

    This exists because an auto-merged pull request (F9/#255) has no human in
    the loop to run this command, and CI cannot run it either: the ledger lives
    in the private content overlay, which a public-repo Actions job has no write
    access to and must not be given any. So the durable record catches up
    locally instead of being written at merge time.
    """
    ledger_path = os.path.join(args.content_dir, "dashboard", "data", "ledger.jsonl")
    already = existing_change_ids(ledger_path)
    try:
        candidates = merged_pull_requests(args.repo, token, args.limit, fetch=fetch)
    except urllib.error.HTTPError as e:
        sys.stderr.write("ledger-append: GitHub API error listing pull requests - %s %s\n"
                         % (e.code, e.reason))
        return 1

    # A slug is a branch name with "/" replaced by "-", so `feat/foo` and
    # `feat-foo` collide, and so does the same branch merged twice. That is a
    # property of the change_id scheme itself (F5 keys the ledger on it, and
    # spec-guard and drift-guard resolve the change spec through the same
    # transform), not something introduced here -- but backfill is the one place
    # a collision turns into a SILENT omission, because the second pull request
    # would be skipped as "already recorded". Detect it and say so.
    by_slug = {}
    for number, head_ref in candidates:
        by_slug.setdefault(head_ref.replace("/", "-"), []).append(number)
    for slug, numbers in sorted(by_slug.items()):
        if len(numbers) > 1:
            sys.stderr.write(
                "ledger-append: pull requests %s all resolve to change_id %r - "
                "only the first can be recorded, because the ledger is keyed on "
                "it. Record the others by hand with --pr and --spec.\n"
                % (", ".join("#%d" % n for n in numbers), slug))

    appended = failed = no_spec = seen_already = 0
    for number, head_ref in candidates:
        slug = head_ref.replace("/", "-")
        if slug in already:
            seen_already += 1
            continue
        # Reuse the single-PR path verbatim rather than reimplementing it. Two
        # code paths that build a ledger entry would eventually build two
        # different shapes of entry.
        one = argparse.Namespace(**vars(args))
        one.pr = str(number)
        one.backfill = False
        rc = append_one(one, token, fetch=fetch)
        if rc != 0:
            failed += 1
            continue
        # rc 0 does NOT mean an entry was written. append_one also returns 0 for
        # the legitimate no-entry-needed case (a standard-tier or spike change
        # with no spec), so counting every zero as an append would report work
        # that never happened. Ask the ledger instead of inferring.
        if slug in existing_change_ids(ledger_path):
            already.add(slug)
            appended += 1
        else:
            no_spec += 1

    print("ledger-append: backfill scanned %d merged pull request(s): appended %d, "
          "already recorded %d, skipped %d with no change spec, failed %d"
          % (len(candidates), appended, seen_already, no_spec, failed))
    if failed:
        # Loud. A partial backfill leaves the durable record incomplete, and
        # "appended 2" with nothing else said reads as success. Re-running is
        # safe: the scan skips everything already present.
        sys.stderr.write(
            "ledger-append: %d pull request(s) could not be recorded - the ledger "
            "is INCOMPLETE. Re-running --backfill is safe and will retry only "
            "those.\n" % failed)
        return 1
    return 0


def append_one(args, token, fetch=np_github_api.default_fetch):
    """Append one pull request's entry. 0 on success or on a legitimate
    no-entry-needed case, 1 on an error worth stopping for."""
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


def main(argv, fetch=np_github_api.default_fetch):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", help="one pull request number; omit with --backfill")
    p.add_argument("--backfill", action="store_true",
                   help="append every recently merged pull request the ledger is "
                        "missing, instead of one named pull request")
    p.add_argument("--limit", type=int, default=50,
                   help="how many recently closed pull requests --backfill scans "
                        "(default 50, capped at 100 by the API page size)")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--content-dir", default=os.environ.get("NP_CONTENT_DIR", ""))
    p.add_argument("--spec")
    p.add_argument("--tier")
    p.add_argument("--merge-sha")
    args = p.parse_args(argv[1:])

    if not args.backfill and not args.pr:
        p.error("either --pr N or --backfill is required")
    if args.backfill and args.pr:
        p.error("--pr and --backfill are mutually exclusive")
    # --spec/--tier/--merge-sha describe ONE pull request. Silently applying a
    # single spec path or merge sha to every backfilled entry would write a
    # ledger full of confidently wrong records.
    if args.backfill:
        for flag in ("spec", "tier", "merge_sha"):
            if getattr(args, flag):
                p.error("--%s applies to a single --pr, not to --backfill"
                        % flag.replace("_", "-"))

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.stderr.write("ledger-append: no GITHUB_TOKEN - aborting (this is the durable "
                         "record; a silent no-op here would be worse than a loud failure)\n")
        return 1

    if not args.content_dir:
        sys.stderr.write("ledger-append: no --content-dir and $NP_CONTENT_DIR is unset\n")
        return 1

    if args.backfill:
        return backfill(args, token, fetch=fetch)
    return append_one(args, token, fetch=fetch)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
