---
id: 0085
status: accepted
date: 2026-10-14
tier: standard
blast_radius:
  - publish/np-publish-scan.py
  - .gitignore
  - engine/setup/tests/publish/**
  - change-specs/fix-scan-skip-venv.md
---

# 0085: Skip local virtualenvs in the PII scan

## Context and problem statement

A local `uv` run creates `engine/.venv/` and `engine/uv.lock`. Neither is ignored by git. The local PII test scans the working tree, so it fails on author emails inside the venv's Python files. CI passes because CI has no venv.

## Considered options

1. Skip `.venv` in the scanner and ignore it in git. Good, because both the scan and pushes stay clean.
2. Delete the venv by hand. Bad, because it recurs on the next `uv` run.

## Decision

We will add `.venv` to the scanner's skipped dirs. We will add `.venv/` and `engine/uv.lock` to `.gitignore`.

## Non-goals

Adding any third-party dependency. The engine stays stdlib-only.

## Cross-cutting concerns

- Security: a venv never holds engine code, and git now ignores it, so skipping it hides nothing publishable.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because the local test suite passes with a venv present.
- Neutral, because CI behavior is unchanged.

## Confirmation

`test_scan_skips_venv` in `engine/setup/tests/publish/test_no_engine_pii.py`, and `git check-ignore engine/.venv engine/uv.lock`.

## Deviations
