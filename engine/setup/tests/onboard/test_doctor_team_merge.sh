#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/team"
printf 'team.merge=concatenate\n' > "$tmp/local"
out="$(NP_TEAM_DIR="$tmp/team" NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" bash "$S/np-doctor.sh" 2>&1 || true)"
grep -qi 'concatenate' <<<"$out" || { echo "FAIL: doctor doesn't report the merge mode"; exit 1; }
echo "PASS test_doctor_team_merge"
