#!/usr/bin/env bash
# The team capability line reports the active merge mode (phase 15; via the Python
# doctor `cli.py doctor`, np-doctor.sh retired). Hermetic HOME + toggles.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."                                   # engine/setup
CLI="$S/../nervepack_engine/cli.py"
CAPS="$S/../onboard/capabilities.json"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/team"
printf 'team=on\nteam.merge=concatenate\n' > "$tmp/local"
out="$(NP_TEAM_DIR="$tmp/team" NP_CAPABILITIES="$CAPS" CLAUDE_BIN="$tmp/no-claude" \
       NP_TOGGLES_CONF="$S/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" \
       python3 "$CLI" doctor 2>&1 || true)"
grep -qi 'concatenate' <<<"$out" || { echo "FAIL: doctor doesn't report the merge mode"; exit 1; }
echo "PASS test_doctor_team_merge"
