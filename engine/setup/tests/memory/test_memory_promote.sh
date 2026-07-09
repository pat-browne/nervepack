#!/usr/bin/env bash
# np-test: memory-promote-wrapper | gating, content-skip, backend-preflight,
#          re-entrancy, stubbed-agent commit routing for 71-run-memory-promote.sh.
#
# Sections 1-4 run the REAL driver directly (no sandbox needed — each bails
# before touching git), sandboxing only HOME (+ toggles) so the driver's own
# ~/.cache/nervepack/memory-promote.log write never touches the real machine.
# Sections 5-6 need the full two-repo sandbox (agentjob.sh) because they drive
# the driver all the way to invoking the (stubbed) agent and inspect where the
# resulting commit landed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# tests/memory/ -> repo root is 4 levels up (memory -> tests -> setup -> engine -> root)
ROOT="$(cd "$HERE/../../../.." && pwd)"
source "$ROOT/engine/setup/tests/_lib/agentjob.sh"

DRIVER="$ROOT/engine/setup/71-run-memory-promote.sh"

# Defensive: never let ambient env leak into any of the below (each section sets
# only what it needs via inline VAR=val prefixes, never `export`, so this is
# belt-and-suspenders against a polluted parent shell).
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
# command. Non-negotiable (exits immediately, does not just record a failure):
# bash treats `cd ""` as a no-op that silently stays in the CALLER's cwd rather
# than erroring (verified on bash 3.2/macOS) — so a blank/invalid sandbox
# variable ahead of a `cd ... && git add -A && git commit` would silently
# operate on the REAL repo instead of a throwaway tmp dir. Every `cd "$X"`
# below where X is a sandbox path is preceded by require_dir "$X".
require_dir() {  # $1=path $2=label
  [[ -n "$1" && -d "$1" ]] || { echo "FAIL: $2: path is empty or missing ('${1:-}') — refusing to cd into it"; exit 1; }
}

# ---------------------------------------------------------------------------
# 1. Gating: memory.promote toggle off -> skip + exit 0; on -> proceeds past
#    the toggle gate (it may still bail later for content-dir/backend reasons
#    — that's fine, this section only checks the TOGGLE guard specifically).
# ---------------------------------------------------------------------------
t1="$(mktemp -d)"; _CLEANUP+=("$t1")
home1="$t1/home"; mkdir -p "$home1"
conf1="$t1/toggles.conf"; local1="$t1/local"
: > "$conf1"

printf 'memory.promote=off\n' > "$local1"
rc=0
out_off="$(HOME="$home1" NP_TOGGLES_CONF="$conf1" NP_TOGGLES_LOCAL="$local1" bash "$DRIVER" 2>&1)" || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "gating(off): exit $rc (want 0)"
echo "$out_off" | grep -qE 'skipped: memory\.promote disabled' \
  || fail_msg "gating(off): no skip message: $out_off"
[[ "$fail" -eq 0 ]] && echo "PASS: gating off -> skip + exit0"

printf 'memory.promote=on\n' > "$local1"
out_on="$(HOME="$home1" NP_TOGGLES_CONF="$conf1" NP_TOGGLES_LOCAL="$local1" bash "$DRIVER" 2>&1 || true)"
echo "$out_on" | grep -qE 'skipped: memory\.promote disabled' \
  && fail_msg "gating(on): guard skipped while toggle is on: $out_on"
[[ "$fail" -eq 0 ]] && echo "PASS: gating on -> proceeds past toggle gate"

# ---------------------------------------------------------------------------
# 2. content_is_explicit skip: NP_CONTENT_DIR unset AND no
#    ~/.config/nervepack/content-dir (implicit engine-root fallback) -> the
#    job skips its commit and exits 0 (no agent invoked, log records why).
# ---------------------------------------------------------------------------
t2="$(mktemp -d)"; _CLEANUP+=("$t2")
home2="$t2/home"; mkdir -p "$home2"
conf2="$t2/toggles.conf"; local2="$t2/local"
: > "$conf2"; printf 'memory.promote=on\n' > "$local2"

rc=0
HOME="$home2" NP_TOGGLES_CONF="$conf2" NP_TOGGLES_LOCAL="$local2" \
  bash "$DRIVER" >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "content-skip: exit $rc (want 0)"
