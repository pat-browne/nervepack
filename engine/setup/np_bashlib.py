r"""Runtime bash + path portability for nervepack's Python glue (stdlib, zero-dep).

The runtime mirror of engine/setup/tests/_lib/nptest.py. On Windows the Python glue
(np-mcp-server.py, np-dashboard-server.py, dashboard/build.py) shells out to bash
scripts; two things break, and this module fixes both as a no-op off Windows:

  * a bare ``bash`` resolves to C:\Windows\System32\bash.exe (the WSL stub, no distro
    installed), not Git-bash — System32 wins the Windows PATH. NP_BASH (exported by the
    test runner and the MCP launcher) pins the right interpreter; the fallback prefers a
    Git-bash install.
  * Windows can't CreateProcess a ``.sh`` (WinError 193) and os.path paths are backslash/
    drive form bash can't open. ``argv()`` routes ``.sh`` invocations through bash and
    converts path-shaped args to MSYS form (C:\x -> /c/x). As of phase 9 of the
    bash->Python migration (np_model.py's `agent()`/`complete()` call an
    env-overridable CLAUDE_BIN directly, no bash intermediary), this also covers an
    extensionless file that turns out to be a shebang script (e.g. a test's CLAUDE_BIN
    stub) -- Windows CreateProcess doesn't understand shebangs regardless of
    extension, but sniffing every argv[0] is wasteful, so this only fires for a path
    with no recognized Windows executable extension.
"""
import os
import signal
import subprocess

_WIN_EXE_EXTS = (".exe", ".bat", ".cmd", ".com")


def bash():
    b = os.environ.get("NP_BASH")
    if b:
        return b
    if os.name == "nt":
        for cand in (r"%ProgramFiles%\Git\bin\bash.exe",
                     r"%ProgramFiles(x86)%\Git\bin\bash.exe",
                     r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"):
            cand = os.path.expandvars(cand)
            if os.path.exists(cand):
                return cand
    return "bash"


BASH = bash()


def u(path):
    r"""Native path -> bash (MSYS) form: C:\x -> /c/x. No-op off Windows."""
    if os.name != "nt" or not path:
        return path
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def _pathish(a):
    return isinstance(a, str) and (a.endswith(".sh") or "\\" in a)


def _has_shebang(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def _needs_bash_wrap(head):
    """True if `head` is a script Windows CreateProcess can't exec directly:
    a `.sh` path, or (Windows only) an extensionless/unrecognized-extension
    file that turns out to start with a `#!` shebang line."""
    if not isinstance(head, str):
        return False
    if head.endswith(".sh"):
        return True
    if os.name != "nt":
        return False
    if os.path.splitext(head)[1].lower() in _WIN_EXE_EXTS:
        return False
    return _has_shebang(head)


def _kill_tree(proc):
    """Kill the WHOLE process tree rooted at proc, not just the direct child.
    Windows only: proc must have been started with creationflags=
    CREATE_NEW_PROCESS_GROUP so it (and everything it spawns) shares a
    process-group id that taskkill /T can target."""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   stdin=subprocess.DEVNULL)


def run_killtree(cmd, input=None, stdin=None, cwd=None, env=None, timeout=None, text=True):
    """subprocess.run()-alike whose timeout actually bounds wall-clock time when
    `cmd` spawns a process TREE (bash -> git -> a helper it launches) -- which
    plain subprocess.run(..., timeout=N) does NOT reliably do on Windows.

    subprocess.run's own timeout handling (see CPython subprocess.py) does, on
    a timeout: process.kill() (TerminateProcess on the DIRECT child only) then
    process.communicate() again WITH NO TIMEOUT to drain the captured pipes.
    If any grandchild is still alive and holds the stdout/stderr pipe's write
    end open (an orphaned helper process bash spawned, e.g.), that second
    communicate() blocks forever -- confirmed by reading CPython's own
    subprocess.run source, not inferred. This is the actual mechanism behind
    a real multi-hour Windows CI hang traced to exactly this pattern (a bash
    subprocess run with capture_output=True + timeout=N).

    Fix: spawn the child in its own process group (CREATE_NEW_PROCESS_GROUP on
    Windows, a new session on POSIX) so that on timeout we can kill the ENTIRE
    tree via `taskkill /F /T` (Windows) / killpg (POSIX) before doing any
    further blocking read -- no descendant survives to hold a pipe open.

    Returns a subprocess.CompletedProcess. Raises subprocess.TimeoutExpired
    (same as subprocess.run) on a genuine timeout, so existing
    `except subprocess.TimeoutExpired` call sites need no changes."""
    if input is not None:
        stdin = subprocess.PIPE
    elif stdin is None:
        stdin = subprocess.DEVNULL  # never inherit our own stdin -- see np_implement_suggestion._git()
    popen_kwargs = dict(stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=cwd, env=env, text=text)
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            _kill_tree(proc)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = "" if text else b"", "" if text else b""
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def argv(cmd):
    r"""Normalize a subprocess argv for a Windows Git-bash host (no-op off Windows):
       ["bash", ...]     -> [BASH, ...]        (run via the right bash, not WSL)
       ["x.sh", ...]      -> [BASH, "x.sh", ...]   (Windows can't exec a .sh directly)
       ["<shebang>", ...] -> [BASH, "<shebang>", ...] (Windows-only: an extensionless
                              or non-.exe/.bat/.cmd/.com file starting with `#!`, e.g.
                              a test's CLAUDE_BIN stub)
       anything else      -> unchanged         (python/git/a real .exe/etc.)
    Path-shaped args (.sh paths, or any arg with a backslash) are converted to MSYS
    form. Preserves the argv-list shape (never shell=True) — no injection surface."""
    if not cmd:
        return cmd
    head = cmd[0]
    if head == "bash":
        return [BASH] + [u(a) if _pathish(a) else a for a in cmd[1:]]
    if _needs_bash_wrap(head):
        return [BASH] + [u(a) if _pathish(a) else a for a in cmd]
    return cmd
