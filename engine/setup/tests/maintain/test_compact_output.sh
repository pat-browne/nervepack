#!/usr/bin/env bash
# np-test: compact-output | wrapper re-entrancy, TWO-COMMIT contract, no-empty-commit,
#          and overlay-retarget for 77-run-compact.sh.
#
# Complements test_toggle_gating.sh / test_fail_open.sh / test_backend_preflight.sh
# / test_install_idempotency.sh (which cover the toggle/backend/install seams shared
# by 76+77) by proving 77-run-compact.sh's COMMITTED-OUTPUT contract against a
# stubbed agent: the re-entrancy bail, the driver's distinctive TWO-COMMIT shape
# (Commit A = auto-merge/archive, Commit B = a review proposal — dedup-two-commit
# in agentjob.sh models this), no commit when the agent finds nothing to dedup, and
# — the seam shared with 76 — that an overlay (NP_CONTENT_DIR) resolving makes the
# driver inject an "Additional skill roots" instruction naming that overlay, and a
# cooperative agent acting on it commits into the OVERLAY's own history, never the
# engine's.
#
# Uses the two-repo sandbox from agentjob.sh (engine repo w/ the driver + libs;
# overlay repo resolved via NP_CONTENT_DIR). The overlay-retarget section needs a
# BESPOKE inline stub (not the shared stub_agent) because the shared stub only ever
# commits in its own CWD — it cannot model 77's ability to `git -C <overlay>` into a
# DIFFERENT repo named in the prompt text. agentjob.sh itself stays unmodified.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# tests/maintain/ -> repo root is 4 levels up (maintain -> tests -> setup -> engine -> root)
ROOT="$(cd "$HERE/../../../.." && pwd)"
source "$ROOT/engine/setup/tests/_lib/agentjob.sh"

DRIVER_REL="engine/setup/77-run-compact.sh"

# Defensive: never let ambient env leak into any section below.
unset CLAUDE_BIN NP_LLM_AGENT_CMD NP_CONTENT_DIR NERVEPACK_AGENT NP_LLM_BACKEND \
      NP_TOGGLES_CONF NP_TOGGLES_LOCAL COMPACT_LOG 2>/dev/null || true

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

# no_trailer <repo> <sha> <label> — portable (BSD/macOS grep, ERE, no GNU `\|`)
# trailer-absence assertion, shared by both commits below.
no_trailer() {
  local repo="$1" sha="$2" label="$3" body
  body="$(git -C "$repo" log -1 --format=%B "$sha")"
  echo "$body" | grep -qiE 'co-authored-by|generated with' \
    && fail_msg "$label: commit carries an LLM-attribution trailer: $body"
}

# ---------------------------------------------------------------------------
# 1. Re-entrancy: NERVEPACK_AGENT=1 -> bail exit0, no agent spawned. The guard
#    (77-run-compact.sh line 27) must fire before LOG is even set, so no log
#    file should exist afterward.
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

log1="$home1/.cache/nervepack/compact.log"
[[ -f "$log1" ]] && fail_msg "re-entrancy: log written despite NERVEPACK_AGENT=1 guard: $(cat "$log1")"

engine1_after="$(git -C "$engine1" rev-parse HEAD)"
[[ "$engine1_before" == "$engine1_after" ]] \
  || fail_msg "re-entrancy: engine HEAD moved despite the guard ($engine1_before -> $engine1_after)"
[[ "$fail" -eq 0 ]] && echo "PASS: re-entrancy NERVEPACK_AGENT=1 -> bail exit0, no agent spawned, no log"

# ---------------------------------------------------------------------------
# 2. Two-commit contract: stub_agent dedup-two-commit makes Commit A (archive
#    duplicate) then Commit B (review proposal) in ITS OWN CWD (the engine repo,
#    since 77 stays cd'd into $NP — no overlay involved here). Assert BOTH
#    commits exist, are each path-limited to exactly the files the stub touched
#    (Commit A -> archive/np-stub-dup/SKILL.md only; Commit B ->
#    compact-proposals/stub-proposal.md only — neither commit's diff bleeds into
#    the other's path), and neither carries an LLM-attribution trailer.
# ---------------------------------------------------------------------------
sandbox2="$(make_agent_sandbox)"
engine2="$(sed -n '1p' <<<"$sandbox2")"
require_dir "$engine2" "sandbox(2) engine"
_CLEANUP+=("$(dirname "$engine2")")
[[ -d "$engine2/.git" ]] || fail_msg "sandbox(2): engine repo missing .git"

stub_agent dedup-two-commit   # exports CLAUDE_BIN + NP_LLM_BACKEND=claude for the rest of this script

home2="$(mktemp -d)"; _CLEANUP+=("$home2")

require_dir "$engine2" "sandbox(2) engine (pre-cd)"
rc=0
( cd "$engine2" && HOME="$home2" bash "$DRIVER_REL" ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || fail_msg "two-commit: driver exited $rc"

# --- Commit A: archive/merge, path-limited to the archived duplicate ---
assert_commit_in "$engine2" "archive/np-stub-dup/SKILL.md" "archive duplicate (stub)" || fail=1
commitA_sha="$(git -C "$engine2" log --format='%H%x09%s' | grep -F 'archive duplicate (stub)' | head -n1 | cut -f1)"
if [[ -n "$commitA_sha" ]]; then
  filesA="$(git -C "$engine2" diff-tree --no-commit-id --name-only -r "$commitA_sha")"
  [[ "$filesA" == "archive/np-stub-dup/SKILL.md" ]] \
    || fail_msg "two-commit: Commit A touches more than the archived duplicate: $filesA"
  subjA="$(git -C "$engine2" log -1 --format=%s "$commitA_sha")"
  case "$subjA" in skill\(*) : ;; *) fail_msg "two-commit: Commit A subject lacks conventional 'skill(' prefix: $subjA" ;; esac
  no_trailer "$engine2" "$commitA_sha" "two-commit: Commit A"
