#!/usr/bin/env bash
# Symlink every skill from the engine repo's skills/ AND the overlay's skills/
# into ~/.claude/skills so Claude Code picks them up as user-level skills in
# every session.  Overlay-wins on a name clash (same dedup rule as npm workspaces).
#
# Safe to re-run:
#   - Existing symlinks to the correct target are left alone.
#   - Any non-symlink at the target path is reported and skipped (no overwrite).
#   - Dangling symlinks whose target is under either source base are pruned.
#   - Symlinks pointing elsewhere are never touched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-content-lib.sh"
ENGINE_SKILLS="$(cd "$HERE/../.." && pwd)/skills"
OVERLAY_SKILLS="$(np_content_dir)/skills"
DST="${NP_SKILLS_DST:-$HOME/.claude/skills}"
mkdir -p "$DST"

# Ordered source map: engine first, then overlay (overlay-wins on name clash).
# When content==engine (default) the two are identical -> no dupes.
# Stock macOS ships bash 3.2, which has no associative arrays, so we keep two
# parallel arrays + a linear upsert instead of `declare -A`. The skill set is
# small (tens of entries), so O(n^2) is irrelevant — this keeps the harness
# running on the default bash without requiring bash 4+.
_skill_names=(); _skill_dirs=()
_skill_upsert() {   # $1=name $2=dir ; overrides an existing name in place
  local i
  for ((i = 0; i < ${#_skill_names[@]}; i++)); do
    if [[ "${_skill_names[$i]}" == "$1" ]]; then _skill_dirs[$i]="$2"; return; fi
  done
  _skill_names+=("$1"); _skill_dirs+=("$2")
}
for base in "$ENGINE_SKILLS" "$OVERLAY_SKILLS"; do
  [[ -d "$base" ]] || continue
  for sd in "$base"/*/; do
    [[ -d "$sd" ]] || continue
    _skill_upsert "$(basename "$sd")" "${sd%/}"   # later (overlay) overrides earlier (engine)
  done
done

# Prune pass: remove symlinks in $DST whose target is under either source base but missing.
shopt -s nullglob
for link in "$DST"/*; do
  [[ -L "$link" ]] || continue
  target="$(readlink "$link")"
  case "$target" in
    "$ENGINE_SKILLS"/*|"$OVERLAY_SKILLS"/*)
      [[ -e "$link" ]] || { rm "$link"; echo "prune $(basename "$link") (target gone: $target)"; } ;;
  esac
done
shopt -u nullglob

# Link pass: iterate the deduped name→dir map, repointing a link when the overlay
# now overrides what was previously an engine-sourced link.
for ((_i = 0; _i < ${#_skill_names[@]}; _i++)); do
  name="${_skill_names[$_i]}"
  skill_dir="${_skill_dirs[$_i]}"
  target="$DST/$name"
  if [[ -L "$target" ]]; then
    cur="$(readlink "$target")"
    if [[ "$cur" == "$skill_dir" ]]; then echo "ok    $name (already linked)"; continue; fi
    case "$cur" in
      "$ENGINE_SKILLS"/*|"$OVERLAY_SKILLS"/*) rm "$target" ;;   # repoint (overlay-wins / path change)
      *) echo "skip  $name (symlink to external target, not repointing: $cur)" >&2; continue ;;
    esac
  elif [[ -e "$target" ]]; then
    echo "skip  $name (real file/dir already at $target)" >&2; continue
  fi
  ln -s "$skill_dir" "$target"
  echo "link  $name -> $skill_dir"
done

# Regenerate INDEX.md so it tracks the current skill set.
if [[ -x "$HERE/60-generate-index.sh" ]]; then
  "$HERE/60-generate-index.sh" >/dev/null
fi
