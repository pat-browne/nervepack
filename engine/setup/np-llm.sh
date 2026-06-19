#!/usr/bin/env bash
# nervepack LLM-CLI contract — the backend-neutral wrapper the runtime calls instead
# of hardcoding `claude -p`. This is the seam that lets nervepack run on a non-Claude
# agentic host (see docs/superpowers/specs/2026-06-05-agnostic-onboarding-design.md).
#
# Subcommands (prompt always arrives on STDIN):
#   complete [--system S]   prompt -> text on stdout. Cheap model, no tools. For
#                           summaries/verdicts (episodic-capture, np-evaluator).
#   agent --tools "T..."    prompt -> run an agentic task (file edits, commits). Agent
#                           model, the given tools, bypass permissions. For the
#                           maintenance crons (71/72/75).
#
# Config: NP_LLM_BACKEND (default claude) · NP_LLM_MODEL_CHEAP · NP_LLM_MODEL_AGENT.
# Sets NERVEPACK_AGENT=1 on the backend call — centralizes the SETTER of the
# SessionEnd recursion guard (the matching bail stays at each hook's top). See
# [[np-kb-claude-headless-scripting]] §7.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

BACKEND="${NP_LLM_BACKEND:-claude}"
MODEL_CHEAP="${NP_LLM_MODEL_CHEAP:-claude-haiku-4-5-20251001}"
MODEL_AGENT="${NP_LLM_MODEL_AGENT:-claude-sonnet-4-6}"
CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"

mode="${1:-}"; shift || true
sys=""; tools=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) sys="${2:-}"; shift 2 ;;
    --tools)  tools="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

prompt="$(cat)"

case "$BACKEND" in
  claude)
    case "$mode" in
      complete)
        args=(-p --bare --model "$MODEL_CHEAP" --allowedTools "")
        [[ -n "$sys" ]] && args+=(--append-system-prompt "$sys")
        printf '%s' "$prompt" | NERVEPACK_AGENT=1 "$CLAUDE" "${args[@]}"
        ;;
      agent)
        # shellcheck disable=SC2086 # word-split tools into the variadic --allowedTools
        # --bare: suppress hooks so third-party PostToolUse hooks (e.g. security-review)
        # cannot spawn long-running child processes that block the command substitution
        # in the caller and prevent write_status from ever running (see sdd/investigate-implement.md).
        printf '%s' "$prompt" | NERVEPACK_AGENT=1 "$CLAUDE" -p \
          --bare \
          --permission-mode bypassPermissions --model "$MODEL_AGENT" \
          --allowedTools $tools
        ;;
      *) echo "np-llm: unknown mode '$mode' (want: complete|agent)" >&2; exit 2 ;;
    esac
    ;;
  local)
    case "$mode" in
      complete)
        largs=(complete)
        [[ -n "$sys" ]] && largs+=(--system "$sys")
        printf '%s' "$prompt" | NERVEPACK_AGENT=1 python3 "$HERE/np-llm-local.py" "${largs[@]}"
        ;;
      agent)
        if [[ -n "${NP_LLM_AGENT_CMD:-}" ]]; then
          printf '%s' "$prompt" | NERVEPACK_AGENT=1 NP_LLM_TOOLS="$tools" bash -c "$NP_LLM_AGENT_CMD"
        else
          echo "np-llm: agent mode needs NP_LLM_AGENT_CMD (an agentic host, e.g. goose); see onboard" >&2
          exit 2
        fi
        ;;
      *) echo "np-llm: unknown mode '$mode' (want: complete|agent)" >&2; exit 2 ;;
    esac
    ;;
  *)
    echo "np-llm: backend '$BACKEND' not implemented (only 'claude' so far)" >&2; exit 2 ;;
esac
