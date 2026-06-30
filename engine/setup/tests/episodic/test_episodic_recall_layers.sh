#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
export NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
export EPISODIC_STATE_DIR="$tmp/state"
mk(){ mkdir -p "$tmp/$1/memory/episodic"
  printf '| topic | last_updated | keywords | lines |\n|---|---|---|---|\n| onboarding | 2026-06-01 | onboarding | 5 |\n' > "$tmp/$1/memory/episodic/INDEX.md"
  printf -- '---\nname: onboarding\n---\n%s theme body\n' "$2" > "$tmp/$1/memory/episodic/onboarding.md"; }
mk personal "PERSONAL"; mk team "TEAM"
run(){ printf '%s' "$(jq -nc '{session_id:"s1",prompt:"about onboarding"}')" | bash "$S/episodic-recall.sh"; }

printf 'team.merge=override\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'TEAM theme' && ! echo "$out" | grep -q 'PERSONAL theme' || { echo "FAIL override"; exit 1; }
printf 'team.merge=concatenate\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; { echo "$out" | grep -q 'TEAM theme' && echo "$out" | grep -q 'PERSONAL theme'; } || { echo "FAIL concat"; exit 1; }
unset NP_TEAM_DIR; rm -f "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'PERSONAL theme' || { echo "FAIL no-team"; exit 1; }
echo "PASS test_episodic_recall_layers"
