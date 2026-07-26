# The bash → Python CLI cutover

**Status: COMPLETE (phases 1–20, 2026-07).** The nervepack harness that was once a
mix of bash scripts + Python helpers is now **Python end-to-end**, dispatched through
a single entrypoint, `engine/nervepack_engine/cli.py`. This document is the guide to
what changed and the checklist to verify the cutover holds.

Authoritative design specs (content overlay `docs/superpowers/specs/`):
`2026-07-15-nervepack-python-cli-consolidation-design.md` (phases 1–11) and
`2026-07-23-nervepack-python-cli-full-cutover-roadmap-design.md` (phases 12–20).

## Why

The old rule was "bash for latency-critical glue, Python for parsing/logic off the hot
path." It cost correctness (bash footguns — `pipefail` no-match, `grep -c` printing `0`
and exiting non-zero, word-splitting, SIGPIPE — bit the toggle CLI, the cron guards,
and the signal extractor) and cognition (every script's language was a per-file fact).
The user accepted a ~20–70ms/call latency cost for **one language everywhere**,
banking the performance for a future compiled-language phase (Phase B, `ROADMAP.md`).

## What changed (the shape)

- **One dispatcher.** `engine/nervepack_engine/cli.py` routes every hook, cron, setup
  step, and top-level command: `cli.py hook <name>`, `cli.py cron <name>`,
  `cli.py setup <step>`, `cli.py toggle|doctor|sync|open-dashboard|…`.
- **Hooks** are Python (`engine/nervepack_engine/hooks/*.py`), registered by one
  declarative manifest — `engine/setup/hooks.manifest` driven by
  `cli.py setup install-hooks` (`np_hook.py`, the stdlib-json port of the retired
  `np_register_hook`). The 11 `NN-install-*.sh` installers + `np-hook-lib.sh` are gone.
- **Resolvers** (`np_toggle.py`, `np_content.py`) are the sole toggle/content/layer
  resolvers; the three sourced libs (`np-toggle-lib.sh`, `np-content-lib.sh`,
  `np-layer-lib.sh`) are deleted.
- **Seams** are Python and in-process for the MCP server: `np_doctor.py` (the full
  15-capability doctor), `np_sync.py` (full defensive sync incl. team-ff + hook
  reinstall), `np_dashboard.py`, `np_model.py` (the sole model seam —
  `complete()`/`agent()`), `np_toggle.py` write side. The MCP server has **no bash
  hybrids left**.

### Retired scripts (deleted)

`np-hook-lib.sh` + the 11 `50–63 NN-install-*hook*.sh` installers · `np-toggle-lib.sh` ·
`np-content-lib.sh` · `np-layer-lib.sh` · `np-doctor.sh` · `40-sync-nervepack.sh` ·
`30-link-skills.sh` · `60-generate-index.sh` · `np-mcp-install.sh` · `open-dashboard.sh` ·
`np-dashboard-launch.sh` · `episodic-scrub.sh` · `np-llm.sh` · (earlier phases:
`np-evaluator.sh`, `episodic-capture.sh`, the `71–77` cron bodies, `35-link-dashboard-data.sh`,
`np-merge-wait.sh`, `np-suggestion-resolve.sh`, `np-instruction-block.sh`,
`np-architecture-freshness.sh`).

## What bash legitimately remains (deliberate, enumerated)

The cutover is not "zero bash" — it is "no bash *harness logic*." These stay by design:

1. **`np_bashlib.argv()`-wrapped shell-outs to git / native tools** — running git, the
   OS scheduler, or another CLI is legitimately a subprocess. `np_bashlib.argv()` makes
   the invocation Windows-safe (a bare `bash` resolves to System32 WSL). Callers:
   `np_sync.py`, `np_mcp_install.py`, `np-mcp-server.py`, `np-dashboard-server.py`,
   `dashboard/build.py`, `np_onboard.py`.
2. **The two model-seam paths that run a USER-CONFIGURED command** — `np_model.agent()`'s
   `local` backend runs `bash -c "$NP_LLM_AGENT_CMD"` (your agentic host, e.g. goose)
   and `np_implement_suggestion._default_agent_fn` runs `bash <$IMPLEMENT_LLM> agent`
   (an override script). Neither is a nervepack script; neither can be "ported" (they
   execute a command the user supplies). Both are `np_bashlib.argv()`-wrapped; unset →
   in-process `np_model.agent()`.
3. **OS-scheduler interop** (`np_scheduler_install.py`) shells cron / `launchctl` /
   `schtasks.exe` — the portable-shell-to-native-tool pattern (ARCHITECTURE invariant
   16); a native `.ps1` was rejected because it can't be CI-tested on the zero-dep
   Ubuntu runners.
4. **A few small bash installers/entrypoints that aren't harness logic:**
   `58-install-mcp.sh` (one `claude mcp add`), `62-install-scheduled-auth-token.sh` (an
   interactive `claude setup-token` walkthrough that needs a real terminal),
   `np-token-lib.sh` (sourced by 62), `episodic-match.sh` (has a Python peer
   `np_episodic_match.py` used in-process; the `.sh` remains a thin CLI), plus the test/CI
   entrypoints (`engine/setup/tests/run-all.sh`) and the served-mode HTTP server.
5. **The `np_hook.py` Windows hook shim** — wraps a stored hook command as
   `bash -lc '<cmd>'` on a MINGW/MSYS kernel so PowerShell-dispatched hooks resolve to
   Git-bash (ARCHITECTURE invariant 16). Linux/macOS byte-for-byte unchanged.

## Verification — how to confirm the cutover holds

Run these from the engine repo root. All should hold on a clean `main`.

**1. The retired scripts are gone.**
```bash
for f in np-hook-lib np-toggle-lib np-content-lib np-layer-lib np-doctor \
         40-sync-nervepack 30-link-skills 60-generate-index np-mcp-install \
         open-dashboard np-dashboard-launch episodic-scrub np-llm; do
  ls engine/setup/$f.sh 2>/dev/null && echo "STILL PRESENT: $f.sh"
done
# expect: no output
```

**2. No production Python sources or shells a retired lib/script.**
```bash
grep -rn "np-toggle-lib\|np-content-lib\|np-layer-lib\|np-hook-lib\|np-llm\.sh\|np-doctor\.sh\|40-sync-nervepack\.sh" \
  engine/ --include="*.py" --include="*.sh" | grep -v /tests/ \
  | grep -vE "#|\"\"\"|retired|formerly|past|docstring"
# expect: no live references (only past-tense docstrings, filtered out)
```

**3. Every `bash -c` / `["bash", …]` in production Python is one of the enumerated
exceptions.** Audit each hit against §"What bash legitimately remains":
```bash
grep -rn '"bash"\|bash -c' engine/ --include="*.py" | grep -v /tests/
# expect only: np_model.py (NP_LLM_AGENT_CMD), np_implement_suggestion.py (IMPLEMENT_LLM),
# np_bashlib.py (the argv wrapper itself), np_sync/np_mcp_install/np_onboard/
# np_scheduler_install (argv-wrapped native-tool shell-outs)
```

**4. The MCP server has no bash hybrids** — every tool runs in-process:
```bash
python3 engine/setup/tests/mcp/test_bashfree.py   # proves the ported surface works with bash unreachable
```

**5. The full suite is green** (one known-local false positive only — the git-ignored
`dashboard/data/metrics.js` contains a local `$HOME` path that the PII guard flags;
it is never committed, so CI is clean):
```bash
bash engine/setup/tests/run-all.sh            # Linux
# The Windows/Git-bash lane is a required CI gate — native-Windows-Python portability.
```

**6. The dispatcher covers everything.** `cli.py` routes `hook`/`cron`/`setup`/`toggle`/
`doctor`/`sync`/`open-dashboard`/`implement-suggestion`/`merge-wait`/`suggestion-resolve`/
`instruction-block`/`resume-write`. The `hooks.manifest`↔`cli.py _HOOKS` bidirectional
coverage is enforced by `engine/setup/tests/setup/test_installer_glob_coverage.sh`.

## Not done here / follow-ups

- **Phase B** (compiled-language rewrite to reclaim the latency) — future, tracked in
  `ROADMAP.md`, not designed yet.
- The 12 genuinely-complete library modules (`np_toggle`, `np_content`,
  `np_episodic_match`, `np_doctor`, `np_sync`, `np_model`, `np_scrub`, `np_capture`,
  `np_evaluator`, `np_dashboard`, `np_hook`, `np_token_lib`/`np_token_status`) were
  **relocated from `engine/setup/` into the package `engine/nervepack_engine/` in phase
  20b** (config resolution was decoupled from location first, via the `np_paths` anchor
  that stays in `engine/setup/`). Each relocated module self-bootstraps `engine/setup/`
  onto `sys.path` so it still resolves `np_paths`/`np_bashlib`/config and its stayed
  siblings. The remaining `np_*.py` still in `engine/setup/` (helpers, installers,
  resolvers that keep bash siblings) stay put. **Follow-up:** the modules still use flat
  imports (`import np_toggle`) plus `sys.path` bootstraps rather than absolute-package
  imports (`from nervepack_engine import np_toggle`); a full package-import conversion is
  a future refinement — see `docs/ROADMAP.md`.
