#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
: > "$tmp/toggles.conf"
mkdir -p "$tmp/pb"
printf '| topic | tool_match | gate | topic_triggers | seen |\n|---|---|---|---|---:|\n| r |  | warn | rename | 1 |\n' > "$tmp/pb/INDEX.md"
printf -- '---\nname: r\n---\n**Do:** x\n' > "$tmp/pb/r.md"
# playbook-recall OFF -> no output even on a matching prompt
echo "playbooks.recall=off" > "$tmp/local"
out="$(printf '%s' "$(jq -nc '{session_id:"x",prompt:"rename stuff"}')" | EPISODIC_PLAYBOOK_DIR="$tmp/pb" EPISODIC_STATE_DIR="$tmp/st" bash "$S/playbook-recall.sh")"
[[ -z "$out" ]] || { echo "FAIL: playbook-recall ran while off: $out"; exit 1; }
# with it ON, it injects
echo "playbooks.recall=on" > "$tmp/local"
out2="$(printf '%s' "$(jq -nc '{session_id:"y",prompt:"rename stuff"}')" | EPISODIC_PLAYBOOK_DIR="$tmp/pb" EPISODIC_STATE_DIR="$tmp/st" bash "$S/playbook-recall.sh")"
echo "$out2" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null || { echo "FAIL: playbook-recall silent while on"; exit 1; }
echo "PASS test_guards"
