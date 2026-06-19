#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../np-instruction-block.sh"
fail=0
chk() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export NP_DIRECTIVE_PATH="/opt/np/nervepack-session-directive.md"
F="$TMP/CLAUDE.md"
printf '# My project rules\n\nUse tabs.\n' > "$F"

bash "$LIB" install "$F"
chk "user content preserved"        "grep -q 'Use tabs.' '$F'"
chk "exactly one begin marker"      "[ \"\$(grep -c 'nervepack:begin' '$F')\" = 1 ]"
chk "import line present"           "grep -qF '@/opt/np/nervepack-session-directive.md' '$F'"

bash "$LIB" install "$F"
chk "idempotent: still one block"   "[ \"\$(grep -c 'nervepack:begin' '$F')\" = 1 ]"
chk "user content still present"    "grep -q 'Use tabs.' '$F'"

bash "$LIB" remove "$F"
chk "block removed"                 "[ \"\$(grep -c 'nervepack:begin' '$F')\" = 0 ]"
chk "user content intact"           "grep -q 'Use tabs.' '$F'"
chk "no nervepack markers remain"   "! grep -q 'nervepack:' '$F'"

G="$TMP/sub/AGENTS.md"
bash "$LIB" install "$G"
chk "creates missing target"        "[ -f '$G' ]"
chk "block present in new file"     "[ \"\$(grep -c 'nervepack:begin' '$G')\" = 1 ]"

H="$TMP/CLAUDE_with_trailing.md"
printf '# My instructions\n\nInitial content.\n' > "$H"
bash "$LIB" install "$H"
printf 'TRAILING user line\n' >> "$H"
bash "$LIB" remove "$H"
chk "remove preserves trailing content" "grep -q 'TRAILING user line' '$H'"
chk "remove cleans all nervepack markers" "! grep -q 'nervepack:' '$H'"

I="$TMP/CLAUDE_lone_begin.md"
BEGIN_MARKER='<!-- nervepack:begin (managed — do not edit; remove via np-instruction-block.sh remove) -->'
printf '%s\nORPHAN user content\n' "$BEGIN_MARKER" > "$I"
bash "$LIB" remove "$I"
chk "lone begin: trailing content preserved" "grep -q 'ORPHAN user content' '$I'"
chk "lone begin: no block dropped"           "[ \"\$(wc -l < '$I')\" -ge 1 ]"

[ $fail -eq 0 ] && echo "PASS test_instruction_block" || { echo "FAIL test_instruction_block"; exit 1; }
