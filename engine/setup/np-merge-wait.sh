#!/usr/bin/env bash
# np-merge-wait.sh — the nervepack concurrency merge-gate waiter.
#
# When another agent/session/cron is operating on this repo, wait for it to go
# QUIET (repo refs + HEAD + working tree stable across a full poll interval),
# then report whether <branch> is merge-ready against <base>:
#
#   exit 0  CLEAN    — quiet + merges cleanly + no policy issues  → proceed (option 1)
#   exit 2  ISSUES   — quiet but conflicts and/or forbidden AI-attribution trailers
#                      were found                                  → notify user (option 2)
#   exit 3  TIMEOUT  — repo never settled within --timeout         → notify user
#   exit 1  usage/error
#
# Poll cadence: start at --interval seconds, add --backoff each cycle, give up
# after --timeout total. "Quiet" = --settle consecutive identical state samples.
#
# Pairs with the np-flow-merge-gate skill. Read-only: it never commits, merges,
# pushes, or mutates the repo — it only observes and reports.
set -uo pipefail

repo="$PWD" branch="" base="origin/main"
interval=60 backoff=30 timeout=1800 settle=2

die() { echo "np-merge-wait: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)     repo="$2"; shift 2;;
    --branch)   branch="$2"; shift 2;;
    --base)     base="$2"; shift 2;;
    --interval) interval="$2"; shift 2;;
    --backoff)  backoff="$2"; shift 2;;
    --timeout)  timeout="$2"; shift 2;;
    --settle)   settle="$2"; shift 2;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || die "not a git repo: $repo"
[[ -n "$branch" ]] || branch="$(git -C "$repo" symbolic-ref --quiet --short HEAD || true)"
[[ -n "$branch" ]] || die "could not determine --branch (detached HEAD?)"

# One state sample. Overridable for tests via NP_MERGEWAIT_STATE_CMD (a command
# whose stdout is the snapshot — same role CLAUDE_BIN plays for the model seam).
sample_state() {
  if [[ -n "${NP_MERGEWAIT_STATE_CMD:-}" ]]; then
    eval "$NP_MERGEWAIT_STATE_CMD"
  else
    { git -C "$repo" show-ref 2>/dev/null
      git -C "$repo" symbolic-ref --quiet HEAD 2>/dev/null
      git -C "$repo" status --porcelain 2>/dev/null; } | cksum
  fi
}

echo "np-merge-wait: watching $repo (branch '$branch' vs '$base') for quiescence…"
elapsed=0 iv="$interval" prev="" stable=0
while :; do
  s="$(sample_state)"
  if [[ "$s" == "$prev" ]]; then stable=$((stable + 1)); else stable=1; fi
  prev="$s"
  if (( stable >= settle )); then
    echo "np-merge-wait: repo quiet (${stable} stable samples)."
    break
  fi
  if (( elapsed >= timeout )); then
    echo "np-merge-wait: still active after ${elapsed}s (timeout ${timeout}s)."
    echo "RESULT: TIMEOUT"
    exit 3
  fi
  sleep "$iv"
  elapsed=$(( elapsed + iv ))
  iv=$(( iv + backoff ))
done

# --- Merge-readiness check (quiet → now evaluate the diff) ---
issues=()

# 1) Conflict check via merge-tree (git ≥2.38 --write-tree exits nonzero on conflict).
if ! git -C "$repo" merge-tree --write-tree "$base" "$branch" >/dev/null 2>&1; then
  issues+=("merge conflicts vs $base")
fi

# 2) Forbidden AI-attribution trailers in the branch range (coding-rules §6).
trailers=0
if git -C "$repo" rev-parse --verify --quiet "$base" >/dev/null 2>&1; then
  trailers="$(git -C "$repo" log "$base..$branch" --format='%B' 2>/dev/null \
                | grep -ciE 'Co-Authored-By: Claude|Generated with .*Claude' || true)"
fi
(( trailers > 0 )) && issues+=("$trailers commit(s) carry a forbidden AI-attribution trailer")

if (( ${#issues[@]} == 0 )); then
  echo "np-merge-wait: '$branch' merges cleanly into '$base'; no policy issues."
  echo "RESULT: CLEAN"
  exit 0
fi

echo "np-merge-wait: '$branch' is NOT ready to merge into '$base':"
for i in "${issues[@]}"; do echo "  - $i"; done
echo "RESULT: ISSUES (${#issues[@]})"
exit 2
