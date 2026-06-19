#!/usr/bin/env bash
# Cron wrapper around `claude -p` for the weekly memory→nervepack promotion.
# Reads the prompt from agents/np-flow-memory-promote.md and appends output to
# ~/.cache/nervepack/memory-promote.log.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_npl="$HERE/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled memory.promote || { echo "$(date -u +%FT%TZ) skipped: memory.promote disabled via toggle"; exit 0; }; }
source "$HERE/np-content-lib.sh"   # personal skills + memory layers live in the content overlay (cwd below)

LOG="$HOME/.cache/nervepack/memory-promote.log"
mkdir -p "$(dirname "$LOG")"

# Issue #12: this agent cd's into the content dir and commits personal-memory promotions
# there. If the content dir resolved via the IMPLICIT engine-root fallback (NP_CONTENT_DIR
# unset AND no ~/.config/nervepack/content-dir), those commits would land in the PII-clean
# engine repo. Skip the run (fail-open, log, exit 0). A deliberate single-repo user opts
# in via the config file (origin 'config') and runs as before.
if ! np_content_is_explicit; then
  echo "$(date -u +%FT%TZ) skipped: content dir is the implicit engine-root fallback — set NP_CONTENT_DIR or ~/.config/nervepack/content-dir to enable memory promotion" >> "$LOG"
  exit 0
fi

NERVEPACK="$HOME/Code/nervepack"
CLAUDE="$HOME/.local/bin/claude"
PROMPT_FILE="$NERVEPACK/agents/np-flow-memory-promote.md"

# Only the claude backend needs the binary; a local agentic backend is served via
# NP_LLM_AGENT_CMD (np-llm.sh agent mode routes there) — don't hard-require claude on
# a non-Claude host. See the #4b validation report + [[np-kb-local-llm]].
BACKEND="${NP_LLM_BACKEND:-claude}"
if [[ "$BACKEND" == claude && ! -x "$CLAUDE" ]]; then
  echo "$(date -u +%FT%TZ) ERROR: claude CLI not found at $CLAUDE" >> "$LOG"
  exit 1
elif [[ "$BACKEND" != claude && -z "${NP_LLM_AGENT_CMD:-}" ]]; then
  echo "$(date -u +%FT%TZ) ERROR: local backend agent mode needs NP_LLM_AGENT_CMD" >> "$LOG"
  exit 1
fi

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "$(date -u +%FT%TZ) ERROR: prompt file missing at $PROMPT_FILE" >> "$LOG"
  exit 1
fi

# Extract just the "## Prompt" section onward — the leading metadata is for
# humans, not the model.
prompt="$(awk '/^## Prompt$/{p=1; next} p' "$PROMPT_FILE")"

if [[ -z "$prompt" ]]; then
  echo "$(date -u +%FT%TZ) ERROR: empty prompt extracted from $PROMPT_FILE" >> "$LOG"
  exit 1
fi

{
  echo
  echo "=== $(date -u +%FT%TZ) memory-promote run ==="
} >> "$LOG"

cd "$(np_content_dir)"   # commit personal-skill/memory promotions in the content repo; the agent commits a GENERAL engine skill in $NERVEPACK itself
# np-llm.sh routes to the configured agentic backend and sets NERVEPACK_AGENT=1 on
# the call (the SessionEnd recursion guard's setter); prompt via stdin.
printf '%s' "$prompt" | "$HERE/np-llm.sh" agent --tools "Bash Read Write Edit Glob Grep" >> "$LOG" 2>&1
