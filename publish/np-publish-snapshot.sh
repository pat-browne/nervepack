#!/usr/bin/env bash
# Export a clean, history-free snapshot of the engine tree and verify it carries no
# secrets/PII before publication. This is the repeatable pre-publish GATE. It does NOT
# push — creating/updating the public repo is a deliberate, irreversible manual step
# (see publish/PUBLISH.md). Pairs with np-publish-scan.py (the rules) and the pii-guard
# CI job (the per-push enforcement); this is the snapshot-the-whole-tree story.
#
# Why a snapshot and not just scanning the working tree: publishing from a fresh export
# of one ref guarantees the public artifact has zero git history (no old commits that
# may predate the genericization) and zero uncommitted local noise.
#
# Usage: np-publish-snapshot.sh [git-ref] [out-dir]
#   git-ref   ref to export. Default HEAD (the committed tree, not the dirty worktree).
#   out-dir   keep the clean export here for the operator to push. Default: a temp dir
#             that is scanned and then removed (gate-only run).
#   NP_PUBLISH_REPO  override the repo root (default: the engine repo this script is in).
#
# Exit 0 = snapshot clean (safe to publish); 1 = scan blocked (do NOT publish); 2 = setup error.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${NP_PUBLISH_REPO:-$(cd "$HERE/.." && pwd)}"
REF="${1:-HEAD}"
OUT="${2:-}"
SCAN="$HERE/np-publish-scan.py"

command -v git >/dev/null 2>&1 || { echo "publish-snapshot: git not found" >&2; exit 2; }
[[ -e "$REPO/.git" ]] || { echo "publish-snapshot: not a git repo: $REPO" >&2; exit 2; }
git -C "$REPO" rev-parse --verify -q "$REF^{commit}" >/dev/null || { echo "publish-snapshot: bad ref: $REF" >&2; exit 2; }
[[ -f "$SCAN" ]] || { echo "publish-snapshot: scanner missing at $SCAN" >&2; exit 2; }

keep=1
if [[ -z "$OUT" ]]; then
  OUT="$(mktemp -d)"; keep=0
  trap 'rm -rf "$OUT"' EXIT
else
  mkdir -p "$OUT" || { echo "publish-snapshot: cannot create out-dir $OUT" >&2; exit 2; }
  [[ -z "$(ls -A "$OUT" 2>/dev/null)" ]] || { echo "publish-snapshot: out-dir not empty: $OUT" >&2; exit 2; }
fi

# History-free export of the committed tree at REF (no .git, no reflog, no old commits).
if ! git -C "$REPO" archive --format=tar "$REF" | tar -x -C "$OUT"; then
  echo "publish-snapshot: git archive failed for $REF" >&2; exit 2
fi

echo "publish-snapshot: exported '$REF' from $REPO (history-free) -> scanning $OUT"
if python3 "$SCAN" "$OUT"; then
  echo "publish-snapshot: CLEAN — '$REF' is safe to publish as a fresh snapshot."
  [[ "$keep" == 1 ]] && echo "publish-snapshot: clean tree kept at $OUT (push it per publish/PUBLISH.md)."
  exit 0
else
  echo "publish-snapshot: BLOCKED — the snapshot carries secrets/PII; do NOT publish." >&2
  exit 1
fi
