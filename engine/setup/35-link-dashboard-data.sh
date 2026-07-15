#!/usr/bin/env bash
# Ensure the engine's dashboard/data entry is a symlink into the content overlay so
# that index.html can load data/metrics.js as a relative sibling regardless of where
# the content dir lives. Idempotent: no-op if the correct symlink already exists.
# Fail-open: any trouble logs one line and exits 0 so a fresh bootstrap is never blocked.
#
# In a single-repo layout (content dir == engine root) the real dashboard/data dir
# already exists — no symlink is needed (and a self-referential symlink would break
# things), so this script does nothing.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../.." && pwd)"
source "$HERE/np-content-lib.sh"

bail() { echo "35-link-dashboard-data: $*"; exit 0; }

CONTENT="$(np_content_dir 2>/dev/null)" || bail "np_content_dir failed — skipping"

# Single-repo layout: content dir IS the engine root. The real dashboard/data dir
# is already in place; creating a symlink here would be self-referential.
if [[ "$CONTENT" == "$NP" ]]; then
  echo "35-link-dashboard-data: single-repo layout — no symlink needed"
  exit 0
fi

# Split layout: the symlink we want to maintain.
LINK="$NP/dashboard/data"
TARGET="$CONTENT/dashboard/data"

# Ensure the target dir exists in the content overlay.
mkdir -p "$TARGET" || bail "could not create $TARGET"

# Check current state of LINK.
if [[ -L "$LINK" ]]; then
  cur="$(readlink "$LINK")"
  if [[ "$cur" == "$TARGET" ]]; then
    echo "35-link-dashboard-data: ok (already correct symlink -> $TARGET)"
    exit 0
  fi
  # Wrong symlink target — replace it.
  rm -f "$LINK" || bail "could not remove stale symlink $LINK -> $cur"
  echo "35-link-dashboard-data: replaced stale symlink ($cur -> $TARGET)"
elif [[ -e "$LINK" ]]; then
  # Real file or directory — don't overwrite; log and skip.
  bail "$LINK exists and is not a symlink — skipping (remove it manually to enable the bridge)"
fi

# Create the link. IMPORTANT (Windows): a bare `ln -s` under Git-Bash silently
# DEEP-COPIES the target when native symlinks are off (the default), planting a real
# dashboard/data dir that then freezes while the overlay keeps growing — the exact
# drift this bridge exists to prevent. Force a *native* symlink (nativestrict makes ln
# fail loudly instead of copying); on a box without symlink privilege, fall back to a
# directory junction (mklink /J — no admin needed). On Linux/macOS the MSYS var is
# ignored and this is a plain `ln -s`.
if MSYS=winsymlinks:nativestrict ln -s "$TARGET" "$LINK" 2>/dev/null; then
  echo "35-link-dashboard-data: linked $LINK -> $TARGET"
elif [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]] && command -v cygpath >/dev/null 2>&1; then
  # Windows without symlink privilege: a junction bridges I/O without admin.
  [[ -e "$LINK" ]] && rm -rf "$LINK"
  if cmd //c mklink /J "$(cygpath -w "$LINK")" "$(cygpath -w "$TARGET")" >/dev/null 2>&1; then
    echo "35-link-dashboard-data: linked via junction $LINK -> $TARGET"
  else
    bail "could not create native symlink or junction for $LINK -> $TARGET"
  fi
else
  bail "ln -s failed for $LINK -> $TARGET"
fi
