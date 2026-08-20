#!/usr/bin/env python3
"""Generate .github/CODEOWNERS from the risk tier registry (F8/#254).

CODEOWNERS is the only path-sensitive mechanism GitHub offers, and with one
maintainer it enforces nothing: required approvals are zero and the sole owner
is the author of every PR. So this file is **a declaration and a review route,
not a gate**. The gate is np-tier-gate.py, which reads risk-tiers.json directly.

Generating it rather than hand-writing it exists to stop one specific drift: a
high-risk path added to the registry and forgotten in CODEOWNERS, leaving a file
that claims to enumerate the sensitive paths and does not. A test asserts the
committed file matches this generator byte for byte.

## The globs are copied, not translated

risk-tiers.json globs are `fnmatch`, where `*` crosses `/`. CODEOWNERS patterns
are gitignore-style, where `*` does not and `**` does. The two disagree, and
this module copies the glob verbatim rather than rewriting it, because a
translation layer would be a second thing that can be wrong about the same
question.

The disagreement is real and runs both ways:

  engine/setup/*install*   under-matches here - CODEOWNERS will not reach a
                           nested engine/setup/x/install-y.sh that fnmatch does
  **/*cron*                over-matches here - CODEOWNERS also reaches a
                           top-level cron.py that fnmatch does not

That is acceptable only because this file routes review requests. Every gate
that decides anything reads the registry through np_risk_tiers, never this.

Syntactic safety comes free: np_risk_tiers._check_glob already rejects any glob
containing `[`, which is also the character class CODEOWNERS does not support.

Pure stdlib.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_risk_tiers  # noqa: E402

DEFAULT_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "..", ".github", "CODEOWNERS"))

# GitHub's cap. Past it, code-owner functionality is SILENTLY disabled for the
# whole repository - no warning, no error, the feature simply stops. A file this
# small will never approach it; the check exists so that if the registry ever
# grows machine-generated rules, the failure is a red test rather than a gate
# that quietly stopped applying.
SIZE_CAP_BYTES = 3 * 1024 * 1024

_CAVEAT = (
    "# The globs below are COPIED VERBATIM from risk-tiers.json, which uses\n"
    "# fnmatch, where `*` crosses `/`. CODEOWNERS uses gitignore-style matching,\n"
    "# where `*` does not and `**` does. The two therefore disagree in both\n"
    "# directions on some entries. That is tolerable because this file routes\n"
    "# review requests; every gate that DECIDES anything reads risk-tiers.json\n"
    "# through np_risk_tiers, never this file.\n"
)

_OWNER_LINE = re.compile(r"^\*\s+(\S.*?)\s*$", re.MULTILINE)


def owner_from(text):
    """The owner(s) on the `*` catch-all line, or None.

    Read out of the committed file rather than hardcoded here so the generator
    carries no account name of its own.
    """
    match = _OWNER_LINE.search(text or "")
    return match.group(1) if match else None


def high_tier_rules(registry):
    """The registry's high-tier rules, in registry order.

    Order is preserved because CODEOWNERS resolves last-match-wins exactly as
    the registry does, so copying the order copies the precedence.
    """
    return [r for r in registry.get("rules", []) if r.get("tier") == "high"]


def render(registry, owner):
    """The full CODEOWNERS text. Deterministic: same registry, same bytes."""
    lines = [
        "# Code owners for nervepack.",
        "#",
        "# GENERATED from engine/setup/risk-tiers.json by engine/setup/np_codeowners.py.",
        "# Do not edit by hand - add a rule to the registry and re-run:",
        "#   python3 engine/setup/np_codeowners.py --write",
        "# engine/setup/tests/docs/test_codeowners.py fails when this drifts.",
        "#",
        "# This file DECLARES the high-risk paths and routes review requests to",
        "# their owner. It does not gate anything. With one maintainer its",
        "# approval role is inert: required approvals are zero and the only owner",
        "# is the author of every pull request. It becomes load-bearing the day a",
        "# second contributor exists, and not before. The enforcing gate is",
        "# engine/setup/np-tier-gate.py.",
        "#",
    ]
    lines.extend(_CAVEAT.rstrip("\n").split("\n"))
    lines.extend([
        "#",
        "# https://docs.github.com/articles/about-code-owners",
        "",
        "# Default owner for everything in the repo. First, because CODEOWNERS",
        "# resolves last match wins - the high-risk rules below override it.",
        "*       %s" % owner,
        "",
        "# --- high-tier paths, from risk-tiers.json (last match wins) ---",
    ])
    for rule in high_tier_rules(registry):
        why = rule.get("why")
        if why:
            lines.append("# %s" % why)
        lines.append("%s    %s" % (rule["glob"], owner))
    return "\n".join(lines) + "\n"


def problems(text, registry, owner=None):
    """[] when the committed text is what this generator produces.

    `owner` defaults to the one already on the file's `*` line, so a maintainer
    handle change is a one-line edit followed by --write, not a code change.
    """
    owner = owner or owner_from(text)
    if not owner:
        return ["CODEOWNERS has no `*` catch-all line, so the owner cannot be "
                "read; nothing else can be checked"]
    found = []
    if len(text.encode("utf-8")) > SIZE_CAP_BYTES:
        found.append(
            "CODEOWNERS is over GitHub's %d-byte cap - past it, code-owner "
            "functionality is silently disabled for the whole repository"
            % SIZE_CAP_BYTES)
    if text != render(registry, owner):
        found.append(
            "CODEOWNERS is out of sync with engine/setup/risk-tiers.json - "
            "re-run `python3 engine/setup/np_codeowners.py --write`")
    return found


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Generate or check .github/CODEOWNERS")
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--owner", default="")
    p.add_argument("--write", action="store_true",
                   help="rewrite the file; default is to check it")
    args = p.parse_args(argv[1:])

    registry = np_risk_tiers.load()
    existing = ""
    if os.path.isfile(args.path):
        with open(args.path, encoding="utf-8") as fh:
            existing = fh.read()
    owner = args.owner or owner_from(existing)
    if not owner:
        sys.stderr.write("np_codeowners: no owner given and none found in %s\n"
                         % args.path)
        return 1

    if args.write:
        with open(args.path, "w", encoding="utf-8") as fh:
            fh.write(render(registry, owner))
        print("np_codeowners: wrote %s" % args.path)
        return 0

    found = problems(existing, registry, owner)
    for problem in found:
        sys.stderr.write("np_codeowners: %s\n" % problem)
    if found:
        return 1
    print("np_codeowners: %s is in sync with risk-tiers.json" % args.path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
