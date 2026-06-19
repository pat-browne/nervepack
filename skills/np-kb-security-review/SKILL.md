---
name: np-kb-security-review
description: Methodical source-to-sink security audit for code changes — enumerate sources and sinks, verify escapers/validators still guard every sink, classify trust boundaries (attacker vs operator vs victim), then adversarially refute each candidate finding. Use when reviewing or auditing a diff or codebase for security (XSS/DOM, injection, SSRF, path traversal, credential handling, info disclosure), or when a task says "security review", "audit", "is this safe", or "check for vulnerabilities".
---

# Security review — source-to-sink with adversarial refutation

The discipline that beats ad-hoc "look for scary functions": map every **source**
(attacker- or operator-controlled input) to every **sink** (where it lands and
could do harm), prove each sink is still guarded, then try to *refute* every
finding before reporting it. Invoke this FIRST on any security/audit/review task —
before opening files — so scope is set by the method, not by whatever you happen to
grep (see the `security-review-skill-first` playbook). Pairs with
[[np-kb-coding-rules]] (surgical, root-cause) and [[np-kb-testing-ci]] (the PII/secret gate).

## The method

1. **Read the existing security model first.** Manifest, scanner policy/allowlist,
   RUNBOOK, doctor, permission boundaries. Knowing what's *already* protected
   prevents false positives and reveals the intended trust boundaries.
2. **Enumerate sources** — user input, env vars, stdin, CLI args, config files, API
   responses, untrusted file content.
3. **Enumerate sinks** — `innerHTML`/`outerHTML`/raw HTML, network calls, subprocess
   args, file paths, `eval`/`exec`, SQL, template render, logs, IaC, file permissions.
4. **Trace each source → sink.** Verify a validator/escaper sits between them and
   that it's correct *for that sink's context* (an escaper built for one context is
   not automatically right for another — see references). A change that only
   *reads/compares* external data, or only swaps a constant feeding identical sinks,
   adds no attack surface.
5. **Classify the trust boundary** for each candidate:
   - **Operator-config** surfaces (endpoints, secrets, agent commands the operator
     sets) → validation shifts to the operator; classify *trusted*, not attacker-controlled.
   - **Single-user** vs **cross-tenant** — don't over-report a single-user issue as
     cross-tenant, and don't miss a real cross-user path.
6. **Adversarially refute every finding** before reporting. For each candidate ask:
   (1) who controls the input? (2) who is harmed? (3) is there a *privilege boundary*
   between them? (4) is there a sanitizer between input and sink? **Default verdict
   is SURVIVES (not a finding)** unless a refute criterion fails. "Dev-only" does
   **not** mitigate when the attacker is internet-reachable (any web page the
   developer visits while the dev server runs).
7. **Be diff-aware.** Distinguish `in_diff` (code this change adds) from `off_diff`
   (pre-existing). For `in_diff`, check for an added sanitizer / typed sink /
   privilege boundary. For `off_diff` candidates, require the specific diff line that
   newly enables the sink — otherwise it's not introduced by this change.

## Per-domain checklists

The high-miss, recurring checks (XSS/DOM escaping, credential-handling shell
scripts, browser/dashboard info-disclosure, YAML/template injection & SSRF, archive
extraction, config-only changes) live in **references/checklists.md** — consult it
when the diff touches that surface.

## Output

Report only findings that survive refutation. For each: the source, the sink, the
trust boundary that's crossed, the specific line, and a minimal fix. State what you
checked and ruled out (source→sink map) so "no findings" means "audited", not "skimmed".
