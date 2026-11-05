# nervepack — roadmap

Deferred work and design decisions are tracked as **GitHub issues**:
<https://github.com/pat-browne/nervepack/issues>

Each open issue is a deliberately-deferred item — not a generic feature request, but a
decision put off on purpose, written down with the condition that should make us pick it
back up. Browse the **`roadmap`** label for the current backlog (engine internals,
dashboard, the knowledge layers, onboarding, and OSS hygiene).

If you're an AI session starting work in this repo: skim the open `roadmap` issues and
re-evaluate any whose trigger now applies before you begin.

## Deferred: prove non-KB changes are never auto-completed

The kb-promote-scan job enables auto-merge on its own PRs. Nothing yet proves it
cannot complete a PR that touches anything but KB docs.

**Work:** add a path allowlist guard and prove it.
- Allow only `docs/solutions`, `docs/systems`, `docs/runbooks`, and receipts.
- Allow add-only changes: no deletes, renames, symlinks, or path tricks.
- Read the PR's real file list from the API. Fail closed on any doubt.
- Add negative unit tests (stdlib `unittest`, no network).
- Run one live throwaway draft PR test.

**Trigger:** before the job writes outside `docs/`, or before the per-run cap of 3 rises.
