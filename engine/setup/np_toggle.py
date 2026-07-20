"""Pure-Python port of np-toggle-lib.sh's np_enabled / np_param.

Parity-locked to the bash original by tests/mcp/parity/test_toggle_parity.sh:
byte-identical decision + exit code across an input table. The long-running MCP
server calls these in-process (`import np_toggle`) so it needs no bash subprocess
per request; the bash lib stays the source of truth for hot-path hooks/crons.
See the git-for-windows-free MCP design spec (overlay docs/superpowers/specs/).

Mirrors the bash precedence exactly: ~/.config/nervepack/toggles.local
-> engine/setup/toggles.conf -> default-on. stdlib only.
"""
import os
import re
import sys

_WS = " \t\r\v\f"            # POSIX [[:space:]] minus the per-line newline
_HERE = os.path.dirname(os.path.abspath(__file__))


def _conf_path():
    # Bash default: "$_np_dir/toggles.conf" where _np_dir is the lib's dir (engine/setup).
    return os.environ.get("NP_TOGGLES_CONF") or os.path.join(_HERE, "toggles.conf")


def _local_path():
    # Bash default: "$HOME/.config/nervepack/toggles.local".
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.environ.get("NP_TOGGLES_LOCAL") or os.path.join(
        home, ".config", "nervepack", "toggles.local")


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


def _conf_state(feature):
    """Mirror _np_conf_state: first non-comment row whose col1 == feature -> col4."""
    path = _conf_path()
    if not os.path.isfile(path):
        return ""
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            fields = line.split("|")
            if fields and fields[0] == feature:
                col = fields[3] if len(fields) > 3 else ""
                return col.strip(" ")              # gsub(/^ +| +$/) — spaces only
    return ""


def _conf_param(key):
    """Mirror _np_conf_param: feature=before first dot, param=after; scan col5."""
    if "." in key:
        feat, p = key.split(".", 1)
    else:
        feat = p = key
    path = _conf_path()
    if not os.path.isfile(path):
        return ""
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            fields = line.split("|")
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
    on evaluator.signals. Fail-open (any OSError -> no-op), mirroring the
    bash original in np-toggle-lib.sh."""
    if not enabled("evaluator.signals"):
        return
    d = os.environ.get("NP_SIGNAL_DIR") or os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"),
        ".cache", "nervepack", "session-signals")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid.replace("/", "_") + ".log"), "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


# --- write + status surface (ported from nervepack-toggle.sh) ---------------
# Only the LOCAL-file write (_set_local) and the status table are ported here.
# Shared-feature writes (toggles.conf + git commit/push) and managed-permission
# scripts stay bash — the MCP server routes those to nervepack-toggle.sh when bash
# is available. See is_local_set() and np-mcp-server.py _tool_toggle.
def scope(family):
    """The conf 'scope' column ($2) for a family, or '' if absent. Mirrors _scope."""
    path = _conf_path()
    if not os.path.isfile(path):
        return ""
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            fields = line.split("|")
            if fields and fields[0] == family:
                return fields[1].strip(" ") if len(fields) > 1 else ""
    return ""


def features():
    """Declared feature names (conf rows with >=4 columns). Mirrors _features."""
    path = _conf_path()
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            fields = line.split("|")
            if len(fields) >= 4:
                out.append(fields[0].strip(" "))
    return out


def all_params(family):
    """Every declared param for `family` (conf column 5) in one shot, each
    overlaid by its LOCAL override when one is set. Returns dict[bare_key] ->
    raw string value (bare_key has no family prefix — e.g. 'dashboard_port',
    not 'evaluator.dashboard_port'). Mirrors _conf_param's parsing but for every
    key of one family at once — param() only fetches a single key, which is
    enough for a runtime check but not for rendering an entire panel."""
    path = _conf_path()
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r'^[' + _WS + r']*#', line):
                continue
            fields = line.split("|")
            if not fields or fields[0] != family:
                continue
            params = fields[4] if len(fields) > 4 else ""
            for tok in re.split(r'[ ,]+', params):
                if not tok:
                    continue
                kv = tok.split("=")
                key = kv[0].strip(" ")
                if not key:
                    continue
                conf_val = kv[1] if len(kv) > 1 else ""
                out[key] = _local_get(family + "." + key) or conf_val
            break
    return out


def set_local(key, value):
    """Write key=value to toggles.local, dropping any prior line for key. Mirrors
    _set_local byte-for-byte: kept lines verbatim, then the new line appended last."""
    path = _local_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pat = re.compile(r'^[' + _WS + r']*(?:' + key + r')[' + _WS + r']*=')
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


if __name__ == "__main__":
    # CLI mirror used by the A/B parity harness (and handy for debugging).
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
