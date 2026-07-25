#!/usr/bin/env bash
# np-test: link-skills | happy
# Team skill overrides personal overrides engine in the symlink set.
# Drives np_link_skills.py (phase 17 port of 30-link-skills.sh).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
LINK=(python3 "$S/np_link_skills.py")

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_team_skill_override: no python3"; exit 0; }
# Symlink creation is privilege-gated on the Windows lane — skip the actual-symlink
# assertion there (the INDEX-regen half is covered host-agnostically elsewhere).
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) echo "SKIP test_team_skill_override: symlinks privilege-gated on Windows"; exit 0 ;;
esac

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
mkdir -p "$tmp/.config/nervepack" "$tmp/dst"
# Three overlays, each carrying a skill of the SAME name.
for layer in engine personal team; do
  mkdir -p "$tmp/$layer/skills/np-kb-x"
  printf -- '---\nname: np-kb-x\ndescription: %s copy\n---\nbody\n' "$layer" \
    > "$tmp/$layer/skills/np-kb-x/SKILL.md"
done
export NP_SKILLS_DST="$tmp/dst"
export NP_DIR="$tmp/engine"
export NP_CONTENT_DIR="$tmp/personal"
export NP_TEAM_DIR="$tmp/team"
export NP_TOGGLES_CONF="$S/toggles.conf"   # team default on

"${LINK[@]}" >/dev/null
tgt="$(readlink "$tmp/dst/np-kb-x")"
[[ "$tgt" == "$tmp/team/skills/np-kb-x" ]] || { echo "FAIL: team did not win: $tgt"; exit 1; }

# Regression: no team -> personal wins
rm -rf "$tmp/dst"/*; unset NP_TEAM_DIR
"${LINK[@]}" >/dev/null
tgt="$(readlink "$tmp/dst/np-kb-x")"
[[ "$tgt" == "$tmp/personal/skills/np-kb-x" ]] || { echo "FAIL: no-team should be personal: $tgt"; exit 1; }

echo "PASS test_team_skill_override"
