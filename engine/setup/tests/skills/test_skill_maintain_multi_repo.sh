#!/usr/bin/env bash
# Regression test for commit-ROUTING correctness in 75-skill-maintain.sh across
# two REAL, separate git repos: a fake "engine" repo (the scripts under test,
# mirroring how test_skill_maintain.sh stages them) and a separate "overlay"
# content repo (resolved via NP_CONTENT_DIR) holding the skills/ that need
# maintenance. test_skill_maintain_roots.sh only exercises np_skill_budget.py's
# scan/report step directly; it never runs 75-skill-maintain.sh, so the
# find_skill_root / repo_root / commit_repos-and-push loop (75-skill-maintain.sh
# ~121-173) — the part that decides WHICH repo receives the split commit — had no
# coverage at all. That is exactly the issue #11 failure class: a skill edit that
# belongs to the content overlay getting mis-committed into the engine repo.
#
# This test places an over-budget skill in the OVERLAY only, runs the real
# script end to end (same CLAUDE_BIN-stub + SKILL_MAINTAIN_NO_PUSH pattern as
# test_skill_maintain.sh), and asserts the split commit landed in the overlay's
# git history AND did not leak into the engine's.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"     # setup/
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- Engine repo: the scripts under test, its OWN (separate) git history. No
# skills/ of its own is needed to exercise the bug class — routing correctness
# is proven by asserting the engine's commit count never moves off 1 (init).
NP="$tmp/engine"; mkdir -p "$NP/engine/setup" "$NP/skills" "$NP/agents"
cp "$SETUP/75-skill-maintain.sh" "$SETUP/np_skill_budget.py" \
   "$SETUP/np_skill_validate.py" "$SETUP/np-toggle-lib.sh" "$SETUP/np-llm.sh" \
   "$SETUP/np-content-lib.sh" "$SETUP/np-layer-lib.sh" "$SETUP/np_graduation_detect.py" \
   "$NP/engine/setup/"
printf 'skills|shared|runtime|on|split_kb=8,soft_kb=6,catalog_tok=4000,max_per_run=2,graduate_seen=10,graduate_kb=6\n' \
   > "$NP/engine/setup/toggles.conf"
{ echo "## Prompt"; echo "split it"; } > "$NP/agents/np-flow-skill-maintain.md"
( cd "$NP" && git init -q && git config user.email "engine@t" && git config user.name "engine" \
    && git add -A && git commit -qm init )

# --- Overlay (content) repo: a SEPARATE git history, holding the over-budget
# skill (>8KB) that must be split. Resolved at runtime via NP_CONTENT_DIR.
OV="$tmp/overlay"; mkdir -p "$OV/skills/big"
{ printf -- '---\nname: big\ndescription: a big skill\n---\n[[np-core-sync]]\n';
  head -c 9000 /dev/zero | tr '\0' 'x'; } > "$OV/skills/big/SKILL.md"
( cd "$OV" && git init -q && git config user.email "overlay@t" && git config user.name "overlay" \
    && git add -A && git commit -qm init )

run_with_stub() {  # $1 = stub body
  cat > "$tmp/claude" <<STUB
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
$1
STUB
  chmod +x "$tmp/claude"
  ( cd "$NP" && CLAUDE_BIN="$tmp/claude" SKILL_MAINTAIN_NO_PUSH=1 \
      SKILL_MAINTAIN_LOG="$tmp/log" GRADUATION_MARKER="$tmp/grad" NP_CONTENT_DIR="$OV" \
      bash engine/setup/75-skill-maintain.sh >/dev/null 2>&1 )
}

# --- GOOD split of the OVERLAY's over-budget skill ---
run_with_stub '
mkdir -p skills/big/references
printf -- "---\nname: big\ndescription: a big skill\n---\nRule. Detail: references/d.md\n[[np-core-sync]]\n" > skills/big/SKILL.md
printf "long detail\n" > skills/big/references/d.md'

test -f "$OV/skills/big/references/d.md" || {
  echo "FAIL: split not applied in the overlay repo"; cat "$tmp/log" 2>/dev/null; exit 1;
}

# --- Routing correctness (the core anti-regression) ---
# The split commit MUST land in the OVERLAY's history...
ov_log="$(git -C "$OV" log --oneline)"
grep -q 'skill(maintain)' <<<"$ov_log" || { echo "FAIL: split commit missing from OVERLAY history: $ov_log"; exit 1; }
grep -q 'skills/big' <<<"$(git -C "$OV" show --stat HEAD)" || { echo "FAIL: overlay HEAD commit doesn't touch skills/big"; exit 1; }

# ...and must NOT land in the ENGINE's history: a routing bug (e.g. always
# committing into $NP regardless of which root owned the skill) would show up
# here as an extra commit and/or a leaked "skill(maintain)" subject.
engine_log="$(git -C "$NP" log --oneline)"
engine_count="$(git -C "$NP" rev-list --count HEAD)"
[[ "$engine_count" == "1" ]] || { echo "FAIL: engine repo gained commit(s) it should not have: $engine_log"; exit 1; }
grep -q 'skill(maintain)' <<<"$engine_log" && { echo "FAIL: split commit leaked into ENGINE history: $engine_log"; exit 1; }

echo "PASS test_skill_maintain_multi_repo"
