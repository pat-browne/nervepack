#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
export NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
export EPISODIC_STATE_DIR="$tmp/state"
mk(){ # $1=root $2=desc  — a playbook 'gitflow' triggered by "merge"
  mkdir -p "$tmp/$1/memory/playbooks"
  printf '| topic | tool_match | gate | topic_triggers | seen |\n|---|---|---|---|---|\n| gitflow |  | warn | merge | 1 |\n' > "$tmp/$1/memory/playbooks/INDEX.md"
  printf -- '---\nname: gitflow\n---\n**Do:** %s\n' "$2" > "$tmp/$1/memory/playbooks/gitflow.md"
}
mk personal "PERSONAL playbook"; mk team "TEAM playbook"
run(){ printf '%s' "$(jq -nc '{session_id:"s1",prompt:"about to merge"}')" | bash "$S/playbook-recall.sh"; }

# override (default): team wins, personal NOT injected
printf 'team.merge=override\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'TEAM playbook' || { echo "FAIL override: no team"; exit 1; }
echo "$out" | grep -q 'PERSONAL playbook' && { echo "FAIL override: personal leaked"; exit 1; }

# concatenate: both
printf 'team.merge=concatenate\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; { echo "$out" | grep -q 'TEAM playbook' && echo "$out" | grep -q 'PERSONAL playbook'; } || { echo "FAIL concat"; exit 1; }

# team-only: only team
printf 'team.merge=team-only\n' > "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'TEAM playbook' && ! echo "$out" | grep -q 'PERSONAL playbook' || { echo "FAIL team-only"; exit 1; }

# no team -> personal only (regression)
unset NP_TEAM_DIR; rm -f "$tmp/local"; rm -rf "$tmp/state"
out="$(run)"; echo "$out" | grep -q 'PERSONAL playbook' || { echo "FAIL no-team regression"; exit 1; }

echo "PASS test_playbook_recall_layers"
