#!/usr/bin/env bash
# Targeted diagnostic for np_implement_suggestion.py's _pid_alive() /
# _pid_alive_windows(). Isolates JUST the liveness check (no worktrees, no git,
# no agent stub, no test_implement.sh end-to-end scenario) so a failure here
# gives direct evidence -- GetLastError, the raw OpenProcess handle value --
# instead of a terse end-to-end failure with no diagnostic detail.
#
# History: a real multi-cycle Windows CI chase (2026-07-22) initially also
# checked bash-tracked pids ($$, and a backgrounded child's $! cross-checked
# via ps's WINPID column) here, on the theory that a bash job-control pid
# might not be a native-Windows-resolvable pid. That theory was CONFIRMED
# (bash's own $$ fails OpenProcess with GetLastError=87/ERROR_INVALID_PARAMETER)
# but turned out to be a red herring for the real bug: the SAME run showed a
# bash $! pid resolving correctly in this diagnostic while the mechanistically
# identical check failed in test_implement.sh scenario 5 -- proof bash-tracked
# pids are simply unreliable on this platform (can coincidentally resolve or
# not), not that _pid_alive_windows() was broken. The actual fix landed in
# test_implement.sh (scenario 5/5b now simulate a live/dead pid via a real
# python3 helper's own os.getpid(), matching what production actually writes)
# -- see docs/ARCHITECTURE.md's pid-liveness change-impact row for the full
# chain of evidence. The bash-$!/ps-WINPID cross-check was removed from this
# file once it had served that investigative purpose: it had no ongoing
# regression-guard value (production never writes a bash-tracked pid) and its
# `ps -a | awk` command substitution, run immediately after backgrounding a
# 30s child, reproducibly hung for ~30s on Linux CI (root cause not fully
# understood, but the code had zero reason to exist once the investigation
# closed -- removed rather than worked around).
#
# On non-Windows this just confirms the harness/import path is sound (the
# ctypes.windll branch this exists to probe doesn't exist off Windows --
# _pid_alive()'s POSIX path is already exercised by test_implement.sh's own
# scenarios 5/5b on every platform).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"
SETUP="$NP/engine/setup"

# run-all.sh only echoes a test's captured output when it FAILS (see its
# `if out=$(...); then ... else echo "$out"; fi`) -- this diagnostic's evidence
# is the whole point even when every check passes, so mirror it to a fixed
# on-disk path an always()-gated CI step can cat regardless of pass/fail.
DEBUG_LOG="$NP/.ci-debug-pid-diag.log"
: > "$DEBUG_LOG"
log() { echo "$1"; printf '%s\n' "$1" >> "$DEBUG_LOG"; }

# MSYS/Cygwin expose /proc/<pid>/winpid: the REAL native Windows PID behind an
# MSYS-numbered pid, when the two differ. If this file exists and its value
# differs from $$, that's direct proof bash's own $$ is not a Windows-API-
# resolvable PID at all here (which fully explains OpenProcess($$) failing
# with ERROR_INVALID_PARAMETER regardless of how correct the ctypes call
# itself is). Purely informational -- never a hard failure below.
winpid=""
if [[ -r "/proc/$$/winpid" ]]; then
  winpid="$(cat "/proc/$$/winpid" 2>/dev/null || true)"
fi
log "bash \$\$=$$ /proc/\$\$/winpid=${winpid:-<not present>}"

# THE production shape: a real, live, backgrounded python3 process's own
# self-reported os.getpid() -- exactly what _acquire_lock()'s _claim() writes
# into the lock file in production (never a bash-tracked pid). This is the
# one check with ongoing regression-guard value.
py_pid_file="$(mktemp)"
python3 -c '
import os, sys, time
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(str(os.getpid())); f.flush()
time.sleep(30)
' "$py_pid_file" &
py_bg_pid=$!
for _ in $(seq 1 50); do [[ -s "$py_pid_file" ]] && break; sleep 0.1; done
py_reported_pid="$(cat "$py_pid_file" 2>/dev/null || echo 0)"
log "backgrounded python3 helper: bash \$!=$py_bg_pid self-reported os.getpid()=$py_reported_pid"

# Safety net only (belt-and-braces): the REAL cleanup is the inline kill right
# after the heredoc below, which is what actually needs to run before this
# script's own process exits. This trap just catches an early/error exit path
# (e.g. `set -e` firing inside the heredoc invocation itself) that would skip
# past the inline cleanup -- killing an already-dead pid is a harmless no-op.
cleanup_bg() {
  kill "$py_bg_pid" 2>/dev/null || true
  wait "$py_bg_pid" 2>/dev/null || true
  rm -f "$py_pid_file"
}
trap cleanup_bg EXIT

