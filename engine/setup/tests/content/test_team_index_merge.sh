#!/usr/bin/env bash
# Merged overlay INDEX picks the team copy; engine INDEX stays engine-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
mkdir -p "$tmp/nervepack/engine/setup" "$tmp/nervepack/skills/np-kb-x" \
         "$tmp/personal/skills/np-kb-x" "$tmp/team/skills/np-kb-x" "$tmp/.config/nervepack"
cp "$S/np-content-lib.sh" "$S/np-toggle-lib.sh" "$S/np-layer-lib.sh" "$S/60-generate-index.sh" "$tmp/nervepack/engine/setup/"
printf -- '---\nname: np-kb-x\ndescription: ENGINE copy\n---\n' > "$tmp/nervepack/skills/np-kb-x/SKILL.md"
printf -- '---\nname: np-kb-x\ndescription: PERSONAL copy\n---\n' > "$tmp/personal/skills/np-kb-x/SKILL.md"
printf -- '---\nname: np-kb-x\ndescription: TEAM copy\n---\n' > "$tmp/team/skills/np-kb-x/SKILL.md"
export NERVEPACK="$tmp/nervepack" NP_CONTENT_DIR="$tmp/personal" NP_TEAM_DIR="$tmp/team"
export NP_TOGGLES_CONF="$S/toggles.conf"

bash "$tmp/nervepack/engine/setup/60-generate-index.sh" >/dev/null
grep -q 'TEAM copy' "$tmp/personal/INDEX.md" || { echo "FAIL: merged INDEX missing TEAM copy"; cat "$tmp/personal/INDEX.md"; exit 1; }
grep -q 'PERSONAL copy' "$tmp/personal/INDEX.md" && { echo "FAIL: personal copy should be overridden"; exit 1; }
grep -q 'ENGINE copy' "$tmp/nervepack/INDEX.md" || { echo "FAIL: engine INDEX should keep engine copy"; cat "$tmp/nervepack/INDEX.md"; exit 1; }
grep -q 'TEAM copy' "$tmp/nervepack/INDEX.md" && { echo "FAIL: engine INDEX must stay engine-only"; exit 1; }

# --- two team dirs: higher-precedence (first) team wins the merged INDEX ------
mkdir -p "$tmp/teamHi/skills/np-kb-x" "$tmp/teamLo/skills/np-kb-x"
printf -- '---\nname: np-kb-x\ndescription: TEAMHI copy\n---\n' > "$tmp/teamHi/skills/np-kb-x/SKILL.md"
printf -- '---\nname: np-kb-x\ndescription: TEAMLO copy\n---\n' > "$tmp/teamLo/skills/np-kb-x/SKILL.md"
NP_TEAM_DIR="$tmp/teamHi,$tmp/teamLo" bash "$tmp/nervepack/engine/setup/60-generate-index.sh" >/dev/null
grep -q 'TEAMHI copy' "$tmp/personal/INDEX.md" || { echo "FAIL: merged INDEX should pick highest-precedence team"; cat "$tmp/personal/INDEX.md"; exit 1; }
grep -q 'TEAMLO copy' "$tmp/personal/INDEX.md" && { echo "FAIL: lower-precedence team should be overridden"; exit 1; }

# --- non-clashing skill unique to the LOWER-precedence team must still be merged in
# (proves the index spans ALL team dirs, not just the highest — a single-team
# implementation would omit this entirely regardless of the clash-winner check above).
mkdir -p "$tmp/teamLo/skills/np-kb-lo-only"
printf -- '---\nname: np-kb-lo-only\ndescription: LO-ONLY copy\n---\n' > "$tmp/teamLo/skills/np-kb-lo-only/SKILL.md"
NP_TEAM_DIR="$tmp/teamHi,$tmp/teamLo" bash "$tmp/nervepack/engine/setup/60-generate-index.sh" >/dev/null
grep -q 'LO-ONLY copy' "$tmp/personal/INDEX.md" || { echo "FAIL: merged INDEX should span all team dirs, not just highest-precedence"; cat "$tmp/personal/INDEX.md"; exit 1; }

echo "PASS test_team_index_merge"
