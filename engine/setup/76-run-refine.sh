#!/usr/bin/env bash
# Weekly cron: run the refine agent (lint frontmatter, audit cross-refs).
# Gated by maintain.refine toggle. Fails open — always exits 0.
# Mirrors 72-run-episodic-maintain.sh / 75-skill-maintain.sh.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-toggle-lib.sh"
source "$HERE/np-content-lib.sh" 2>/dev/null || true   # np_content_dir
source "$HERE/np-layer-lib.sh" 2>/dev/null || true     # np_merge_roots (skill roots: engine + overlay [+ team])
np_enabled maintain.refine || { echo "$(date -u +%FT%TZ) skipped: maintain.refine disabled"; exit 0; }

# Extra skill roots (content overlay [+ team]) beyond the engine's own skills/ —
# this is an agentic pass driven by a prose prompt (no Python enumeration to
# retarget), so retargeting means telling the agent about the other repo(s) to
# also lint/audit, each committed separately. Fail-open: no overlay -> no note,
# behavior unchanged from before this repo split existed.
EXTRA_ROOTS=()
if declare -f np_merge_roots >/dev/null 2>&1; then
  while IFS= read -r _r; do
    [[ -n "$_r" && "$_r" != "$NP" && -d "$_r/skills" ]] && EXTRA_ROOTS+=("$_r")
  done < <(np_merge_roots 2>/dev/null)
fi

# Invariant 2: bail if already running inside a nervepack agent context
# (prevents re-entrancy when called from a headless session).
[[ -z "${NERVEPACK_AGENT:-}" ]] || exit 0

LOG="${REFINE_LOG:-$HOME/.cache/nervepack/refine.log}"
mkdir -p "$(dirname "$LOG")"
bail() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; exit 0; }

CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROMPT_FILE="$NP/agents/np-flow-scheduled-refine.md"

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

if [[ ${#EXTRA_ROOTS[@]} -gt 0 ]]; then
  extra_note=$'\n\n### Additional skill roots (content overlay)\n\nBesides `skills/` in this working directory, also apply steps 2-3 to the `skills/` directory under EACH of these paths — content-overlay (and/or team) repos that hold the personal/knowledge skills relocated out of the engine:\n'
  for _r in "${EXTRA_ROOTS[@]}"; do
    extra_note+="- \`$_r/skills/\` — a SEPARATE git repo rooted at \`$_r\`. Stage and commit ONLY the paths you changed there via \`git -C \"$_r\" add <paths> && git -C \"$_r\" commit -m ... -- <paths>\`, then \`git -C \"$_r\" push\`. Never combine its commit with this repo's commit."$'\n'
  done
  prompt="$prompt$extra_note"
fi

{ echo; echo "=== $(date -u +%FT%TZ) refine run ==="; } >> "$LOG"
# cd into the repo so relative paths in the prompt resolve correctly.
cd "$NP"
# np-llm.sh routes to the configured backend and sets NERVEPACK_AGENT=1 on the call.
printf '%s' "$prompt" | "$HERE/np-llm.sh" agent --tools "Bash Read Write Edit Glob Grep" >> "$LOG" 2>&1 \
  || bail "ERROR: agent run exited non-zero"