log2="$home2/.cache/nervepack/memory-promote.log"
if [[ -f "$log2" ]]; then
  grep -qE 'skipped: content dir is the implicit engine-root fallback' "$log2" \
    || fail_msg "content-skip: log missing skip message: $(cat "$log2")"
else
  fail_msg "content-skip: no log written at $log2"
fi
[[ "$fail" -eq 0 ]] && echo "PASS: content_is_explicit implicit fallback -> skip, exit0, no commit"

# ---------------------------------------------------------------------------
# 3. Backend pre-flight: claude backend w/ no claude binary -> bail exit0;
#    local backend w/ no NP_LLM_AGENT_CMD -> bail exit0. Content dir is made
#    EXPLICIT here (a real, empty tmp dir) so we get PAST the content-skip
#    from section 2 and actually reach the backend check.
# ---------------------------------------------------------------------------
t3="$(mktemp -d)"; _CLEANUP+=("$t3")
home3="$t3/home"; mkdir -p "$home3"
content3="$t3/content"; mkdir -p "$content3"
conf3="$t3/toggles.conf"; local3="$t3/local"
: > "$conf3"; printf 'memory.promote=on\n' > "$local3"

rc=0
HOME="$home3" NP_TOGGLES_CONF="$conf3" NP_TOGGLES_LOCAL="$local3" NP_CONTENT_DIR="$content3" \
  NP_LLM_BACKEND=claude bash "$DRIVER" >/dev/null 2>&1 || rc=$?
log3="$home3/.cache/nervepack/memory-promote.log"
[[ "$rc" -eq 0 ]] || fail_msg "backend-preflight(claude/no-bin): exit $rc (want 0)"
[[ -f "$log3" ]] && grep -qi 'claude CLI not found' "$log3" \
  || fail_msg "backend-preflight(claude/no-bin): log missing message: $(cat "$log3" 2>/dev/null)"
[[ "$fail" -eq 0 ]] && echo "PASS: backend preflight claude/no-bin -> bail exit0"

rm -f "$log3"
rc=0
HOME="$home3" NP_TOGGLES_CONF="$conf3" NP_TOGGLES_LOCAL="$local3" NP_CONTENT_DIR="$content3" \
  NP_LLM_BACKEND=local bash "$DRIVER" >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "backend-preflight(local/no-cmd): exit $rc (want 0)"
[[ -f "$log3" ]] && grep -qi 'NP_LLM_AGENT_CMD' "$log3" \
  || fail_msg "backend-preflight(local/no-cmd): log missing message: $(cat "$log3" 2>/dev/null)"
[[ "$fail" -eq 0 ]] && echo "PASS: backend preflight local/no-cmd -> bail exit0"

# ---------------------------------------------------------------------------
# 4. Re-entrancy: NERVEPACK_AGENT=1 -> bail exit0, no agent spawned. The guard
#    must fire before ANY other work, so no log file should even be created.
# ---------------------------------------------------------------------------
t4="$(mktemp -d)"; _CLEANUP+=("$t4")
home4="$t4/home"; mkdir -p "$home4"
conf4="$t4/toggles.conf"; local4="$t4/local"
: > "$conf4"; printf 'memory.promote=on\n' > "$local4"

rc=0
HOME="$home4" NP_TOGGLES_CONF="$conf4" NP_TOGGLES_LOCAL="$local4" NERVEPACK_AGENT=1 \
  bash "$DRIVER" >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "re-entrancy: exit $rc (want 0)"
log4="$home4/.cache/nervepack/memory-promote.log"
[[ -f "$log4" ]] && fail_msg "re-entrancy: log written despite NERVEPACK_AGENT=1 guard: $(cat "$log4")"
[[ "$fail" -eq 0 ]] && echo "PASS: re-entrancy NERVEPACK_AGENT=1 -> bail exit0, no agent spawned"

