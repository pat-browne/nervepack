#!/usr/bin/env python3
"""Emit one structured gate verdict as a JSON file (F4/#250).

Schema (nervepack.gate-verdict/1):
  schema        str  "nervepack.gate-verdict/1" - bump the trailing version
                      when the MEANING of a field changes, not on every run
                      (in-toto SVR's "version the verifier identifier"
                      convention).
  gate          str  the CI job's name, e.g. "regression".
  verdict       str  "PASSED" | "FAILED" | "SKIPPED".
  reason        str  one-line human-readable summary.
  evidence_ref  str  URL to the full run. A locator, not a tamper-evident
                      proof - check runs are presentation, not record (see
                      the change-traceability wiki topic); F5's ledger is
                      the durable, change-keyed record.
  rules_sha     str  the commit SHA whose checked-out tree governed this run
                      (the workflow file and gate scripts ARE the rules).

No published standard fills this gap. SLSA VSA's verificationResult is
binary PASSED/FAILED with no rationale field; in-toto SVR has no negative
assertion at all (absence of a property is the failure signal, so it cannot
distinguish "gate failed" from "gate not run"). This is a deliberate
homegrown predicate, not a shortcut around an existing one.

Usage:
  np-gate-verdict.py --gate NAME --status success|failure|cancelled
    --reason TEXT --evidence-ref URL --rules-sha SHA --out PATH
"""
import argparse
import json
import sys

SCHEMA = "nervepack.gate-verdict/1"

_VERDICT_MAP = {"success": "PASSED", "failure": "FAILED"}


def to_verdict(status):
    """cancelled and any other/unknown status both map to SKIPPED - a job
    that started but didn't cleanly pass or fail reads the same as one that
    never ran, from a verdict-consumer's point of view."""
    return _VERDICT_MAP.get(status, "SKIPPED")


def build(gate, status, reason, evidence_ref, rules_sha):
    return {
        "schema": SCHEMA,
        "gate": gate,
        "verdict": to_verdict(status),
        "reason": reason,
        "evidence_ref": evidence_ref,
        "rules_sha": rules_sha,
    }


def main(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gate", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--evidence-ref", required=True)
    p.add_argument("--rules-sha", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv[1:])

    verdict = build(args.gate, args.status, args.reason, args.evidence_ref, args.rules_sha)
    with open(args.out, "w") as f:
        json.dump(verdict, f, indent=2)
        f.write("\n")
    print("gate-verdict: wrote %s (%s)" % (args.out, verdict["verdict"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
