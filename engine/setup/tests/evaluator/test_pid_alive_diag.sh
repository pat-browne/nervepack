#!/usr/bin/env bash
# Targeted diagnostic for np_implement_suggestion.py's _pid_alive() /
# _pid_alive_windows(). Isolates JUST the liveness check (no worktrees, no git,
# no agent stub, no test_implement.sh end-to-end scenario) so a failure here
# gives direct evidence -- GetLastError, the raw OpenProcess handle value --
# instead of the terse "FAIL: ran while a live lock was held" that scenario 5
# of test_implement.sh has now produced identically across FOUR straight fix
# attempts (os.kill-is-unsafe, ctypes ABI/restype, $$->$!, still failing), with
# zero diagnostic detail each time -- the threshold (systematic-debugging: 3+
# failed fixes on the same symptom) to stop patching the function and instead
# gather evidence on whether the TEST's simulation of "a live pid" is even
# valid on this platform, before touching production code again.
#
# Covers three distinct pid shapes side by side in one run:
#   1. bash's own $$ (this script's pid)
#   2. bash's $! from a backgrounded child (test_implement.sh scenario 5/5b's
#      mechanism) -- cross-checked against ps's WINPID column, a second,
#      independent MSYS->native-pid translation from /proc/<pid>/winpid
#      (already confirmed absent on this install)
#   3. a real backgrounded python3 process's own self-reported os.getpid() --
#      THE actual production shape (_acquire_lock()'s _claim() only ever
#      writes a live Python process's own os.getpid(), never a bash-tracked
#      pid). Only this one is a hard failure: if OpenProcess can't resolve a
#      pid a live Windows-native Python process reported about itself, that's
#      a genuine _pid_alive_windows() defect, not a test-fixture pid-namespace
#      mismatch.
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
# is the whole point even when every check passes (e.g. confirming ps's WINPID
# cross-check resolves correctly), so mirror it to a fixed on-disk path an
# always()-gated CI step can cat regardless of pass/fail.
#
# NOTE: deliberately NOT `exec > >(tee ...) 2>&1` -- a live process-substitution
# pipe combined with backgrounded 30s children (below) reproduced a genuine
# 30s hang on Linux CI (confirmed: run-all.sh's outer `out=$(...)` blocked
# until the backgrounded sleep/python helper naturally exited, because their
# inherited fd1 pointed at that pipe and nothing closed it early enough). A
# plain per-line append has no persistent pipe for a background child to hold
# open, so it can't reproduce that class of bug regardless of the exact
# mechanism. test_implement.sh's own scenario 5 avoids the same hazard by
# killing its backgrounded sleep INLINE, immediately after use, rather than
# deferring cleanup -- mirrored below for the same reason.
DEBUG_LOG="$NP/.ci-debug-pid-diag.log"
: > "$DEBUG_LOG"
log() { echo "$1"; printf '%s\n' "$1" >> "$DEBUG_LOG"; }

# MSYS/Cygwin expose /proc/<pid>/winpid: the REAL native Windows PID behind an
# MSYS-numbered pid, when the two differ. If this file exists and its value
# differs from $$, that's direct proof bash's own $$ is not a Windows-API-
# resolvable PID at all here (which would fully explain OpenProcess($$)
# failing with ERROR_INVALID_PARAMETER regardless of how correct the ctypes
# call itself is).
winpid=""
if [[ -r "/proc/$$/winpid" ]]; then
  winpid="$(cat "/proc/$$/winpid" 2>/dev/null || true)"
fi
log "bash \$\$=$$ /proc/\$\$/winpid=${winpid:-<not present>}"

# Three straight fix attempts targeting _pid_alive_windows() itself (os.kill-is-
# unsafe, ctypes ABI/restype, then retargeting scenario 5 from $$ to $!) have
# produced ZERO change in test_implement.sh scenario 5's outcome -- per
# systematic-debugging, that's the threshold to stop patching the function and
# instead question whether the TEST's simulation of "a live pid" is even valid
# on this platform. Two more evidence sources, neither tried yet:
#
# a) ps's WINPID column: Git-bash/MSYS ps exposes the real CreateProcess'd
#    Windows pid distinct from its own MSYS-numbered PID column -- a second,
#    independent mechanism from /proc/<pid>/winpid (confirmed absent above).
# b) production's ACTUAL shape: _acquire_lock()'s _claim() writes str(os.getpid())
#    from a live, real Windows-native Python process -- never a bash-tracked
#    pid. Scenario 5/5b simulate "a live owner" with bash job control ($$ or
#    $!) because that's cheap in a bash test harness, but if bash-tracked pids
#    are categorically not what OpenProcess expects on this install, that's a
#    test-fixture defect, not a production one. Check a REAL backgrounded
#    python3 process's self-reported os.getpid() directly -- this is the only
#    check here that mirrors production exactly.
sleep 30 &
bang_pid=$!

