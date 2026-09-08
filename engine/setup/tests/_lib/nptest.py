"""Cross-platform helpers for nervepack Python tests (stdlib-only, zero-dep).

On Linux/macOS every function is a no-op pass-through. On a Git-for-Windows host
(the suite runs under MINGW bash, but the Python interpreter is native Windows)
it bridges the two portability gaps that bite a Python test driving bash scripts:

  * Windows cannot CreateProcess a `.sh` file directly (OSError WinError 193,
    "%1 is not a valid Win32 application") — a shebang means nothing to the OS
    loader. Invoke the script through `bash` instead.
  * `os.path` produces Windows-form paths (`C:\\Users\\x`, backslashes). Handed to
    bash (`source`, `[[ -d ]]`, as a script path) the backslashes break and the
    drive-letter form doesn't match what Git-bash `pwd` prints. Convert to MSYS
    form (`/c/Users/x`) — the exact form Git-bash uses internally and emits from
    `pwd`, so both execution AND output-comparison line up.

Usage:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_lib"))
    from nptest import u, sh, bash_eval
"""
import os
import subprocess

_WIN = os.name == "nt"

# The bash interpreter to drive. run-all.sh exports NP_BASH as the exact bash running
# the suite, because a bare "bash" resolves to System32\bash.exe (WSL) on Windows, not
# Git-bash. Fall back to "bash" when run standalone (e.g. a single test invoked directly
# on Linux/macOS).
_BASH = os.environ.get("NP_BASH") or "bash"


def u(path):
    """Native path -> the form bash expects. No-op off Windows.

    `C:\\Users\\x` -> `/c/Users/x` (MSYS form, matches Git-bash `pwd`).
    Already-POSIX paths (e.g. "/no/such/dir") pass through unchanged.
    """
    if not _WIN or path is None:
        return path
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def sh(script, *args, **kwargs):
    """Run a `.sh` script cross-platform: always via `bash`, with the script
    path converted to bash form. Extra positional args are passed to the script.
    kwargs are forwarded to subprocess.run (caller sets capture_output/text/env/
    input). Replaces `subprocess.run([script_path], ...)`, which raises WinError
    193 on Windows."""
    return subprocess.run([_BASH, u(script), *args], **kwargs)


def bash_eval(snippet, **kwargs):
    """Run `bash -c <snippet>`. The caller must u()-convert any paths embedded in
    the snippet (this helper can't know which substrings are paths)."""
    return subprocess.run([_BASH, "-c", snippet], **kwargs)


def git_ignored(repo, rels):
    """The subset of `rels` that git ignores, or an empty set on any git failure.

    Tool scratch lands in the checkout and is git-ignored for exactly the reason
    it should not be scanned by a doc/source guard: nobody wrote it as part of
    the repo and nobody can fix it. A guard that reads it is red locally and
    green in CI, which teaches people to ignore it (#307).

    A filter, never a gate: if git is missing or `repo` is not a repo (several
    callers repoint their REPO at a temp dir), nothing is filtered and the scan
    is exactly what it was.

    `rels` are repo-relative and slash-separated. Returns the same form.
    """
    rels = list(rels)
    if not rels:
        return set()
    # BYTES, not text=True. A text-mode stdin pipe translates "\n" to os.linesep
    # on write, so on Windows git reads "path\r" and matches nothing. That fails
    # open to "nothing is ignored", which reads exactly like a clean scan -- the
    # filter was silently dead on the Windows lane before this.
    try:
        out = subprocess.run(["git", "-C", repo, "check-ignore", "--stdin"],
                             input=("\n".join(rels) + "\n").encode("utf-8"),
                             capture_output=True)
    except OSError:
        return set()
    if out.returncode not in (0, 1):        # 0 = some ignored, 1 = none; >1 = error
        return set()
    return {line.strip().replace(os.sep, "/")
            for line in out.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()}
