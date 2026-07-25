#!/usr/bin/env bash
# np-test: generate-index | failure
# STRAY-WRITE GUARD (phase 17): past agents corrupted ~/Code/nervepack and
# ~/Code/nervepack-content by running the index generator against the real repo.
# np_generate_index.generate() MUST write ONLY to the resolved NP_DIR + overlay,
# and MUST NOT fall back to an unconditional $HOME/Code/nervepack default. This
# test plants a sentinel at $HOME/Code/nervepack/INDEX.md and proves a hermetic
# run (NP_DIR + NP_CONTENT_DIR at temp) leaves it byte-for-byte untouched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"

command -v python3 >/dev/null 2>&1 || { echo "SKIP test_index_no_stray_write: no python3"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Windows/Git-bash: mixed form (C:/x) so paths handed to native Windows Python are
# resolvable and survive MSYS env conversion. No-op off Windows (no cygpath).
command -v cygpath >/dev/null 2>&1 && tmp="$(cygpath -m "$tmp")"
export HOME="$tmp/home"; mkdir -p "$HOME"

# Decoy "real repo" at the historical default location. If the generator ever
# defaults NP_DIR to $HOME/Code/nervepack, this sentinel would be overwritten.
decoy="$HOME/Code/nervepack"
mkdir -p "$decoy/skills/np-should-not-appear"
cat > "$decoy/skills/np-should-not-appear/SKILL.md" <<'S'
---
name: np-should-not-appear
description: If this shows up in any index the generator wrote to the wrong repo.
---
S
sentinel="DO-NOT-TOUCH-$(date +%s)"
printf '%s\n' "$sentinel" > "$decoy/INDEX.md"

# Hermetic target: a completely separate engine + overlay.
eng="$tmp/eng"; ov="$tmp/ov"
mkdir -p "$eng/skills/np-eng-x" "$ov/skills/np-ov-y"
printf -- '---\nname: np-eng-x\ndescription: engine x\n---\n' > "$eng/skills/np-eng-x/SKILL.md"
printf -- '---\nname: np-ov-y\ndescription: overlay y\n---\n' > "$ov/skills/np-ov-y/SKILL.md"

NP_DIR="$eng" NP_CONTENT_DIR="$ov" python3 "$SETUP/np_generate_index.py" >/dev/null

# The hermetic targets were written.
grep -q 'np-eng-x' "$eng/INDEX.md" || { echo "FAIL: hermetic engine INDEX not written"; exit 1; }
grep -q 'np-ov-y'  "$ov/INDEX.md"  || { echo "FAIL: hermetic overlay INDEX not written"; exit 1; }

# The decoy real-repo INDEX.md is byte-for-byte untouched.
[[ "$(cat "$decoy/INDEX.md")" == "$sentinel" ]] \
  || { echo "FAIL: STRAY WRITE — the generator overwrote $decoy/INDEX.md"; exit 1; }
grep -rq 'np-should-not-appear' "$eng/INDEX.md" "$ov/INDEX.md" \
  && { echo "FAIL: decoy skill leaked into a hermetic index"; exit 1; }

echo "PASS test_index_no_stray_write"
