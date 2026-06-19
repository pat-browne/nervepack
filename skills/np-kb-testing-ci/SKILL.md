---
name: np-kb-testing-ci
description: Testing-quality and CI gotchas for bash/Python + GitHub Actions projects (nervepack-style — stdlib tests, a discovery runner, a PII/secret gate). Use when writing or reviewing regression tests, wiring or debugging a CI workflow, a CI job that hangs or fails only in CI, deciding what a happy/failure test must assert, or before merging an agent-built branch. Complements [[np-kb-coding-rules]] §5 (every script has a test) and §6 (no LLM attribution).
---

# Testing & CI discipline

Hard-won rules for keeping a regression suite *honest* and a CI gate *trustworthy*.
Companion to [[np-kb-coding-rules]] (§5 every script has a test, §6 no AI attribution)
and ARCHITECTURE invariant 6 (stdlib `unittest`/bash tests in `engine/setup/tests/`).

## 1. No tautological happy-tests — assert a real side effect

A happy-path test that only checks "no error + non-empty output" can pass for a
**broken** implementation. The classic trap: a **fail-open** script run with a
**stubbed backend** (e.g. `CLAUDE_BIN=/bin/false`) bails and the caller returns a
fallback literal (`"captured"`), so `assertFalse(isError)` + `len(text)>0` passes no
matter what.

**Fix:** assert a concrete, observable effect. For capture → a `.jsonl` note actually
appears in the inbox dir. For a toggle-set → the conf column actually flipped. For a
commit step → the commit actually exists. If a happy path genuinely has no reachable
deterministic side effect (output goes only to a log), rename the test to say what it
*does* cover (e.g. `test_*_writes_gate_passthrough`) and drop the meaningless assertion
rather than implying more coverage than exists. Make the strengthened assertion fail
first (remove the side effect) to prove it bites.

## 2. Bound every stdio/subprocess read with a timeout

A test that spawns a server/subprocess and does a **blocking** `readline()` on its
stdout will **hang forever** if the process is alive but never answers (e.g. a handler
swallows an exception without responding). In CI that means the job wedges to the
global timeout instead of failing fast with a useful message — the opposite of what a
regression gate is for.

**Fix:** wrap each response read in a timeout. With Python stdlib, a daemon
`threading.Thread` around `readline()` + `join(timeout)` is the most robust (a bare
`select.select()` on the fd misreads a `BufferedReader` whose internal buffer is
pre-filled). Use a generous bound (≈15 s; bump for known-slow calls). Always
terminate/kill the subprocess in a `finally`/`tearDown` so a timed-out test leaves no
orphan. Verify both directions: it goes green on a healthy server **and** fails fast
(not hangs) on a deliberately-broken one.

## 3. CI: pin the interpreter for jobs with compiled/pinned deps

`actions/setup-python` with `python-version: "3.x"` resolves to the **newest** CPython
the runner has. A dependency that pins a compiled transitive package (e.g.
`playwright==1.48.0` → `greenlet==3.1.1`) may have **no wheel** for a brand-new CPython,
so pip tries to build it from source and the install step fails — with an error that
looks nothing like "wrong Python version."

**Fix:** pin heavyweight/dependency-laden jobs (browser/e2e, anything with C-extension
deps) to a stable interpreter (`python-version: "3.12"`). Keep **zero-dependency**,
stdlib-only jobs on `"3.x"` so they catch real forward-compat breakage. Quarantine the
one dependency-bearing suite to its own job so the rest of CI stays install-free.

## 4. Scrub agent-introduced commit trailers before merge

When subagents/fixers make commits, the host harness's default may inject a
`Co-Authored-By: Claude …` trailer — which [[np-kb-coding-rules]] §6 forbids. It slips
in per-commit and is easy to miss in a long agent-built branch.

**Fix:** before opening/merging the PR, scan the whole branch range and strip it:
```bash
git log <base>..HEAD --format='%B' | grep -ciE 'Co-Authored-By: Claude'   # detect
git filter-branch -f --msg-filter 'sed "/^Co-[Aa]uthored-[Bb]y: Claude/d"' -- <base>..HEAD
```
(Safe to rewrite while the branch is unpushed; force-push if already pushed.) Then
re-verify `0` matches. Same idea for any "Generated with Claude" footer.

## 5. CI gate shape (for a publishable repo)

- A single discovery **runner** is the local *and* CI entrypoint (one command,
  hermetic, zero-dep) so "run the tests" has one answer and CI runs exactly what
  developers run.
- Make the **secret/PII scan the terminal gate** (`needs:` the test jobs) so nothing
  merges unless it's clean *after* tests pass.
- Keep flaky/heavyweight suites (browser e2e) **informational** (`continue-on-error:
  true`) and **out of the required status checks**, so a browser hiccup never blocks a
  merge — but still runs and reports.
- Emit a per-run report to `$GITHUB_STEP_SUMMARY` so pass/fail is visible on the run
  page without digging through logs.

## 6. A test must never mutate live/committed data — isolate output or snapshot/restore

A hermetic harness that only isolates `HOME`/`XDG` is **not enough** when a test runs a
real entrypoint (cron/build) that writes a **fixed, non-isolated output path**. nervepack
bug: `dashboard/build.py`'s `DEFAULT_OUT` (`dashboard/data/metrics.js`) is a **symlink into
the live content overlay**, and the hermetic `HOME` makes the content dir resolve to the
engine root (empty `wiki/`/`playbooks/`/`strategies/`). So any test running
`73-aggregate`/`open-dashboard` with no explicit out arg silently overwrote the user's
**live committed** dashboard data with empty `window.WIKI`/`LEARNED` — on every suite run.
The suite passed; it surfaced later as "the dashboard went blank."

**Fix — defense in depth:**
- Isolate per test where the path is parameterizable (`NP_CONTENT_DIR=$tmp` so
  content-dir-relative writes land in temp).
- A **fixed** default-out can't be isolated that way — so the **runner** snapshots the live
  data files before the suite and restores them in its `EXIT` trap (a test may write them;
  the suite must never leave them mutated).
- Grep smell: a test invoking a real `setup/NN-*.sh` / `build.py` with **no explicit output
  path** — doubly dangerous when the repo's data dir is a symlink.
