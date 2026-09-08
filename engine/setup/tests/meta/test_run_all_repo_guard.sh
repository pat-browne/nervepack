#!/usr/bin/env bash
# np-test: test-runner | failure
# Proves run-all.sh catches a test that writes a file this repo has committed.
#
# The guard exists because one did. A toggle test called flip() on a SHARED
# family, which writes set_conf_state() into engine/setup/toggles.conf, and the
# flipped default rode into a commit while the suite stayed green. The leak is
# invisible to the test that causes it, so only the runner can see it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$HERE/../run-all.sh"
NP_ROOT="$(cd "$HERE/../../../.." && pwd)"

VICTIM="$NP_ROOT/VERSION"
[[ -f "$VICTIM" ]] || { echo "FAIL: no committed VERSION file to use as the victim"; exit 1; }

tmp="$(mktemp -d)"
# Restore by BYTES, never `git checkout --`: the developer may have their own
# uncommitted edit to this file, and the test must not eat it.
cp -p "$VICTIM" "$tmp/VERSION.orig"
trap 'cp -p "$tmp/VERSION.orig" "$VICTIM"; rm -rf "$tmp"' EXIT

mkdir -p "$tmp/tests/leaky"
cat > "$tmp/tests/leaky/test_writes_the_repo.sh" <<T
#!/usr/bin/env bash
printf '\n# planted by test_run_all_repo_guard\n' >> "$VICTIM"
echo "this fixture passes on its own terms"
T

set +e
( unset NP_CONTENT_DIR; NP_TESTS_ROOT="$tmp/tests" bash "$RUNNER" ) >"$tmp/out" 2>&1
rc=$?
set -e

fails=0
if [[ $rc -eq 0 ]]; then
  echo "FAIL: runner exited 0 despite a test writing a committed file"; fails=1
fi
if ! grep -q "repo-mutation guard" "$tmp/out"; then
  echo "FAIL: guard did not report the mutation"; sed 's/^/  /' "$tmp/out"; fails=1
fi
if ! grep -q "VERSION" "$tmp/out"; then
  echo "FAIL: guard did not name the file that changed"; fails=1
fi
# The fixture itself must have passed, or this proves nothing about the guard:
# a red child would fail the run on its own and the guard would be untested.
if ! grep -q "test_writes_the_repo.sh" "$tmp/out"; then
  echo "FAIL: fixture test did not run"; fails=1
fi

[[ $fails -eq 0 ]] || exit 1
echo "PASS: the runner catches a test that writes a committed file"
