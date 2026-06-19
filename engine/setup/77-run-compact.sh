#!/usr/bin/env bash
# Weekly cron: run the compact agent (dedup near-identical skills, propose splits).
# Gated by maintain.compact toggle. Fails open — always exits 0.
# Mirrors 72-run-episodic-maintain.sh / 75-skill-maintain.sh.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-toggle-lib.sh"
np_enabled maintain.compact || { echo "$(date -u +%FT%TZ) skipped: maintain.compact disabled"; exit 0; }

# Invariant 2: bail if already running inside a nervepack agent context
# (prevents re-entrancy when called from a headless session).
[[ -z "${NERVEPACK_AGENT:-}" ]] || exit 0

LOG="${COMPACT_LOG:-$HOME/.cache/nervepack/compact.log}"
mkdir -p "$(dirname "$LOG")"
bail() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; exit 0; }

CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROMPT_FILE="$NP/agents/np-flow-weekly-compact.md"

# Backend-aware pre-flight (ARCHITECTURE invariant 13): claude backend needs
# the claude binary; a local/OSS backend needs NP_LLM_AGENT_CMD.
BACKEND="${NP_LLM_BACKEND:-claude}"
if [[ "$BACKEND" == claude && ! -x "$CLAUDE" ]]; then
  bail "ERROR: claude CLI not found at $CLAUDE (backend=claude)"
fi
if [[ "$BACKEND" != claude && -z "${NP_LLM_AGENT_CMD:-}" ]]; then
  bail "ERROR: local backend agent mode needs NP_LLM_AGENT_CMD (backend=$BACKEND)"
fi
[[ -f "$PROMPT_FILE" ]] || bail "ERROR: prompt file missing at $PROMPT_FILE"

prompt="$(awk '/^## Prompt$/{p=1; next} p' "$PROMPT_FILE")"
[[ -n "$prompt" ]] || bail "ERROR: empty prompt extracted from $PROMPT_FILE"

{ echo; echo "=== $(date -u +%FT%TZ) compact run ==="; } >> "$LOG"
# cd into the repo so relative paths in the prompt resolve correctly.
cd "$NP"
# np-llm.sh routes to the configured backend and sets NERVEPACK_AGENT=1 on the call.
printf '%s' "$prompt" | "$HERE/np-llm.sh" agent --tools "Bash Read Write Edit Glob Grep" >> "$LOG" 2>&1 \
  || bail "ERROR: agent run exited non-zero"
