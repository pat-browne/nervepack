#!/usr/bin/env bash
# A/B parity: np_doctor.py's deterministic CORE-check lines (git-sync, toggles,
# content, team, dashboard-data, resume-pointer) must be byte-identical to
# np-doctor.sh's, in a controlled environment. The model-seam (llm-cli) and
# host-adapter checks are intentionally NOT compared — the Python doctor reports
# them N/A (bash-free), while the bash doctor runs them; that divergence is by
# design. hook-scripts is also excluded: it has NO python mirror (SKIP in
# np_doctor.py) so there is nothing to compare — but resume-pointer DOES have a
# mirror, so it is included and driven with a real (both-hooks-registered) fixture
# below so the compared line is a meaningful PASS, not the trivial no-settings WARN.
#
# Requires bash + git, so it runs on Linux + the Git-bash Windows lane, not the
# bash-free lane.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../../.." && pwd)"          # engine/setup
SH="$SETUP/np-doctor.sh"
PY="$SETUP/np_doctor.py"
CAPS="$SETUP/../onboard/capabilities.json"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no python3"; exit 0; }
command -v git     >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no git"; exit 0; }
command -v jq      >/dev/null 2>&1 || { echo "SKIP test_doctor_parity: no jq"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Use a path form BOTH Git-bash and the native-Windows Python resolve to the SAME
# location (mixed C:/... form), so the team-list dirs the doctor prints exist for the
# bash resolver AND the native-Python port — otherwise native Python can't stat the
# MSYS-only /tmp/... path, team_dirs() returns empty, and the team line diverges from
# bash. Mirrors test_content_parity.sh. No-op off Windows (no cygpath).
if command -v cygpath >/dev/null 2>&1; then tmp="$(cygpath -m "$tmp")"; fi
export HOME="$tmp/home"; mkdir -p "$HOME/.config/nervepack"

# A throwaway repo with an origin remote (git-sync PASS), a separate content dir
# (content PASS, split layout -> dashboard-data WARN bridge-missing), hermetic toggles.
mkdir -p "$tmp/repo" "$tmp/content" "$tmp/team" "$tmp/team2"
git -C "$tmp/repo" init -q
git -C "$tmp/repo" remote add origin https://example.test/nervepack.git
: > "$tmp/toggles.conf"
export NP_DIR="$tmp/repo" NP_CONTENT_DIR="$tmp/content" NP_CAPABILITIES="$CAPS"
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$HOME/.config/nervepack/toggles.local"
export NP_TEAM_DIR="$tmp/team,$tmp/team2"

# resume-pointer fixture: a writer stub under the throwaway NP_DIR (both doctors
# resolve the writer at $NP_DIR/engine/nervepack_engine/hooks/resume_write.py) plus
# a CLAUDE_SETTINGS registering BOTH hooks (SessionStart -> np-resume-sessionstart.sh,
# UserPromptSubmit -> np-resume-recall.sh). This drives the check's real logic so both
# bash and python emit the PASS line — proving they agree on a non-trivial input, not
# just the no-settings WARN both sides would emit vacuously.
mkdir -p "$tmp/repo/engine/nervepack_engine/hooks"
printf '# stub\n' > "$tmp/repo/engine/nervepack_engine/hooks/resume_write.py"
cat > "$tmp/settings.json" <<'JSON'
{"hooks":{
  "SessionStart":[{"matcher":"","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/np-resume-sessionstart.sh &"}]}],
  "UserPromptSubmit":[{"matcher":"","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/np-resume-recall.sh"}]}]
}}
JSON
export CLAUDE_SETTINGS="$tmp/settings.json"

core='\] (git-sync|toggles|content|team|dashboard-data|resume-pointer) '
bash    "$SH" 2>/dev/null | grep -E "$core" > "$tmp/b.out"
python3 "$PY" 2>/dev/null | grep -E "$core" > "$tmp/p.out"

if ! cmp -s "$tmp/b.out" "$tmp/p.out"; then
  echo "FAIL test_doctor_parity: core-check lines differ"
  echo "--- bash ---";   cat "$tmp/b.out"
  echo "--- python ---"; cat "$tmp/p.out"
  exit 1
fi
# Sanity: we actually compared the six core lines (not an empty match).
[[ "$(wc -l < "$tmp/b.out")" -eq 6 ]] || { echo "FAIL test_doctor_parity: expected 6 core lines, got $(wc -l < "$tmp/b.out")"; exit 1; }
# And that the resume-pointer line we compared is the meaningful PASS (fixture drove
# the real both-hooks-registered logic), not a trivial WARN both sides emit vacuously.
grep -qE '\] resume-pointer +PASS$' "$tmp/b.out" \
  || { echo "FAIL test_doctor_parity: resume-pointer fixture did not yield PASS: $(grep resume-pointer "$tmp/b.out")"; exit 1; }

# --- over-cap fixture: NP_TEAM_DIR set to 5 existing dirs (> the 4-dir cap), team
# toggle on -> np_team_dirs/team_dirs returns empty + non-zero but origin is "env"
# (not "none"), so the `team` core-check line must WARN (configured-but-invalid),
# not silently PASS as "no team layer configured". Confirm bash/python stay identical.
mkdir -p "$tmp/team1" "$tmp/team2" "$tmp/team3" "$tmp/team4" "$tmp/team5"
export NP_TEAM_DIR="$tmp/team1,$tmp/team2,$tmp/team3,$tmp/team4,$tmp/team5"
printf 'team=on\n' > "$NP_TOGGLES_LOCAL"
bash    "$SH" 2>/dev/null | grep -E '\] team ' > "$tmp/b-overcap.out"
python3 "$PY" 2>/dev/null | grep -E '\] team ' > "$tmp/p-overcap.out"
if ! cmp -s "$tmp/b-overcap.out" "$tmp/p-overcap.out"; then
  echo "FAIL test_doctor_parity: over-cap team line differs"
  echo "--- bash ---";   cat "$tmp/b-overcap.out"
  echo "--- python ---"; cat "$tmp/p-overcap.out"
  exit 1
fi
grep -q 'WARN (team layer configured (origin env) but invalid' "$tmp/b-overcap.out" \
  || { echo "FAIL test_doctor_parity: over-cap team line missing expected WARN text: $(cat "$tmp/b-overcap.out")"; exit 1; }

echo "PASS test_doctor_parity"
