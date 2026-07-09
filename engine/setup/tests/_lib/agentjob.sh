#!/usr/bin/env bash
# Shared sandbox + stub-agent helper for the "agentic job" driver tests —
# 71-run-memory-promote.sh, 72-run-episodic-maintain.sh, 76-run-refine.sh,
# 77-run-compact.sh. SOURCE this; do not execute directly.
#
# All four drivers share the same shape: read a prompt from agents/np-flow-*.md,
# pipe it to np-llm.sh (which shells out to $CLAUDE_BIN), and expect the agent to
# edit + commit files IN WHICHEVER REPO IT WAS INVOKED FROM (71/72 cd into the
# content overlay first via np_content_dir; 76/77 stay in the engine repo, naming
# any extra overlay roots as text in the prompt). This helper stands up that
# two-repo shape once and gives each driver test a stub agent + git-state
# assertions, so per-test files only need the bespoke bits (fixture content,
# prompt tweaks).
#
# Interface (consumed by tasks 2-5):
#   make_agent_sandbox                             -> prints 2 lines: <engine-path>\n<overlay-path>
#   stub_agent <mode>                               -> installs a stub on CLAUDE_BIN for <mode>
#   assert_commit_in    <repo> <pathspec> <subject-substr>
#   assert_no_commit_in <repo> <subject-substr>
#   assert_no_empty_commit <repo>
#
# make_agent_sandbox creates both repos under ONE mktemp parent
# (<tmp>/engine, <tmp>/overlay) — a caller that wants cleanup can
# `trap '[[ -n "${engine:-}" ]] && rm -rf "$(dirname "$engine")"' EXIT` using the
# returned engine path (guard the empty case — `dirname ""` is `.`, and an
# unguarded trap would `rm -rf .` if the variable were ever unset).
# The caller (not this helper) is responsible for exporting
# NP_CONTENT_DIR=<overlay-path> before invoking a real driver — this helper
# only builds the two repos and copies the files a driver needs to run.
set -uo pipefail

# _lib is at tests/_lib/ -> repo root is 4 levels up: _lib -> tests -> setup -> engine -> root
_AGENTJOB_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_AGENTJOB_ROOT="$(cd "$_AGENTJOB_LIB/../../../.." && pwd)"
_AGENTJOB_SETUP="$_AGENTJOB_ROOT/engine/setup"

make_agent_sandbox() {
  local tmp engine overlay
  tmp="$(mktemp -d)"
  engine="$tmp/engine"
  overlay="$tmp/overlay"
  mkdir -p "$engine/engine/setup" "$engine/agents" "$engine/skills" "$overlay"
  # Note: no pre-created empty dirs under $overlay (skills/, memory/episodic/,
  # archive/, compact-proposals/) — git tracks files, not directories, so an
  # init commit of nothing but empty dirs is a no-op ("nothing to commit"),
  # which prints to STDOUT and would corrupt the two-line contract below. The
  # marker file seeds a real init commit; stub_agent's own `mkdir -p` creates
  # whichever of these dirs it actually needs at mutation time.
  printf 'agentjob sandbox overlay\n' > "$overlay/README.md"

  # Driver + the libs it sources, mirroring test_skill_maintain.sh's sandbox build.
  cp "$_AGENTJOB_SETUP/71-run-memory-promote.sh" \
     "$_AGENTJOB_SETUP/72-run-episodic-maintain.sh" \
     "$_AGENTJOB_SETUP/76-run-refine.sh" \
     "$_AGENTJOB_SETUP/77-run-compact.sh" \
     "$_AGENTJOB_SETUP/np-toggle-lib.sh" \
     "$_AGENTJOB_SETUP/np-content-lib.sh" \
     "$_AGENTJOB_SETUP/np-layer-lib.sh" \
     "$_AGENTJOB_SETUP/np-llm.sh" \
     "$engine/engine/setup/"
  printf 'memory.promote|shared|runtime|on|\nmemory.maintain|shared|runtime|on|\nmaintain.refine|shared|runtime|on|\nmaintain.compact|shared|runtime|on|\n' \
    > "$engine/engine/setup/toggles.conf"

  # Prompt files each driver reads (the "## Prompt" section onward).
  cp "$_AGENTJOB_ROOT/agents/np-flow-memory-promote.md" \
     "$_AGENTJOB_ROOT/agents/np-flow-episodic-maintain.md" \
     "$_AGENTJOB_ROOT/agents/np-flow-scheduled-refine.md" \
     "$_AGENTJOB_ROOT/agents/np-flow-weekly-compact.md" \
     "$engine/agents/"

  ( cd "$engine" && git init -q && git config user.email "engine@agentjob.test" \
      && git config user.name "engine" && git add -A && git commit -qm init )
  ( cd "$overlay" && git init -q && git config user.email "overlay@agentjob.test" \
      && git config user.name "overlay" && git add -A && git commit -qm init )

  printf '%s\n%s\n' "$engine" "$overlay"
}

