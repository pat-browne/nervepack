#!/usr/bin/env bash
# np-test: refine-output | wrapper re-entrancy, stubbed-output, overlay-retarget
#          for 76-run-refine.sh.
#
# Complements test_toggle_gating.sh / test_fail_open.sh / test_backend_preflight.sh
# / test_install_idempotency.sh (which cover the toggle/backend/install seams for
# 76+77) by proving 76-run-refine.sh's COMMITTED-OUTPUT contract against a
# stubbed agent: the re-entrancy bail, a real commit landing in the engine repo
# for an ordinary skill fix, no commit when the agent finds nothing, and — the
# seam unique to 76 among the four agentic-job drivers — that an overlay
# (NP_CONTENT_DIR) resolving makes the driver inject an "Additional skill roots"
# instruction into the agent prompt naming that overlay, and that a cooperative
# agent acting on it commits into the OVERLAY's own history, never the engine's.
#
# Uses the two-repo sandbox from agentjob.sh (engine repo w/ the driver + libs;
# overlay repo resolved via NP_CONTENT_DIR). Sections 3-4 need a BESPOKE inline
# stub (not the shared stub_agent) because the shared stub only ever commits in
# its own CWD — it cannot model 76's ability to `git -C <overlay>` into a
# DIFFERENT repo named in the prompt text. agentjob.sh itself stays unmodified.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# tests/maintain/ -> repo root is 4 levels up (maintain -> tests -> setup -> engine -> root)
ROOT="$(cd "$HERE/../../../.." && pwd)"
source "$ROOT/engine/setup/tests/_lib/agentjob.sh"

DRIVER_REL="engine/setup/76-run-refine.sh"

# Defensive: never let ambient env leak into any section below.
unset CLAUDE_BIN NP_LLM_AGENT_CMD NP_CONTENT_DIR NERVEPACK_AGENT NP_LLM_BACKEND \
      NP_TOGGLES_CONF NP_TOGGLES_LOCAL REFINE_LOG 2>/dev/null || true

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
# 1. Re-entrancy: NERVEPACK_AGENT=1 -> bail exit0, no agent spawned. The guard
#    (76-run-refine.sh line 27) must fire before the LOG var is even set, so no
#    log file should exist afterward.
# ---------------------------------------------------------------------------
sandbox1="$(make_agent_sandbox)"
engine1="$(sed -n '1p' <<<"$sandbox1")"
require_dir "$engine1" "sandbox(1) engine"
_CLEANUP+=("$(dirname "$engine1")")

home1="$(mktemp -d)"; _CLEANUP+=("$home1")
engine1_before="$(git -C "$engine1" rev-parse HEAD)"

