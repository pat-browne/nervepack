#!/usr/bin/env python3
"""auto-merge gate: decide whether a pull request may merge without a human
(F9/#255).

Reads tier-policy.json (F8/#254) and engine/setup/automerge.json, writes the
decision as automerge-decision.json, and reports `will_enable` on
$GITHUB_OUTPUT so the workflow can conditionally ask GitHub to enable NATIVE
auto-merge.

**Nothing here merges anything.** The workflow step that follows calls
`gh pr merge --auto`, which asks GitHub to hold the pull request until every
required check and ruleset requirement is satisfied. That is a waiting
mechanism, on the same side of the gate as a human clicking the button. A
script that merged directly would hold a token able to merge regardless of gate
state, and change spec 0012 rejects that shape.

The decision is written and the verdict emitted on EVERY pull request, whether
it qualifies or not. A record that exists only when the mechanism fires cannot
be audited for the case that matters -- the one where it fired and should not
have -- and it is also what makes the shipped-disabled watch period worth
running.

--author MUST be github.event.pull_request.user.login. Never github.actor: that
is the last identity to act on the pull request, not its author, and an attacker
who can cause any bot activity on a pull request they control flips it.

Usage:
  np-automerge-gate.py --tier-policy PATH --author LOGIN [--policy PATH]
                       [--out PATH]

Exit 0 = a decision was made and recorded, whichever way it went.
Exit 1 = the policy file is missing or invalid, which is not a decision.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_automerge  # noqa: E402


def read_tier_policy(path):
    """The tier policy dict, or None when it is missing or unreadable.

    None is a legitimate input: np_automerge.decide treats it as "nothing is
    known about what this pull request touched", which blocks. Failing hard here
    would turn a missing artifact into a red check on a pull request that may be
    perfectly fine and simply not eligible.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("auto-merge: cannot read %s (%s) - treating it as absent, "
                         "which blocks auto-merge\n" % (path, exc))
        return None


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tier-policy", default="tier-policy.json")
    p.add_argument("--author", default="")
    p.add_argument("--policy", default="")
    p.add_argument("--out", default="")
    args = p.parse_args(argv[1:])

    try:
        policy = np_automerge.load(args.policy or None)
    except np_automerge.PolicyError as exc:
        # Loud, like a broken risk-tiers registry. A policy file that vanished
        # must not read as "auto-merge everything", and must not read as
        # "auto-merge nothing" silently either - the second is a mechanism that
        # stopped working with nobody told.
        sys.stderr.write("auto-merge: %s\n" % exc)
        return 1

    decision = np_automerge.decide(
        read_tier_policy(args.tier_policy), args.author, policy)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(decision, fh, indent=2)
            fh.write("\n")

    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as fh:
            fh.write("will_enable=%s\n" % ("true" if decision["will_enable"] else "false"))

    print("auto-merge: tier '%s', author '%s'" % (decision["tier"], decision["author"]))
    print("auto-merge: eligible=%s policy-enabled=%s -> will_enable=%s"
          % (decision["eligible"], decision["enabled"], decision["will_enable"]))
    if decision["eligible"] and not decision["enabled"]:
        print("auto-merge: this change WOULD have merged itself. The policy's "
              "kill switch is off, so it will not.")
    for reason in decision["reasons"]:
        print("auto-merge:   - %s" % reason)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