# stub_agent <mode> — installs a stub on CLAUDE_BIN (and sets NP_LLM_BACKEND=claude,
# matching how the real drivers/np-llm.sh pick a backend) that consumes the piped
# prompt and then performs ONE canonical mutation+commit for <mode>. The stub is
# COOPERATIVE (it does the write+commit a real agent asked to do this job would do)
# but HONEST: every path it touches and every `git` call it makes is relative to
# its OWN CWD at invocation time — it never hardcodes an absolute repo path. So if
# the driver under test fails to `cd` into the repo it's supposed to operate in
# (a routing bug), the mutation+commit land in the WRONG repo and the
# assert_commit_in/assert_no_commit_in checks below catch it for real, instead of
# a stub that "always commits in the right place regardless" and would mask
# exactly that class of bug.
#
# Modes (mirror the four drivers):
#   promote            (71) — write a new skill, commit path-limited.
#   episodic-drain      (72) — append to memory/episodic/<topic>.md, commit.
#   lint-fix            (76) — edit one skill, commit.
#   dedup-two-commit    (77) — archive/merge commit, then a separate proposal commit.
stub_agent() {
  local mode="$1" tmp
  tmp="$(mktemp -d)"

  case "$mode" in
    promote)
      cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
mkdir -p skills/np-stub-promoted
printf -- '---\nname: np-stub-promoted\ndescription: stub-promoted skill (agentjob test).\n---\nStub body.\n' \
  > skills/np-stub-promoted/SKILL.md
git add skills/np-stub-promoted/SKILL.md
git commit -m "skill(np-stub-promoted): promote from memory (stub)" -- skills/np-stub-promoted/SKILL.md
STUB
      ;;
    episodic-drain)
      cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
mkdir -p memory/episodic
printf -- '## drained entry\nstub note.\n' >> memory/episodic/stub-topic.md
git add memory/episodic/stub-topic.md
git commit -m "episodic(stub-topic): drain inbox (stub)" -- memory/episodic/stub-topic.md
STUB
      ;;
    lint-fix)
      cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
mkdir -p skills/np-stub-lintfix
if [[ -f skills/np-stub-lintfix/SKILL.md ]]; then
  printf '\nLint fix note (stub).\n' >> skills/np-stub-lintfix/SKILL.md
else
  printf -- '---\nname: np-stub-lintfix\ndescription: stub skill for lint-fix test.\n---\nBody.\nLint fix note (stub).\n' \
    > skills/np-stub-lintfix/SKILL.md
fi
git add skills/np-stub-lintfix/SKILL.md
git commit -m "skill(np-stub-lintfix): lint fix (stub)" -- skills/np-stub-lintfix/SKILL.md
STUB
      ;;
    dedup-two-commit)
      cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null   # consume the piped prompt
mkdir -p archive/np-stub-dup compact-proposals
printf 'archived (stub)\n' > archive/np-stub-dup/SKILL.md
git add archive/np-stub-dup/SKILL.md
git commit -m "skill(np-stub-dup): archive duplicate (stub)" -- archive/np-stub-dup/SKILL.md
printf -- '## Proposal\nMerge np-stub-dup into np-stub-target (stub).\n' > compact-proposals/stub-proposal.md
git add compact-proposals/stub-proposal.md
git commit -m "maintain(compact): propose merge (stub)" -- compact-proposals/stub-proposal.md
STUB
      ;;
    *)
      echo "stub_agent: unknown mode '$mode' (want: promote|episodic-drain|lint-fix|dedup-two-commit)" >&2
      return 2
      ;;
  esac

  chmod +x "$tmp/claude"
  export CLAUDE_BIN="$tmp/claude"
  export NP_LLM_BACKEND=claude
}

# assert_commit_in <repo> <pathspec> <subject-substr>
# PASS iff some commit in <repo>'s history has a subject containing
# <subject-substr> AND that commit's diff touches <pathspec>.
assert_commit_in() {
  local repo="$1" pathspec="$2" subject="$3" log sha
  log="$(git -C "$repo" log --format='%H%x09%s' 2>/dev/null)" || {
    echo "FAIL: assert_commit_in($repo): not a git repo"; return 1;
  }
  sha="$(grep -F -- "$subject" <<<"$log" | head -n1 | cut -f1)"
  if [[ -z "$sha" ]]; then
    echo "FAIL: assert_commit_in($repo): no commit subject contains '$subject'"
    return 1
  fi
  if ! git -C "$repo" show --stat "$sha" 2>/dev/null | grep -qF -- "$pathspec"; then
    echo "FAIL: assert_commit_in($repo): commit $sha ('$subject') does not touch '$pathspec'"
    return 1
  fi
  echo "PASS: assert_commit_in($repo): '$subject' touches '$pathspec'"
}

# assert_no_commit_in <repo> <subject-substr>
# PASS iff NO commit in <repo>'s history has a subject containing <subject-substr>.
assert_no_commit_in() {
  local repo="$1" subject="$2" log
  log="$(git -C "$repo" log --oneline 2>/dev/null)" || {
    echo "FAIL: assert_no_commit_in($repo): not a git repo"; return 1;
  }
  if grep -qF -- "$subject" <<<"$log"; then
    echo "FAIL: assert_no_commit_in($repo): found a commit subject containing '$subject'"
    return 1
  fi
  echo "PASS: assert_no_commit_in($repo): no commit subject contains '$subject'"
}

# assert_no_empty_commit <repo>
# PASS iff <repo>'s HEAD commit touches at least one file (i.e. HEAD is not an
# empty commit — a real agent run must have actually produced a change).
assert_no_empty_commit() {
  local repo="$1" sha files
  sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || {
    echo "FAIL: assert_no_empty_commit($repo): not a git repo"; return 1;
  }
  files="$(git -C "$repo" diff-tree --no-commit-id --name-only -r "$sha" 2>/dev/null)"
  if [[ -z "$files" ]]; then
    echo "FAIL: assert_no_empty_commit($repo): HEAD ($sha) is an empty commit"
    return 1
  fi
  echo "PASS: assert_no_empty_commit($repo): HEAD touches files"
}
