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
import json
import os
import re
import subprocess
import sys
import tempfile

import np_paths

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
)


def _settings_path(settings_path=None):
    if settings_path:
        return settings_path
    env = os.environ.get("CLAUDE_SETTINGS")
    if env:
        return env
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".claude", "settings.json")


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


def read_manifest(manifest_path=None):
    """Yield (event, matcher, command) rows from hooks.manifest, in file order."""
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
            rows.append((event.strip(), matcher.strip(), command.strip()))
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
    for event, matcher, command in read_manifest(manifest_path):
        register(event, command, matcher, settings_path=settings_path, wrap=wrap, uname=uname)
    return 0
