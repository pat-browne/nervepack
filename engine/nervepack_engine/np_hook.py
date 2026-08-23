"""Register nervepack lifecycle hooks in ~/.claude/settings.json -- the
stdlib-json port of the retired bash hook-registration lib's np_register_hook
(phase 13 of the bash->Python CLI migration). Replaces the 11 `NN-install-*.sh`
hook installers + that sourced bash lib with one declarative manifest
(hooks.manifest) driven by install_hooks().

register() mirrors np_register_hook's settings.json shape exactly (no jq, no
third-party deps -- stdlib json only). The one deliberate generalization: the
dedup key is (matcher, base), not base alone. Keying on the pair is what lets
53's two lesson-guard matchers (Bash + Read) coexist in one event while the
empty-matcher bucket reproduces the old np_register_hook behavior verbatim.

register-by-basename: before adding an entry, drop any existing entry in the
same event AND matcher whose command references the same nervepack script
(dedup key). Re-running after a script MOVED (setup/ -> engine/setup/) REPLACES
the stale entry; re-running unchanged is a no-op. A CLI-dispatched hook
("... nervepack_engine/cli.py <group> <name> ...") keys on the full
"cli.py <group> <name>" tail -- every CLI hook shares the literal file cli.py,
so keying on the filename alone would let two distinct hooks collide.

Windows hook shim: Claude Code on Windows runs hook commands via PowerShell,
which can't execute a bare `~/...sh &` string, so on a Git-for-Windows host the
command is routed through bash. NP_HOOK_WRAP forces it (1=on, 0=off) for tests;
default auto-detects a Git-bash kernel (uname MINGW/MSYS/CYGWIN) and leaves
Linux/macOS commands verbatim. Wrapping happens AFTER computing `base` so the
dedup key stays the script basename (the wrapper still contains it). nervepack's
own hook commands are single-quote-free, so single-quote wrapping is safe.
"""
import os
import sys
# self-bootstrap (phase 20b-2): engine/setup holds np_paths, np_bashlib, the config
# files, and the stayed sibling modules; add it so this relocated module resolves them
# whether imported in-process or run standalone. Its own dir (nervepack_engine) is
# already on sys.path[0] when run directly, so moved-sibling imports resolve too.
_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import json
import os
import re
import subprocess
import sys
import tempfile

import np_paths
import np_host

_MANIFEST = os.path.join(np_paths.SETUP_DIR, "hooks.manifest")

# A CLI-dispatched hook dedups on the full "cli.py <group> <name>" tail. The second
# token is optional so a TOP-LEVEL command (`cli.py sync` / `cli.py sync exit`,
# phase 17) keys on "cli.py sync" (or "cli.py sync exit") rather than falling back to
# the shared "cli.py" filename — which would collide with every other CLI hook. The
# optional group is greedy, so a two-token hook (`cli.py hook <name>`) still keys on
# the full three-token tail exactly as before.
_CLI_TAIL = re.compile(r"nervepack_engine/cli\.py\s+[\w-]+(?:\s+[\w-]+)?")
# Else the first *.sh / *.py filename token in the command.
_SCRIPT = re.compile(r"[A-Za-z0-9._-]+\.(?:sh|py)")

# 53's legacy migration cleanup: one-off purges of pre-merge hook commands that
# register-by-basename can't recognize as "the same hook" (different filename).
_LEGACY_PURGES = (
    ("PreToolUse", ("playbook-guard.sh", "lesson-guard.sh")),
    ("UserPromptSubmit", ("playbook-recall.sh", "strategy-recall.sh", "lesson-recall.sh")),
    # Phase 17 retired 40-sync-nervepack.sh for np_sync.py (`cli.py sync`). The
    # dedup key changed from a script basename to a "cli.py sync" tail, so
    # register-by-basename never recognized the old SessionStart/SessionEnd
    # entries as the same hook -- any host that onboarded before phase 17 and
    # then fast-forwarded past it was left running BOTH the dead script (a
    # silent no-op each session) and the new cli.py hook, until a manual
    # `cli.py setup install-hooks` (or an explicit purge) cleaned it up.
    ("SessionStart", ("40-sync-nervepack.sh",)),
    ("SessionEnd", ("40-sync-nervepack.sh",)),
)


