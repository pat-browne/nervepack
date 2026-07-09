"""Pure-Python port of np-content-lib.sh + np-layer-lib.sh.

Parity-locked to the bash originals by tests/mcp/parity/test_content_parity.sh.
The long-running MCP server resolves the content overlay root, the team>personal
layer stack, and the merge mode IN-PROCESS via this module so it needs no bash;
the bash libs stay the source of truth for hot-path hooks/crons. Reuses the
already-ported np_toggle for the `team` / `team.merge` decisions. stdlib only.
See the git-for-windows-free MCP design spec (overlay docs/superpowers/specs/).
"""
import os
import sys

import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
# Bash: _npc_engine="$_npc_setup/../.." — the engine repo root (this file's dir is
# engine/setup, so two levels up is the repo root).
_ENGINE = os.path.dirname(os.path.dirname(_HERE))


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _cfg(name):
    return os.path.join(_home(), ".config", "nervepack", name)


def _first_line(path):
    # Mirror `d="$(head -n1 "$path")"`: first line, trailing \n stripped, \r kept
    # (so a CRLF config behaves identically to bash, including its dir-not-found).
    try:
        with open(path, "r", newline="") as f:
            return f.readline().rstrip("\n")
    except OSError:
        return ""


# --- content overlay (np-content-lib.sh) ------------------------------------
def _content_target():
    """Resolved path + origin, before the existence check. Mirrors the env ->
    config-first-line -> engine-root precedence."""
    env = os.environ.get("NP_CONTENT_DIR")
    if env:
        return env, "env"
    cfg = _cfg("content-dir")
    if os.path.isfile(cfg):
        return (_first_line(cfg) or _ENGINE), "config"
    return _ENGINE, "default"


def content_dir():
    """np_content_dir: the overlay root, or "" if an explicit path doesn't exist
    (bash returns 1 + no stdout; the server falls back to REPO on empty)."""
    d, _ = _content_target()
    return d if os.path.isdir(d) else ""


def content_origin():
    """np_content_dir_origin: env | config | default."""
    return _content_target()[1]


def content_is_explicit():
    """np_content_is_explicit: True when chosen via env/config (not the fallback)."""
    return content_origin() != "default"


def team_dirs():
    """np_team_dirs: configured team overlay roots, highest-precedence first.
    Comma-separated value; split / trim / drop-empty / dedup, then validate the
    <=4 cap and each dir's existence. Returns [] on unconfigured, over-cap, or a
    missing dir (bash: no stdout + exit 1 in all three; loud stderr is bash-only
    and ignored by the parity harness)."""
    env = os.environ.get("NP_TEAM_DIR")
    if env:
        raw = env
    else:
        cfg = _cfg("team-dir")
        raw = _first_line(cfg) if os.path.isfile(cfg) else ""
    if not raw:
        return []
    dirs = []
    for part in raw.split(","):
        d = part.strip()
        if d and d not in dirs:
            dirs.append(d)
    if not dirs or len(dirs) > 4:
        return []
    for d in dirs:
        if not os.path.isdir(d):
            return []
    return dirs


def team_dir():
    """np_team_dir: the highest-precedence team dir (first of team_dirs), or ""."""
    ds = team_dirs()
    return ds[0] if ds else ""


def team_origin():
    """np_team_dir_origin: env | config | none."""
    if os.environ.get("NP_TEAM_DIR"):
        return "env"
    if os.path.isfile(_cfg("team-dir")):
        return "config"
    return "none"


# --- layer stack (np-layer-lib.sh) ------------------------------------------
def content_layers():
    """np_content_layers: all team roots (precedence order, deduped vs personal)
    when the `team` toggle is on, then personal. [] if personal fails to resolve."""
    personal = content_dir()
    if not personal:
        return []
    layers = []
    if np_toggle.enabled("team"):
        for t in team_dirs():
            if t != personal and t not in layers:
                layers.append(t)
    layers.append(personal)
    return layers


def merge_mode():
    """np_merge_mode: validated team.merge (override | concatenate | team-only)."""
    m = np_toggle.param("team.merge", "override")
    return m if m in ("override", "concatenate", "team-only") else "override"


def merge_roots():
    """np_merge_roots: the roots a reader scans for the current mode. team-only
    with >=1 team -> all team roots (personal, the last layer, dropped)."""
    roots = content_layers()
    if merge_mode() == "team-only" and len(roots) > 1:
        return roots[:-1]
    return roots


if __name__ == "__main__":
    # CLI mirror used by the A/B parity harness. Each mirrors the matching bash
    # function's stdout (trailing newline where bash uses printf '\n') and exit.
    # Emit LF, not CRLF: native-Windows Python translates \n -> \r\n in text mode,
    # which would make every line differ from bash's LF output under Git-bash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "content_dir":
        d = content_dir()
        if not d:
            sys.exit(1)
        sys.stdout.write(d + "\n")
    elif cmd == "content_origin":
        sys.stdout.write(content_origin() + "\n")
    elif cmd == "is_explicit":
        sys.exit(0 if content_is_explicit() else 1)
    elif cmd == "team_dir":
        d = team_dir()
        if not d:
            sys.exit(1)
        sys.stdout.write(d + "\n")
    elif cmd == "team_dirs":
        ds = team_dirs()
        if not ds:
            sys.exit(1)
        for d in ds:
            sys.stdout.write(d + "\n")
    elif cmd == "team_origin":
        sys.stdout.write(team_origin() + "\n")
    elif cmd == "content_layers":
        for r in content_layers():
            sys.stdout.write(r + "\n")
    elif cmd == "merge_mode":
        sys.stdout.write(merge_mode() + "\n")
    elif cmd == "merge_roots":
        for r in merge_roots():
            sys.stdout.write(r + "\n")
    else:
        sys.stderr.write("usage: np_content.py {content_dir|content_origin|is_explicit|"
                         "team_dir|team_dirs|team_origin|content_layers|merge_mode|merge_roots}\n")
        sys.exit(2)
