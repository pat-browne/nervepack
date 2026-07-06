#!/usr/bin/env bash
# A/B parity: np_capture.py must write the SAME inbox note as episodic-capture.sh
# given identical inputs and a stubbed model. Both run the same Python helpers
# (transcript-extract, json-extract) + the same scrub, so the only variable is the
# orchestration + the jq-vs-json envelope build — compared byte-identical modulo
# the embedded UTC timestamp.
#
# Skipped on the Git-bash Windows lane: the model stub (CLAUDE_BIN) is a shebang
# script that native-Windows Python can't CreateProcess (WinError 193). The
# orchestration is platform-independent; the windows-bashfree lane covers the
# Python path functionally.
set -uo pipefail
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) echo "SKIP test_capture_parity: model stub unavailable on Windows-bash"; exit 0 ;;
esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/episodic-capture.sh"
PY="$SETUP/np_capture.py"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_capture_parity: no python3"; exit 0; }
command -v jq      >/dev/null 2>&1 || { echo "SKIP test_capture_parity: no jq"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"
# pii_filter must be off to match production (toggles.conf: pii_filter|shared|runtime|off|).
# An empty conf makes np_enabled fail-open (unknown=on), accidentally enabling PII scrub
# in the bash path. Python checks NP_PII_FILTER=1 env var instead — so without this line
# the two paths diverge: bash applies /home/u/ -> [PATH]/, python does not.
printf 'pii_filter|shared|runtime|off|\n' > "$tmp/conf"
export NP_TOGGLES_CONF="$tmp/conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"; : > "$NP_TOGGLES_LOCAL"

# A transcript file (content irrelevant — the stub ignores the prompt; only its
# size matters for the dedup fingerprint, which we keep out of the way per-run).
printf '{"type":"user","message":{"role":"user","content":"hi"}}\n' > "$tmp/transcript.jsonl"

# Model stub: drain stdin, emit a fixed JSON note (what the summarizer would return).
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"headline":"ported the toggle resolver","body":"We ported np-toggle-lib to Python and locked it with a parity test. Left off wiring the server.","candidate_topics":["nervepack","mcp"],"keywords":["toggle","parity","python","mcp","bashfree"],"struggles":[],"strategies":[]}'
STUB
chmod +x "$tmp/claude"
export CLAUDE_BIN="$tmp/claude" NP_LLM_BACKEND=claude

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" '{transcript_path:$t, cwd:"/home/u/proj", session_id:"sess-123"}')"

# Run each into its own inbox + seen dir (so dedup never suppresses either).
printf '%s' "$payload" | EPISODIC_INBOX="$tmp/binbox" EPISODIC_SEEN_DIR="$tmp/bseen" bash "$SH" session-end >/dev/null 2>&1
printf '%s' "$payload" | EPISODIC_INBOX="$tmp/pinbox" EPISODIC_SEEN_DIR="$tmp/pseen" python3 "$PY" session-end >/dev/null 2>&1

bfile="$(find "$tmp/binbox" -name '*.jsonl' 2>/dev/null | head -1)"
pfile="$(find "$tmp/pinbox" -name '*.jsonl' 2>/dev/null | head -1)"
if [[ -z "$bfile" || -z "$pfile" ]]; then
  echo "FAIL test_capture_parity: missing inbox note (bash=$bfile python=$pfile)"; exit 1
fi
norm() { sed -E 's/"ts":"[0-9T:Z-]+"/"ts":"<TS>"/g'; }
if ! diff <(norm < "$bfile") <(norm < "$pfile") >/dev/null; then
  echo "FAIL test_capture_parity: inbox notes differ"
  echo "--- bash ---";   norm < "$bfile"
  echo "--- python ---"; norm < "$pfile"
  exit 1
fi
echo "PASS test_capture_parity"
