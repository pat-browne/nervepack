#!/usr/bin/env python3
"""Differential gating by tier (F8/#254).

Answers one question: given the tier a diff resolves to, what must be true
before a human should merge it, and may it merge itself.

The design constraint that shapes everything here: **every PR runs the same
jobs, and the tier decides which of their verdicts are load-bearing.** The
alternative -- skipping jobs a tier does not need -- was rejected because a
skipped required check on GitHub is indistinguishable from a pending one, so a
conditionally-skipped required check strands the PR forever.

Consequently this module never re-checks what another gate already checked. It
does not parse a spec's frontmatter, diff a blast radius, or scan for secrets;
`spec-guard` and `pii-guard` do that and emit verdicts. This module *requires
those verdicts*. Composition rather than duplication is what keeps the two from
drifting into disagreement.

The one content check it does own is the rollback section, because no other gate
has a reason to look for it and it exists only for the `high` tier.

`high` requires the adversarial lens (F6/#252) to have RUN, never to have
PASSED. Measured LLM review precision is 50-85%, and the largest rejection
category is missing project context rather than wrongness, so making that
reviewer a blocking authority would be unsound. Requiring it to have been
applied is the strongest honest reading of DORA's "subject high-risk changes to
additional scrutiny": the lens was pointed at the diff and its output is on the
PR, and a human decides what it is worth.

Pure stdlib. No I/O -- `np-tier-gate.py` is the CLI that feeds it.
"""
import re

SCHEMA = "nervepack.tier-policy/1"

# Same order and vocabulary as np_risk_tiers.TIERS. Duplicated as a literal
# rather than imported so this module stays a pure policy statement with no
# dependency on the registry's file I/O; a test asserts the two agree.
TIERS = ("standard", "normal", "high")

# The five deterministic gates, by the `--gate` name each CI job passes to
# np-gate-verdict.py. Deterministic means: same tree in, same answer out, no
# model in the loop. Only gates of that kind are ever *required* to have passed.
DETERMINISTIC_GATES = ("syntax", "regression", "windows", "windows-bashfree",
                       "pii-guard")
SPEC_GATE = "spec-guard"
ADVERSARIAL_GATE = "diff-review"

# A verdict of exactly this satisfies a required gate. FAILED and SKIPPED do
# not, and neither does a verdict that never arrived -- see `_gate_problems`.
PASSED = "PASSED"
SKIPPED = "SKIPPED"

_ROLLBACK_HEADING = re.compile(r"^#{1,6}\s*rollback\b.*$", re.IGNORECASE | re.MULTILINE)
_ANY_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

_POLICY = {
    "standard": {
        "required_gates": list(DETERMINISTIC_GATES),
        "spec_required": False,
        "rollback_required": False,
        "adversarial_lens_required": False,
        "auto_merge_eligible": True,
        "merge_authority": "deterministic-gates",
    },
    "normal": {
        "required_gates": list(DETERMINISTIC_GATES) + [SPEC_GATE],
        "spec_required": True,
        "rollback_required": False,
        "adversarial_lens_required": False,
        "auto_merge_eligible": False,
        "merge_authority": "human",
    },
    "high": {
        "required_gates": list(DETERMINISTIC_GATES) + [SPEC_GATE],
        "spec_required": True,
        "rollback_required": True,
        "adversarial_lens_required": True,
        "auto_merge_eligible": False,
        "merge_authority": "human",
    },
}


def policy_for(tier):
    """The requirement set for one tier.

    An unrecognized tier gets `high`. A typo in a spec's `tier:` field, or a
    tier vocabulary that grew in the registry without growing here, must never
    read as permission -- and "I do not recognize this" has exactly one safe
    reading. Returns a copy: callers put this in a JSON artifact and a shared
    mutable default would let one PR's evaluation edit the next one's policy.
    """
    policy = dict(_POLICY.get(tier, _POLICY["high"]))
    # The list too, not just the dict: a shallow copy shares it, and a caller
    # appending to `required_gates` would edit every later evaluation's policy.
    policy["required_gates"] = list(policy["required_gates"])
    return policy


def _gate_problems(required, verdicts):
    """One line per required gate that is not PASSED.

    An ABSENT verdict is reported separately from a failing one, and neither
    passes. F4's own schema docstring names this: in-toto SVR has no negative
    assertion, so absence and failure are indistinguishable to a consumer that
    does not treat absence as a problem in its own right. A gate whose upload
    step never ran would otherwise be a free pass.
    """
    problems = []
    for gate in required:
        actual = verdicts.get(gate)
        if actual is None:
            problems.append(
                "required gate '%s' produced no verdict - it did not run, or its "
                "artifact upload failed. Absence is not a pass." % gate)
        elif actual != PASSED:
            problems.append("required gate '%s' is %s, not PASSED" % (gate, actual))
    return problems


def _rollback_problems(spec_text):
    """[] when the spec carries a rollback section with something under it.

    An empty heading is what a template leaves behind, so accepting one would
    turn a rollback *plan* into a formatting exercise.
    """
    if spec_text is None:
        return ["tier requires a rollback plan, but no change spec was found "
                "for this branch"]
    match = _ROLLBACK_HEADING.search(spec_text)
    if not match:
        return ["tier requires a '## Rollback' section in the change spec; "
                "none found"]
    body = spec_text[match.end():]
    next_heading = _ANY_HEADING.search(body)
    if next_heading:
        body = body[:next_heading.start()]
    if not body.strip():
        return ["the change spec's Rollback section is empty - a heading is not "
                "a plan"]
    return []


def _lens_problems(verdicts):
    """The adversarial lens must have run. Its findings are advisory."""
    actual = verdicts.get(ADVERSARIAL_GATE)
    if actual is None:
        return ["tier requires the adversarial lens, but '%s' produced no "
                "verdict" % ADVERSARIAL_GATE]
    if actual == SKIPPED:
        return ["tier requires the adversarial lens to have run; '%s' is "
                "SKIPPED. Its findings stay advisory - this requires the lens "
                "to have been applied, not to have approved."
                % ADVERSARIAL_GATE]
    return []


def evaluate(tier, spec_text, verdicts, tier_source=None):
    """The full decision record for one PR.

    `spec_text` is the change spec's contents, or None when the branch has no
    spec. `verdicts` maps gate name to "PASSED" | "FAILED" | "SKIPPED".
    `tier_source` is the [(path, tier)] list from np_risk_tiers.explain, carried
    through so a failure names the file that forced the tier.

    The returned dict is #255's input and is written verbatim to
    tier-policy.json, so its shape is a contract.
    """
    policy = policy_for(tier)
    problems = _gate_problems(policy["required_gates"], verdicts)
    if policy["rollback_required"]:
        problems.extend(_rollback_problems(spec_text))
    if policy["adversarial_lens_required"]:
        problems.extend(_lens_problems(verdicts))

    return {
        "schema": SCHEMA,
        "tier": tier,
        "tier_source": [{"path": p, "tier": t} for p, t in (tier_source or [])],
        "required_gates": policy["required_gates"],
        "spec_required": policy["spec_required"],
        "rollback_required": policy["rollback_required"],
        "adversarial_lens_required": policy["adversarial_lens_required"],
        "merge_authority": policy["merge_authority"],
        "gate_verdicts": dict(verdicts),
        "problems": problems,
        # Eligibility is the AND of "this tier may auto-merge at all" and "this
        # PR satisfied everything". #255 reads this one field, so it must never
        # be true on a PR with an open problem.
        "auto_merge_eligible": bool(policy["auto_merge_eligible"]) and not problems,
    }
