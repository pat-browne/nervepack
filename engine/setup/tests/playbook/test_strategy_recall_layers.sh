#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
export NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
export EPISODIC_STATE_DIR="$tmp/state"
mk(){ mkdir -p "$tmp/$1/strategies"
  printf '| topic | topic_triggers | seen |\n|---|---|---|\n| [deploydance](deploydance.md) | deploy | 1 |\n' > "$tmp/$1/strategies/INDEX.md"
  printf -- '---\nname: deploydance\n---\n**Title:** %s\n' "$2" > "$tmp/$1/strategies/deploydance.md"; }
mk personal "PERSONAL strategy"; mk team "TEAM strategy"
run(){ printf '%s' "$(jq -nc '{session_id:"s1",prompt:"time to deploy"}')" | bash "$S/strategy-recall.sh"; }

printf 'team.merge=override\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'TEAM strategy' && ! echo "$out" | grep -q 'PERSONAL strategy' || { echo "FAIL override"; exit 1; }
printf 'team.merge=concatenate\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; { echo "$out" | grep -q 'TEAM strategy' && echo "$out" | grep -q 'PERSONAL strategy'; } || { echo "FAIL concat"; exit 1; }
unset NP_TEAM_DIR; rm -f "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'PERSONAL strategy' || { echo "FAIL no-team"; exit 1; }
echo "PASS test_strategy_recall_layers"
