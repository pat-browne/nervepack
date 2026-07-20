#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
: > "$tmp/toggles.conf"
mkdir -p "$tmp/lessons"
printf '| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n| r |  | warn | rename |\n' > "$tmp/lessons/INDEX.md"
printf -- '---\nname: r\nkind: lesson\nprovenance: failure\n---\n**Do:** x\n' > "$tmp/lessons/r.md"
# lessons OFF -> no output even on a matching prompt
echo "lessons=off" > "$tmp/local"
out="$(printf '%s' "$(jq -nc '{session_id:"x",prompt:"rename stuff"}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/st" python3 "$S/../nervepack_engine/cli.py" hook lesson-recall)"
[[ -z "$out" ]] || { echo "FAIL: lesson-recall ran while off: $out"; exit 1; }
# with it ON, it injects
echo "lessons=on" > "$tmp/local"
out2="$(printf '%s' "$(jq -nc '{session_id:"y",prompt:"rename stuff"}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/st" python3 "$S/../nervepack_engine/cli.py" hook lesson-recall)"
echo "$out2" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null || { echo "FAIL: lesson-recall silent while on"; exit 1; }
echo "PASS test_guards"
