#!/usr/bin/env bash
# Regression test for the `claude -p` invocation in 72-run-episodic-maintain.sh.
#
# Same bug class as test_capture_invocation.sh: the prompt was passed as a
# trailing positional after the variadic `--allowedTools`, so the CLI aborted
# with "Input must be provided ... when using --print" on every cron run. Here
# the failure was loud (logged) rather than silent.
#
# The stub faithfully models the variadic parsing and errors if the prompt did
# not arrive. The wrapper must pass the prompt via stdin for this to pass.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$HERE/../../72-run-episodic-maintain.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# The wrapper resolves NERVEPACK="$HOME/Code/nervepack" and reads the prompt file
# from there. Build a minimal fake home so the test works when HOME is hermetically
# redirected by the regression runner.
fake_home="$tmp/home"
mkdir -p "$fake_home/.local/bin" "$fake_home/.cache/nervepack" "$fake_home/Code/nervepack/agents"
cat > "$fake_home/Code/nervepack/agents/np-flow-episodic-maintain.md" <<'AGENT'
# np-flow-episodic-maintain

## Prompt
Summarise the session for episodic memory. Return a brief JSON note.
AGENT
export HOME="$fake_home"

# Issue #12: 72 now SKIPS its agent run when the content dir is the implicit engine-root
# fallback (NP_CONTENT_DIR unset + no config file) — so configure an explicit overlay,
# the state in which the agent actually runs, to exercise the `claude -p` invocation.
export NP_CONTENT_DIR="$tmp/content"; mkdir -p "$NP_CONTENT_DIR"

cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
in_variadic=0
prompt_arg=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allowedTools|--allowed-tools|--disallowedTools|--disallowed-tools)
      in_variadic=1; shift ;;
    --model|--permission-mode|--append-system-prompt|--system-prompt)
      in_variadic=0; shift 2 ;;
    -p|--print) in_variadic=0; shift ;;
    --*) in_variadic=0; shift ;;
    *) if [[ $in_variadic -eq 1 ]]; then shift; else prompt_arg="$1"; shift; fi ;;
  esac
done
stdin_data="$(cat)"
prompt="${stdin_data:-$prompt_arg}"
if [[ -z "$prompt" ]]; then
  echo "Error: Input must be provided either through stdin or as a prompt argument when using --print" >&2
  exit 1
fi
echo "MAINTAIN_RAN ok"
STUB
chmod +x "$tmp/claude"

log="$tmp/maintain.log"
CLAUDE_BIN="$tmp/claude" EPISODIC_MAINTAIN_LOG="$log" bash "$WRAPPER"

[[ -f "$log" ]] || { echo "FAIL: no log written"; exit 1; }
grep -q 'MAINTAIN_RAN ok' "$log" || { echo "FAIL: claude never received the prompt; log:"; cat "$log"; exit 1; }
grep -q 'Input must be provided' "$log" && { echo "FAIL: CLI aborted on input; log:"; cat "$log"; exit 1; }
echo "PASS test_maintain_invocation"
