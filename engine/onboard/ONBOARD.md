# Onboard nervepack to your host

**You are an agentic coding assistant onboarding nervepack onto this machine for
your own host (Claude Code, Goose, OpenHands, Cline, Continue, …).** nervepack is
tool-neutral; *you* create the host-specific wiring by satisfying the contract
below, then prove it with the doctor. There is no privileged path. Claude Code
onboards through these same docs.

> **Prerequisite:** your host must be *agentic* (able to read/write files and run
> shell commands). A plain chat UI (e.g. raw Ollama / Open WebUI) cannot self-wire;
> it can only consume the knowledge as context.

## The loop

1. **Identify your host** and how it does three things: surfaces standing context to
   the model, fires lifecycle events (session start/end), and runs a headless model
   call. Check `engine/onboard/capabilities.json` `hints` for a recipe for your host.
2. **Satisfy each capability** in `engine/onboard/capabilities.json` (the contract). Tiers:
   - **MUST**: `knowledge`, `llm-cli`, `git-sync`, `toggles`, `content`. Onboarding fails without these.
   - **SHOULD**: `session-start`, `session-end-capture`, `session-end-flush`,
     `scheduled-maint`, `scheduled-auth-token`. Wire what your host supports; mark
     the rest `unsupported` (and prefer the wrapper fallbacks the hints describe).
     `scheduled-auth-token` is the one capability with a genuinely manual step —
     `engine/setup/62-install-scheduled-auth-token.sh` needs a human at a real
     terminal to run `claude setup-token` and approve in a browser; you cannot
     complete it on the user's behalf, just point them at the script.
3. **Record what you did** in an adapter manifest so the doctor can verify it:
   `~/.config/nervepack/adapter.json` (per-machine). Shape:
   ```json
   {
     "host": "<your-host>",
     "capabilities": {
       "knowledge":            { "status": "wired",       "verify": "<shell cmd, exit 0 = ok>" },
       "session-end-capture":  { "status": "wired",       "verify": "<shell cmd>" },
       "scheduled-maint":      { "status": "unsupported", "verify": "" }
     }
   }
   ```
   Only `check:adapter` capabilities need an entry here (the doctor checks
   `check:core` ones itself). `status` ∈ `wired | unsupported`. `verify` is a
   deterministic command that exits 0 when the capability is genuinely in place
   (e.g. Claude: `test -L ~/.claude/skills/np-core-sync`; `grep -q episodic-capture ~/.claude/settings.json`).
4. **Configure the model seam** (`np_model.py`) for your model: set `NP_LLM_BACKEND` (+ `NP_LLM_MODEL_CHEAP`
   / `NP_LLM_MODEL_AGENT`) so `printf 'hi' | python3 engine/nervepack_engine/np_model.py complete` returns text.
   Claude Code is the default backend; for a local box use the goose/ollama backend.
5. **Run the doctor until green:** `python3 engine/nervepack_engine/cli.py doctor`. It reports each capability
   per tier (PASS / MISSING / UNSUPPORTED) and exits non-zero on any MUST failure.
   Fix and re-run. That generate → verify → fix loop is what makes self-wiring safe.

### Surfacing the directive without a session-start hook

If your host loads standing context from an instruction file (AGENTS.md / a Cursor rule)
but cannot fire a session-start hook, satisfy `knowledge` for the directive by appending a
managed block instead:

    python3 engine/nervepack_engine/cli.py instruction-block install <your instruction file>   # additive + idempotent
    python3 engine/nervepack_engine/cli.py instruction-block remove  <your instruction file>   # clean uninstall

It only ever touches its own `nervepack:begin`/`end` fence. Record the verify in your
adapter: `"verify": "grep -q nervepack:begin <file>"`. Do NOT use this on a host that
already injects the directive via a session-start hook (double-injection).

### One-shot onboard (Claude Code and hosts that reproduce its wiring)

If your host wires the same way Claude Code does (skill symlinks + lifecycle hooks
in a settings file + OS-scheduler crons), the whole sequence is one command:

    python3 engine/nervepack_engine/cli.py onboard