# ---------------------------------------------------------------------------
# 5. Stubbed-agent happy path: explicit overlay + stub_agent promote ->
#    the resulting skill commit lands in the OVERLAY, never the engine.
# ---------------------------------------------------------------------------
sandbox5="$(make_agent_sandbox)"
engine5="$(sed -n '1p' <<<"$sandbox5")"
overlay5="$(sed -n '2p' <<<"$sandbox5")"
require_dir "$engine5" "sandbox(5) engine"
require_dir "$overlay5" "sandbox(5) overlay"
_CLEANUP+=("$(dirname "$engine5")")
[[ -d "$engine5/.git" ]] || fail_msg "sandbox(5): engine repo missing .git"
[[ -d "$overlay5/.git" ]] || fail_msg "sandbox(5): overlay repo missing .git"

stub_agent promote   # exports CLAUDE_BIN + NP_LLM_BACKEND=claude for the rest of this script

t5home="$(mktemp -d)"; _CLEANUP+=("$t5home")

require_dir "$engine5" "sandbox(5) engine (pre-cd)"
rc=0
( cd "$engine5" && HOME="$t5home" NP_CONTENT_DIR="$overlay5" \
    bash engine/setup/71-run-memory-promote.sh ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "happy-path: driver exited $rc"

assert_commit_in "$overlay5" "skills/" "skill(" || fail=1
assert_no_commit_in "$engine5" "skill(" || fail=1

# ---------------------------------------------------------------------------
# 6. No-empty-commit: the agent finds nothing new to promote and makes no
#    commit at all — the driver itself never fabricates a commit (it never
#    calls `git commit`; the agent owns that), so the overlay's HEAD must
#    stay the real, non-empty init commit.
# ---------------------------------------------------------------------------
sandbox6="$(make_agent_sandbox)"
engine6="$(sed -n '1p' <<<"$sandbox6")"
overlay6="$(sed -n '2p' <<<"$sandbox6")"
require_dir "$engine6" "sandbox(6) engine"
require_dir "$overlay6" "sandbox(6) overlay"
_CLEANUP+=("$(dirname "$engine6")")
[[ -d "$engine6/.git" ]] || fail_msg "sandbox(6): engine repo missing .git"
[[ -d "$overlay6/.git" ]] || fail_msg "sandbox(6): overlay repo missing .git"

# Seed a second, non-root commit in the overlay before the no-op run. Helper
# limitation (agentjob.sh, not modified here per contract): assert_no_empty_commit
# runs `git diff-tree` WITHOUT `--root`, which always reports a root commit's
# diff as empty regardless of content — it would misreport make_agent_sandbox's
# own init commit as "empty" even though it touches README.md. Advancing HEAD to
# a normal (non-root) commit first sidesteps that edge case without touching the
# frozen helper, while still faithfully proving "the driver made no commit."
require_dir "$overlay6" "sandbox(6) overlay (pre-seed-cd)"
( cd "$overlay6" && printf 'seed\n' >> README.md && git add -A && git commit -qm 'test: seed non-root HEAD (sandbox only)' )

noop_dir="$(mktemp -d)"; _CLEANUP+=("$noop_dir")
cat > "$noop_dir/claude" <<'STUB'
#!/usr/bin/env bash
# Cooperative-but-honest no-op stub: consumes the prompt, decides there is
# nothing worth promoting, and makes NO mutation and NO commit — mirrors a
# real agent run against an empty memory store.
cat >/dev/null
STUB
chmod +x "$noop_dir/claude"

t6home="$(mktemp -d)"; _CLEANUP+=("$t6home")
overlay6_before="$(git -C "$overlay6" rev-parse HEAD)"

require_dir "$engine6" "sandbox(6) engine (pre-cd)"
rc=0
( cd "$engine6" && HOME="$t6home" NP_CONTENT_DIR="$overlay6" \
    CLAUDE_BIN="$noop_dir/claude" NP_LLM_BACKEND=claude \
    bash engine/setup/71-run-memory-promote.sh ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "no-op: driver exited $rc"

overlay6_after="$(git -C "$overlay6" rev-parse HEAD)"
[[ "$overlay6_before" == "$overlay6_after" ]] \
  || fail_msg "no-op: overlay HEAD moved despite the agent making no change ($overlay6_before -> $overlay6_after)"
assert_no_empty_commit "$overlay6" || fail=1

if [[ "$fail" -eq 0 ]]; then
  echo "PASS test_memory_promote"
else
  echo "FAIL test_memory_promote"
  exit 1
fi
