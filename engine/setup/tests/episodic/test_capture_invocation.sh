#!/usr/bin/env bash
# Regression test for the `claude -p` invocation in episodic-capture.sh.
#
# Bug (2026-06-03): the prompt was passed as a trailing positional AFTER the
# variadic `--allowedTools` flag. Commander's `<tools...>` greedily consumes
# every following non-flag arg, so it ate the prompt; the real CLI then aborted
# with "Input must be provided ... when using --print". `2>/dev/null || exit 0`
# swallowed it, so capture silently wrote nothing to the inbox.
#
# The existing test_capture.sh stub ignores all args, so it could not catch this.
# This stub faithfully models the variadic parsing: the prompt MUST arrive via
# stdin (or a positional the variadic did not eat), or claude "fails" like the
# real CLI does — which leaves the inbox empty and fails this test.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo '{"role":"user","content":"hi"}' > "$tmp/transcript.jsonl"

# Faithful stub of `claude -p` arg handling: --allowedTools/--disallowedTools are
# VARIADIC and consume following args until the next --flag. The prompt is stdin
# if non-empty, else the first positional the variadic did not consume. If no
# prompt is found, emulate the real CLI's fatal error and exit non-zero.
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
printf '%s' '{"headline":"did the thing","body":"summarized the session","candidate_topics":["misc"],"keywords":["one","two"]}'
STUB
chmod +x "$tmp/claude"

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t, cwd:$c}')"

printf '%s' "$payload" | EPISODIC_INBOX="$tmp/inbox" EPISODIC_SEEN_DIR="$tmp/seen" CLAUDE_BIN="$tmp/claude" bash "$CAPTURE" session-end

shopt -s nullglob
files=("$tmp"/inbox/*.jsonl)
[[ ${#files[@]} -gt 0 ]] || { echo "FAIL: no inbox note written — claude never received the prompt"; exit 1; }
line="$(cat "${files[@]}")"
echo "$line" | jq -e '.headline == "did the thing"' >/dev/null || { echo "FAIL: note malformed: $line"; exit 1; }
echo "PASS test_capture_invocation"
