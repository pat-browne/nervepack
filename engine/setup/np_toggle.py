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
    """np_enabled: True if on. Fail-open (unknown -> on). Sub-toggle inherits family."""
    feat = feature
    v = _local_get(feat)
    if not v and "." in feat:
        feat = feat.split(".", 1)[0]
        v = _local_get(feat)
    if not v:
        v = _conf_state(feat)
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
    else:
        sys.stderr.write("usage: np_toggle.py enabled <feature> | param <key> <default>\n")
        sys.exit(2)
