#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_SIGNAL_DIR="$tmp/sig"
printf 'evaluator|shared|runtime|on|\nlessons|shared|runtime|on|\n' > "$tmp/toggles.conf"
mkdir -p "$tmp/lessons"
printf '| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n| r |  | warn | rename |\n' > "$tmp/lessons/INDEX.md"
printf -- '---\nname: r\nkind: lesson\nprovenance: failure\n---\n**Do:** x\n' > "$tmp/lessons/r.md"
# evaluator.signals ON -> firing lesson-recall logs a marker
printf '%s' "$(jq -nc '{session_id:"s1",prompt:"rename stuff"}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/st" bash "$S/lesson-recall.sh" >/dev/null
grep -q '^lesson-recall' "$tmp/sig/s1.log" || { echo "FAIL: no signal marker written while on"; exit 1; }
# evaluator.signals OFF -> no marker
echo "evaluator.signals=off" > "$tmp/local"; rm -rf "$tmp/sig"
printf '%s' "$(jq -nc '{session_id:"s2",prompt:"rename stuff"}')" | EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/st" bash "$S/lesson-recall.sh" >/dev/null
[[ -f "$tmp/sig/s2.log" ]] && { echo "FAIL: marker written while signals off"; exit 1; }
echo "PASS test_signal_log"
