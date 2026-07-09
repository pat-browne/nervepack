#!/usr/bin/env bash
# np-test: episodic-maintain-output | committed-output + content_is_explicit skip +
#          no-empty-commit for 72-run-episodic-maintain.sh.
#
# Complements test_maintain_invocation.sh (which proves the prompt reaches
# `claude -p` over stdin) by proving the DRIVER's committed-output + skip
# CONTRACT against a stubbed agent, using the two-repo sandbox from
# agentjob.sh (engine repo w/ the driver + libs; overlay repo resolved via
# NP_CONTENT_DIR, where episodic-maintain must commit).
#
# Note on the documented `enforce` block (agents/np-flow-episodic-maintain.md
# step 5b): that schema belongs to memory/lessons/<topic>.md (failure/success
# clusters), not memory/episodic/<topic>.md. stub_agent's `episodic-drain`
# mode only ever writes a plain narrative note to memory/episodic/, so no
# drained note here ever warrants an `enforce` block — nothing to assert.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# tests/episodic/ -> repo root is 4 levels up (episodic -> tests -> setup -> engine -> root)
ROOT="$(cd "$HERE/../../../.." && pwd)"
source "$ROOT/engine/setup/tests/_lib/agentjob.sh"

DRIVER_REL="engine/setup/72-run-episodic-maintain.sh"

# Defensive: never let ambient env leak into any section below.
unset CLAUDE_BIN NP_LLM_AGENT_CMD NP_CONTENT_DIR NERVEPACK_AGENT NP_LLM_BACKEND \
      NP_TOGGLES_CONF NP_TOGGLES_LOCAL 2>/dev/null || true

fail=0
_CLEANUP=()
cleanup() {
  local d
  for d in "${_CLEANUP[@]:-}"; do
    [[ -n "$d" ]] && rm -rf "$d"
  done
  [[ -n "${_AGENTJOB_STUB_DIR:-}" ]] && rm -rf "$_AGENTJOB_STUB_DIR"
}
trap cleanup EXIT

fail_msg() { echo "FAIL: $1"; fail=1; }

# HARD guard for every sandbox path this file `cd`s into before a mutating git
# command — an unguarded `cd ""` is a bash 3.2 no-op that silently stays in the
# CALLER's cwd (the real repo), not an error. Every `cd "$X"` on a sandbox path
# below is preceded by require_dir "$X".
require_dir() {  # $1=path $2=label
  [[ -n "$1" && -d "$1" ]] || { echo "FAIL: $2: path is empty or missing ('${1:-}') — refusing to cd into it"; exit 1; }
}

# ---------------------------------------------------------------------------
# 1. content_is_explicit skip: NP_CONTENT_DIR unset AND no
#    ~/.config/nervepack/content-dir (implicit engine-root fallback) -> the
#    job skips its commit and exits 0. No agent invoked, no commit anywhere.
# ---------------------------------------------------------------------------
sandbox1="$(make_agent_sandbox)"
engine1="$(sed -n '1p' <<<"$sandbox1")"
overlay1="$(sed -n '2p' <<<"$sandbox1")"
require_dir "$engine1" "sandbox(1) engine"
require_dir "$overlay1" "sandbox(1) overlay"
_CLEANUP+=("$(dirname "$engine1")")

home1="$(mktemp -d)"; _CLEANUP+=("$home1")
overlay1_before="$(git -C "$overlay1" rev-parse HEAD)"

