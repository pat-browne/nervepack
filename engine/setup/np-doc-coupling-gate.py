#!/usr/bin/env python3
"""doc-coupling gate: check that documentation moved with the change (F10/#256).

Two modes, one check.

  --out PATH                 pull-request mode. Evaluates the diff, writes the
                             result as an artifact, prints it, and ALWAYS exits 0.
  --open-issue --repo R      merge mode. Same evaluation against the merge
                             commit, and when it is unsatisfied, opens one issue
                             naming what was left behind.

The consequence is an issue rather than a red check, on purpose. GitLab runs a
hard documentation gate and still needed the three-day escape hatch; Danger's
canonical example ships a `#trivial` bypass. Both are admissions that
unconditional gates get disabled. With one maintainer holding the admin bit, a
blocking version would be overridden once and removed twice.

A red X can be dismissed and leaves nothing behind. An open issue has to be
closed by someone, and until it is, the debt sits where all the other work sits.
Deferred documentation is recorded, not forgiven.

The issue opens at MERGE, never on a pull request: opening from a pull-request
job would file one on every push to the branch, and would hand `issues: write`
to a job running on pull-request-derived input.

Usage:
  np-doc-coupling-gate.py --root DIR [--base REF] [--head REF] [--out PATH]
  np-doc-coupling-gate.py --root DIR --open-issue --repo owner/name
                          [--sha SHA] [--run-url URL]

Exit 0 in pull-request mode, always. Exit 1 only when the config is broken, or
when opening the issue failed in merge mode.
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_doc_coupling  # noqa: E402
import np_github_api  # noqa: E402

MARKER = "<!-- nervepack:doc-coupling -->"


def changed_and_removed(root, base, head):
    """(changed, removed) or (None, None) on a git error.

    `--name-status` rather than `--name-only`: rule 2 needs to know which paths
    went AWAY, and a rename reports as R with both names. The old name is what a
    stale document still points at, so it is the one recorded as removed.
    """
    out = subprocess.run(
        ["git", "-C", root, "diff", "--name-status", "-M", "%s...%s" % (base, head)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write("doc-coupling: could not diff %s...%s (%s) - skipping\n"
                         % (base, head, out.stderr.strip()))
        return None, None
    changed, removed = [], []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            removed.append(parts[1])
            changed.extend([parts[1], parts[2]])
        elif status.startswith("D") and len(parts) >= 2:
            removed.append(parts[1])
            changed.append(parts[1])
        elif len(parts) >= 2:
            changed.append(parts[1])
    return changed, removed


def issue_body(result, repo, sha, run_url):
    lines = [
        MARKER,
        "",
        "Documentation did not move with `%s`." % (sha or "this change"),
        "",
        "This is not a failure and nothing was blocked. The check is advisory by",
        "design — a blocking documentation gate gets overridden and then removed.",
        "The consequence is this issue, which someone has to close.",
        "",
    ]
    if result["triggers"] and not result["docs_changed"]:
        lines.append("## Triggers that fired, with no documentation in the change")
        lines.append("")
        for trigger in result["triggers"]:
            lines.append("- **%s** — %s" % (trigger["id"], ", ".join(trigger["paths"])))
        lines.append("")
    if result["dangling"]:
        lines.append("## Documents naming a path this change removed or renamed")
        lines.append("")
        for item in result["dangling"]:
            lines.append("- `%s` still names `%s`" % (item["doc"], item["removed"]))
        lines.append("")
        lines.append("This is the case the check exists for. Wen et al. (ICPC 2019,")
        lines.append("1.3 billion AST-level changes across 1,500 systems) found")
        lines.append("documentation drift arrives mostly as a side effect of")
        lines.append("refactoring, not of feature work.")
        lines.append("")
    lines.append("## Closing this")
    lines.append("")
    lines.append("Update the documentation, or close it with a sentence saying why")
    lines.append("none was needed. Either is a decision. Leaving it open is not.")
    if run_url:
        lines.extend(["", "Evidence: %s" % run_url])
    if repo and sha:
        lines.extend(["", "Change: https://github.com/%s/commit/%s" % (repo, sha)])
    return "\n".join(lines) + "\n"


def already_filed(repo, sha, token, fetch=np_github_api.default_fetch):
    """True when an issue for this exact commit is already open.

    A re-run of the same workflow must not file a second copy. Keyed on the SHA
    in the body rather than on the title, because a title is the part someone
    edits.
    """
    url = ("https://api.github.com/repos/%s/issues?state=open&per_page=100" % repo)
    for issue in fetch(url, token) or []:
        body = issue.get("body") or ""
        if MARKER in body and sha and sha in body:
            return issue.get("number")
    return None


def open_issue(repo, sha, run_url, result, token, fetch=np_github_api.default_fetch):
    existing = already_filed(repo, sha, token, fetch=fetch)
    if existing:
        print("doc-coupling: issue #%s already covers %s" % (existing, sha))
        return 0
    payload = json.dumps({
        "title": "docs: coupling unmet for %s" % (sha[:8] if sha else "a recent change"),
        "body": issue_body(result, repo, sha, run_url),
        "labels": ["documentation"],
    }).encode("utf-8")
    created = fetch("https://api.github.com/repos/%s/issues" % repo, token,
                    method="POST", data=payload)
    print("doc-coupling: opened issue #%s" % created.get("number"))
    return 0


def main(argv, fetch=np_github_api.default_fetch):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".")
    p.add_argument("--base", default="")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--out", default="")
    p.add_argument("--open-issue", action="store_true")
    p.add_argument("--repo", default="")
    p.add_argument("--sha", default="")
    p.add_argument("--run-url", default="")
    p.add_argument("--config", default="")
    args = p.parse_args(argv[1:])

    try:
        config = np_doc_coupling.load(args.config or None)
    except np_doc_coupling.ConfigError as exc:
        sys.stderr.write("doc-coupling: %s\n" % exc)
        return 1

    base = args.base or ("%s^" % args.head if args.open_issue else "")
    if not base:
        print("doc-coupling: no base ref - nothing to check")
        return 0

    changed, removed = changed_and_removed(args.root, base, args.head)
    if changed is None:
        return 0  # fail open on our own git error, never on policy

    result = np_doc_coupling.evaluate(args.root, changed, removed, config)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            # Warn and carry on: the artifact is observability around a result
            # that still gets printed below, and this check never blocks anyway.
            sys.stderr.write("doc-coupling: could not write %s: %s (continuing)\n"
                             % (args.out, exc))

    if result["satisfied"]:
        print("doc-coupling: satisfied")
    else:
        print("doc-coupling: %d unmet coupling(s) - ADVISORY, nothing is blocked"
              % len(result["problems"]))
        for problem in result["problems"]:
            print("doc-coupling:   - %s" % problem)

    if args.open_issue:
        if result["satisfied"]:
            return 0
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token or not args.repo:
            sys.stderr.write("doc-coupling: --open-issue needs GITHUB_TOKEN and "
                             "--repo; the debt was NOT recorded\n")
            return 1
        return open_issue(args.repo, args.sha, args.run_url, result, token, fetch=fetch)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
