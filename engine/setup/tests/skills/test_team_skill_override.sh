#!/usr/bin/env bash
# Team skill overrides personal overrides engine in the symlink set.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp"
mkdir -p "$tmp/.config/nervepack" "$tmp/dst"
# Three overlays, each carrying a skill of the SAME name.
for layer in engine personal team; do
  mkdir -p "$tmp/$layer/skills/np-kb-x"
  printf -- '---\nname: np-kb-x\ndescription: %s copy\n---\nbody\n' "$layer" \
    > "$tmp/$layer/skills/np-kb-x/SKILL.md"
done
# Point the engine-skills base at our fake engine via a wrapper env the script honors:
# 30-link derives ENGINE_SKILLS from its own location, so run a copy whose ../../skills
# is our fake engine. Simplest: stage a fake engine root that sources the real lib.
mkdir -p "$tmp/fakeengine/engine/setup"
cp "$S/np-content-lib.sh" "$S/np-toggle-lib.sh" "$tmp/fakeengine/engine/setup/"
cp "$S/30-link-skills.sh" "$S/60-generate-index.sh" "$tmp/fakeengine/engine/setup/"
ln -s "$tmp/engine/skills" "$tmp/fakeengine/skills"
export NP_SKILLS_DST="$tmp/dst"
export NP_CONTENT_DIR="$tmp/personal"
export NP_TEAM_DIR="$tmp/team"
export NP_TOGGLES_CONF="$S/toggles.conf"   # team default on
export NERVEPACK="$tmp/fakeengine"

bash "$tmp/fakeengine/engine/setup/30-link-skills.sh" >/dev/null
tgt="$(readlink "$tmp/dst/np-kb-x")"
[[ "$tgt" == "$tmp/team/skills/np-kb-x" ]] || { echo "FAIL: team did not win: $tgt"; exit 1; }

# Regression: no team -> personal wins
rm -rf "$tmp/dst"/*; unset NP_TEAM_DIR
bash "$tmp/fakeengine/engine/setup/30-link-skills.sh" >/dev/null
tgt="$(readlink "$tmp/dst/np-kb-x")"
[[ "$tgt" == "$tmp/personal/skills/np-kb-x" ]] || { echo "FAIL: no-team should be personal: $tgt"; exit 1; }

echo "PASS test_team_skill_override"
