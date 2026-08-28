"""Feature-toggle resolver: np_enabled / np_param (formerly bash np-toggle-lib.sh,
retired in phase 18 — this module is now the sole resolver).

Everything that needs a toggle decision imports this in-process (`import
np_toggle`), or calls `np_toggle.py enabled|param` from a shell step; there is no
bash equivalent. Precedence: ~/.config/nervepack/toggles.local ->
engine/setup/toggles.conf -> default-on. stdlib only.
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
import np_dirs
import np_host

_WS = " \t\r\v\f"            # POSIX [[:space:]] minus the per-line newline
_HERE = os.path.dirname(os.path.abspath(__file__))


def _conf_path():
    # Bash default: "$_np_dir/toggles.conf" where _np_dir is the lib's dir (engine/setup).
    return os.environ.get("NP_TOGGLES_CONF") or os.path.join(np_paths.SETUP_DIR, "toggles.conf")


def _local_path():
    # Bash default: "$HOME/.config/nervepack/toggles.local".
    return os.environ.get("NP_TOGGLES_LOCAL") or np_dirs.config_path("toggles.local")


def _content_conf_path():
    """The content overlay's toggle manifest, or "" when there is none.

    This is the layer that makes a preference BOTH portable and personal. The
    local file is portable to nothing (untracked, one machine) and the engine
    file is personal to nobody (committed, shared with every forker). The
    content overlay is a git repo that already syncs across machines and
    already holds everything personal, so the preference belongs there.

    np_content imports np_toggle, so the import has to be lazy or the module
    graph is a cycle. An empty NP_TOGGLES_CONTENT means "no content layer" and
    is how the tests pin the absent case; unset falls through to the resolver.
    """
    env = os.environ.get("NP_TOGGLES_CONTENT")
    if env is not None:
        return env
    try:
        import np_content
        root = np_content.content_dir()
    except Exception:                      # resolver missing, or misconfigured
        return ""
    if not root or os.path.normpath(root) == os.path.normpath(np_paths.REPO_ROOT):
        # A single-repo user's content dir IS the engine root. There is no
        # second layer there, only the same file reached by another name.
        return ""
    return os.path.join(root, "config", "toggles.conf")


def _conf_paths():
    """Every toggle manifest, highest precedence first.

    Readers below take the FIRST match across this chain, which is what gives
    the content layer its precedence. Because _conf_param keeps scanning rows
    after a family matches, a content row may name only the params it changes
    and the engine row still supplies the rest.
    """
    paths = []
    content = _content_conf_path()
    if content and os.path.isfile(content):
        paths.append(content)
    paths.append(_conf_path())
    return paths


def _write_conf_path():
    """Where a shared-scope WRITE lands.

    Once a content toggle file exists, the user has opted into the layer, so a
    dashboard or CLI flip must land there rather than in the engine repo.
    Writing to the engine would be both un-portable to their other machines and
    a personal value committed to a repo other people fork. With no content
    file present this is the engine conf, exactly as before.
    """
    content = _content_conf_path()
    if content and os.path.isfile(content):
        return content
    return _conf_path()


def _local_get(key):
    """Mirror _np_local_get: last `^\\s*key\\s*=value` line wins; value trimmed.

    The key goes into the regex raw (like grep -E), so `.` is a wildcard exactly
    as in bash. A CRLF file's trailing \\r is stripped by the whitespace trim,
    matching sed's `[[:space:]]*$`.
    """
    path = _local_path()
    if not os.path.isfile(path):
        return ""
    try:
        pat = re.compile(r'^[' + _WS + r']*(?:' + key + r')[' + _WS + r']*=')
    except re.error:
        pat = re.compile(r'^[' + _WS + r']*(?:' + re.escape(key) + r')[' + _WS + r']*=')
    val = ""
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if pat.match(line):
                v = line.split("=", 1)[1]          # [^=]* stops at the first '='
                val = v.strip(_WS)                  # last match wins (tail -1)
    return val


def _iter_rows(path):
    """Yield the '|'-split `fields` list for each non-comment row of ONE manifest.
    The row format lives here once -- open newline='' (raw; the file is LF-pinned via
    .gitattributes), strip the trailing newline, skip comment rows (leading '#'), split
    on '|' -- so the five readers below don't each re-implement it (drift between
    all_params and _conf_param would silently desync rendering from resolution). (#176)"""
    if not path or not os.path.isfile(path):
        return
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            yield line.split("|")


def _iter_conf_rows():
    """Rows of every manifest, highest-precedence layer first. First match wins."""
    for path in _conf_paths():
        for fields in _iter_rows(path):
            yield fields


def _conf_state(feature):
    """Mirror _np_conf_state: first non-comment row whose col1 == feature -> col4."""
    for fields in _iter_conf_rows():
        if fields and fields[0] == feature:
            return (fields[3] if len(fields) > 3 else "").strip(" ")  # spaces only
    return ""


def _conf_param(key):
    """Mirror _np_conf_param: feature=before first dot, param=after; scan col5."""
    if "." in key:
        feat, p = key.split(".", 1)
    else:
        feat = p = key
    for fields in _iter_conf_rows():
        if not fields or fields[0] != feat:
            continue
        params = fields[4] if len(fields) > 4 else ""
        for tok in re.split(r'[ ,]+', params):
            if not tok:
                continue
            kv = tok.split("=")                # awk split on '=', take kv[2]
            if kv[0].strip(" ") == p:
                return kv[1] if len(kv) > 1 else ""
    return ""


def enabled(feature):
    """np_enabled: True if on. Fail-open (unknown -> on). Checks the feature's OWN
    conf state first (even when it contains a dot and is itself a declared row,
    e.g. "maintain.refine"), THEN falls back to the truncated parent family's
    conf state — never the reverse, which was the bug: the parent fallback used
    to run with `feat` already overwritten by the truncated name, so a declared
    dotted feature's own conf row was unreachable."""
    feat = feature
    fam = None
    v = _local_get(feat)
    if not v and "." in feat:
        fam = feat.split(".", 1)[0]
        v = _local_get(fam)
    if not v:
        v = _conf_state(feature)
    if not v and "." in feature:
        v = _conf_state(fam if fam is not None else feature.split(".", 1)[0])
    if not v:
        v = "on"
    return v == "on"


def param(key, default):
    """np_param: local exact -> conf param -> default."""
    v = _local_get(key)
    if not v:
        v = _conf_param(key)
    if not v:
        v = default
    return v


def signal(sid, message):
    """np_signal: append a fire-marker line to the session signal log, gated
    on evaluator.signals. Fail-open (any OSError -> no-op). (Formerly the
    np_signal function in the retired np-toggle-lib.sh.)"""
    if not enabled("evaluator.signals"):
        return
    d = os.environ.get("NP_SIGNAL_DIR") or np_dirs.cache_path("session-signals")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid.replace("/", "_") + ".log"), "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


