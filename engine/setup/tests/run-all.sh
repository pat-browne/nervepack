#!/usr/bin/env bash
# nervepack regression runner. Discovers every test_*.sh / test_*.py under the tests
# root, runs each in a hermetic env, aggregates pass/fail, and (optionally) emits a
# functionality-grouped Markdown report. Zero third-party deps. Exits nonzero if any
# test fails. NOT `set -e` — we run ALL tests and aggregate.
#
# Usage:
#   run-all.sh                     # whole suite (excludes e2e)
#   run-all.sh <substring>         # only tests whose path matches <substring>
#   run-all.sh --with-e2e          # include engine/setup/tests/e2e
#   run-all.sh --report <file>     # also write a Markdown report
#
# Content-overlay test discovery: if NP_CONTENT_DIR is set in the environment and
# $NP_CONTENT_DIR/engine/setup/tests/ exists, those tests are auto-included in the
# default run. This keeps personal content-layer tests in the CI gate on machines
# with the overlay present, while the engine suite stays clean on machines without it
# (e.g. standard CI where NP_CONTENT_DIR is not set).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_lib/harness.sh"
source "$HERE/_lib/report.sh"

ROOT="${NP_TESTS_ROOT:-$HERE}"   # NP_TESTS_ROOT lets the meta-test point at fixtures

# Hand child Python (tests AND the runtime they spawn, e.g. the MCP server) the EXACT
# bash running this suite. On Windows, a native `subprocess.run(["bash", ...])` resolves
# to C:\Windows\System32\bash.exe (the WSL launcher, no distro) instead of Git-bash —
# System32 wins the Windows PATH. NP_BASH (Windows-form via cygpath on Git-bash; plain
# path on Linux/macOS) lets _lib/nptest.py AND np-mcp-server.py invoke the right
# interpreter. (cygpath is absent off-Windows, so the fallback yields the POSIX path.)
export NP_BASH="$(cygpath -w "$(command -v bash)" 2>/dev/null || command -v bash)"

# Content-overlay test discovery: if NP_CONTENT_DIR is set and contains an
# engine/setup/tests/ tree, include those tests in the default run. This keeps
# personal content-layer tests in the CI gate on machines with the overlay
# present, while the engine suite stays clean (no overlay = no content tests).
CONTENT_ROOT=""
if [[ -n "${NP_CONTENT_DIR:-}" ]] && [[ -d "${NP_CONTENT_DIR}/engine/setup/tests" ]]; then
  CONTENT_ROOT="${NP_CONTENT_DIR}/engine/setup/tests"
fi

WITH_E2E=0 REPORT="" FILTER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-e2e) WITH_E2E=1; shift;;
    --report) REPORT="$2"; shift 2;;
    --report=*) REPORT="${1#*=}"; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    -*) echo "unknown flag: $1" >&2; exit 2;;
    *) FILTER="$1"; shift;;
  esac
done

# bash 3.2 (stock macOS) has no `mapfile` — read the discovered test paths into
# the array with a loop instead.
TESTS=()
while IFS= read -r _t; do TESTS+=("$_t"); done < <(
  { find "$ROOT" -type f \( -name 'test_*.sh' -o -name 'test_*.py' \) \
      -not -path '*/_lib/*'; \
    if [[ -n "$CONTENT_ROOT" ]]; then
      find "$CONTENT_ROOT" -type f \( -name 'test_*.sh' -o -name 'test_*.py' \) \
        -not -path '*/_lib/*'; \
    fi; } \
    | { if [[ $WITH_E2E -eq 1 ]]; then cat; else grep -v '/e2e/' || true; fi; } \
    | { if [[ -n "$FILTER" ]]; then grep -F "$FILTER" || true; else cat; fi; } \
    | sort
)

