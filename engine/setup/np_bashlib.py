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
    converts path-shaped args to MSYS form (C:\x -> /c/x).
"""
import os


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


def argv(cmd):
    r"""Normalize a subprocess argv for a Windows Git-bash host (no-op off Windows):
       ["bash", ...]  -> [BASH, ...]           (run via the right bash, not WSL)
       ["x.sh", ...]  -> [BASH, "x.sh", ...]   (Windows can't exec a .sh directly)
       anything else  -> unchanged             (python/git/etc.)
    Path-shaped args (.sh paths, or any arg with a backslash) are converted to MSYS
    form. Preserves the argv-list shape (never shell=True) — no injection surface."""
    if not cmd:
        return cmd
    head = cmd[0]
    if head == "bash":
        return [BASH] + [u(a) if _pathish(a) else a for a in cmd[1:]]
    if isinstance(head, str) and head.endswith(".sh"):
        return [BASH] + [u(a) if _pathish(a) else a for a in cmd]
    return cmd