ps_winpid=""
ps_row="$(ps -a 2>/dev/null | awk -v p="$bang_pid" '$1==p')"
if [[ -n "$ps_row" ]]; then
  # Git-bash/MSYS ps column order: PID PPID PGID WINPID TTY UID STIME COMMAND
  ps_winpid="$(awk -v p="$bang_pid" '$1==p {print $4}' <<<"$ps_row")"
fi
log "bash \$!=$bang_pid ps row=[${ps_row:-<none>}] ps-derived WINPID=${ps_winpid:-<not present>}"

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
  kill "$bang_pid" "$py_bg_pid" 2>/dev/null || true
  wait "$bang_pid" "$py_bg_pid" 2>/dev/null || true
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
python3 - "$SETUP" "$$" "${winpid:-0}" "$bang_pid" "${ps_winpid:-0}" "$py_reported_pid" 2>&1 <<'PYEOF' | tee -a "$DEBUG_LOG"
import ctypes
import os
import subprocess
import sys

setup_dir = sys.argv[1]
bash_pid, winpid, bang_pid, ps_winpid, py_reported_pid = (int(x) for x in sys.argv[2:7])
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

# 2. THE actual production shape: a live Git-bash PID, passed in from a still-
#    running bash script (this python process's own parent), checked while
#    that bash script is blocked waiting on us. NOTE: this is expected to
#    report False on Windows if bash's $$ is an MSYS-internal pid rather than
#    a native Windows pid -- that's the hypothesis winpid (below) tests
#    directly. Not counted as a hard failure here; recorded for comparison.
bash_alive = m._pid_alive(bash_pid)
print("live bash test script via $$ (pid=%d) alive: %s" % (bash_pid, bash_alive))

# 2b. The SAME live process, but via /proc/$$/winpid (the real native Windows
#     pid MSYS/Cygwin expose for translation) instead of bash's own $$. If
#     this reports True while 2 reports False, that's direct confirmation
#     that $$ and the native Windows pid are simply different numbers here --
#     not a bug in _pid_alive_windows(), a pid-namespace mismatch in what the
#     test was feeding it.
if winpid:
    winpid_alive = m._pid_alive(winpid)
    print("live bash test script via /proc/$$/winpid (pid=%d) alive: %s (expect True)"
          % (winpid, winpid_alive))
    if not winpid_alive:
        failures.append("winpid")
else:
    print("no /proc/$$/winpid available -- skipping the winpid cross-check")

# 2c. bash's $! from a backgrounded child (test_implement.sh scenario 5/5b's
#     ACTUAL mechanism as of the last fix attempt) -- not counted as a hard
#     failure, same reasoning as 2 above: a bash-tracked pid, not a
#     production-shaped one.
bang_alive = m._pid_alive(bang_pid)
print("live backgrounded sleep via $! (pid=%d) alive: %s" % (bang_pid, bang_alive))

# 2d. the SAME backgrounded sleep, but via ps's WINPID column instead of $!
#     itself -- a second, independent translation mechanism from /proc/<pid>/winpid
#     (which 2b already found absent). If this reports True while 2c reports
#     False, that's confirmation from an entirely different code path that $!
#     is also not the native Windows pid on this install.
if ps_winpid:
    ps_winpid_alive = m._pid_alive(ps_winpid)
    print("live backgrounded sleep via ps WINPID (pid=%d) alive: %s (expect True)"
          % (ps_winpid, ps_winpid_alive))
    if not ps_winpid_alive:
        failures.append("ps_winpid")
else:
    print("no ps-derived WINPID available -- skipping the ps WINPID cross-check")

# 2e. THE production shape: a real, live, backgrounded python3 process's own
#     self-reported os.getpid() -- exactly what _acquire_lock()'s _claim()
#     writes into the lock file in production (never a bash-tracked pid). This
#     IS counted as a hard failure: if OpenProcess can't resolve a pid a live
#     Windows-native Python process reported about ITSELF, that's a genuine
#     _pid_alive_windows() defect, not a test-fixture pid-namespace mismatch.
py_alive = m._pid_alive(py_reported_pid)
print("live backgrounded python3 helper via its own os.getpid() (pid=%d) alive: %s (expect True)"
      % (py_reported_pid, py_alive))
if not py_alive:
    failures.append("py_reported_pid")

# 3. raw ctypes diagnostics, bypassing _pid_alive entirely, so a failure above
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
raw_probe(bang_pid, "bang_pid")
if ps_winpid:
    raw_probe(ps_winpid, "ps_winpid")
raw_probe(py_reported_pid, "py_reported_pid")

# 4. a definitely-dead pid (a subprocess that has already exited) must report
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
kill "$bang_pid" "$py_bg_pid" 2>/dev/null || true
wait "$bang_pid" "$py_bg_pid" 2>/dev/null || true
rm -f "$py_pid_file"

exit "$diag_status"