# Foreground pipe, not process substitution -- python3 here runs and exits
# before `tee` sees EOF, no lingering background child holds this pipe open.
# set +e around it: under pipefail a nonzero here (the real FAIL/PASS signal)
# would otherwise trip `set -e` at this exact statement and skip the inline
# cleanup right below -- capture the real exit code via PIPESTATUS instead and
# exit with it explicitly once cleanup has run.
set +e
python3 - "$SETUP" "$$" "${winpid:-0}" "$py_reported_pid" 2>&1 <<'PYEOF' | tee -a "$DEBUG_LOG"
import ctypes
import os
import subprocess
import sys

setup_dir = sys.argv[1]
bash_pid, winpid, py_reported_pid = (int(x) for x in sys.argv[2:5])
sys.path.insert(0, setup_dir)

if os.name != "nt":
    print("SKIP: not Windows (os.name=%r) -- the ctypes.windll path this diagnoses "
          "doesn't exist here; _pid_alive()'s POSIX path is already covered by "
          "test_implement.sh scenarios 5/5b on every platform." % os.name)
    sys.exit(0)

import np_implement_suggestion as m

failures = []

# 1. self-check: this python process's own pid must report alive.
self_alive = m._pid_alive(os.getpid())
print("self (pid=%d) alive: %s (expect True)" % (os.getpid(), self_alive))
if not self_alive:
    failures.append("self")

# 2. bash's own $$: informational only (known unreliable on this platform --
#    see the file header). Not counted as a hard failure.
bash_alive = m._pid_alive(bash_pid)
print("live bash test script via $$ (pid=%d) alive: %s" % (bash_pid, bash_alive))

# 2b. the SAME live process via /proc/$$/winpid, when available. Also
#     informational -- confirms the $$-vs-native-pid mismatch when it exists.
if winpid:
    winpid_alive = m._pid_alive(winpid)
    print("live bash test script via /proc/$$/winpid (pid=%d) alive: %s (expect True)"
          % (winpid, winpid_alive))
    if not winpid_alive:
        failures.append("winpid")
else:
    print("no /proc/$$/winpid available -- skipping the winpid cross-check")

# 3. THE production shape: a real, live, backgrounded python3 process's own
#    self-reported os.getpid() -- exactly what _acquire_lock()'s _claim()
#    writes into the lock file in production (never a bash-tracked pid). This
#    IS counted as a hard failure: if OpenProcess can't resolve a pid a live
#    Windows-native Python process reported about ITSELF, that's a genuine
#    _pid_alive_windows() defect.
py_alive = m._pid_alive(py_reported_pid)
print("live backgrounded python3 helper via its own os.getpid() (pid=%d) alive: %s (expect True)"
      % (py_reported_pid, py_alive))
if not py_alive:
    failures.append("py_reported_pid")

# 4. raw ctypes diagnostics, bypassing _pid_alive entirely, so a failure above
#    comes with actual evidence instead of a bare True/False.
from ctypes import wintypes
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def raw_probe(pid, label):
    kernel32.SetLastError(0)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    err = ctypes.GetLastError()
    print("raw OpenProcess(%s=%d) -> handle=%r GetLastError=%d" % (label, pid, handle, err))
    if not handle:
        return
    exit_code = wintypes.DWORD()
    got = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    print("raw GetExitCodeProcess(%s) -> ok=%s exit_code=%d (STILL_ACTIVE=259)"
          % (label, bool(got), exit_code.value))
    kernel32.CloseHandle(handle)


raw_probe(bash_pid, "bash_pid")
raw_probe(py_reported_pid, "py_reported_pid")

# 5. a definitely-dead pid (a subprocess that has already exited) must report
#    NOT alive. subprocess.run() returns a CompletedProcess, which has no
#    .pid attribute (only Popen does) -- use Popen directly and wait() so we
#    still get a real, already-exited native Windows pid to check.
proc = subprocess.Popen([sys.executable, "-c", "pass"])
dead_pid = proc.pid
proc.wait()
dead_alive = m._pid_alive(dead_pid)
print("just-exited subprocess (pid=%d) alive: %s (expect False)" % (dead_pid, dead_alive))
if dead_alive:
    failures.append("dead-pid")

if failures:
    print("FAIL: %s" % ", ".join(failures))
    sys.exit(1)
print("PASS test_pid_alive_diag")
PYEOF
diag_status="${PIPESTATUS[0]}"
set -e

# Inline cleanup (mirrors test_implement.sh scenario 5's proven pattern):
# kill+wait right here, before this script's own process exits, rather than
# deferring to the EXIT trap above (which stays only as a safety net).
kill "$py_bg_pid" 2>/dev/null || true
wait "$py_bg_pid" 2>/dev/null || true
rm -f "$py_pid_file"

exit "$diag_status"