[[ ${#TESTS[@]} -gt 0 ]] || { echo "no tests matched" >&2; exit 2; }

np_hermetic_env

# Defense-in-depth: protect the live dashboard data from the suite. Some tests run the
# real aggregate/open-dashboard path, whose build writes build.py's FIXED DEFAULT_OUT —
# $NP/dashboard/data/metrics.js, which is a SYMLINK into the live content overlay. Under
# the hermetic HOME the content dir resolves to the engine root (no wiki/playbooks/
# strategies), so an unisolated test silently empties the user's real dashboard
# (window.WIKI/LEARNED -> []). Snapshot the committed dashboard files now and restore
# them after the whole suite: a test may write them, but the suite must never leave them
# mutated. (Per-test NP_CONTENT_DIR isolation also helps, but build.py's DEFAULT_OUT is
# not content-dir-relative, so scripts that omit the out arg can't be isolated that way.)
NP_ROOT="$(cd "$HERE/../../.." && pwd)"
_dash_snap="$(mktemp -d)"
for _f in metrics.js metrics.jsonl; do
  [[ -e "$NP_ROOT/dashboard/data/$_f" ]] && cp -p "$NP_ROOT/dashboard/data/$_f" "$_dash_snap/$_f"
done
_restore_dash(){
  for _f in metrics.js metrics.jsonl; do
    [[ -e "$_dash_snap/$_f" ]] && cp -p "$_dash_snap/$_f" "$NP_ROOT/dashboard/data/$_f"
  done
  rm -rf "$_dash_snap"
}

# A test must never write a file this repo has committed. The harness gives every
# test a hermetic HOME, but nothing stopped one reaching back into the checkout --
# and one did: a toggle test called flip() on a SHARED family, which writes
# set_conf_state() straight into engine/setup/toggles.conf, and the flipped default
# rode into a commit. A green suite said nothing, because the leak is invisible to
# the test that causes it. Snapshot the tracked-file state and compare after the run.
#
# Detect, never restore. A test that mutates the checkout is a bug to fix at the
# source; silently reverting it would hide the bug and lose whatever the developer
# had staged. The two dashboard files are excluded because _restore_dash above
# already owns them and runs on the EXIT trap, after this check.
_tracked_state(){ git -C "$NP_ROOT" status --porcelain --untracked-files=no 2>/dev/null | sort; }
# Say so when the guard cannot run. A safety check that disables itself in
# silence is the same class of bug it exists to catch: the suite would report
# green while protecting nothing.
_guard_live=1
if ! git -C "$NP_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  _guard_live=0
  echo "  ⚠️  repo-mutation guard OFF: $NP_ROOT is not a git checkout (or git is missing)"
fi
_repo_before="$(_tracked_state)"

tsv="$(mktemp)"; trap 'rm -f "$tsv"; np_hermetic_cleanup; _restore_dash' EXIT
pass=0 fail=0
start=$SECONDS
for t in "${TESTS[@]}"; do
  rel="${t#"$ROOT"/}"
  area="${rel%%/*}"; [[ "$area" == "$rel" ]] && area="(root)"
  hdr="$(grep -m1 '^# np-test:' "$t" 2>/dev/null | sed 's/^# np-test:[[:space:]]*//')"
  if [[ "$hdr" == *"|"* ]]; then func="${hdr%%|*}"; role="${hdr#*|}"; else func="$hdr"; role=""; fi
  func="$(echo "${func:-$area}" | xargs)"; role="$(echo "${role:-unspecified}" | xargs)"
  name="$(basename "$t")"
  if [[ "$t" == *.py ]]; then runner=(python3 "$t"); else runner=(bash "$t"); fi
  if out="$("${runner[@]}" 2>&1)"; then
    printf '%s\t%s\t%s\tPASS\n' "$func" "$role" "$name" >> "$tsv"; pass=$((pass+1))
    echo "  ✅ $rel"
  else
    printf '%s\t%s\t%s\tFAIL\n' "$func" "$role" "$name" >> "$tsv"; fail=$((fail+1))
    echo "  ❌ $rel"; echo "$out" | sed 's/^/      /'
  fi
done
secs=$((SECONDS - start))

_leaked=""
if [[ $_guard_live -eq 1 ]]; then
  _leaked="$(comm -13 <(printf '%s\n' "$_repo_before") <(printf '%s\n' "$(_tracked_state)") \
             | grep -vE 'dashboard/data/metrics\.(js|jsonl)$' || true)"
fi
if [[ -n "$_leaked" ]]; then
  fail=$((fail+1))
  echo "  ❌ repo-mutation guard: a test wrote to a committed file"
  printf '%s\n' "$_leaked" | sed 's/^/      /'
  echo "      Fix the test that did it. Isolate the path it writes (NP_TOGGLES_CONF,"
  echo "      NP_TOGGLES_LOCAL, CLAUDE_SETTINGS, HOME) rather than reverting the file."
  printf '%s\t%s\t%s\tFAIL\n' "test-runner" "failure" "repo-mutation-guard" >> "$tsv"
fi

echo "----"
echo "$pass passed / $fail failed in ${secs}s"
[[ -n "$REPORT" ]] && np_emit_report "$tsv" "$REPORT" "$pass" "$fail" "$secs"
[[ $fail -eq 0 ]]