require_dir "$engine1" "sandbox(1) engine (pre-cd)"
rc=0
( cd "$engine1" && HOME="$home1" bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "content-skip: driver exited $rc (want 0)"

log1="$home1/.cache/nervepack/episodic-maintain.log"
if [[ -f "$log1" ]]; then
  grep -qE 'skipped: content dir is the implicit engine-root fallback' "$log1" \
    || fail_msg "content-skip: log missing skip message: $(cat "$log1")"
else
  fail_msg "content-skip: no log written at $log1"
fi

overlay1_after="$(git -C "$overlay1" rev-parse HEAD)"
[[ "$overlay1_before" == "$overlay1_after" ]] \
  || fail_msg "content-skip: overlay HEAD moved despite the implicit-fallback skip ($overlay1_before -> $overlay1_after)"
assert_no_commit_in "$overlay1" "episodic(" || fail=1
assert_no_commit_in "$engine1" "episodic(" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: content_is_explicit implicit fallback -> skip, exit0, no commit"

# ---------------------------------------------------------------------------
# 2. Committed-output happy path: an explicit overlay + stub_agent
#    episodic-drain -> the resulting episodic commit lands in the OVERLAY
#    (never the engine), with the drained content present.
# ---------------------------------------------------------------------------
sandbox2="$(make_agent_sandbox)"
engine2="$(sed -n '1p' <<<"$sandbox2")"
overlay2="$(sed -n '2p' <<<"$sandbox2")"
require_dir "$engine2" "sandbox(2) engine"
require_dir "$overlay2" "sandbox(2) overlay"
_CLEANUP+=("$(dirname "$engine2")")
[[ -d "$engine2/.git" ]] || fail_msg "sandbox(2): engine repo missing .git"
[[ -d "$overlay2/.git" ]] || fail_msg "sandbox(2): overlay repo missing .git"

stub_agent episodic-drain   # exports CLAUDE_BIN + NP_LLM_BACKEND=claude for the rest of this script

home2="$(mktemp -d)"; _CLEANUP+=("$home2")
# Seed a fake capture-inbox note under HOME, matching the real inbox shape
# (~/.cache/nervepack/episodic-inbox/*.jsonl) that a real agent run would drain.
# The stub itself doesn't read this (it's a fixed cooperative mutation, per
# agentjob.sh's contract) — this just documents the pre-condition the driver
# is invoked under in production.
mkdir -p "$home2/.cache/nervepack/episodic-inbox"
printf '{"ts":"2026-07-01T00:00:00Z","project":"nervepack","cwd":"/tmp","mode":"session-end","headline":"stub session","body":"stub note body.","candidate_topics":["stub-topic"],"keywords":["stub"]}\n' \
  > "$home2/.cache/nervepack/episodic-inbox/note.jsonl"

require_dir "$engine2" "sandbox(2) engine (pre-cd)"
rc=0
( cd "$engine2" && HOME="$home2" NP_CONTENT_DIR="$overlay2" bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "committed-output: driver exited $rc"

assert_commit_in "$overlay2" "memory/episodic/stub-topic.md" "episodic(stub-topic)" || fail=1
assert_no_commit_in "$engine2" "episodic(stub-topic)" || fail=1
grep -q 'drained entry' "$overlay2/memory/episodic/stub-topic.md" 2>/dev/null \
  || fail_msg "committed-output: drained content missing from $overlay2/memory/episodic/stub-topic.md"
[[ "$fail" -eq 0 ]] && echo "PASS: committed-output -> drained note committed path-limited in overlay, not engine"

# ---------------------------------------------------------------------------
# 3. No-empty-commit: the agent finds an empty inbox and drains nothing —
#    makes no mutation and no commit at all. The driver itself never
#    fabricates a commit, so the overlay's HEAD must not move.
# ---------------------------------------------------------------------------
sandbox3="$(make_agent_sandbox)"
engine3="$(sed -n '1p' <<<"$sandbox3")"
overlay3="$(sed -n '2p' <<<"$sandbox3")"
require_dir "$engine3" "sandbox(3) engine"
require_dir "$overlay3" "sandbox(3) overlay"
_CLEANUP+=("$(dirname "$engine3")")
[[ -d "$engine3/.git" ]] || fail_msg "sandbox(3): engine repo missing .git"
[[ -d "$overlay3/.git" ]] || fail_msg "sandbox(3): overlay repo missing .git"

# Seed a second, non-root commit in the overlay before the no-op run. Known
# helper limitation (agentjob.sh, frozen per task contract): assert_no_empty_commit
# runs `git diff-tree` WITHOUT `--root`, which always misjudges a ROOT commit's
# diff as empty regardless of content. Advancing HEAD to a normal (non-root)
# commit first sidesteps that edge case without touching the frozen helper,
# while still faithfully proving "the driver made no commit."
require_dir "$overlay3" "sandbox(3) overlay (pre-seed-cd)"
( cd "$overlay3" && printf 'seed\n' >> README.md && git add -A && git commit -qm 'test: seed non-root HEAD (sandbox only)' )

noop_dir="$(mktemp -d)"; _CLEANUP+=("$noop_dir")
cat > "$noop_dir/claude" <<'STUB'
#!/usr/bin/env bash
# Cooperative-but-honest no-op stub: consumes the prompt, decides the capture
# inbox is empty, and makes NO mutation and NO commit — mirrors the real
# agent's documented no-op behavior (np-flow-episodic-maintain.md step 2:
# "If there are no inbox files, exit silently -- nothing to do, no empty commit.").
cat >/dev/null
STUB
chmod +x "$noop_dir/claude"

home3="$(mktemp -d)"; _CLEANUP+=("$home3")
overlay3_before="$(git -C "$overlay3" rev-parse HEAD)"

require_dir "$engine3" "sandbox(3) engine (pre-cd)"
rc=0
( cd "$engine3" && HOME="$home3" NP_CONTENT_DIR="$overlay3" \
    CLAUDE_BIN="$noop_dir/claude" NP_LLM_BACKEND=claude \
    bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "no-op: driver exited $rc"

overlay3_after="$(git -C "$overlay3" rev-parse HEAD)"
[[ "$overlay3_before" == "$overlay3_after" ]] \
  || fail_msg "no-op: overlay HEAD moved despite the agent draining nothing ($overlay3_before -> $overlay3_after)"
assert_no_empty_commit "$overlay3" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: no-empty-commit -> empty inbox makes no commit"

if [[ "$fail" -eq 0 ]]; then
  echo "PASS test_maintain_output"
else
  echo "FAIL test_maintain_output"
  exit 1
fi
