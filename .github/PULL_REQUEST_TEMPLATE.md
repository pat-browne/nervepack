<!--
Thanks for contributing to nervepack. Keep PRs surgical: the minimum that solves
the problem, no drive-by refactors. See CONTRIBUTING.md.
-->

## What and why

<!-- What does this change, and what problem does it solve? Link any issue: "Closes #123". -->

## How

<!-- Brief notes on the approach, anything a reviewer should know to read the diff. -->

## Checklist

- [ ] Change is **surgical** — no unrelated refactors or reformatting.
- [ ] Ran the checks locally: `python3 -m py_compile` on touched `*.py`, `bash -n`
      on touched `*.sh`, and `bash engine/setup/tests/run-all.sh`.
- [ ] Added or updated a test for any bug fix or new behavior.
- [ ] If this adds a hook, cron, or managed config: it has a `toggles.conf` row
      and gates itself with `np_enabled <feature> || exit 0` (fail-open).
- [ ] If a model is invoked: it pins a specific model and uses the cheapest one
      that does the job (see AGENTS.md › Model selection policy).
- [ ] Docs updated where relevant (`docs/ARCHITECTURE.md`, `docs/FEATURES.md`,
      `README.md`).
- [ ] **No personal data** — no names, emails, home paths, private hostnames/IPs,
      or credentials. (The `pii-guard` job enforces this.)
- [ ] **No AI/LLM attribution** in commits or this description.
