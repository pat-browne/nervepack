#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_SIGNAL_DIR="$tmp/sig"
printf 'evaluator|shared|runtime|on|\nplaybooks|shared|runtime|on|\n' > "$tmp/toggles.conf"
mkdir -p "$tmp/pb"
printf '| topic | tool_match | gate | topic_triggers | seen |\n|---|---|---|---|---:|\n| r |  | warn | rename | 1 |\n' > "$tmp/pb/INDEX.md"
printf -- '---\nname: r\n---\n**Do:** x\n' > "$tmp/pb/r.md"
# evaluator.signals ON -> firing playbook-recall logs a marker
printf '%s' "$(jq -nc '{session_id:"s1",prompt:"rename stuff"}')" | EPISODIC_PLAYBOOK_DIR="$tmp/pb" EPISODIC_STATE_DIR="$tmp/st" bash "$S/playbook-recall.sh" >/dev/null
grep -q '^playbook-recall' "$tmp/sig/s1.log" || { echo "FAIL: no signal marker written while on"; exit 1; }
# evaluator.signals OFF -> no marker
echo "evaluator.signals=off" > "$tmp/local"; rm -rf "$tmp/sig"
printf '%s' "$(jq -nc '{session_id:"s2",prompt:"rename stuff"}')" | EPISODIC_PLAYBOOK_DIR="$tmp/pb" EPISODIC_STATE_DIR="$tmp/st" bash "$S/playbook-recall.sh" >/dev/null
[[ -f "$tmp/sig/s2.log" ]] && { echo "FAIL: marker written while signals off"; exit 1; }
echo "PASS test_signal_log"
