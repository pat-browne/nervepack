#!/usr/bin/env bash
# A/B parity: np_evaluator.py must write the SAME inbox record as np-evaluator.sh
# given identical inputs and a stubbed model — including the deterministic
# cost-aware suggestion (both when it triggers and when it doesn't). Both run the
# same signals + transcript-extract + scrub, so only the orchestration + the
# jq-vs-json record build vary. Compared byte-identical modulo the UTC timestamp.
#
# Skipped on the Git-bash Windows lane (shebang model stub can't exec under
# native-Windows Python); the orchestration is platform-independent and the
# windows-bashfree lane covers the Python path functionally.
set -uo pipefail
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) echo "SKIP test_evaluator_parity: model stub unavailable on Windows-bash"; exit 0 ;;
esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/np-evaluator.sh"
PY="$SETUP/np_evaluator.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_evaluator_parity: no python3"; exit 0; }
command -v jq      >/dev/null 2>&1 || { echo "SKIP test_evaluator_parity: no jq"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"
: > "$tmp/conf"; export NP_TOGGLES_CONF="$tmp/conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"

printf '{"type":"user","message":{"role":"user","content":"hi"}}\n' > "$tmp/transcript.jsonl"

cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"contribution_score":35,"helped":["reused the toggle skill"],"shortfalls":[],"suggestions":[],"assets_used":[{"asset":"np-kb-testing-ci","kind":"skill","used":true}]}'
STUB
chmod +x "$tmp/claude"
export CLAUDE_BIN="$tmp/claude" NP_LLM_BACKEND=claude

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" '{transcript_path:$t, cwd:"/home/u/proj", session_id:"sess-9"}')"
fails=0

run_case() {  # $1=label
  rm -rf "$tmp/binbox" "$tmp/pinbox"
  printf '%s' "$payload" | EVAL_INBOX="$tmp/binbox" bash    "$SH" >/dev/null 2>&1
  printf '%s' "$payload" | EVAL_INBOX="$tmp/pinbox" python3 "$PY" >/dev/null 2>&1
  local b p; b="$(find "$tmp/binbox" -name '*.jsonl' 2>/dev/null | head -1)"; p="$(find "$tmp/pinbox" -name '*.jsonl' 2>/dev/null | head -1)"
  if [[ -z "$b" || -z "$p" ]]; then echo "FAIL [$1]: missing record (bash=$b python=$p)"; fails=$((fails+1)); return; fi
  norm() { sed -E 's/"ts":"[0-9T:Z-]+"/"ts":"<TS>"/g'; }
  if ! diff <(norm < "$b") <(norm < "$p") >/dev/null; then
    echo "FAIL [$1]: records differ"; echo "--- bash ---"; norm < "$b"; echo "--- python ---"; norm < "$p"; fails=$((fails+1))
  fi
}

# No cost suggestion (default thresholds: cost_hi 200000 not met).
: > "$NP_TOGGLES_LOCAL"
run_case "no cost suggestion"

# Cost suggestion triggers: cost_hi=0 (any output >= 0) AND score_lo=100 (35 <= 100).
printf 'evaluator.cost_hi_tokens=0\nevaluator.score_lo=100\n' > "$NP_TOGGLES_LOCAL"
run_case "cost suggestion appended"

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL test_evaluator_parity: $fails mismatch(es)"; exit 1
fi
echo "PASS test_evaluator_parity"
