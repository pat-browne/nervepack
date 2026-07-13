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

# Long-lived nervepack processes (the dashboard server, backgrounded SessionStart
# hooks) are themselves spawned from inside an interactive Claude Code session and
# inherit its CLAUDECODE/CLAUDE_CODE_* env vars for their whole lifetime — including
# a CLAUDE_CODE_SESSION_ID for a session that has since ended. A nested `claude -p`
# call that inherits those vars can be mistaken for a child of that (possibly stale)
# session rather than an independent headless run, which surfaced as a spurious
# "Not logged in · Please run /login" from `np-implement-suggestion.sh` when the
# dashboard's long-running server process outlived the session that started it
# (found 2026-07-13). Strip them so every nervepack `claude` invocation authenticates
# as its own top-level headless call, never as an implicit child session.
STRIP_ENV=(-u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SESSION_ID \
           -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_EXECPATH -u CLAUDE_CODE_SSE_PORT)

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
        args=(-p --model "$MODEL_CHEAP" --allowedTools "")
        [[ -n "$sys" ]] && args+=(--append-system-prompt "$sys")
        printf '%s' "$prompt" | NERVEPACK_AGENT=1 env "${STRIP_ENV[@]}" "$CLAUDE" "${args[@]}"
        ;;
      agent)
        # shellcheck disable=SC2086 # word-split tools into the variadic --allowedTools
        # --bare: suppress hooks so third-party PostToolUse hooks (e.g. security-review)
        # cannot spawn long-running child processes that block the command substitution
        # in the caller and prevent write_status from ever running (see sdd/investigate-implement.md).
        printf '%s' "$prompt" | NERVEPACK_AGENT=1 env "${STRIP_ENV[@]}" "$CLAUDE" -p \
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
