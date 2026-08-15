---
id: 0005
status: accepted
date: 2026-08-15
tier: normal
blast_radius:
  - engine/setup/np-ledger-append.py
  - engine/setup/np_github_api.py
  - engine/setup/np-gate-verdicts-comment.py
  - engine/onboard/ONBOARD.md
  - dashboard/build.py
  - dashboard/index.html
  - engine/setup/tests/docs/test_ledger_append.py
  - engine/setup/tests/docs/test_github_api.py
  - engine/setup/tests/docs/test_gate_verdicts_comment.py
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - change-specs/**
---

# 0005: change ledger (F5)

## Context and problem statement

`dashboard/data/metrics.jsonl` is session-keyed. There is no change → spec →
gate-decision chain — the missing half criterion 06 needs. F4/#250 gave every
gate a structured verdict; nothing yet persists that verdict against a
specific change, durably, across runs.

## Considered options

1. **A manually-run local script, reading the F4 comment's embedded JSON,
   appending to the overlay's `ledger.jsonl`** — Good, because it matches the
   exact precedent `metrics.jsonl` already sets (a local aggregator, not CI,
   populates overlay telemetry) and needs no new cross-repo credentials. Bad,
   because it is a manual step, not an enforced one — nothing currently fails
   a merge for skipping it. Neutral, because a future CI-side enforcement (a
   required check verifying a ledger entry exists) is a natural follow-up,
   not built here.
2. **A GitHub Actions job in the engine repo, given write access to the
   private overlay repo via a cross-repo token** — Good, fully automatic.
   Bad, and this is the real reason it's rejected: it would require minting
   and storing a credential scoped to write into a *different, private* repo
   from a *public* repo's CI — exactly the kind of standing cross-repo
   credential this project's engine/overlay split exists to avoid. Rejected.
3. **Store the ledger in the engine repo instead**, sidestepping the
   cross-repo problem — Good, CI could write it directly. Bad, change
   history about engine-repo work is still personal analytics (the same
   reasoning that already keeps `metrics.jsonl` in the overlay despite being
   about engine-repo sessions) — moving only the ledger to the engine repo
   while metrics stays in the overlay would split one dataset's two halves
   across two repos for no principled reason. Rejected.

## Decision

We will add `np-ledger-append.py`, a locally-run script following the
`metrics.jsonl` aggregator precedent, plus a small shared `np_github_api.py`
module (factored out of F4's comment poster once a second real caller
needed the same plumbing) and dashboard wiring to display it.

Chosen option: "manual local script, reading F4's embedded JSON", because it
requires no new credential and reuses proven mechanism twice over — the
overlay-write precedent and the embedded-JSON read path.

## Non-goals

- **Enforcing that a ledger entry exists before/after merge.** Not gated by
  anything yet. A future CI check or reminder is real follow-up work, not
  scope creep to fold in here.
- **A cross-script import between `np-gate-verdicts-comment.py` and
  `np-ledger-append.py`.** Considered; the ~8-line JSON-extraction function
  is deliberately duplicated (documented as such in both files) rather than
  importing one hyphenated entry-point script from another, which this
  codebase doesn't do anywhere else. `np_github_api.py` is the real DRY line
  — factored out because it's substantive plumbing two callers now need, not
  a trivial helper.
- **SBOM/VSA/CDXA emission.** Named out of scope in the issue itself; still
  true here.

## Cross-cutting concerns

- **Security:** `GITHUB_TOKEN`/`GH_TOKEN` read from the environment only,
  never a CLI arg, matching F4's own posture. No write access to the overlay
  is ever granted to CI — the whole point of running this locally.
- **Privacy:** the ledger lives in the private overlay, matching
  `metrics.jsonl`'s existing placement. No new PII surface — `change_id`,
  `spec`, `tier`, gate names/verdicts/SHAs are all already public (visible
  on the PR itself).
- **Observability:** this change *is* the observability work — see
  Confirmation.

**Deliberate difference in failure posture from F4:** `np-gate-verdicts-comment.py`
fails open (a broken comment is cosmetic). `np-ledger-append.py` fails
**closed** on a missing token or PR-fetch error (returns 1, not 0) — this is
the durable record; a silent no-op here would be worse than a loud one. A
missing spec file is NOT treated as a failure, though — standard-tier and
spike-path changes may legitimately have none, per #247's own skip rule.

## Consequences

- Good, because a change now has a durable, change-keyed record linking spec,
  tier, gate verdicts, and the commit that shipped it.
- Good, because the dashboard surfaces it using the exact same pattern
  (`load_records()`, a `window.X` global in the shared `metrics.js`) every
  other panel already uses — no new rendering mechanism.
- Bad, because it is a manual step today. Explicitly named, not hidden.
- Neutral, because the `Spec:` trailer and the ledger entry are two
  independent links to the same spec file — either survives if the other is
  skipped for one merge.

## Confirmation

`test_github_api.py` (3 tests, mocked `urlopen`), `test_ledger_append.py` (14
tests: gate trimming, entry shape, append/no-overwrite, the extraction
mirror, PR-meta parsing, comment-finding, and the three failure-mode
branches — missing token, missing content-dir, missing spec is NOT an
error), 2 new tests in `test_gate_verdicts_comment.py` for the JSON-embedding
round-trip, and 2 new tests in `test_dashboard_build.py` for `window.LEDGER`
emission (fixture pass-through sorted by `ts`, and fail-open on a missing
file). Visually verified in a real browser against a real HTTP server (not
a file:// static snapshot, which does not execute external `<script src>`
tags and produced a false negative on first attempt) with three fixture
ledger entries — panel renders tier badges, spec paths, gate-verdict icons,
short merge SHAs, and dates, newest first.

## Deviations

None. The change stayed within the declared blast radius (the addition of
`np_github_api.py` and the refactor of `np-gate-verdicts-comment.py` were
both anticipated in the Decision above, not discovered mid-implementation).