It runs, in order: `setup link-skills` (knowledge) → `setup link-dashboard-data`
→ `setup install-hooks` (all lifecycle hooks, from `engine/setup/hooks.manifest`)
→ `58-install-mcp.sh` (MCP registration) → `62-install-scheduled-auth-token.sh` (the
manual token step; skipped non-interactively) → `setup install-memory-{cron,launchd,schtasks}`
(per-OS scheduler) → the doctor (its exit code is the onboard's). Idempotent — safe
to re-run. **Re-running it also repairs stale wiring** — e.g. a machine whose hooks were
registered before a command changed (a renamed script, a path move) gets the current
`hooks.manifest` re-applied, replacing the stale entries — **but only when the old and
new commands share the same dedup key** (`register()`'s "base": a script basename, or
a full `cli.py <group> <name>` tail). A hook whose *dispatch mechanism itself* changes
(a `.sh` script retired for a `cli.py` subcommand, say) gets a **different** base, so
`install-hooks` adds the new entry alongside the old one instead of replacing it — the
dead script now runs (and silently no-ops) on every session start/end, forever, until
someone notices. **Any commit that changes what command a manifest row runs must ship
a matching row in `np_hook.py`'s `_LEGACY_PURGES`** so already-onboarded hosts get the
old entry purged on their next sync/onboard, not just new hosts wired for the first
time. The doctor's `hook-scripts` SHOULD check is the tripwire for a missed one — see
"Known upgrade gotchas" below (found live during the #149→0bedc5e upgrade, 2026-07-27).
A quick way to prove an install works end-to-end is to remove the wiring and re-run
`cli.py onboard`, then confirm the doctor is green.

## Known upgrade gotchas (from a real re-onboard)

Surfaced doing a 31-commit catch-up sync on an already-onboarded machine
(2026-07-27); worth checking every time a sync jumps more than a few commits.

- **A hook-command *rename that changes mechanism* leaves a live duplicate.**
  See the caveat above — `install-hooks` re-running on a fast-forward is not
  by itself a guarantee the old entry is gone. After any sync that lands
  behind you, run the doctor's SHOULD tier too, not just MUST — `hook-scripts`
  reports exactly this ("N missing script(s)" naming the dead path still
  wired). Fix: add the retired command's substring to `_LEGACY_PURGES` for the
  right event(s), or call `np_hook.purge(event, [substring])` directly for a
  one-off local repair.
- **`git diff-index --quiet HEAD --` can misreport "dirty" right after a
  checkout/reset in the same process** (a stale stat-cache read, not a real
  content difference) — `np_sync.py`'s `_is_dirty()` now runs
  `git update-index -q --refresh` first specifically to close this gap, but
  if you're driving git yourself in a custom host adapter and see a sync
  falsely SKIPPED/DIVERGED against a tree `git status --short` shows clean,
  refresh the index (or just re-run) before assuming real divergence.
- **The engine sync compares against `origin/main` specifically.** If your
  local checkout is sitting on a feature branch (including one with real
  unpushed commits — a prior session's WIP), the sync reports DIVERGED
  relative to `main`, not "up to date," even though the feature branch itself
  is fine. `git checkout main` is non-destructive (the feature branch and its
  commits stay exactly where they are — nothing is discarded), so it's safe
  to switch, sync main, and leave the WIP branch for later. Never `reset`,
  `rebase`, or discard a branch with unpushed commits to force a clean sync.
- **A team-layer capability reporting PASS doesn't mean it pulled anything
  this run.** A configured `team` dir with local uncommitted edits is skipped
  ("has local edits — skipping pull", to stderr, non-fatal) rather than
  fast-forwarded — by design, since the team pull is strict-safe (never
  autostash/rebase, same as the engine sync itself). If you expected fresh
  team content and didn't get it, check for exactly that stderr line before
  assuming the sync is broken.

## Reference output

The Claude Code adapter is reproduced by `cli.py setup link-skills`
(engine/setup/np_link_skills.py — knowledge) and `cli.py setup install-hooks`
(engine/nervepack_engine/np_hook.py, applying `engine/setup/hooks.manifest` — the
lifecycle hooks). Read them as a worked example of what your adapter should achieve, then
express the equivalent for your host. An example manifest lives at
`engine/onboard/adapters/<host>.example.json`.

### Optional: the full (Presidio) PII filter — `pii_filter_full`

The doctor's `pii_filter_full` check (SHOULD) is the one nervepack feature that wants a
third-party dependency (`presidio-analyzer` + a spaCy model) for NER-based PII detection.
It is **opt-in** (the `pii_filter` toggle is default-off) and the always-on regex scrub
covers the common secret shapes without it — so this check WARNs/FAILs harmlessly if you
skip it. To set it up: `python3 engine/nervepack_engine/cli.py setup install-pii-deps`.

**Modern Debian/Ubuntu gotcha (PEP 668):** on an externally-managed Python (Ubuntu 24.04+),
`pip install` to the system/user site is blocked, so `install-pii-deps` fails and even
`--user` won't help. The doctor checks `import presidio_analyzer` in the *system* `python3`
(nervepack runs there — hooks/crons/cli), so a plain venv doesn't satisfy it either. The
working path is an explicit override into system Python:

```bash
python3 -m pip install --break-system-packages presidio-analyzer presidio-anonymizer
# presidio's default AnalyzerEngine() loads spaCy's en_core_web_lg — install the model wheel too:
python3 -m pip install --break-system-packages \
  "https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"
```

`--break-system-packages` writes into system Python (apt-conflict risk) — acceptable on a
personal dev box (verify after with `python3 -m pip check` + `python3 -c "import apt_pkg"`),
but weigh it against the feature being optional. It pulls a large dep tree (spaCy, numpy)
plus a ~400 MB model.

## Satisfying capabilities via MCP

- **Via MCP (any MCP-speaking host):** instead of wiring each script directly, point
  your MCP client at `engine/bin/nervepack-mcp` (stdio). See **[`MCP.md`](MCP.md)** for
  the `mcpServers` config block, the full tool/resource list, and the write-gating story.
  It exposes every capability as MCP tools/resources/prompts (the programmatic form of
  this contract). Push-on-lifecycle behaviors still need a thin host shim that calls the
  `nervepack_*` tools on your host's session-start/-end events.

### Commit identity for auto-commit jobs (headless/cloud)

The episodic/metrics/skill maintenance jobs commit to the content repo using the runner's
configured git identity. On a normal machine that's your `git config user.{name,email}`.
In a headless/cloud sandbox with no git identity, set `NP_GIT_AUTHOR_NAME` and
`NP_GIT_AUTHOR_EMAIL` so commits are attributed to you; otherwise they fall back to a
neutral `nervepack agent <nervepack-agent@localhost>`.

### Local / self-hosted model backend (OpenAI-compatible)

To run nervepack on a local or self-hosted model instead of Claude, set the `local`
backend (it speaks the OpenAI-compatible `/chat/completions` protocol, works with Ollama,
Open WebUI, LM Studio, vLLM, llama.cpp):

```bash
export NP_LLM_BACKEND=local
export NP_LLM_BASE_URL=http://localhost:11434/v1   # full base incl. version path
export NP_LLM_API_KEY=...                            # optional (Open WebUI / hosted)
export NP_LLM_MODEL_CHEAP=qwen2.5                    # model for summaries/verdicts
# smoke test:
echo ping | python3 engine/nervepack_engine/np_model.py complete
```

`complete` mode (capture + evaluator) works directly. `agent` mode (the weekly maintenance
crons) needs an agentic runner. Set `NP_LLM_AGENT_CMD` to a command that takes the prompt
on stdin and the tools in `NP_LLM_TOOLS` (e.g. a Goose/aider invocation); otherwise those
crons report that an agentic host is required.

**Manual smoke (run against your real endpoint; sub-project #4b validates this):**

```bash
printf 'Reply with exactly: OK' | NP_LLM_BACKEND=local \
  NP_LLM_BASE_URL=<your-endpoint>/v1 NP_LLM_API_KEY=<key-if-any> \
  NP_LLM_MODEL_CHEAP=<model> python3 engine/nervepack_engine/np_model.py complete
# expect the model's text on stdout, exit 0
```

## Don't

- Don't edit `engine/onboard/capabilities.json` to make the doctor pass. Fix the wiring.
- Don't skip `git-sync` auth. The maintenance steps push to origin.
- Don't drop the `NERVEPACK_AGENT` guard: any hook that triggers `np_model.py agent`
  (the maintenance/flush path) must bail when `NERVEPACK_AGENT` is set, or the
  model call's own session-end re-fires the hook forever. See
  `skills/np-kb-claude-headless-scripting` §7.