# --- write + status surface (ported from nervepack-toggle.sh) ---------------
# The FULL write surface now lives here (phase 14): local-file writes, shared
# toggles.conf state/param edits + path-limited git commit/push, and the managed
# allowlist install/remove (90/91-*.sh ported to stdlib json). np_toggle.py is the
# single source of truth — the MCP server and dashboard call these in-process, and
# `cli.py toggle ...` dispatches to cli()/menu()/np_toggle_audit. See is_local_set(),
# flip(), managed(), install_permissions()/remove_permissions().
def scope(family):
    """The conf 'scope' column ($2) for a family, or '' if absent. Mirrors _scope."""
    for fields in _iter_conf_rows():
        if fields and fields[0] == family:
            return fields[1].strip(" ") if len(fields) > 1 else ""
    return ""


def features():
    """Declared feature names (conf rows with >=4 columns). Mirrors _features."""
    out = []
    for fields in _iter_conf_rows():
        if len(fields) >= 4:
            name = fields[0].strip(" ")
            # A feature declared in both the content layer and the engine is
            # ONE feature, listed once. Without this the toggle menu would show
            # every overridden family twice.
            if name not in out:
                out.append(name)
    return out


def all_params(family):
    """Every declared param for `family` (conf column 5) in one shot, each
    overlaid by its LOCAL override when one is set. Returns dict[bare_key] ->
    raw string value (bare_key has no family prefix — e.g. 'dashboard_port',
    not 'evaluator.dashboard_port'). Mirrors _conf_param's parsing but for every
    key of one family at once — param() only fetches a single key, which is
    enough for a runtime check but not for rendering an entire panel."""
    out = {}
    for path in _conf_paths():                 # highest-precedence layer first
        for fields in _iter_rows(path):
            if not fields or fields[0] != family:
                continue
            params = fields[4] if len(fields) > 4 else ""
            for tok in re.split(r'[ ,]+', params):
                if not tok:
                    continue
                kv = tok.split("=")
                key = kv[0].strip(" ")
                if not key or key in out:
                    continue                   # a higher layer already set it
                conf_val = kv[1] if len(kv) > 1 else ""
                out[key] = _local_get(family + "." + key) or conf_val
            break                              # only the first matching row PER FILE
    return out


