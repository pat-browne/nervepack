#!/usr/bin/env bash
# Regression test for np-merge-wait.sh — the concurrency merge-gate waiter.
# Covers: quiescence-then-CLEAN, conflict→ISSUES, AI-trailer→ISSUES, never-quiet→TIMEOUT.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."                       # engine/setup
W="$S/np-merge-wait.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Build a base git repo with a feature branch. Args: dir, mode(clean|conflict|trailer)
build_repo() {
  local d="$1" mode="$2"
  git init -q -b main "$d"
  git -C "$d" config user.email t@t && git -C "$d" config user.name t
  printf 'x=a\n' > "$d/f"; git -C "$d" add f; git -C "$d" commit -qm base
  git -C "$d" checkout -q -b feature
  case "$mode" in
    clean)
      printf 'new\n' > "$d/g"; git -C "$d" add g; git -C "$d" commit -qm "add g" ;;
    conflict)
      printf 'x=b\n' > "$d/f"; git -C "$d" add f; git -C "$d" commit -qm "feature edit"
      git -C "$d" checkout -q main
      printf 'x=c\n' > "$d/f"; git -C "$d" add f; git -C "$d" commit -qm "base edit" ;;
    trailer)
      printf 'new\n' > "$d/g"; git -C "$d" add g
      git -C "$d" commit -qm "add g

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" ;;
  esac
}

# --- Test 1: stable repo, cleanly mergeable -> exit 0, RESULT: CLEAN ---
build_repo "$tmp/r1" clean
out="$(bash "$W" --repo "$tmp/r1" --base main --branch feature --interval 0 --settle 2 --timeout 5)"; rc=$?
[[ $rc -eq 0 ]] || { echo "FAIL t1: expected rc 0, got $rc"; exit 1; }
grep -q 'RESULT: CLEAN' <<<"$out" || { echo "FAIL t1: no CLEAN result: $out"; exit 1; }

# --- Test 2: stable repo, merge conflict -> exit 2, RESULT: ISSUES (conflict) ---
build_repo "$tmp/r2" conflict
set +e
out="$(bash "$W" --repo "$tmp/r2" --base main --branch feature --interval 0 --settle 2 --timeout 5)"; rc=$?
set -e
[[ $rc -eq 2 ]] || { echo "FAIL t2: expected rc 2, got $rc"; exit 1; }
grep -q 'RESULT: ISSUES' <<<"$out" || { echo "FAIL t2: no ISSUES result: $out"; exit 1; }
grep -qi 'conflict' <<<"$out" || { echo "FAIL t2: conflict not named: $out"; exit 1; }

# --- Test 3: clean merge but AI-attribution trailer present -> exit 2, names trailer ---
build_repo "$tmp/r3" trailer
set +e
out="$(bash "$W" --repo "$tmp/r3" --base main --branch feature --interval 0 --settle 2 --timeout 5)"; rc=$?
set -e
[[ $rc -eq 2 ]] || { echo "FAIL t3: expected rc 2, got $rc"; exit 1; }
grep -qi 'trailer' <<<"$out" || { echo "FAIL t3: trailer not named: $out"; exit 1; }

# --- Test 4: repo state never settles -> exit 3, RESULT: TIMEOUT ---
build_repo "$tmp/r4" clean
export STATE_CTR="$tmp/ctr"
cat > "$tmp/state.sh" <<'EOF'
#!/usr/bin/env bash
n=$(( $(cat "$STATE_CTR" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE_CTR"; echo "$n"
EOF
set +e
out="$(NP_MERGEWAIT_STATE_CMD="bash $tmp/state.sh" bash "$W" --repo "$tmp/r4" --base main --branch feature --interval 1 --backoff 0 --settle 2 --timeout 1)"; rc=$?
set -e
[[ $rc -eq 3 ]] || { echo "FAIL t4: expected rc 3 (timeout), got $rc"; exit 1; }
grep -q 'RESULT: TIMEOUT' <<<"$out" || { echo "FAIL t4: no TIMEOUT result: $out"; exit 1; }

echo "PASS test_merge_wait"
