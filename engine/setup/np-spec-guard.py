#!/usr/bin/env python3
"""spec-guard: fail a PR when a change touching non-exempt paths has no
change-specs/<branch-slug>.md, a required frontmatter field is empty, a
[NEEDS CLARIFICATION] marker remains, or the diff touches a path the spec's
blast_radius did not declare. See change-specs/README.md for the schema.

Exempt today: doc-only and test-only diffs (a path heuristic). Once
engine/setup/risk-tiers.json exists (#253) its standard-tier globs should take
precedence over this heuristic - not implemented yet, since that issue hasn't
defined the schema.

Ships advisory: this script always reports its real exit code, but the CI job
that runs it is `continue-on-error: true` until promoted into the
required-checks ruleset after a watch period (see change-specs/README.md).

Usage:
  np-spec-guard.py --root DIR [--base REF] [--head REF] [--branch NAME]

--base defaults to $GITHUB_BASE_REF (a bare branch name in Actions - pass
  "origin/<branch>" explicitly if that's what your checkout fetched).
  Unset and not given -> not a pull_request event, nothing to check, exit 0.
--head defaults to $GITHUB_HEAD_REF then falls back to the literal ref "HEAD".
--branch defaults to $GITHUB_HEAD_REF then the current branch
  (`git rev-parse --abbrev-ref HEAD`) - used only to compute the spec path.

Exit 0 = clean, exempt, or nothing to check; 1 = violation(s), listed on
stderr.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_change_spec  # noqa: E402
import np_frontmatter  # noqa: E402

REQUIRED_FIELDS = ("id", "status", "date", "tier")
VALID_STATUS_PREFIXES = ("proposed", "rejected", "accepted", "superseded by")
VALID_TIERS = ("standard", "normal", "high")
# A bare occurrence is a live, unresolved marker (TEMPLATE.md's instruction:
# "mark an underspecified point with this exact string"). A backtick-quoted
# occurrence (`` `[NEEDS CLARIFICATION]` ``) is prose *describing* the
# convention - e.g. this repo's own README.md and specs that explain the
# mechanism - and must not trip the check. Real bug, caught by dogfooding
# this tool against its own PR's spec (#248).
NEEDS_CLARIFICATION = "[NEEDS CLARIFICATION]"
_BARE_NEEDS_CLARIFICATION = re.compile(
    r"(?<!`)\[NEEDS CLARIFICATION\](?!`)"
)

# Doc/test-only exemption, used only until engine/setup/risk-tiers.json (#253)
# can classify tiers itself. fnmatch's `*` is not path-aware - it already
# crosses `/` (translates to regex `.*`) - so a single `*` here behaves like a
# recursive glob; write patterns assuming any wildcard reaches arbitrary depth.
EXEMPT_GLOBS = (
    "*.md",
    "docs/*",
    "wiki/*",
    "*/tests/*",
    "change-specs/*",
)


# Spec location and blast-radius matching live in np_change_spec, shared with
# the drift-guard PreToolUse hook (F3/#249). Two copies of this matcher would
# let a branch pass locally and fail here on the radius alone. Kept as
# module-level names because they are this script's stable surface.
branch_slug = np_change_spec.branch_slug
spec_path_for = np_change_spec.spec_path_for


def changed_files(root, base, head):
    """None on a git error (unresolvable ref, e.g. a shallow clone); a
    (possibly empty) list of repo-relative paths otherwise."""
    out = subprocess.run(
        ["git", "-C", root, "diff", "--name-only", "%s...%s" % (base, head)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write(
            "spec-guard: could not diff %s...%s (%s) - skipping\n"
            % (base, head, out.stderr.strip())
        )
        return None
    return [p for p in out.stdout.splitlines() if p]


def is_exempt(root, files):
    tiers_path = os.path.join(root, "engine", "setup", "risk-tiers.json")
    if os.path.isfile(tiers_path):
        # #253 not yet built - when it lands, prefer its standard-tier globs
        # over the heuristic below rather than guessing at an undefined schema.
        pass
    if not files:
        return True
    return all(any(fnmatch.fnmatch(f, g) for g in EXEMPT_GLOBS) for f in files)


def validate_spec(text):
    """List of human-readable problems; [] means clean."""
    problems = []
    for field_name in REQUIRED_FIELDS:
        if not np_frontmatter.field(text, field_name, ""):
            problems.append("frontmatter field '%s:' is missing or empty" % field_name)
    tier = np_frontmatter.field(text, "tier", "")
    if tier and tier not in VALID_TIERS:
        problems.append("tier '%s' is not one of %s" % (tier, VALID_TIERS))
    status = np_frontmatter.field(text, "status", "")
    if status and not any(status.startswith(p) for p in VALID_STATUS_PREFIXES):
        problems.append(
            "status '%s' is not proposed|rejected|accepted|superseded by <NNNN>" % status
        )
    if not np_frontmatter.list_field(text, "blast_radius"):
        problems.append("frontmatter field 'blast_radius:' has no path globs")
    if _BARE_NEEDS_CLARIFICATION.search(text):
        problems.append(
            "a %s marker remains - resolve before merging" % NEEDS_CLARIFICATION
        )
    return problems


diff_outside_blast_radius = np_change_spec.outside_radius


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".")
    p.add_argument("--base", default=os.environ.get("GITHUB_BASE_REF") or "")
    p.add_argument("--head", default=os.environ.get("GITHUB_HEAD_REF") or "HEAD")
    p.add_argument("--branch", default="")
    args = p.parse_args(argv[1:])

    if not args.base:
        print("spec-guard: no base ref (not a pull_request event) - nothing to check")
        return 0

    branch = args.branch or os.environ.get("GITHUB_HEAD_REF") or subprocess.run(
        ["git", "-C", args.root, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    files = changed_files(args.root, args.base, args.head)
    if files is None:
        return 0  # fail open on our own error resolving the diff, not on policy

    if is_exempt(args.root, files):
        print("spec-guard: exempt diff (doc/test-only, or no changes) - clean")
        return 0

    slug = branch_slug(branch)
    spec_file = spec_path_for(args.root, slug)
    spec_rel = "change-specs/%s.md" % slug

    if not os.path.isfile(spec_file):
        sys.stderr.write(
            "spec-guard: no %s found for a non-exempt change.\n"
            "Add one from change-specs/TEMPLATE.md with these frontmatter "
            "fields: id, status, date, tier, blast_radius (a list of path "
            "globs). See change-specs/README.md.\n" % spec_rel
        )
        return 1

    with open(spec_file, "r") as f:
        text = f.read()

    problems = validate_spec(text)

    globs = np_frontmatter.list_field(text, "blast_radius")
    outside = diff_outside_blast_radius(
        [f for f in files if f != spec_rel], globs
    )
    if outside:
        problems.append(
            "diff touches path(s) outside declared blast_radius: %s"
            % ", ".join(sorted(outside))
        )

    if problems:
        sys.stderr.write("spec-guard: %s is not satisfied:\n" % spec_rel)
        for prob in problems:
            sys.stderr.write("  - %s\n" % prob)
        return 1

    print("spec-guard: %s clean" % spec_rel)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