def set_local(key, value):
    """Write key=value to toggles.local, dropping any prior line for key. Mirrors
    _set_local byte-for-byte: kept lines verbatim, then the new line appended last."""
    path = _local_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:                                        # mirror _local_get: a key with regex
        pat = re.compile(r'^[' + _WS + r']*(?:' + key + r')[' + _WS + r']*=')
    except re.error:                            # metachars (or a '.' wildcard) must
        pat = re.compile(r'^[' + _WS + r']*(?:' + re.escape(key) + r')[' + _WS + r']*=')  # not crash the write path (#172)
    kept = []
    if os.path.isfile(path):
        with open(path, "r", newline="") as f:
            for line in f:
                if not pat.match(line.rstrip("\n")):
                    kept.append(line)
    with open(path, "w", newline="") as f:
        f.writelines(kept)
        f.write(key + "=" + value + "\n")


def is_local_set(feat):
    """True when setting `feat` is a pure local-file write (portable, bash-free).
    A param (dotted) is local unless its family is shared; a bare feature is local
    only when its family scope is 'local' (shared -> conf+commit, managed -> scripts)."""
    fam = feat.split(".", 1)[0]
    sc = scope(fam)
    return sc != "shared" if "." in feat else sc == "local"


def status_lines():
    """The `status` table, byte-identical to nervepack-toggle.sh's printf layout."""
    lines = ["%-14s %-7s %s" % ("FEATURE", "STATE", "SCOPE")]
    for feat in features():
        lines.append("%-14s %-7s %s" % (feat, "on" if enabled(feat) else "off", scope(feat)))
    return lines


def _is_declared(feat):
    """Membership in the declared feature set. Mirrors _is_declared."""
    return feat in features()


