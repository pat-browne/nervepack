#!/usr/bin/env python3
"""F6/#252: multi-lens adversarial diff review. Advisory, never blocking.

## Why this stays advisory

Measured evidence does not support a blocking posture: 27-45% of agent
review comments go unresolved across 54,713 comments in 341 repositories
(arXiv 2607.21997); the largest rejection category is missing project
context at 23.8%, not wrongness - exactly what a blocking gate handles
worst, since the override path does not scale; LLMs systematically
overcorrect, misclassifying correct implementations as defective; Google
ships its own suggester at a 50% precision target specifically because it
is dismissable; GitHub's own Copilot code review always posts a "Comment"
review, never Approve or Request changes, and cannot satisfy CODEOWNERS or
block merging. Measured precision across tasks and tools: roughly 50-85%.

This script posts comments. It never votes, never approves, never requests
changes, and the `event` field passed to the GitHub review API is a fixed
literal - not a parameter anything can flip.

## Four distinct lenses, not N runs of one prompt

Perspective-based review catches 35% more defects than undirected review;
aggregating several raises F1 by up to 43.67% (SWR-Bench). Each lens below
is a genuinely different question, not the same prompt repeated - a
security-only finding on a line is not "the same finding" as a
maintainability note on that line, so findings are deduplicated only on
exact (file, line, comment) collision, never filtered to consensus.

## Fails open when the model is unavailable

Mirrors np_evaluator.py's own established check for exactly this scenario:
if the `claude` CLI isn't installed and executable, skip cleanly rather
than error. True today in this repo's CI - see this feature's own
change-spec for the CLAUDE_CODE_OAUTH_TOKEN secret this needs before it
does anything beyond logging a skip. Haiku (`claude-haiku-4-5-20251001`,
np_model.py's default cheap model) is the right tier per this repo's model
policy: single-shot, no tool use, bounded JSON output per lens.

Usage:
  np-diff-review.py --repo owner/name --pr N --repo-root DIR
    [--base REF] [--head REF] [--branch NAME]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_github_api  # noqa: E402

_NERVEPACK_ENGINE = os.path.normpath(os.path.join(_HERE, "..", "nervepack_engine"))
if _NERVEPACK_ENGINE not in sys.path:
    sys.path.insert(0, _NERVEPACK_ENGINE)
import np_model  # noqa: E402

SCHEMA = "nervepack.gate-verdict/1"  # must track np-gate-verdict.py's own SCHEMA
GATE_NAME = "diff-review"
CONVENTIONS_CAP = 4000

LENS_PROMPTS = {
    "correctness": (
        "You are reviewing this diff for CORRECTNESS: logic errors, off-by-one "
        "mistakes, null/None handling, race conditions, incorrect exception "
        "handling, and behavior that contradicts the stated intent."
    ),
    "security": (
        "You are reviewing this diff for SECURITY: injection (command, SQL, "
        "template), secret or credential handling, authentication/authorization "
        "boundaries, unsafe deserialization, and trust-boundary violations."
    ),
    "operability": (
        "You are reviewing this diff for OPERABILITY: what happens when this "
        "fails in production, error handling and logging, whether an on-call "
        "engineer could diagnose a failure from what this emits, and whether a "
        "rollback is possible."
    ),
    "maintainer": (
        "You are reviewing this diff AS THE MAINTAINER SIX MONTHS FROM NOW, with "
        "no memory of this PR's conversation: is the intent clear from the code "
        "alone, are names honest, is there a surprising behavior a future reader "
        "would trip over, and is anything here more clever than it needs to be."
    ),
}

_OUTPUT_FORMAT = (
    "\n\nRespond with a single JSON object, nothing else: "
    '{"findings": [{"file": "path/relative/to/repo", "line": <int, new-file line '
    'number>, "severity": "high"|"medium"|"low", "comment": "<one or two '
    'sentences>", "suggestion": "<optional: a concrete replacement for that line, '
    'or omit this key if there is none>"}]}. '
    'An empty diff or a diff with nothing to flag from this lens -> {"findings": []}. '
    "Do not invent files or line numbers outside the diff below."
)


def model_available():
    """Mirrors np_evaluator.py's own inline check for this exact scenario."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    if backend != "claude":
        return True
    claude = os.environ.get("CLAUDE_BIN") or os.path.join(
        os.path.expanduser("~"), ".local", "bin", "claude")
    return os.path.isfile(claude) and os.access(claude, os.X_OK)


