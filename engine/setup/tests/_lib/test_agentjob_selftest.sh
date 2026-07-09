#!/usr/bin/env bash
# np-test: agentjob-selftest | sandbox+stub+assertions
# Self-test for _lib/agentjob.sh, the shared sandbox + stub-agent helper that
# engine/setup/tests/{maintain,memory,episodic}/test_run_*.sh (tasks 2-5) source.
# Exercises the helper's own mechanics — NOT a real driver — so a break here
# means the shared foundation is broken, before any driver test can be trusted:
#   1. make_agent_sandbox stands up two REAL, separate git repos.
#   2. stub_agent installs a cooperative-but-honest stub on CLAUDE_BIN: it commits
#      wherever it is invoked from (cwd), not a hardcoded path — so a mis-route
#      shows up as a commit landing in the wrong repo, which assert_commit_in /
#      assert_no_commit_in must catch.
#   3. assert_no_empty_commit must itself fail (return nonzero) against a
#      deliberately empty commit — otherwise the assertion would rubber-stamp a
#      driver run that did nothing.
#   4. the assertions guard against an empty/invalid <repo> arg — git -C "" falls
#      through to the CURRENT working directory (the real repo), so an assertion
#      with an empty repo must FAIL loudly, never silently validate the real repo.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/agentjob.sh"

fail=0
engine="" overlay="" scratch=""
# Register cleanup BEFORE creating any tmp dirs so a mid-run failure under set -u
# can't leak them (matches test_skill_maintain.sh's trap-first pattern). Covers
# the sandbox parent, the scratch repo, and stub_agent's reused stub dir.
cleanup() {
  [[ -n "$engine" ]] && rm -rf "$(dirname "$engine")"
  [[ -n "$scratch" ]] && rm -rf "$scratch"
  [[ -n "${_AGENTJOB_STUB_DIR:-}" ]] && rm -rf "$_AGENTJOB_STUB_DIR"
  return 0
}
trap cleanup EXIT

# --- 1+2: sandbox + stub routing ---
sandbox_out="$(make_agent_sandbox)"
engine="$(sed -n '1p' <<<"$sandbox_out")"
overlay="$(sed -n '2p' <<<"$sandbox_out")"

[[ -d "$engine/.git" ]] || { echo "FAIL: make_agent_sandbox: no .git in engine repo ($engine)"; fail=1; }
[[ -d "$overlay/.git" ]] || { echo "FAIL: make_agent_sandbox: no .git in overlay repo ($overlay)"; fail=1; }

stub_agent promote
[[ -n "${CLAUDE_BIN:-}" && -x "$CLAUDE_BIN" ]] || { echo "FAIL: stub_agent promote: CLAUDE_BIN not installed"; fail=1; }

# Trivial invocation: simulate what a driver does before handing off to np-llm.sh
# (cd into the repo it resolved, pipe the prompt to $CLAUDE_BIN) — enough to
# trigger the stub's mutation+commit without running a real driver script.
( cd "$overlay" && printf 'irrelevant prompt body\n' | "$CLAUDE_BIN" )

assert_commit_in "$overlay" "skills/np-stub-promoted/SKILL.md" "skill(np-stub-promoted)" || fail=1
assert_no_commit_in "$engine" "skill(np-stub-promoted)" || fail=1

# --- 3: assert_no_empty_commit must catch a deliberately empty commit ---
scratch="$(mktemp -d)"
( cd "$scratch" && git init -q && git config user.email "s@t" && git config user.name "s" \
    && git commit -q --allow-empty -m "empty commit (deliberate)" )
if assert_no_empty_commit "$scratch" >/dev/null 2>&1; then
  echo "FAIL: assert_no_empty_commit did not catch a deliberately empty commit"
  fail=1
else
  echo "PASS: assert_no_empty_commit correctly caught a deliberately empty commit"
fi

# --- 4: the empty/invalid-repo guard. An empty repo arg must FAIL (return
# nonzero), NOT silently validate against the current working directory (the
# real nervepack repo). Run each from the real repo root to make the danger
# concrete: without the guard, git -C "" here would inspect nervepack's own
# history and could return a misleading PASS. All three assertions share the
# guard; spot-check one of each shape (history-scan, negative, HEAD-scan).
ROOT="$(cd "$HERE/../../../.." && pwd)"
check_guard() {  # $1=label; runs $2... in a subshell cd'd to the real repo
  local label="$1"; shift
  if ( cd "$ROOT" && "$@" ) >/dev/null 2>&1; then
    echo "FAIL: $label accepted an empty repo arg (would validate the real cwd)"; fail=1
  else
    echo "PASS: $label rejected an empty repo arg"
  fi
}
check_guard assert_commit_in       assert_commit_in "" "x" "y"
check_guard assert_no_commit_in    assert_no_commit_in "" "y"
check_guard assert_no_empty_commit assert_no_empty_commit ""

if [[ "$fail" -eq 0 ]]; then
  echo "PASS test_agentjob_selftest"
else
  echo "FAIL test_agentjob_selftest"
  exit 1
fi
