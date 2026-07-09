# nervepack regression tests

One command runs everything:

    bash engine/setup/tests/run-all.sh            # whole suite (excludes e2e)
    bash engine/setup/tests/run-all.sh episodic   # only matching tests (path substring)
    bash engine/setup/tests/run-all.sh --report report.md   # + functionality-grouped Markdown report
    bash engine/setup/tests/run-all.sh --with-e2e # include the Playwright dashboard e2e

Layout: each feature area has its own dir (`episodic/`, `evaluator/`, `mcp/`, …).
Bash tests are plain `bash` scripts that print `PASS test_x` and exit 0/1. Python
tests are stdlib `unittest` (no pytest). `_lib/` holds the hermetic-env + report
helpers; `meta/` tests the runner itself. `e2e/` is the ONLY suite with a
third-party dependency (Playwright) — install it first:

    pip install -r engine/setup/tests/e2e/requirements.txt
    python3 -m playwright install chromium

An optional `# np-test: <functionality> | <happy|failure>` header on a test labels
its row in the report (defaults to the area dir + `unspecified`).

CI (`.github/workflows/ci.yml`) runs `run-all.sh` (blocking `regression` job), the
e2e suite (`dashboard-e2e`, informational), and the secret/PII scanner (`pii-guard`,
terminal gate). The regression report renders in each run's job summary. Merges to
`main` are gated on `Syntax sweep` + `Regression suite` + `Secret/PII guard` +
`Windows suite (Git-bash)` + `Bash-free MCP suite`; `dashboard-e2e` is
informational and does not block.

## Portability — the suite also runs under Git-bash on Windows CI

`run-all.sh` runs on macOS, on Linux, AND under **Git-bash on `windows-latest`**
(the required `Windows suite (Git-bash)` check, plus the Git-bash-dir-free
`Bash-free MCP suite`). A test that passes on macOS/Linux can still fail on
Windows Git-bash / MSYS. The recurring gotchas (each has bitten a real PR):

- **`chmod -x` is a no-op under Git-bash.** Windows has no POSIX exec bit, so
  `[[ -x file ]]` stays *true* for a `chmod -x`'d file. To exercise a
  "not executable / unusable" branch portably, test a **missing** file
  (`[[ ! -x ]]` is reliably false for a missing path everywhere) — not a chmod'd one.
- **MSYS rewrites POSIX-path-like arguments to native binaries.** An argument
  like `/tmp/foo` passed to a *native* Windows binary (e.g. `jq.exe`) as `--arg`
  is auto-converted to `C:/Users/…/Temp/foo` (with 8.3 short names like
  `RUNNER~1`), corrupting emitted text and breaking full-path assertions. Disable
  it per-invocation with `MSYS_NO_PATHCONV=1 jq …`, and in tests assert on a
  stable path **suffix** (`.../foo`), not a full absolute path.
- **General rule:** any test or hook that touches the exec bit, hard-codes an
  absolute path, or passes a path-like value to a native binary must be
  MSYS-aware. Use `date +%s` (identical everywhere) and the `np_mtime` helper
  (`stat -c %Y || stat -f %m`) over GNU-only `date`/`stat` flags, and `grep -E`/`-F`
  over GNU `\|` alternation.
