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
`main` are gated on `syntax` + `regression` + `pii-guard`; `dashboard-e2e` is
informational and does not block.
