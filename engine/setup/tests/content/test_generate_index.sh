#!/usr/bin/env bash
# np-test: generate-index | happy
# Regression for np_generate_index.py (phase 17 port of 60-generate-index.sh) in a
# split (engine + overlay) layout:
#   - the COMMITTED engine INDEX.md must list ENGINE skills ONLY (publishable
#     surface — overlay/personal skills must not leak in; pii-guard depends on this);
#   - a MERGED index (engine + overlay) is written to the overlay for local discovery;
#   - in the legacy single-repo layout (content == engine) only one index is written.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
GEN=(python3 "$SETUP/np_generate_index.py")

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_generate_index: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Windows/Git-bash: mixed form (C:/x) so paths handed to native Windows Python are
# resolvable and survive MSYS env conversion. No-op off Windows (no cygpath).
command -v cygpath >/dev/null 2>&1 && tmp="$(cygpath -m "$tmp")"
export HOME="$tmp/home"; mkdir -p "$HOME"        # hermetic: no real ~/.config/team-dir

# Fake engine repo with one engine skill.
eng="$tmp/engine-repo"
mkdir -p "$eng/skills/np-eng-demo" "$eng/archive"
cat > "$eng/skills/np-eng-demo/SKILL.md" <<'S'
---
name: np-eng-demo
description: An engine skill that belongs in the publishable engine index.
---
# Engine demo
S

# Overlay repo with one personal skill (description carries a personal-looking host).
ov="$tmp/overlay"
mkdir -p "$ov/skills/np-kb-personal-demo"
cat > "$ov/skills/np-kb-personal-demo/SKILL.md" <<'S'
---
name: np-kb-personal-demo
description: A personal skill pointing at example.test that must stay out of the engine index.
---
# Personal demo
S

# --- split layout: NP_CONTENT_DIR points at the overlay --------------------
NP_DIR="$eng" NP_CONTENT_DIR="$ov" "${GEN[@]}" >/dev/null

grep -q 'np-eng-demo' "$eng/INDEX.md" \
  || { echo "FAIL: engine INDEX missing the engine skill"; exit 1; }
if grep -q 'np-kb-personal-demo' "$eng/INDEX.md"; then
  echo "FAIL: engine INDEX leaked the overlay/personal skill"; exit 1
fi
[[ -f "$ov/INDEX.md" ]] || { echo "FAIL: overlay merged INDEX not written"; exit 1; }
grep -q 'np-eng-demo' "$ov/INDEX.md" && grep -q 'np-kb-personal-demo' "$ov/INDEX.md" \
  || { echo "FAIL: overlay INDEX is not the merged (engine+overlay) set"; exit 1; }

# --- legacy single-repo: content == engine, only one index, no overlay write -
rm -f "$eng/INDEX.md" "$ov/INDEX.md"
NP_DIR="$eng" NP_CONTENT_DIR="$eng" "${GEN[@]}" >/dev/null
grep -q 'np-eng-demo' "$eng/INDEX.md" \
  || { echo "FAIL(legacy): engine INDEX missing engine skill"; exit 1; }
[[ ! -f "$ov/INDEX.md" ]] \
  || { echo "FAIL(legacy): overlay INDEX should not be written when content==engine"; exit 1; }

echo "PASS test_generate_index"
