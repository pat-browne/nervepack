#!/usr/bin/env bash
# np-test: resume|writer
# Exercises np-resume-write.sh: base field correctness (session/cwd/git/last-user/
# sdd ledger+plan), git_dirty flipping, --throttle vs always-write, toggle-off, and
# non-git cwd. Hermetic: builds its own tmp git repo + toggles files, never touches
# the real $HOME/.cache/nervepack or ~/.config/nervepack.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"   # tests/resume -> setup -> engine -> repo root
SCRIPT="$NP/engine/setup/np-resume-write.sh"

fail() { echo "FAIL: $*"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- sandbox git repo with a committed baseline + an sdd ledger ---
REPO="$tmp/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo "hello" > "$REPO/README.md"
mkdir -p "$REPO/.superpowers/sdd"
cat > "$REPO/.superpowers/sdd/progress.md" <<'EOF'
# Progress

Plan: some/path.md

Status: in progress
EOF
git -C "$REPO" add README.md .superpowers/sdd/progress.md
git -C "$REPO" commit -q -m "baseline"

# --- stub transcript ending in a genuine typed user line (Task 1's extractor) ---
TRANSCRIPT="$tmp/transcript.jsonl"
cat > "$TRANSCRIPT" <<'EOF'
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}
{"type":"user","promptSource":"typed","message":{"role":"user","content":"resume the widget refactor"}}
EOF

# --- hermetic toggle isolation: neither file exists -> resume falls open (on) ---
export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"
export NP_TOGGLES_LOCAL="$tmp/toggles-local-none"
export NP_RESUME_POINTER="$tmp/pointer.json"
export NP_RESUME_STAMP="$tmp/last-write"
export NP_RESUME_LOG="$tmp/resume.log"

SID="test-session-123"

# === RUN 1: no --throttle -> writes ===
bash "$SCRIPT" --session "$SID" --transcript "$TRANSCRIPT" --cwd "$REPO"
[[ -f "$NP_RESUME_POINTER" ]] || fail "pointer not written on first run"

head="$(git -C "$REPO" rev-parse --short HEAD)"
branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
# git resolves symlinks in --show-toplevel (e.g. macOS /tmp -> /private/tmp), so
# compute the ledger path the same way the script does rather than assuming it
# equals the literal $REPO we passed as --cwd.
repo_root="$(git -C "$REPO" rev-parse --show-toplevel)"

jq -e --arg v "$SID" '.session_id == $v' "$NP_RESUME_POINTER" >/dev/null || fail "session_id mismatch"
jq -e --arg v "$REPO" '.cwd == $v' "$NP_RESUME_POINTER" >/dev/null || fail "cwd mismatch"
jq -e --arg v "$branch" '.git_branch == $v' "$NP_RESUME_POINTER" >/dev/null || fail "git_branch mismatch"
jq -e --arg v "$head" '.git_head == $v' "$NP_RESUME_POINTER" >/dev/null || fail "git_head mismatch"
jq -e '.git_dirty == false' "$NP_RESUME_POINTER" >/dev/null || fail "git_dirty should be false on clean tree"
jq -e --arg v "$TRANSCRIPT" '.transcript_path == $v' "$NP_RESUME_POINTER" >/dev/null || fail "transcript_path mismatch"
jq -e '.last_user_instruction == "resume the widget refactor"' "$NP_RESUME_POINTER" >/dev/null || fail "last_user_instruction mismatch"
jq -e --arg v "$repo_root/.superpowers/sdd/progress.md" '.sdd_ledger == $v' "$NP_RESUME_POINTER" >/dev/null || fail "sdd_ledger mismatch"
jq -e '.sdd_plan == "some/path.md"' "$NP_RESUME_POINTER" >/dev/null || fail "sdd_plan mismatch"
jq -e '.schema_version == 1' "$NP_RESUME_POINTER" >/dev/null || fail "schema_version mismatch"
jq -e '.ts | type == "number"' "$NP_RESUME_POINTER" >/dev/null || fail "ts missing/not a number"

echo "PASS: base fields"

# === RUN 2: dirty working tree -> git_dirty flips true ===
echo "uncommitted" > "$REPO/scratch.txt"
bash "$SCRIPT" --session "$SID" --transcript "$TRANSCRIPT" --cwd "$REPO"
jq -e '.git_dirty == true' "$NP_RESUME_POINTER" >/dev/null || fail "git_dirty should be true with an untracked file present"
rm -f "$REPO/scratch.txt"

echo "PASS: git_dirty"

# === RUN 3: throttle with a fresh stamp -> pointer NOT updated ===
date +%s > "$NP_RESUME_STAMP"
NEW_SID="should-not-appear"
bash "$SCRIPT" --session "$NEW_SID" --transcript "$TRANSCRIPT" --cwd "$REPO" --throttle
jq -e --arg v "$SID" '.session_id == $v' "$NP_RESUME_POINTER" >/dev/null || fail "throttle: pointer was updated within the interval"

echo "PASS: throttle blocks within-interval write"

# === RUN 4: without --throttle -> always writes, ignoring the stamp ===
bash "$SCRIPT" --session "$NEW_SID" --transcript "$TRANSCRIPT" --cwd "$REPO"
jq -e --arg v "$NEW_SID" '.session_id == $v' "$NP_RESUME_POINTER" >/dev/null || fail "non-throttled call should always write"

echo "PASS: non-throttled call always writes"

# === RUN 5: toggle off -> no write ===
rm -f "$NP_RESUME_POINTER"
export NP_TOGGLES_CONF="$tmp/toggles-off.conf"
printf 'resume|shared|runtime|off|\n' > "$NP_TOGGLES_CONF"
bash "$SCRIPT" --session "off-test" --transcript "$TRANSCRIPT" --cwd "$REPO"
[[ -f "$NP_RESUME_POINTER" ]] && fail "wrote pointer while resume toggle is off"
export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"

echo "PASS: toggle off suppresses write"

# === RUN 6: non-git cwd -> git fields empty, dirty false, still writes ===
NONGIT="$tmp/nongit"
mkdir -p "$NONGIT"
rm -f "$NP_RESUME_POINTER"
bash "$SCRIPT" --session "nongit-test" --transcript "$TRANSCRIPT" --cwd "$NONGIT"
[[ -f "$NP_RESUME_POINTER" ]] || fail "non-git cwd: pointer not written"
jq -e '.git_branch == "" and .git_head == "" and .git_dirty == false' "$NP_RESUME_POINTER" >/dev/null || fail "non-git cwd: git fields not empty/false"
jq -e '.sdd_ledger == "" and .sdd_plan == ""' "$NP_RESUME_POINTER" >/dev/null || fail "non-git cwd: sdd fields not empty"

echo "PASS: non-git cwd"

echo "PASS test_resume_write"