def _atomic_write(path, text):
    """Write `text` to `path` via temp-file + os.replace, in path's own dir.
    Mirrors the bash `> tmp && mv` pattern (never a partial file at `path`)."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".np-toggle-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_conf_state(feature, state):
    """Rewrite column $4 (state) of the matching toggles.conf row. Mirrors
    _set_conf_state: comment rows verbatim; a row whose col1 == feature has its
    4th field replaced (OFS='|'); every other row is preserved byte-for-byte.

    Writes land in the content layer once one exists -- see _write_conf_path."""
    path = _write_conf_path()
    if not os.path.isfile(path):
        return
    out = []
    with open(path, "r", newline="") as f:
        for line in f:
            body = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', body):
                out.append(line)
                continue
            fields = body.split("|")
            if fields and fields[0] == feature:
                while len(fields) < 4:
                    fields.append("")           # awk $4=s auto-extends NF
                fields[3] = state
                nl = line[len(body):]           # preserve original line terminator
                out.append("|".join(fields) + nl)
            else:
                out.append(line)                # unmodified -> awk prints $0 verbatim
    _atomic_write(path, "".join(out))


def set_conf_param(key, value):
    """In the row for `feat` (before the first dot), replace param `k`'s value in
    column $5, or append `k=value`. Mirrors _set_conf_param: params are the
    space/comma-separated k=v tokens of column 5, re-joined with single spaces."""
    if "." in key:
        feat, pkey = key.split(".", 1)
    else:
        feat = pkey = key
    path = _write_conf_path()
    if not os.path.isfile(path):
        return
    out = []
    with open(path, "r", newline="") as f:
        for line in f:
            body = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', body):
                out.append(line)
                continue
            fields = body.split("|")
            if not fields or fields[0] != feat:
                out.append(line)
                continue
            while len(fields) < 5:
                fields.append("")
            params = fields[4]
            toks = []
            found = False
            for tok in re.split(r'[ ,]+', params):
                if tok == "":                   # awk: if(a[i]=="") continue
                    continue
                if tok.split("=")[0] == pkey:
                    tok = pkey + "=" + value
                    found = True
                toks.append(tok)
            if not found:
                toks.append(pkey + "=" + value)
            fields[4] = " ".join(toks)
            nl = line[len(body):]
            out.append("|".join(fields) + nl)
    _atomic_write(path, "".join(out))


def commit_shared(message, np_root=None):
    """Path-limited commit+push of toggles.conf (issue-#11 discipline: never a bare
    `git commit` that would sweep a concurrent session's staged index). Best-effort,
    each step swallowed; a no-op when NP_TOGGLE_NO_COMMIT=1. git is routed through
    np_bashlib.argv() for the Windows Git-bash lane."""
    if os.environ.get("NP_TOGGLE_NO_COMMIT") == "1":
        return
    import np_bashlib
    conf = _write_conf_path()
    # Commit in the repo that OWNS the file. Once writes land in the content
    # overlay, committing from the engine root would stage nothing and push an
    # unrelated branch.
    np = np_root or os.path.dirname(conf) or np_paths.REPO_ROOT

    def _git(args):
        try:
            return subprocess.run(np_bashlib.argv(["git", "-C", np] + args),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        except OSError:
            return None

    _git(["add", conf])
    r = _git(["commit", "-q", "-m", message, "--", conf])
    if r is not None and r.returncode == 0:
        _git(["push", "-q", "origin", "HEAD:main"])


# --- managed allowlist (90/91-*.sh ported to stdlib json) -------------------
def _allowlist_path():
    return os.path.join(np_paths.SETUP_DIR, "allowlist-entries.txt")


def _settings_path():
    """The host's settings file, resolved once in np_host: CLAUDE_SETTINGS ->
    adapter.json `paths.settings` -> ~/.claude/settings.json."""
    return np_host.settings_path()


def _read_allowlist():
    """One entry per non-empty line, order preserved. \\r stripped (CRLF-safe)."""
    path = _allowlist_path()
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            entry = line.rstrip("\n").rstrip("\r")
            if entry != "":
                out.append(entry)
    return out


def _load_settings(path):
    """Missing file -> {} (first install, bash `echo '{}'`). A PRESENT but malformed
    file raises (json.JSONDecodeError/ValueError) and propagates -- callers must
    fail-safe rather than overwrite it (the phase-13 np_hook lesson: a malformed
    settings.json once wiped the user's permissions). Mirrors the old `jq … && mv`,
    where a parse error skipped the mv and left settings.json intact."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _dump_settings(path, data):
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


def install_permissions():
    """Union allowlist-entries.txt into settings.json .permissions.allow (append
    entries not already present, preserving existing order + every other settings
    key). Atomic. FAIL-SAFE: a present-but-malformed settings.json raises before any
    write, leaving the file untouched. Port of 90-install-claude-permissions.sh."""
    path = _settings_path()
    entries = _read_allowlist()
    data = _load_settings(path)                 # raises on malformed present file
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    allow = perms.get("allow")
    if not isinstance(allow, list):
        allow = []
    present = set(allow)
    perms["allow"] = list(allow) + [e for e in entries if e not in present]
    _dump_settings(path, data)


def remove_permissions():
    """Set-minus: drop exactly the allowlist-entries.txt entries from
    .permissions.allow, leaving hand-added rules intact. No-op if settings.json is
    absent. FAIL-SAFE on a malformed present file (raises, no clobber). Port of
    91-remove-claude-permissions.sh."""
    path = _settings_path()
    if not os.path.exists(path) or not os.path.isfile(_allowlist_path()):
        return
    managed_set = set(_read_allowlist())
    data = _load_settings(path)                 # raises on malformed present file
    perms = data.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
        perms["allow"] = [a for a in perms["allow"] if a not in managed_set]
    _dump_settings(path, data)


def managed(feat, state):
    """Managed-scope write (allowlist): install/remove permissions, then set_local.
    NP_TOGGLE_NO_MANAGED=1 -> just set_local (skip the permission scripts). Each
    permission op is best-effort (bash `|| true`), so a fail-safe abort inside
    install_permissions() never blocks the local-state write. Mirrors _managed."""
    if os.environ.get("NP_TOGGLE_NO_MANAGED") == "1":
        set_local(feat, state)
        return
    try:
        if state == "on":
            install_permissions()
        else:
            remove_permissions()
    except Exception:
        pass
    set_local(feat, state)


def flip(feat, state):
    """Route a feature flip to the right write for its family scope. Mirrors flip:
    a declared feature keys on its own name; otherwise the truncated family. Returns
    'feat -> state'."""
    fam = feat if _is_declared(feat) else feat.split(".", 1)[0]
    sc = scope(fam)
    if sc == "managed":
        managed(feat, state)
    elif sc == "local":
        set_local(feat, state)
    else:                                       # shared or "" (unknown -> shared)
        if feat != fam:
            set_local(feat, state)
        else:
            set_conf_state(feat, state)
            commit_shared("toggle(%s): %s" % (feat, state))
    return "%s -> %s" % (feat, state)


# --- interactive menu (nervepack-toggle-menu.sh ported to input()) ----------
def _render_menu(feats, out=None):
    out = out or sys.stdout
    out.write("Nervepack feature toggles — number to flip, 's' save & quit, 'q' quit\n")
    for i, f in enumerate(feats, 1):
        badge = "[x]" if enabled(f) else "[ ]"
        out.write("  %2d) %s %s\n" % (i, badge, f))


def menu(feats=None):
    """Numbered feature picker. Number flips that feature IN-PROCESS (flip()), 'q'/'s'
    quit, non-numeric / out-of-range / empty input re-renders. Reads via input();
    EOF exits. Mirrors nervepack-toggle-menu.sh's read-loop + input validation."""
    feats = features() if feats is None else feats
    while True:
        _render_menu(feats)
        try:
            choice = input("> ")
        except EOFError:
            break
        choice = choice.strip()                 # bash `read` strips surrounding IFS ws
        if choice in ("q", "s"):
            return 0
        if choice == "" or not choice.isdigit():
            continue                            # '' | *[!0-9]* -> re-render
        idx = int(choice) - 1
        if idx < 0 or idx >= len(feats):
            continue
        f = feats[idx]
        ns = "off" if enabled(f) else "on"
        flip(f, ns)
    return 0


def cli(argv):
    """`cli.py toggle ...` entry: status | param <k> <v> | audit | <feature> [on|off]
    | (empty/menu). Ports nervepack-toggle.sh's top-level case. Returns an exit code;
    emits LF (Windows Python would otherwise translate \\n -> \\r\\n)."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(newline="\n")
        except (ValueError, OSError):
            pass
    cmd = argv[0] if argv else ""
    if cmd == "" or cmd == "menu":
        return menu()
    if cmd == "status":
        sys.stdout.write("\n".join(status_lines()) + "\n")
        return 0
    if cmd == "param":
        key = argv[1] if len(argv) > 1 else ""
        value = argv[2] if len(argv) > 2 else ""
        if scope(key.split(".", 1)[0]) == "shared":
            set_conf_param(key, value)
            commit_shared("toggle(%s): %s" % (key, value))
        else:
            set_local(key, value)
        sys.stdout.write("%s = %s\n" % (key, value))
        return 0
    if cmd == "audit":
        import np_toggle_audit
        return np_toggle_audit.run()
    feat = cmd
    state = argv[1] if len(argv) > 1 else ""
    if state == "":
        sys.stdout.write("%s: %s\n" % (feat, "on" if enabled(feat) else "off"))
        return 0
    if state not in ("on", "off"):
        sys.stderr.write("usage: cli.py toggle <feature> on|off\n")
        return 2
    sys.stdout.write(flip(feat, state) + "\n")
    return 0


if __name__ == "__main__":
    # CLI mirror (the setup steps call `enabled`; handy for debugging).
    #   np_toggle.py enabled <feature>      -> prints on/off, exits 0/1
    #   np_toggle.py param   <key> <default>-> prints value (no newline)
    # Emit LF, not CRLF: native-Windows Python translates \n -> \r\n in text mode,
    # which would make every line differ from bash's LF output under Git-bash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "enabled":
        ok = enabled(sys.argv[2])
        sys.stdout.write("on" if ok else "off")
        sys.exit(0 if ok else 1)
    elif cmd == "param":
        sys.stdout.write(param(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
    elif cmd == "status":
        sys.stdout.write("\n".join(status_lines()) + "\n")
    elif cmd == "set-local":
        set_local(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "scope":
        sys.stdout.write(scope(sys.argv[2]) + "\n")
    else:
        sys.stderr.write("usage: np_toggle.py enabled <feature> | param <key> <default> "
                         "| status | set-local <key> <value> | scope <family>\n")
        sys.exit(2)
