---
name: np-core-onboard
description: Install/onboard nervepack onto this machine for whatever agentic host you are (Claude Code, Goose, OpenHands, Cline, Continue, …) by reading the tool-neutral onboard contract, wiring the host yourself, and verifying with the doctor. Use when setting up nervepack on a new machine/host, when the user says "/np-onboard" or "onboard nervepack" / "set up nervepack here", or when np-doctor reports MUST failures.
---

# Onboard nervepack to this host

nervepack is tool-neutral: **you** create the host-specific wiring by satisfying a
contract, then prove it with a deterministic doctor. No host is privileged — Claude
Code onboards the same way. Full instructions live in `~/Code/nervepack/engine/onboard/ONBOARD.md`;
this skill is the entry point.

## The loop (run it, don't ask the user to)

1. **Read the contract:** `engine/onboard/ONBOARD.md` + `engine/onboard/capabilities.json`. Identify
   your host and how it (a) surfaces standing context to the model, (b) fires session
   start/end events, (c) runs a headless model call. Each capability has per-host `hints`.
2. **Check current state first:** `bash ~/Code/nervepack/engine/setup/np-doctor.sh`. It shows
   what's already wired vs MISSING — only do work the doctor flags.
3. **Satisfy each capability** for your host (MUST: `knowledge`, `llm-cli`, `git-sync`,
   `toggles`; SHOULD: the session-start/end + scheduled-maint ones — wire what your host
   supports, mark the rest `unsupported`). For Claude Code the worked example is
   `engine/setup/30-link-skills.sh` (knowledge) + `engine/setup/5x-install-*.sh` (hooks); reproduce the
   equivalent for your host.
4. **Configure the model:** set `NP_LLM_BACKEND` (+ `NP_LLM_MODEL_CHEAP`/`_AGENT`) so
   `printf hi | engine/setup/np-llm.sh complete` returns text. Claude is the default backend; a
   local Ollama box uses the goose/ollama backend.
5. **Record what you did** in `~/.config/nervepack/adapter.json` (per-machine): for each
   `check:adapter` capability, `{status: wired|unsupported, verify: "<cmd, exit 0 = ok>"}`.
   Start from `engine/onboard/adapters/<host>.example.json` if one exists.
6. **Run the doctor until green:** `engine/setup/np-doctor.sh` (exits non-zero on a MUST
   shortfall). Fix → re-run. That generate→verify→fix loop is what makes self-wiring safe.
7. **Report** the doctor's per-capability table to the user and offer toggle choices
   (`np-core-toggle`).

## Hard rules

- Never edit `capabilities.json` to make the doctor pass — fix the wiring.
- Any hook that triggers `np-llm.sh agent` (the maintenance/flush path) MUST bail when
  `NERVEPACK_AGENT` is set, or the model call's own session-end re-fires the hook forever
  → see [[np-kb-claude-headless-scripting]] §7.
- A non-agentic host (plain chat) can't self-wire; it can only consume `skills/` as context.
- The `scheduled-auth-token` capability has a genuinely manual step — point the user
  at `engine/setup/62-install-scheduled-auth-token.sh`; you cannot run `claude
  setup-token`'s browser approval on their behalf.

See [[np-core-toggle]] to tune features after onboarding, [[np-core-sync]] to keep the
repo current.
