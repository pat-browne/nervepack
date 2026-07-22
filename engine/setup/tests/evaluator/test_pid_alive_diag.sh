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

python3 - "$SETUP" "$$" <<'PYEOF'
import ctypes
import os
import subprocess
import sys

setup_dir, bash_pid = sys.argv[1], int(sys.argv[2])
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
#    that bash script is blocked waiting on us -- must report alive.
bash_alive = m._pid_alive(bash_pid)
print("live bash test script (pid=%d) alive: %s (expect True)" % (bash_pid, bash_alive))
if not bash_alive:
    failures.append("bash-parent")

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
#    NOT alive.
p = subprocess.run([sys.executable, "-c", "pass"])
dead_alive = m._pid_alive(p.pid)
print("just-exited subprocess (pid=%d) alive: %s (expect False)" % (p.pid, dead_alive))
if dead_alive:
    failures.append("dead-pid")

if failures:
    print("FAIL: %s" % ", ".join(failures))
    sys.exit(1)
print("PASS test_pid_alive_diag")
PYEOF
