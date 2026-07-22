#!/usr/bin/env bash
# A/B parity: np_model.py `agent` must invoke the model backend with the SAME
# argv + stdin as `np-llm.sh agent`. We stub the backend (CLAUDE_BIN -> a script
# that echoes its argv then its stdin) and compare what each driver produced —
# equivalence without a real model call. Also verifies the env-stripping fix
# (2026-07-13, np-llm.sh; carried into np_model.py in phase 9): a stale
# CLAUDE_CODE_SESSION_ID inherited by the parent process must not reach the
# child, for BOTH drivers.
#
# Skipped on the Git-bash Windows lane: the stub must be exec'd by BOTH bash (via
# "$CLAUDE") and the native-Windows Python child (subprocess argv[0]), and a
# shebang script can't be CreateProcess'd on Windows (WinError 193).
set -uo pipefail
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) echo "SKIP test_agent_parity: dual-exec stub unavailable on Windows-bash"; exit 0 ;;
esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/np-llm.sh"
PY="$SETUP/np_model.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_agent_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Stub backend: print each argv element on its own line, a marker + stdin, then
# whether the stale session var leaked through.
cat > "$tmp/stub" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do printf 'ARG:[%s]\n' "$a"; done
printf 'STDIN:['; cat; printf ']\n'
printf 'SESSION_LEAKED:[%s]\n' "${CLAUDE_CODE_SESSION_ID:-}"
STUB
chmod +x "$tmp/stub"

export CLAUDE_BIN="$tmp/stub" NP_LLM_MODEL_AGENT="test-agent-model" NP_LLM_BACKEND="claude"
export CLAUDE_CODE_SESSION_ID="stale-session-should-not-leak"

cmp_agent() {  # $1=label  $2=prompt  $3=tools
  printf '%s' "$2" | bash    "$SH" agent --tools "$3" > "$tmp/b.out" 2>/dev/null
  printf '%s' "$2" | python3 "$PY" agent --tools "$3" > "$tmp/p.out" 2>/dev/null
  if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
    echo "FAIL [$1]:"; echo "--- bash ---"; cat "$tmp/b.out"; echo "--- python ---"; cat "$tmp/p.out"
    fails=$((fails+1))
  fi
  if grep -q 'SESSION_LEAKED:\[stale-session-should-not-leak\]' "$tmp/b.out"; then
    echo "FAIL [$1]: bash driver leaked CLAUDE_CODE_SESSION_ID to the child"; fails=$((fails+1))
  fi
  if grep -q 'SESSION_LEAKED:\[stale-session-should-not-leak\]' "$tmp/p.out"; then
    echo "FAIL [$1]: python driver leaked CLAUDE_CODE_SESSION_ID to the child"; fails=$((fails+1))
  fi
}

cmp_agent "single tool"      "implement this"                    "Read"
cmp_agent "multiple tools"   "implement this"                    "Bash Read Write Edit Glob Grep"
cmp_agent "multiline prompt" $'line one\nline two\nline three'    "Read Write"
cmp_agent "empty prompt"     ""                                   "Read"

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_agent_parity: $fails mismatch(es)"; exit 1
fi
echo "PASS test_agent_parity"
