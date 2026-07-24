#!/usr/bin/env bash
# Team-layer reporting via the Python doctor (phase 15; np-doctor.sh retired —
# this drives `cli.py doctor`). A configured NP_TEAM_DIR must surface on the team
# capability line. Hermetic HOME; llm-cli is left to FAIL (no real model call —
# CLAUDE_BIN points at a missing path) since this test only asserts the team line.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."                                   # engine/setup
CLI="$S/../nervepack_engine/cli.py"
CAPS="$S/../onboard/capabilities.json"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"; mkdir -p "$tmp/team"
out="$(NP_TEAM_DIR="$tmp/team" NP_CAPABILITIES="$CAPS" CLAUDE_BIN="$tmp/no-claude" \
       python3 "$CLI" doctor 2>&1 || true)"
grep -qiE 'team' <<<"$out" || { echo "FAIL: doctor never mentions team"; exit 1; }
# Assert the configured team layer SURFACED (the PASS branch emits "team layers
# (N): …"), rather than grepping the literal $tmp path: on the Windows/Git-bash
# lane $tmp is an MSYS/backslash path that differs in form (and regex-escapes) from
# what native-Python echoes back, making an exact-path match spuriously fail. The
# exact-path behavior is covered host-natively in-process by test_np_doctor.py.
grep -qi 'team layer' <<<"$out" || { echo "FAIL: doctor doesn't surface the configured team layer: $out"; exit 1; }
echo "PASS test_doctor_team"
