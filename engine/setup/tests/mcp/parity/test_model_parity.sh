#!/usr/bin/env bash
# A/B parity: np_model.py `complete` must invoke the model backend with the SAME
# argv + stdin as `np-llm.sh complete`. We stub the backend (CLAUDE_BIN -> a script
# that echoes its argv then its stdin) and compare what each driver produced —
# equivalence without a real model call.
#
# Skipped on the Git-bash Windows lane: the stub must be exec'd by BOTH bash (via
# "$CLAUDE") and the native-Windows Python child (subprocess argv[0]), and a
# shebang script can't be CreateProcess'd on Windows (WinError 193). The argv
# construction is platform-independent Python string logic, so Linux/macOS parity
# fully validates it; Windows gets functional coverage once capture/evaluate land.
set -uo pipefail
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) echo "SKIP test_model_parity: dual-exec stub unavailable on Windows-bash"; exit 0 ;;
esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/np-llm.sh"
PY="$SETUP/np_model.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_model_parity: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0

# Stub backend: print each argv element on its own line, then a marker + stdin.
cat > "$tmp/stub" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do printf 'ARG:[%s]\n' "$a"; done
printf 'STDIN:['; cat; printf ']\n'
STUB
chmod +x "$tmp/stub"

export CLAUDE_BIN="$tmp/stub" NP_LLM_MODEL_CHEAP="test-model-x" NP_LLM_BACKEND="claude"

cmp_complete() {  # $1=label  $2=prompt  $3=system (optional)
  local sysargs=()
  [[ -n "${3:-}" ]] && sysargs=(--system "$3")
  printf '%s' "$2" | bash    "$SH" complete "${sysargs[@]}" > "$tmp/b.out" 2>/dev/null
  printf '%s' "$2" | python3 "$PY" complete "${sysargs[@]}" > "$tmp/p.out" 2>/dev/null
  if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
    echo "FAIL [$1]:"; echo "--- bash ---"; cat "$tmp/b.out"; echo "--- python ---"; cat "$tmp/p.out"
    fails=$((fails+1))
  fi
}

cmp_complete "no system"        "summarize this please"
cmp_complete "with system"      "summarize this please" "You are a non-conversational extractor."
cmp_complete "multiline prompt" $'line one\nline two\nline three'
cmp_complete "empty prompt"     ""

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_model_parity: $fails mismatch(es)"; exit 1
fi
echo "PASS test_model_parity"
