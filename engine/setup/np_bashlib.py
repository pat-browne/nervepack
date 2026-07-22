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
