#!/usr/bin/env python3
"""tier-gate: apply the tier's requirement set to one pull request (F8/#254).

Resolves the diff's risk tier through engine/setup/risk-tiers.json, reads the
gate verdicts every other CI job already uploaded (F4/#250), and decides whether
this change satisfied what its tier demands. Writes the decision as
tier-policy.json, which is #255's input for auto-merge.

Why this reads verdicts instead of re-running checks: every PR runs the same
jobs and the tier decides which of their verdicts are load-bearing. Skipping
jobs a tier does not need was rejected -- a skipped required check on GitHub is
indistinguishable from a pending one, so a conditionally-skipped required check
strands the PR forever.

The policy itself lives in np_tier_policy.py. This file is I/O: git, the
registry, the verdict directory, and an exit code.

Ships advisory. The CI job is `continue-on-error: true` and the check stays out
of the required set until it has been watched on real PRs -- this repo's own
"ship any new gate advisory first, then promote" rule. It reports its real exit
code regardless, because an advisory period that reports nothing measures
nothing.

Usage:
  np-tier-gate.py --root DIR --verdicts-dir DIR --out PATH
                  [--base REF] [--head REF] [--branch NAME]

Exit 0 = clean, not a pull request, or fail-open on our own git error.
Exit 1 = the tier's requirements are not satisfied, or the registry is broken.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_change_spec  # noqa: E402
import np_risk_tiers  # noqa: E402
import np_tier_policy  # noqa: E402


def changed_files(root, base, head):
    """None on a git error (unresolvable ref, e.g. a shallow clone); a
    (possibly empty) list of repo-relative paths otherwise. Mirrors
    np-spec-guard.py deliberately: the two gates must see the same diff."""
    out = subprocess.run(
        ["git", "-C", root, "diff", "--name-only", "%s...%s" % (base, head)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write(
            "tier-gate: could not diff %s...%s (%s) - skipping\n"
            % (base, head, out.stderr.strip())
        )
        return None
    return [p for p in out.stdout.splitlines() if p]


def read_verdicts(verdicts_dir):
    """{gate: verdict} from every gate-verdict-*.json in a directory.

    Keyed on each file's own `gate` field rather than its filename: the filename
    is a workflow-authored artifact name, the field is what the emitting job
    declared it was gating. A file that is unreadable, unparseable, or missing
    either field is skipped rather than fatal -- an absent verdict is already a
    problem in np_tier_policy, reported there with the gate's name, and raising
    here would replace that specific message with a stack trace.
    """
    verdicts = {}
    if not verdicts_dir or not os.path.isdir(verdicts_dir):
        return verdicts
    for path in sorted(glob.glob(os.path.join(verdicts_dir, "gate-verdict-*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            sys.stderr.write("tier-gate: ignoring %s (%s)\n" % (path, exc))
            continue
        gate = isinstance(data, dict) and data.get("gate")
        verdict = isinstance(data, dict) and data.get("verdict")
        if gate and verdict:
            verdicts[gate] = verdict
    return verdicts


class SpecUnreadable(Exception):
    """The change spec exists but could not be read."""


def spec_text_for(root, branch):
    """The change spec's contents, or None when the branch has no spec.

    Raises SpecUnreadable when the file EXISTS and cannot be read. Returning
    None there would make np_tier_policy report "no change spec was found",
    sending the author to look for a file that is sitting right in front of
    them. A wrong reason costs more time than no reason.
    """
    path = np_change_spec.spec_path_for(root, np_change_spec.branch_slug(branch))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise SpecUnreadable("cannot read %s: %s" % (path, exc))


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".")
    p.add_argument("--base", default=os.environ.get("GITHUB_BASE_REF") or "")
    p.add_argument("--head", default=os.environ.get("GITHUB_HEAD_REF") or "HEAD")
    p.add_argument("--branch", default="")
    p.add_argument("--verdicts-dir", default="")
    p.add_argument("--out", default="")
    args = p.parse_args(argv[1:])

    if not args.base:
        print("tier-gate: no base ref (not a pull_request event) - nothing to check")
        return 0

    branch = args.branch or os.environ.get("GITHUB_HEAD_REF") or subprocess.run(
        ["git", "-C", args.root, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    files = changed_files(args.root, args.base, args.head)
    if files is None:
        return 0  # fail open on our own error resolving the diff, not on policy

    try:
        registry = np_risk_tiers.load()
    except np_risk_tiers.RegistryError as exc:
        # Same reasoning as spec-guard: a broken registry is a versioned file in
        # this repo, and reading it as "nothing to check" would be a silent
        # repo-wide downgrade of every tier at once.
        sys.stderr.write("tier-gate: %s\n" % exc)
        return 1

    # The spec file itself is excluded from the tier computation, matching
    # spec-guard. `change-specs/**` is standard tier so it could never raise the
    # answer; excluding it keeps the two gates reading the same file list.
    spec_rel = np_change_spec.spec_rel_for(np_change_spec.branch_slug(branch))
    subject = [f for f in files if f != spec_rel]

    tier, offenders = np_risk_tiers.explain(subject, registry)
    try:
        spec_text = spec_text_for(args.root, branch)
    except SpecUnreadable as exc:
        # A policy failure, not an infra one, for the same reason a broken
        # registry is: the file is versioned in this repo, and reading it as
        # "no spec" would silently exempt the change from every spec-derived
        # requirement its tier has.
        sys.stderr.write("tier-gate: %s\n" % exc)
        return 1
    decision = np_tier_policy.evaluate(
        tier, spec_text, read_verdicts(args.verdicts_dir), tier_source=offenders)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(decision, fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            # Warn and carry on, deliberately. The artifact is observability;
            # the verdict below is the gate's actual job. Returning here on a
            # full disk would suppress a policy answer that is already computed
            # and correct, and report an infrastructure problem in the same
            # shape as an unmet requirement.
            sys.stderr.write("tier-gate: could not write %s: %s (continuing - "
                             "the verdict below is unaffected)\n"
                             % (args.out, exc))

    forced_by = ", ".join(path for path, _ in offenders[:5]) or "(empty diff)"
    print("tier-gate: tier '%s', forced by: %s" % (tier, forced_by))
    print("tier-gate: required gates: %s" % ", ".join(decision["required_gates"]))
    print("tier-gate: merge authority: %s; auto-merge eligible: %s"
          % (decision["merge_authority"], decision["auto_merge_eligible"]))

    if decision["problems"]:
        sys.stderr.write("tier-gate: tier '%s' requirements are not satisfied:\n" % tier)
        for problem in decision["problems"]:
            sys.stderr.write("  - %s\n" % problem)
        return 1

    print("tier-gate: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