def build_context(repo_root, spec_rel):
    """(spec_text_or_None, conventions_text). spec_text is the change-spec's
    content when one exists for this branch (may not - standard-tier/spike
    changes can have none). conventions_text is a capped excerpt of AGENTS.md,
    the canonical conventions doc for this repo - kept small per this repo's
    own "cap + extract" model-input policy."""
    spec_path = os.path.join(repo_root, spec_rel)
    spec_text = None
    if os.path.isfile(spec_path):
        with open(spec_path) as f:
            spec_text = f.read()
    conventions = ""
    agents_path = os.path.join(repo_root, "AGENTS.md")
    if os.path.isfile(agents_path):
        with open(agents_path) as f:
            conventions = f.read()[:CONVENTIONS_CAP]
    return spec_text, conventions


def lens_prompt(lens, diff_text, spec_text, conventions_text):
    parts = [LENS_PROMPTS[lens]]
    if conventions_text:
        parts.append("\n\nProject conventions (excerpt from AGENTS.md):\n" + conventions_text)
    if spec_text:
        parts.append("\n\nThis change's own spec (its stated intent and non-goals - "
                      "do not flag something the spec explicitly declares out of "
                      "scope):\n" + spec_text)
    parts.append("\n\nThe diff:\n" + diff_text)
    parts.append(_OUTPUT_FORMAT)
    return "".join(parts)


def parse_findings(raw_text):
    """Lenient JSON extraction via the shared np-json-extract.py tool (handles
    prose/markdown-fence-wrapped model output). Fail-open: no valid JSON
    object, or no "findings" list inside it -> []."""
    if not raw_text or not raw_text.strip():
        return []
    jx = subprocess.run(
        [sys.executable, os.path.join(_HERE, "np-json-extract.py")],
        input=raw_text, capture_output=True, text=True,
    )
    if jx.returncode != 0 or not jx.stdout.strip():
        return []
    try:
        obj = json.loads(jx.stdout)
    except ValueError:
        return []
    findings = obj.get("findings")
    return findings if isinstance(findings, list) else []


def run_lens(lens, diff_text, spec_text, conventions_text, complete=np_model.complete):
    prompt = lens_prompt(lens, diff_text, spec_text, conventions_text)
    raw = complete(prompt)
    findings = parse_findings(raw)
    for f in findings:
        f["lens"] = lens
    return findings


def dedup_findings(findings):
    """Collapse only exact (file, line, comment) duplicates across lenses.
    Deliberately NOT consensus-filtering (unlike adversarial-verify's
    refute-until-majority pattern) - each lens is meant to catch DIFFERENT
    things, so two distinct findings on the same line both survive."""
    seen = set()
    out = []
    for f in findings:
        key = (f.get("file"), f.get("line"), f.get("comment"))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def diff_line_positions(patch_text):
    """Valid RIGHT-side (new-file) line numbers a GitHub inline review comment
    may attach to, parsed from a unified-diff patch (as returned per-file by
    the Pulls Files API). Includes context and added lines; excludes
    removed-only lines (they have no new-file line number)."""
    positions = set()
    if not patch_text:
        return positions
    new_line = None
    for line in patch_text.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            new_line = int(m.group(1))
            continue
        if new_line is None:
            continue
        if line.startswith("-"):
            continue  # removed line: no new-file line number, don't advance
        positions.add(new_line)
        new_line += 1
    return positions


def build_review_comments(findings, file_patches):
    """(inline_comments, unplaced_findings). A finding lands as a true inline
    GitHub review comment only when its file is in the diff and its claimed
    line is a valid position in that file's patch; otherwise it's returned
    unplaced so the caller can fold it into the review's summary body instead
    of losing it or letting the GitHub API reject the whole review with a 422."""
    comments = []
    unplaced = []
    for f in findings:
        patch = file_patches.get(f.get("file"))
        if patch is None or f.get("line") not in diff_line_positions(patch):
            unplaced.append(f)
            continue
        body = f.get("comment", "")
        if f.get("suggestion"):
            body += "\n\n```suggestion\n%s\n```" % f["suggestion"]
        comments.append({
            "path": f["file"], "line": f["line"], "side": "RIGHT", "body": body,
        })
    return comments, unplaced


def render_review_body(findings, unplaced):
    lines = ["## Diff review (advisory)", "",
             "Multi-lens review — correctness, security, operability, and the "
             "maintainer six months from now. Comments only; this never "
             "approves, requests changes, or blocks merge."]
    if not findings:
        lines.append("")
        lines.append("No findings from any lens.")
        return "\n".join(lines)
    if unplaced:
        lines.append("")
        lines.append("**Findings outside the diff's inline range:**")
        for f in unplaced:
            lines.append("- `%s:%s` (%s, %s) — %s" % (
                f.get("file"), f.get("line"), f.get("lens"), f.get("severity"),
                f.get("comment")))
    return "\n".join(lines)


