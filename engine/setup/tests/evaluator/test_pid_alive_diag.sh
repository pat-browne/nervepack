#!/usr/bin/env bash
# Targeted diagnostic for np_implement_suggestion.py's _pid_alive() /
# _pid_alive_windows(). Isolates JUST the liveness check (no worktrees, no git,
# no agent stub, no test_implement.sh end-to-end scenario) so a failure here
# gives direct evidence -- GetLastError, the raw OpenProcess handle value --
# instead of the terse "FAIL: ran while a live lock was held" that scenario 5
# of test_implement.sh has now produced identically across three different
# _pid_alive fix attempts, with zero diagnostic detail each time.
#
# Mirrors the ACTUAL production shape of the bug: a live Git-bash PID ($$,
# read from a still-running bash script), checked from a separate native
# Windows python3 child process -- exactly what test_implement.sh's scenario 5
# does (lock/pid holds the bash test script's own $$; python3 implement-
# suggestion checks it while the bash script blocks waiting on that call).
#
# On non-Windows this just confirms the harness/import path is sound (the
# ctypes.windll branch this exists to probe doesn't exist off Windows --
# _pid_alive()'s POSIX path is already exercised by test_implement.sh's own
# scenarios 5/5b on every platform).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"
SETUP="$NP/engine/setup"

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
echo "bash \$\$=$$ /proc/\$\$/winpid=${winpid:-<not present>}"

python3 - "$SETUP" "$$" "${winpid:-0}" <<'PYEOF'
import ctypes
import os
import subprocess
import sys

setup_dir, bash_pid, winpid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
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

# 3. raw ctypes diagnostics for the bash-parent pid, bypassing _pid_alive
#    entirely, so a failure above comes with actual evidence instead of a
#    bare True/False.
from ctypes import wintypes
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.SetLastError(0)
handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, bash_pid)
err = ctypes.GetLastError()
print("raw OpenProcess(bash_pid=%d) -> handle=%r GetLastError=%d"
      % (bash_pid, handle, err))
if handle:
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle(handle)
    exit_code = wintypes.DWORD()
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    # re-open since we already closed the handle above; just for the exit-code probe
    handle2 = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, bash_pid)
    if handle2:
        got = kernel32.GetExitCodeProcess(handle2, ctypes.byref(exit_code))
        print("raw GetExitCodeProcess -> ok=%s exit_code=%d (STILL_ACTIVE=259)"
              % (bool(got), exit_code.value))
        kernel32.CloseHandle(handle2)

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
