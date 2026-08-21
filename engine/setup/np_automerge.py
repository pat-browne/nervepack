#!/usr/bin/env python3
"""Confidence-gated auto-merge decision (F9/#255).

Answers one question: may this pull request merge without a human, and if not,
which condition stopped it.

**This module decides. It never merges.** The CI job it feeds asks GitHub to
enable NATIVE auto-merge, which is a waiting mechanism: GitHub holds the pull
request until every required check passes and every ruleset requirement is met,
then merges. It sits on the same side of the gate as a human clicking the
button, so it cannot bypass one.

The alternative -- a workflow that calls the merge API when it judges the pull
request ready -- was rejected in change spec 0012. That job would hold a token
able to merge whether or not the gates passed, and the safety property would
rest on our own conditional being right forever.

Two things this deliberately does NOT check, because the branch ruleset already
guarantees them:

  Unresolved review findings. `diff-review` is advisory and never reports
  FAILED; what it does with a finding is post a review comment, and the ruleset
  requires conversation resolution. A pull request with open findings is
  natively unmergeable, so auto-merge waits for a human. This module checks only
  that the lens RAN, because SKIPPED means no adversarial signal exists at all.

  A stale base. `strict_required_status_checks_policy` means a pull request
  cannot merge while behind `main`, so a base move forces re-verification. That
  is Prow/Tide's guarantee obtained from the ruleset rather than from code.

`eligible` and `enabled` are kept separate so a watch period is meaningful: with
the kill switch off, the record still says whether this change WOULD have merged
itself.

Pure stdlib, no I/O beyond reading the policy file.
"""
import json
import os

SCHEMA = "nervepack.automerge/1"

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(_HERE, "automerge.json")

POLICY_SCHEMA = 1
ADVERSARIAL_GATE = "diff-review"
PASSED = "PASSED"


class PolicyError(Exception):
    """The policy file is missing, unparseable, or declares something unknown.

    Raised rather than defaulted. A policy file that vanished must not read as
    "auto-merge everything", and it must not read as "auto-merge nothing"
    silently either -- the first is dangerous and the second is a gate that
    stopped working with no one told.
    """


def load(path=None):
    """Parse and validate the policy. Raises PolicyError on any problem."""
    path = path or DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise PolicyError("cannot read auto-merge policy at %s: %s" % (path, exc))
    except ValueError as exc:
        raise PolicyError("auto-merge policy at %s is not valid JSON: %s" % (path, exc))

    if not isinstance(data, dict):
        raise PolicyError("auto-merge policy must be a JSON object")
    if data.get("schema") != POLICY_SCHEMA:
        raise PolicyError("auto-merge policy schema %r is not the supported %d"
                          % (data.get("schema"), POLICY_SCHEMA))
    if not isinstance(data.get("enabled"), bool):
        raise PolicyError("auto-merge policy 'enabled' must be true or false, not %r"
                          % (data.get("enabled"),))
    for field in ("allowed_tiers", "trusted_authors"):
        value = data.get(field)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise PolicyError("auto-merge policy %r must be a list of strings" % field)
    return data


def _eligibility_reasons(tier_policy, author, policy):
    """Every reason this pull request may not merge itself, not just the first.

    Collected rather than short-circuited: a record that names one blocker sends
    the reader round the loop again for the next one, and the whole point of
    writing the decision down is to read it once.
    """
    reasons = []

    if not isinstance(tier_policy, dict):
        return ["no tier policy was produced for this pull request, so nothing "
                "is known about what it touched"]

    tier = tier_policy.get("tier")
    if not tier_policy.get("auto_merge_eligible"):
        problems = tier_policy.get("problems") or []
        detail = ("; ".join(problems) if problems
                  else "tier '%s' never auto-merges" % tier)
        reasons.append("tier-gate did not mark this eligible: %s" % detail)

    allowed = policy.get("allowed_tiers", [])
    if tier not in allowed:
        reasons.append("tier '%s' is not in the policy's allowed_tiers %s"
                       % (tier, allowed))

    trusted = policy.get("trusted_authors", [])
    if not author:
        reasons.append("no pull request author was supplied, so trust cannot be "
                       "established")
    elif author not in trusted:
        reasons.append("author '%s' is not in the policy's trusted_authors" % author)

    verdicts = tier_policy.get("gate_verdicts") or {}
    lens = verdicts.get(ADVERSARIAL_GATE)
    if lens != PASSED:
        reasons.append(
            "the adversarial lens did not run (%s is %s). Its FINDINGS stay "
            "advisory and are handled by the ruleset's conversation-resolution "
            "requirement; this checks only that a lens was applied at all."
            % (ADVERSARIAL_GATE, lens or "absent"))

    return reasons


def decide(tier_policy, author, policy):
    """The full decision record for one pull request.

    `author` MUST be github.event.pull_request.user.login. Never github.actor,
    which is the last identity to act on the pull request rather than its
    author: an attacker who can cause any bot activity on a pull request they
    control flips that context and inherits the privileged path. It is a
    parameter, not something this module reads from the environment, so a test
    can prove which one the caller passed.

    The returned dict is written verbatim as the decision artifact, so its shape
    is a contract.
    """
    reasons = _eligibility_reasons(tier_policy, author, policy)
    eligible = not reasons
    enabled = bool(policy.get("enabled"))
    return {
        "schema": SCHEMA,
        "tier": (tier_policy or {}).get("tier") if isinstance(tier_policy, dict) else None,
        "author": author,
        # Everything except the kill switch. During a watch period this is the
        # interesting field: it says whether the change WOULD have merged itself.
        "eligible": eligible,
        "enabled": enabled,
        # The only field the workflow acts on.
        "will_enable": eligible and enabled,
        "reasons": reasons,
    }