def _settings_path(settings_path=None):
    if settings_path:
        return settings_path
    return np_host.settings_path()


def _load(path):
    # Missing file -> fresh {} (first install). A PRESENT but malformed file
    # raises (ValueError) and propagates: callers must fail-safe rather than
    # overwrite it -- matching the old `jq … > tmp && mv` behavior, where a jq
    # parse error skipped the mv and preserved the user's settings.json intact.
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _dump(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _hook_basename(cmd):
    """Extract the dedup key from a hook command string (verbatim from bash)."""
    m = _CLI_TAIL.search(cmd)
    if m:
        return m.group(0)
    m = _SCRIPT.search(cmd)
    return m.group(0) if m else ""


def _wrap(cmd, wrap=None, uname=None):
    """Apply the Windows Git-bash shim if requested/auto-detected."""
    mode = os.environ.get("NP_HOOK_WRAP")
    if wrap is not None:
        mode = wrap
    if mode is None:
        mode = "auto"
    mode = str(mode)
    if mode == "auto":
        # The kernel string is authoritative: an explicitly-injected `uname` (tests)
        # decides on its own, and real detection routes the os.name=="nt" fallback
        # THROUGH _uname_s() (which returns "Windows" when `uname -s` is unreachable
        # on a native-Windows host). Keeping the os.name check out of _wrap is what
        # lets an injected uname="Linux" stay verbatim even when the test process
        # itself runs on Windows (phase-13 Windows-lane finding).
        kernel = uname if uname is not None else _uname_s()
        mode = "1" if kernel.startswith(("MINGW", "MSYS", "CYGWIN", "Windows")) else "0"
    if mode == "1":
        return "bash -lc '%s'" % cmd
    return cmd


def _uname_s():
    """`uname -s` (parity with the bash original + np_scheduler_install.uname_s):
    a Git-for-Windows host reports MINGW*/MSYS*/CYGWIN*. Falls back to a "Windows"
    sentinel when uname is unavailable but os.name says we're on Windows, and to
    "" elsewhere (Linux/macOS uname is always reachable)."""
    try:
        r = subprocess.run(["uname", "-s"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "Windows" if os.name == "nt" else ""


def _entry_joined(entry):
    return " ".join(h.get("command", "") for h in entry.get("hooks", []) or [])


def register(event, command, matcher="", settings_path=None, wrap=None, uname=None):
    """Register a hook, replacing any stale (matcher, base) entry in the event."""
    path = _settings_path(settings_path)
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    lst = hooks.setdefault(event, [])
    base = _hook_basename(command)
    cmd = _wrap(command, wrap=wrap, uname=uname)
    # Drop existing entries in this event whose matcher matches AND whose joined
    # commands reference the same base (base != "" guard).
    kept = []
    for entry in lst:
        same_matcher = entry.get("matcher", "") == matcher
        if same_matcher and base and base in _entry_joined(entry):
            continue
        kept.append(entry)
    kept.append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})
    hooks[event] = kept
    _dump(path, data)
    return cmd


def purge(event, substrings, matcher=None, settings_path=None):
    """Drop entries in `event` whose joined commands contain any substring.

    Optionally scoped to a specific matcher. Used for 53's one-off legacy
    migration cleanup (pre-merge playbook/strategy/bash-lesson hooks).
    """
    path = _settings_path(settings_path)
    data = _load(path)
    lst = data.get("hooks", {}).get(event)
    if not lst:
        return
    kept = []
    for entry in lst:
        if matcher is not None and entry.get("matcher", "") != matcher:
            kept.append(entry)
            continue
        joined = _entry_joined(entry)
        if any(sub in joined for sub in substrings):
            continue
        kept.append(entry)
    data["hooks"][event] = kept
    _dump(path, data)


NP_DIR_TOKEN = "{NP_DIR}"

# A resolved root is interpolated into a command that bash later evaluates as an
# UNQUOTED word, so anything the shell would act on has to be rejected rather
# than substituted. Whitespace is in the set for the same reason and is the more
# likely case in practice: `/home/my user/nervepack` would split into two argv
# tokens long before anyone tried `$(id)`.
#
# Quoting the path instead was considered and rejected. `_CLI_TAIL` above keys
# the dedup on `cli.py` followed by WHITESPACE, so `"…/cli.py" sync` would stop
# matching and every hook would re-register under a different key on the next
# sync. Failing loudly at install time is both safer and easier to act on than a
# command that is subtly wrong.
_UNSAFE_IN_ROOT = re.compile(r"""[\s"'\\$`;&|<>()*?\[\]{}!#]""")
# A tilde is only special at the START of a word. Bash performs tilde expansion
# on `~/x` and on `~user/x`, and leaves a tilde anywhere else in a word literal.
#
# Rejecting it everywhere broke Windows outright: 8.3 short paths are the DEFAULT
# for a profile whose name exceeds eight characters, so a GitHub Windows runner
# resolves its temp directory to C:\Users\RUNNER~1\... and every install there
# raised. The clean-clone test on #296 is what found it, which is the entire
# reason that test exists.
_LEADING_TILDE = re.compile(r"^~")


# Absolute means absolute IN THE STRING, judged the same way on every platform.
# `os.path.isabs` cannot be used here: on Windows Python it rejects "/opt/x" for
# having no drive letter, so the identical root would validate on Linux and fail
# on the Windows lane. That is precisely the class of platform-dependent
# assumption #257 exists to remove, and the check for it had one.
#
# The judgement is about a string that will be embedded in a bash command on the
# TARGET machine, not about the machine running the check, so it must not consult
# the local platform at all.
_ABSOLUTE_ROOT = re.compile(r"^(/|[A-Za-z]:/)")


class UnsafeRootError(Exception):
    """The resolved engine root cannot be expressed in a manifest command."""


def main_worktree_root(root):
    """The MAIN checkout, even when called from a linked worktree.

    This matters only because #257 made the hook commands follow the resolved
    root. Registering from `.worktrees/feat-x` would otherwise write 26 hook
    commands pointing INTO that worktree, and the next `git worktree remove`
    would leave every hook on the machine pointing at a deleted directory --
    which, because hooks fail open, would be silent.

    A linked worktree's `.git` is a FILE containing `gitdir: <main>/.git/worktrees/<name>`.
    Walking up three levels from there lands on the main checkout. A normal
    checkout has `.git` as a directory and is returned unchanged, as is anything
    that is not a git checkout at all -- this is a best-effort correction, never
    a precondition.
    """
    dot_git = os.path.join(root, ".git")
    if not os.path.isfile(dot_git):
        return root
    try:
        with open(dot_git, encoding="utf-8") as fh:
            line = fh.read().strip()
    except OSError:
        return root
    if not line.startswith("gitdir:"):
        return root
    target = line.split(":", 1)[1].strip()
    if not os.path.isabs(target):
        target = os.path.normpath(os.path.join(root, target))
    # <main>/.git/worktrees/<name> -> <main>
    candidate = os.path.dirname(os.path.dirname(os.path.dirname(target)))
    if os.path.isdir(os.path.join(candidate, ".git")):
        return candidate
    return root


def _repo_root_for_commands(root=None):
    """The engine repo root as it should appear inside a hook command string.

    Resolved by np_paths from ITS OWN file location, so a clone at /opt/nervepack
    or D:\\src\\nervepack gets its own path. Nothing here reads $HOME or assumes
    ~/Code/nervepack -- that assumption is exactly what #257 removed.

    Backslashes become forward slashes. These commands are routed through bash on
    a Git-bash host, where a backslash is an escape character rather than a
    separator, and Git-bash accepts C:/Users/... perfectly well. This is also the
    S1075 sub-rule in practice: the separator is not hardcoded per-platform, it is
    normalised to the one form the consumer of this string understands.
    """
    resolved = main_worktree_root(root or np_paths.REPO_ROOT)
    if not resolved or not str(resolved).strip():
        # np_paths computes REPO_ROOT from its own __file__, so this should be
        # unreachable. Checked anyway because the failure it prevents is the one
        # this whole change is about: an empty root substitutes silently and
        # registers 26 hooks pointing at /engine/..., which fail open and say
        # nothing.
        raise UnsafeRootError(
            "the engine root resolved to nothing, so hook commands would point "
            "at /engine/... and fail open silently")
    resolved = str(resolved).replace("\\", "/")
    # BEFORE the absolute check, deliberately. A leading tilde also fails
    # "is it absolute", so with the checks the other way round this branch was
    # unreachable and `~/Code/nervepack` - the exact string #295 removed from the
    # manifest - reported only "not absolute". True, and useless: it says nothing
    # about why passing a tilde path here is a mistake.
    if _LEADING_TILDE.match(resolved):
        raise UnsafeRootError(
            "the engine root %r starts with '~', which bash would expand to a "
            "home directory. Pass the resolved path instead." % resolved)
    if not _ABSOLUTE_ROOT.match(resolved):
        raise UnsafeRootError(
            "the engine root %r is not absolute; a relative path in a hook "
            "command resolves against whatever directory the session started in"
            % resolved)
    bad = _UNSAFE_IN_ROOT.search(resolved)
    if bad:
        raise UnsafeRootError(
            "the engine root %r contains %r, which bash would act on: these "
            "commands are interpolated unquoted. Move the checkout somewhere "
            "without shell metacharacters or whitespace." % (resolved, bad.group(0)))
    return resolved


def substitute_root(command, root=None):
    """Replace {NP_DIR} in one manifest command with the resolved repo root."""
    return command.replace(NP_DIR_TOKEN, _repo_root_for_commands(root))


def read_manifest(manifest_path=None, root=None):
    """Yield (event, matcher, command) rows from hooks.manifest, in file order.

    {NP_DIR} is substituted here rather than at registration, so every consumer
    of read_manifest -- the installer, the doctor's drift check, the tests -- sees
    the same command string that lands in settings.json. Two places doing this
    substitution would eventually disagree about one row.
    """
    path = manifest_path or _MANIFEST
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            event, matcher, command = parts
            rows.append((event.strip(), matcher.strip(),
                         substitute_root(command.strip(), root)))
    return rows


def install_hooks(settings_path=None, manifest_path=None, wrap=None, uname=None):
    """Driver: run the 53 legacy purges, then register every manifest row in order."""
    # Fail-safe pre-flight: never overwrite a PRESENT-but-malformed settings.json
    # (that would silently wipe the user's permissions/model/env). Abort loudly and
    # leave the file untouched -- the old jq path preserved it on a parse error too.
    path = _settings_path(settings_path)
    if os.path.exists(path):
        try:
            _load(path)
        except (OSError, ValueError) as e:
            sys.stderr.write(
                "np_hook: refusing to modify malformed settings file %s (%s) -- "
                "fix it and re-run install-hooks\n" % (path, e))
            return 1
    for event, substrings in _LEGACY_PURGES:
        purge(event, substrings, settings_path=settings_path)
    # Say which root the 26 commands were built from. Without it, diagnosing a
    # hook that does not fire means opening ~/.claude/settings.json by hand to
    # find out where it points - and "points somewhere unexpected" is the exact
    # failure this change exists to remove.
    sys.stderr.write("np_hook: registering hooks rooted at %s\n"
                     % _repo_root_for_commands())
    for event, matcher, command in read_manifest(manifest_path):
        register(event, command, matcher, settings_path=settings_path, wrap=wrap, uname=uname)
    return 0