require_dir "$engine1" "sandbox(1) engine (pre-cd)"
rc=0
( cd "$engine1" && HOME="$home1" NERVEPACK_AGENT=1 bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "re-entrancy: exit $rc (want 0)"

log1="$home1/.cache/nervepack/refine.log"
[[ -f "$log1" ]] && fail_msg "re-entrancy: log written despite NERVEPACK_AGENT=1 guard: $(cat "$log1")"

engine1_after="$(git -C "$engine1" rev-parse HEAD)"
[[ "$engine1_before" == "$engine1_after" ]] \
  || fail_msg "re-entrancy: engine HEAD moved despite the guard ($engine1_before -> $engine1_after)"
[[ "$fail" -eq 0 ]] && echo "PASS: re-entrancy NERVEPACK_AGENT=1 -> bail exit0, no agent spawned, no log"

# ---------------------------------------------------------------------------
# 2. Stubbed-agent happy path: stub_agent lint-fix against a pre-seeded engine
#    skill -> a real, path-limited, conventionally-prefixed commit lands in the
#    ENGINE repo (76 stays cd'd into its own repo; no overlay involved here),
#    with no LLM-attribution trailer.
# ---------------------------------------------------------------------------
sandbox2="$(make_agent_sandbox)"
engine2="$(sed -n '1p' <<<"$sandbox2")"
require_dir "$engine2" "sandbox(2) engine"
_CLEANUP+=("$(dirname "$engine2")")
[[ -d "$engine2/.git" ]] || fail_msg "sandbox(2): engine repo missing .git"

# Pre-seed the target skill so the stub's lint-fix mode exercises its "append a
# fix to an EXISTING skill" branch, not skill creation from nothing.
mkdir -p "$engine2/skills/np-stub-lintfix"
printf -- '---\nname: np-stub-lintfix\ndescription: stub skill for lint-fix test.\n---\nBody.\n' \
  > "$engine2/skills/np-stub-lintfix/SKILL.md"
( cd "$engine2" && git add skills/np-stub-lintfix/SKILL.md \
    && git commit -qm 'test: seed pre-existing engine skill (sandbox only)' -- skills/np-stub-lintfix/SKILL.md )

stub_agent lint-fix   # exports CLAUDE_BIN + NP_LLM_BACKEND=claude for the rest of this script

home2="$(mktemp -d)"; _CLEANUP+=("$home2")

require_dir "$engine2" "sandbox(2) engine (pre-cd)"
rc=0
( cd "$engine2" && HOME="$home2" bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "happy-path: driver exited $rc"

assert_commit_in "$engine2" "skills/np-stub-lintfix/SKILL.md" "skill(np-stub-lintfix)" || fail=1

# path-limited: the commit's file list is EXACTLY the one skill file, nothing else.
lintfix_sha="$(git -C "$engine2" log --format='%H%x09%s' | grep -F 'skill(np-stub-lintfix)' | head -n1 | cut -f1)"
if [[ -n "$lintfix_sha" ]]; then
  files="$(git -C "$engine2" diff-tree --no-commit-id --name-only -r "$lintfix_sha")"
  [[ "$files" == "skills/np-stub-lintfix/SKILL.md" ]] \
    || fail_msg "happy-path: commit touches more than the one skill file: $files"
  subj="$(git -C "$engine2" log -1 --format=%s "$lintfix_sha")"
  case "$subj" in skill\(*) : ;; *) fail_msg "happy-path: subject lacks conventional 'skill(' prefix: $subj" ;; esac
  body="$(git -C "$engine2" log -1 --format=%B "$lintfix_sha")"
  echo "$body" | grep -qiE 'co-authored-by|generated with' \
    && fail_msg "happy-path: commit carries an LLM-attribution trailer: $body"
else
  fail_msg "happy-path: no skill(np-stub-lintfix) commit found to inspect"
fi
[[ "$fail" -eq 0 ]] && echo "PASS: stubbed happy path -> path-limited, conventional, trailer-free commit in engine"

# ---------------------------------------------------------------------------
# 3. No-empty-commit: the agent finds nothing to fix and makes no mutation and
#    no commit at all. The driver itself never fabricates a commit, so the
#    engine's HEAD must not move.
# ---------------------------------------------------------------------------
sandbox3="$(make_agent_sandbox)"
engine3="$(sed -n '1p' <<<"$sandbox3")"
require_dir "$engine3" "sandbox(3) engine"
_CLEANUP+=("$(dirname "$engine3")")
[[ -d "$engine3/.git" ]] || fail_msg "sandbox(3): engine repo missing .git"

# Seed a second, non-root commit first. Known helper limitation (agentjob.sh,
# frozen per task contract): assert_no_empty_commit runs `git diff-tree` WITHOUT
# `--root`, which always misjudges a ROOT commit's diff as empty regardless of
# content. Advancing HEAD to a normal (non-root) commit sidesteps that edge case
# without touching the frozen helper.
require_dir "$engine3" "sandbox(3) engine (pre-seed-cd)"
( cd "$engine3" && printf 'seed\n' >> README.md \
    && git add README.md && git commit -qm 'test: seed non-root HEAD (sandbox only)' -- README.md )

noop_dir="$(mktemp -d)"; _CLEANUP+=("$noop_dir")
cat > "$noop_dir/claude" <<'STUB'
#!/usr/bin/env bash
# Cooperative-but-honest no-op stub: consumes the prompt, decides there is
# nothing to lint/audit-fix, and makes NO mutation and NO commit — mirrors a
# real refine run against an already-clean repo.
cat >/dev/null
STUB
chmod +x "$noop_dir/claude"

home3="$(mktemp -d)"; _CLEANUP+=("$home3")
engine3_before="$(git -C "$engine3" rev-parse HEAD)"

require_dir "$engine3" "sandbox(3) engine (pre-cd)"
rc=0
( cd "$engine3" && HOME="$home3" CLAUDE_BIN="$noop_dir/claude" NP_LLM_BACKEND=claude \
    bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "no-op: driver exited $rc"

engine3_after="$(git -C "$engine3" rev-parse HEAD)"
[[ "$engine3_before" == "$engine3_after" ]] \
  || fail_msg "no-op: engine HEAD moved despite the agent making no change ($engine3_before -> $engine3_after)"
assert_no_empty_commit "$engine3" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: no-empty-commit -> agent finds nothing, no commit made"

# ---------------------------------------------------------------------------
# 4. Overlay retarget (A+B §4 seam). A BESPOKE inline stub — not stub_agent,
#    which only ever commits in its own CWD — because faithfully modeling 76's
#    real behavior requires reading the overlay path OUT of the prompt text and
#    `git -C <that-path>` committing into it, exactly as agents/np-flow-scheduled-
#    refine.md's own commit instructions (as echoed into the prompt by 76 at
#    ~line 53) tell a real agent to do. The stub also records the raw prompt it
#    received (via $STUB_PROMPT_FILE) so this test can assert the overlay-roots
#    instruction's presence/absence directly, independent of whether the stub
#    acted on it.
# ---------------------------------------------------------------------------
retarget_dir="$(mktemp -d)"; _CLEANUP+=("$retarget_dir")
cat > "$retarget_dir/claude" <<'STUB'
#!/usr/bin/env bash
# Recording + cooperative retarget stub. Records the exact prompt it received,
# then — ONLY if the prompt names an overlay root via the driver's documented
# "... a SEPARATE git repo rooted at `<path>`." phrasing — commits an
# overlay-skill fix into THAT path via `git -C`, mirroring what
# agents/np-flow-scheduled-refine.md instructs a real agent to do for extra
# skill roots. If no such phrasing is present (no overlay configured), it makes
# no overlay commit at all — there is nowhere named to commit into.
set -uo pipefail
prompt="$(cat)"
: "${STUB_PROMPT_FILE:?STUB_PROMPT_FILE not set}"
printf '%s' "$prompt" > "$STUB_PROMPT_FILE"

overlay_path="$(printf '%s' "$prompt" | sed -n 's/.*rooted at `\([^`]*\)`.*/\1/p' | head -n1)"
if [[ -n "$overlay_path" && -d "$overlay_path/.git" ]]; then
  mkdir -p "$overlay_path/skills/np-overlay-target"
  printf -- '---\nname: np-overlay-target\ndescription: overlay skill fixed by refine (stub).\n---\nBody.\nOverlay fix note (stub).\n' \
    > "$overlay_path/skills/np-overlay-target/SKILL.md"
  git -C "$overlay_path" add skills/np-overlay-target/SKILL.md
  git -C "$overlay_path" commit -m "skill(np-overlay-target): overlay fix (stub)" \
    -- skills/np-overlay-target/SKILL.md
fi
STUB
chmod +x "$retarget_dir/claude"

# --- 4a. WITH an overlay configured: instruction PRESENT, overlay gets the commit ---
sandbox4="$(make_agent_sandbox)"
engine4="$(sed -n '1p' <<<"$sandbox4")"
overlay4="$(sed -n '2p' <<<"$sandbox4")"
require_dir "$engine4" "sandbox(4a) engine"
require_dir "$overlay4" "sandbox(4a) overlay"
_CLEANUP+=("$(dirname "$engine4")")
[[ -d "$engine4/.git" ]] || fail_msg "sandbox(4a): engine repo missing .git"
[[ -d "$overlay4/.git" ]] || fail_msg "sandbox(4a): overlay repo missing .git"

# Give the overlay a skills/ dir — 76's EXTRA_ROOTS filter requires -d "$root/skills".
mkdir -p "$overlay4/skills/np-overlay-existing"
printf -- '---\nname: np-overlay-existing\ndescription: pre-existing overlay skill.\n---\nBody.\n' \
  > "$overlay4/skills/np-overlay-existing/SKILL.md"
require_dir "$overlay4" "sandbox(4a) overlay (pre-seed-cd)"
( cd "$overlay4" && git add skills/np-overlay-existing/SKILL.md \
    && git commit -qm 'test: seed overlay skills dir (sandbox only)' -- skills/np-overlay-existing/SKILL.md )

home4a="$(mktemp -d)"; _CLEANUP+=("$home4a")
prompt4a="$(mktemp)"; _CLEANUP+=("$prompt4a")

require_dir "$engine4" "sandbox(4a) engine (pre-cd)"
rc=0
( cd "$engine4" && HOME="$home4a" NP_CONTENT_DIR="$overlay4" \
    CLAUDE_BIN="$retarget_dir/claude" NP_LLM_BACKEND=claude STUB_PROMPT_FILE="$prompt4a" \
    bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "overlay-retarget(with-overlay): driver exited $rc"

[[ -s "$prompt4a" ]] || fail_msg "overlay-retarget(with-overlay): stub recorded no prompt"
grep -qF -- "Additional skill roots" "$prompt4a" \
  || fail_msg "overlay-retarget(with-overlay): prompt missing the overlay-roots instruction: $(cat "$prompt4a" 2>/dev/null | tail -5)"
grep -qF -- "$overlay4" "$prompt4a" \
  || fail_msg "overlay-retarget(with-overlay): prompt does not name the overlay path $overlay4"

assert_commit_in "$overlay4" "skills/np-overlay-target/SKILL.md" "skill(np-overlay-target)" || fail=1
assert_no_commit_in "$engine4" "skill(np-overlay-target)" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: overlay-retarget(with-overlay) -> instruction present, fix committed into overlay only"

# --- 4b. WITH NO overlay configured: instruction ABSENT ---
sandbox5="$(make_agent_sandbox)"
engine5="$(sed -n '1p' <<<"$sandbox5")"
require_dir "$engine5" "sandbox(4b) engine"
_CLEANUP+=("$(dirname "$engine5")")
[[ -d "$engine5/.git" ]] || fail_msg "sandbox(4b): engine repo missing .git"

home4b="$(mktemp -d)"; _CLEANUP+=("$home4b")
prompt4b="$(mktemp)"; _CLEANUP+=("$prompt4b")

require_dir "$engine5" "sandbox(4b) engine (pre-cd)"
rc=0
( cd "$engine5" && HOME="$home4b" \
    CLAUDE_BIN="$retarget_dir/claude" NP_LLM_BACKEND=claude STUB_PROMPT_FILE="$prompt4b" \
    bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "overlay-retarget(no-overlay): driver exited $rc"

[[ -s "$prompt4b" ]] || fail_msg "overlay-retarget(no-overlay): stub recorded no prompt"
grep -qF -- "Additional skill roots" "$prompt4b" \
  && fail_msg "overlay-retarget(no-overlay): prompt UNEXPECTEDLY contains the overlay-roots instruction: $(cat "$prompt4b" 2>/dev/null | tail -5)"

assert_no_commit_in "$engine5" "skill(np-overlay-target)" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: overlay-retarget(no-overlay) -> instruction absent, no overlay commit fabricated"

if [[ "$fail" -eq 0 ]]; then
  echo "PASS test_refine_output"
else
  echo "FAIL test_refine_output"
  exit 1
fi
