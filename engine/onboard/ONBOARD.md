# Onboard nervepack to your host

**You are an agentic coding assistant onboarding nervepack onto this machine for
your own host (Claude Code, Goose, OpenHands, Cline, Continue, …).** nervepack is
tool-neutral; *you* create the host-specific wiring by satisfying the contract
below, then prove it with the doctor. There is no privileged path — Claude Code
onboards through these same docs.

> **Prerequisite:** your host must be *agentic* — able to read/write files and run
> shell commands. A plain chat UI (e.g. raw Ollama / Open WebUI) cannot self-wire;
> it can only consume the knowledge as context.

## The loop

1. **Identify your host** and how it does three things: surfaces standing context to
   the model, fires lifecycle events (session start/end), and runs a headless model
   call. Check `onboard/capabilities.json` `hints` for a recipe for your host.
2. **Satisfy each capability** in `onboard/capabilities.json` (the contract). Tiers:
   - **MUST** — `knowledge`, `llm-cli`, `git-sync`, `toggles`. Onboarding fails without these.
   - **SHOULD** — `session-start`, `session-end-capture`, `session-end-flush`,
     `scheduled-maint`. Wire what your host supports; mark the rest `unsupported`
     (and prefer the wrapper fallbacks the hints describe).
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
4. **Configure `np-llm.sh`** for your model: set `NP_LLM_BACKEND` (+ `NP_LLM_MODEL_CHEAP`
   / `NP_LLM_MODEL_AGENT`) so `printf 'hi' | setup/np-llm.sh complete` returns text.
   Claude Code is the default backend; for a local box use the goose/ollama backend.
5. **Run the doctor until green:** `setup/np-doctor.sh`. It reports each capability
   per tier (PASS / MISSING / UNSUPPORTED) and exits non-zero on any MUST failure.
   Fix and re-run. That generate → verify → fix loop is what makes self-wiring safe.

### Surfacing the directive without a session-start hook

If your host loads standing context from an instruction file (AGENTS.md / a Cursor rule)
but cannot fire a session-start hook, satisfy `knowledge` for the directive by appending a
managed block instead:

    setup/np-instruction-block.sh install <your instruction file>   # additive + idempotent
    setup/np-instruction-block.sh remove  <your instruction file>   # clean uninstall

It only ever touches its own `nervepack:begin`/`end` fence. Record the verify in your
adapter: `"verify": "grep -q nervepack:begin <file>"`. Do NOT use this on a host that
already injects the directive via a session-start hook (double-injection).

## Reference output

The Claude Code adapter is reproduced by `setup/30-link-skills.sh` (knowledge) and
`setup/5x-install-*.sh` (the hooks) — read them as a worked example of what your
adapter should achieve, then express the equivalent for your host. An example
manifest lives at `onboard/adapters/<host>.example.json`.

## Satisfying capabilities via MCP

- **Via MCP (any MCP-speaking host):** instead of wiring each script directly, point
  your MCP client at `engine/bin/nervepack-mcp` (stdio) — see **[`MCP.md`](MCP.md)** for
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
backend (it speaks the OpenAI-compatible `/chat/completions` protocol — works with Ollama,
Open WebUI, LM Studio, vLLM, llama.cpp):

```bash
export NP_LLM_BACKEND=local
export NP_LLM_BASE_URL=http://localhost:11434/v1   # full base incl. version path
export NP_LLM_API_KEY=...                            # optional (Open WebUI / hosted)
export NP_LLM_MODEL_CHEAP=qwen2.5                    # model for summaries/verdicts
# smoke test:
echo ping | setup/np-llm.sh complete
```

`complete` mode (capture + evaluator) works directly. `agent` mode (the weekly maintenance
crons) needs an agentic runner — set `NP_LLM_AGENT_CMD` to a command that takes the prompt
on stdin and the tools in `NP_LLM_TOOLS` (e.g. a Goose/aider invocation); otherwise those
crons report that an agentic host is required.

**Manual smoke (run against your real endpoint — sub-project #4b validates this):**

```bash
printf 'Reply with exactly: OK' | NP_LLM_BACKEND=local \
  NP_LLM_BASE_URL=<your-endpoint>/v1 NP_LLM_API_KEY=<key-if-any> \
  NP_LLM_MODEL_CHEAP=<model> setup/np-llm.sh complete
# expect the model's text on stdout, exit 0
```

## Don't

- Don't edit `onboard/capabilities.json` to make the doctor pass — fix the wiring.
- Don't skip `git-sync` auth — the maintenance steps push to origin.
- Don't drop the `NERVEPACK_AGENT` guard: any hook that triggers `np-llm.sh agent`
  (the maintenance/flush path) must bail when `NERVEPACK_AGENT` is set, or the
  model call's own session-end re-fires the hook forever. See
  `skills/np-kb-claude-headless-scripting` §7.
