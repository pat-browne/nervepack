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
    return subprocess.run(["bash", u(script), *args], **kwargs)


def bash_eval(snippet, **kwargs):
    """Run `bash -c <snippet>`. The caller must u()-convert any paths embedded in
    the snippet (this helper can't know which substrings are paths)."""
    return subprocess.run(["bash", "-c", snippet], **kwargs)
