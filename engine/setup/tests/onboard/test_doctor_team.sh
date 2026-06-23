#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/team"
out="$(NP_TEAM_DIR="$tmp/team" bash "$S/np-doctor.sh" 2>&1 || true)"
grep -qiE 'team' <<<"$out" || { echo "FAIL: doctor never mentions team"; exit 1; }
grep -q "$tmp/team" <<<"$out" || { echo "FAIL: doctor doesn't show the team dir"; exit 1; }
echo "PASS test_doctor_team"