else
  fail_msg "two-commit: no archive/merge commit found to inspect"
fi

# --- Commit B: review proposal, path-limited to compact-proposals/ ---
assert_commit_in "$engine2" "compact-proposals/stub-proposal.md" "propose merge (stub)" || fail=1
commitB_sha="$(git -C "$engine2" log --format='%H%x09%s' | grep -F 'propose merge (stub)' | head -n1 | cut -f1)"
if [[ -n "$commitB_sha" ]]; then
  filesB="$(git -C "$engine2" diff-tree --no-commit-id --name-only -r "$commitB_sha")"
  [[ "$filesB" == "compact-proposals/stub-proposal.md" ]] \
    || fail_msg "two-commit: Commit B touches more than the proposal file: $filesB"
  subjB="$(git -C "$engine2" log -1 --format=%s "$commitB_sha")"
  case "$subjB" in maintain\(*) : ;; *) fail_msg "two-commit: Commit B subject lacks conventional 'maintain(' prefix: $subjB" ;; esac
  no_trailer "$engine2" "$commitB_sha" "two-commit: Commit B"
else
  fail_msg "two-commit: no proposal commit found to inspect"
fi

# Both commits landed in the ENGINE repo (77 never cd's elsewhere absent an
# overlay) — distinct from the archive/proposal paths already checked above.
[[ -n "$commitA_sha" && -n "$commitB_sha" && "$commitA_sha" != "$commitB_sha" ]] \
  || fail_msg "two-commit: expected two DISTINCT commits, got A='$commitA_sha' B='$commitB_sha'"

[[ "$fail" -eq 0 ]] && echo "PASS: two-commit contract -> Commit A (archive) + Commit B (proposal), each path-limited, conventional, trailer-free, in engine"

# ---------------------------------------------------------------------------
# 3. No-empty-commit: the agent finds nothing to dedup and makes no mutation
#    and no commit at all. The driver itself never fabricates a commit, so the
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
# nothing to dedup/propose (no pair above 0.3 similarity, no oversized skill),
# and makes NO mutation and NO commit — mirrors a real compact run against a
# repo with no candidates.
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
[[ "$fail" -eq 0 ]] && echo "PASS: no-empty-commit -> agent finds nothing to dedup, no commit made"

# ---------------------------------------------------------------------------
# 4. Overlay retarget (shared seam w/ 76). A BESPOKE inline stub — not
#    stub_agent, which only ever commits in its own CWD — because faithfully
#    modeling 77's real behavior requires reading the overlay path OUT of the
#    prompt text and `git -C <that-path>` committing into it, exactly as 77's
#    own extra_note (~line 53) and agents/np-flow-weekly-compact.md's commit
#    instructions tell a real agent to do for extra skill roots. The stub also
#    records the raw prompt it received (via $STUB_PROMPT_FILE) so this test
#    can assert the overlay-roots instruction's presence/absence directly,
#    independent of whether the stub acted on it.
# ---------------------------------------------------------------------------
retarget_dir="$(mktemp -d)"; _CLEANUP+=("$retarget_dir")
cat > "$retarget_dir/claude" <<'STUB'
#!/usr/bin/env bash
# Recording + cooperative retarget stub. Records the exact prompt it received,
# then — ONLY if the prompt names an overlay root via 77's documented "... a
# SEPARATE git repo rooted at `<path>`." phrasing — commits an archive-duplicate
# fix into THAT path via `git -C`, mirroring what a real compact run does for
# extra skill roots (dedup-two-commit's Commit A, retargeted). If no such
# phrasing is present (no overlay configured), it makes no overlay commit at
# all — there is nowhere named to commit into.
set -uo pipefail
prompt="$(cat)"
: "${STUB_PROMPT_FILE:?STUB_PROMPT_FILE not set}"
printf '%s' "$prompt" > "$STUB_PROMPT_FILE"

overlay_path="$(printf '%s' "$prompt" | sed -n 's/.*rooted at `\([^`]*\)`.*/\1/p' | head -n1)"
if [[ -n "$overlay_path" && -d "$overlay_path/.git" ]]; then
  mkdir -p "$overlay_path/archive/np-overlay-dup"
  printf 'archived (overlay stub)\n' > "$overlay_path/archive/np-overlay-dup/SKILL.md"
  git -C "$overlay_path" add archive/np-overlay-dup/SKILL.md
  git -C "$overlay_path" commit -m "skill(np-overlay-dup): archive duplicate (overlay stub)" \
    -- archive/np-overlay-dup/SKILL.md
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

# Give the overlay a skills/ dir — 77's EXTRA_ROOTS filter requires -d "$root/skills".
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

assert_commit_in "$overlay4" "archive/np-overlay-dup/SKILL.md" "skill(np-overlay-dup)" || fail=1
assert_no_commit_in "$engine4" "skill(np-overlay-dup)" || fail=1
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

assert_no_commit_in "$engine5" "skill(np-overlay-dup)" || fail=1
[[ "$fail" -eq 0 ]] && echo "PASS: overlay-retarget(no-overlay) -> instruction absent, no overlay commit fabricated"

if [[ "$fail" -eq 0 ]]; then
  echo "PASS test_compact_output"
else
  echo "FAIL test_compact_output"
  exit 1
fi
