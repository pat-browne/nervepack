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
declare -A _skill_src
for base in "$ENGINE_SKILLS" "$OVERLAY_SKILLS"; do
  [[ -d "$base" ]] || continue
  for sd in "$base"/*/; do
    [[ -d "$sd" ]] || continue
    _skill_src["$(basename "$sd")"]="${sd%/}"   # later (overlay) overrides earlier (engine)
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
for name in "${!_skill_src[@]}"; do
  skill_dir="${_skill_src[$name]}"
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
