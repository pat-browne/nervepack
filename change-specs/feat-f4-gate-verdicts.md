---
id: 0004
status: accepted
date: 2026-08-15
tier: normal
blast_radius:
  - .github/workflows/ci.yml
  - engine/setup/np-gate-verdict.py
  - engine/setup/np-gate-verdicts-comment.py
  - engine/setup/tests/docs/test_gate_verdict.py
  - engine/setup/tests/docs/test_gate_verdicts_comment.py
  - change-specs/**
---

# 0004: structured gate verdicts (F4)

## Context and problem statement

CI gates report pass/fail today with no structured reasoning attached.
Nothing records *why* a gate approved a change, or what would have satisfied
it if it failed. Criterion 06 (traceability) is Partial partly because of
this gap.

No published standard fills it, and that's the correct conclusion rather
than a gap to keep searching for: SLSA VSA's `verificationResult` is binary
PASSED/FAILED with no rationale field; in-toto SVR has no negative assertion
at all, so it can't distinguish "gate failed" from "gate never ran." Only
CycloneDX Attestations model rationale natively, and adopting that whole
framework for six CI jobs would be disproportionate. This is a deliberate
homegrown predicate.

## Considered options

1. **Per-job JSON artifact + a summary job that posts/amends one PR
   comment** — Good, because every job already uploads artifacts for other
   evidence (regression reports, e2e reports) — this is the same idiom, and
   posting one amended comment (not one per run) keeps a PR's comment
   history readable. Bad, because it adds two new steps to six jobs (~60
   lines of near-identical YAML) and a permissions grant to a new job.
   Neutral, because check runs themselves were considered and rejected below.
2. **Write the verdict directly into the job's own check-run output
   (`output.text`/`raw_details`)** — Good, because no new comment mechanism.
   Bad, and this is the one worth stating plainly: check runs are mutable by
   any app with `checks:write`, not content-addressed, and subject to GitHub's
   log retention — they are a UI surface, not a record. Using them as the
   only home for the verdict would silently misrepresent the guarantee this
   criterion needs. Rejected; the acceptance criteria say this explicitly and
   it's worth re-deriving here, not just citing.
3. **A single job-level GitHub Action from the marketplace for PR
   comments** — Good, less code. Bad, third-party trust dependency this
   codebase's language policy already avoids (stdlib-only, no external
   deps), and it doesn't know this repo's verdict schema. Rejected.

## Decision

We will add `np-gate-verdict.py` (writer, run once per existing job) and
`np-gate-verdicts-comment.py` (collector, run once by a new summary job),
both stdlib Python, using the existing artifact-upload/download idiom this
workflow already relies on for the regression and e2e reports.

Chosen option: "per-job artifact + one amended PR comment", because it
reuses proven CI mechanism, and because it lets us state on the record —
inside the comment itself and in this spec — that check runs are
presentation, never the record; a future F5 ledger is where the durable,
change-keyed history lives.

## Non-goals

- **F5's ledger.** This produces the per-run comment; it does not persist
  anything change-keyed across runs. That's the explicit next issue.
- **Auto-promoting any gate to blocking.** Unrelated to this change; gate
  blocking status is governed by the required-checks ruleset, not by
  whether it emits a verdict.
- **A composite Action to de-duplicate the six near-identical YAML blocks.**
  This repo has no existing composite-action precedent (checked
  `.github/actions/` before deciding — empty), and introducing the mechanism
  purely to save repetition in one PR would be exactly the kind of
  speculative abstraction the coding rules warn against. Plain repeated
  steps, matching how `regression`/`windows` already duplicate their report-
  publishing steps almost verbatim.
- **Rich per-gate `reason` text derived from parsing each gate's own
  output** (e.g. actual failing test names). Each job passes a static
  description string; parsing structured detail out of every gate's log is
  a larger, separate effort with its own failure modes, not required by the
  acceptance criteria as written.

## Cross-cutting concerns

- **Security:** the summary job is the first job in this workflow to
  request `permissions: pull-requests: write` — scoped to that one job only,
  not workflow-wide, and paired with `contents: read` (no broader grant).
  `GITHUB_TOKEN` is read from the environment inside the Python script, never
  passed as a CLI argument, so it cannot appear in a process listing or log
  line. Every value interpolated directly via `${{ }}` in the new `run:`
  lines (`job.status`, `github.sha`, `github.run_id`, `github.server_url`,
  `github.repository`) was checked against this repo's own
  security-guidance hook's risk list before writing — none of them are
  PR-author-controlled (unlike `head_ref`/`base_ref`, which #248 already
  had to fix once).
- **Privacy:** no personal data. The comment body is derived entirely from
  gate names, verdicts, and static reason strings already visible in CI logs.
- **Observability:** this change *is* the observability work for this
  criterion's gate-annotation gap. The summary job explicitly documents, in
  its own posted comment, that it is presentation and not the record.

## Consequences

- Good, because a PR now carries one legible, amended comment summarizing
  every gate's verdict, instead of needing to open six separate job logs.
- Good, because the `evidence_ref`/`rules_sha` fields give F5's future
  ledger something concrete to link back to per gate, per run.
- Bad, because six jobs each grew by ~10 lines of near-duplicate YAML — a
  real, accepted cost, not hidden (see Non-goals on composite actions).
- Neutral, because `dashboard-e2e` deliberately does not get a verdict step
  — it's already informational (`continue-on-error: true`) and outside the
  six gates the originating issue names.

## Confirmation

`engine/setup/tests/docs/test_gate_verdict.py` (8 tests: status-to-verdict
mapping including the unknown/cancelled fallback, verdict shape, and two
CLI end-to-end writes) and `engine/setup/tests/docs/test_gate_verdicts_comment.py`
(11 tests: loading/sorting verdicts, comment rendering including the
zero-verdicts case, finding an existing marked comment via an injectable
`fetch`, create-vs-patch branching, and a fail-open path when
`GITHUB_TOKEN` is absent). `python3 -c "import yaml; yaml.safe_load(...)"`
confirms the workflow file parses and lists all 8 jobs. Full suite green
locally before push.

## Deviations

None. The change stayed within the declared blast radius.
