#!/usr/bin/env python3
"""Risk tier registry resolver (F7/#253).

Answers one question: what tier is this path, or this diff. `spec-guard` uses it
to decide whether a change needs a spec at all, and whether the tier the spec
declares is high enough for what the diff actually touches. #254 will use it to
vary the gate set and #255 to gate auto-merge.

**Last match wins**, mirroring CODEOWNERS. Position in the `rules` array decides,
not specificity. The alternative shapes were considered and rejected in
change-specs/feat-f7-risk-tiers.md: a tier-keyed object cannot express this at
all, since JSON object key order carries no semantic guarantee.

**The registry classifies itself high.** Otherwise the policy governing how much
scrutiny every change receives could be rewritten in a standard-tier diff that
needs no spec -- a privilege escalation using the tiering mechanism as the
vector. `test_risk_tiers.py` asserts it.

Pure stdlib.
"""
import fnmatch
import json
import os

SCHEMA = 1
# Ordered least to most restrictive. `satisfies` compares by index, so the
# ORDER here is the ratchet, not the names.
TIERS = ("standard", "normal", "high")

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(_HERE, "risk-tiers.json")


class RegistryError(Exception):
    """The registry is missing, unparseable, or declares something unknown.

    Raised rather than swallowed: a CI gate whose policy file vanished must say
    so. Quietly treating everything as the default would turn a broken registry
    into a silent, repo-wide downgrade -- the exact failure the self-classifying
    rules exist to prevent.
    """


def load(path=None):
    """Parse and validate the registry. Raises RegistryError on any problem."""
    path = path or DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise RegistryError("cannot read risk-tiers registry at %s: %s" % (path, exc))
    except ValueError as exc:
        raise RegistryError("risk-tiers registry at %s is not valid JSON: %s" % (path, exc))

    if not isinstance(data, dict):
        raise RegistryError("risk-tiers registry must be a JSON object")
    if data.get("schema") != SCHEMA:
        raise RegistryError("risk-tiers schema %r is not the supported %d"
                            % (data.get("schema"), SCHEMA))
    default = data.get("default")
    if default not in TIERS:
        raise RegistryError("risk-tiers default %r is not one of %s" % (default, TIERS))
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise RegistryError("risk-tiers 'rules' must be a list")
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("glob"):
            raise RegistryError("every risk-tiers rule needs a 'glob': %r" % (rule,))
        if rule.get("tier") not in TIERS:
            raise RegistryError("risk-tiers rule %r declares tier %r, not one of %s"
                                % (rule.get("glob"), rule.get("tier"), TIERS))
        _check_glob(rule["glob"])
    return data


def _check_glob(glob):
    """Reject a glob whose `[` never opened a character class.

    fnmatch does NOT raise on a malformed pattern - it silently escapes the
    unmatched `[` to a literal, so `**/hooks/[**` compiles to a regex demanding a
    literal `[` after `hooks/` and therefore matches NOTHING.

    For this file that is worse than a crash. A typo in a high-tier rule stops
    classifying anything, and every path it protected silently falls through to
    the `normal` default - no error, no warning, and no failing test unless the
    path happens to be one the self-classification test names.

    A valid class (`[a-z]`, `[pd]`) translates without an escaped bracket and is
    left alone. `[[]`, the escape for a literal `[` in a filename, is rejected
    too: a bracket in a path glob here is a typo far more often than an
    intention, and two rules always express the same thing more clearly.
    """
    if "\\[" in fnmatch.translate(glob):
        raise RegistryError(
            "risk-tiers glob %r has an unmatched '[' - fnmatch turns it into a "
            "LITERAL bracket rather than raising, so this rule silently matches "
            "nothing and every path it was meant to cover falls through to the "
            "default tier" % (glob,))


def tier_for(rel, registry):
    """Tier of one repo-relative path. LAST matching rule wins; the registry's
    `default` applies when nothing matches."""
    tier = registry.get("default", "normal")
    for rule in registry.get("rules", []):
        if fnmatch.fnmatch(rel, rule["glob"]):
            tier = rule["tier"]          # no break: last match wins, not first
    return tier


def tier_for_paths(rels, registry):
    """Highest tier across every path in a diff.

    Empty diff -> "standard": nothing touched is nothing to protect, and this is
    what lets spec-guard treat a no-op diff as exempt without a special case.
    """
    highest = 0
    for rel in rels:
        highest = max(highest, TIERS.index(tier_for(rel, registry)))
    return TIERS[highest] if rels else "standard"


def satisfies(declared, required):
    """True when `declared` is at least as restrictive as `required`.

    Over-declaring always passes -- the ratchet turns one way only. An
    unrecognized `declared` never passes, so a typo or an empty field cannot read
    as permission (spec-guard reports the bad vocabulary separately).
    """
    if declared not in TIERS or required not in TIERS:
        return False
    return TIERS.index(declared) >= TIERS.index(required)


def explain(rels, registry):
    """(required_tier, [(path, tier), ...]) for the paths at that tier.

    A tier failure that does not name the file which forced it is unactionable,
    so spec-guard reports the offenders rather than only the verdict.
    """
    required = tier_for_paths(rels, registry)
    offenders = [(r, tier_for(r, registry)) for r in rels
                 if tier_for(r, registry) == required]
    return required, offenders