def build_verdict(findings, evidence_ref, rules_sha, verdict="PASSED", reason=None):
    """F4-shaped. This gate reports on whether the REVIEW PROCESS completed,
    never on the content of what it found - a finding existing is not a
    failure, so `verdict` stays PASSED whenever the review actually ran.
    SKIPPED is for when it didn't run at all (no model credential). See
    np-gate-verdict.py for the shared schema."""
    if reason is None:
        n = len(findings)
        lenses = len({f.get("lens") for f in findings})
        reason = ("%d finding%s across %d lens%s" %
                  (n, "" if n == 1 else "s", lenses, "" if lenses == 1 else "es")
                  if findings else "no findings")
    return {
        "schema": SCHEMA,
        "gate": GATE_NAME,
        "verdict": verdict,
        "reason": reason,
        "evidence_ref": evidence_ref,
        "rules_sha": rules_sha,
    }


def _write_verdict(path, verdict):
    with open(path, "w") as f:
        json.dump(verdict, f, indent=2)
        f.write("\n")


def fetch_pr_files(repo, pr, token, fetch=np_github_api.default_fetch):
    """{filename: patch}. A file with no `patch` key (e.g. binary, or a rename
    with no content change) is omitted - nothing to attach an inline comment to."""
    url = "https://api.github.com/repos/%s/pulls/%s/files?per_page=100" % (repo, pr)
    out = {}
    for f in fetch(url, token) or []:
        if f.get("patch"):
            out[f["filename"]] = f["patch"]
    return out


def post_review(repo, pr, token, body, comments, fetch=np_github_api.default_fetch):
    """event is a fixed literal - "COMMENT" - never a parameter. This is what
    makes "never approves, never requests changes, never blocks" true at the
    API level, not just by convention."""
    url = "https://api.github.com/repos/%s/pulls/%s/reviews" % (repo, pr)
    data = {"body": body, "event": "COMMENT"}
    if comments:
        data["comments"] = comments
    return fetch(url, token, method="POST", data=data)


def main(argv, fetch=np_github_api.default_fetch, complete=np_model.complete):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--base")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--branch")
    p.add_argument("--evidence-ref", default="")
    p.add_argument("--rules-sha", default="")
    p.add_argument("--out", default="gate-verdict-diff-review.json")
    args = p.parse_args(argv[1:])

    if not model_available():
        print("diff-review: claude CLI not installed/executable - skipping "
              "(see change-specs/feat-f6-diff-review.md for the credential "
              "this needs)")
        _write_verdict(args.out, build_verdict(
            [], args.evidence_ref, args.rules_sha, verdict="SKIPPED",
            reason="model unavailable (no claude CLI/credential configured)"))
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.stderr.write("diff-review: no GITHUB_TOKEN - skipping\n")
        _write_verdict(args.out, build_verdict(
            [], args.evidence_ref, args.rules_sha, verdict="SKIPPED",
            reason="no GITHUB_TOKEN available"))
        return 0

    branch = args.branch or subprocess.run(
        ["git", "-C", args.repo_root, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    slug = branch.replace("/", "-")
    spec_rel = "change-specs/%s.md" % slug
    spec_text, conventions_text = build_context(args.repo_root, spec_rel)

    try:
        file_patches = fetch_pr_files(args.repo, args.pr, token, fetch=fetch)
    except urllib.error.HTTPError as e:
        sys.stderr.write("diff-review: GitHub API error fetching PR files - %s %s\n"
                          % (e.code, e.reason))
        return 0

    diff_text = "\n\n".join(
        "--- %s ---\n%s" % (name, patch) for name, patch in file_patches.items()
    )

    all_findings = []
    for lens in LENS_PROMPTS:
        all_findings.extend(
            run_lens(lens, diff_text, spec_text, conventions_text, complete=complete))
    findings = dedup_findings(all_findings)

    comments, unplaced = build_review_comments(findings, file_patches)
    body = render_review_body(findings, unplaced)

    try:
        post_review(args.repo, args.pr, token, body, comments, fetch=fetch)
    except urllib.error.HTTPError as e:
        sys.stderr.write("diff-review: GitHub API error posting review - %s %s\n"
                          % (e.code, e.reason))

    _write_verdict(args.out, build_verdict(findings, args.evidence_ref, args.rules_sha))
    print("diff-review: %d finding(s) across %d file(s)" % (len(findings), len(file_patches)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
