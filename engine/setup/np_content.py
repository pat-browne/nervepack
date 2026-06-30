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


def team_dir():
    """np_team_dir: the optional team overlay root, or "" when unconfigured OR an
    explicit path doesn't exist (bash returns non-zero + no stdout in both)."""
    env = os.environ.get("NP_TEAM_DIR")
    if env:
        d = env
    else:
        cfg = _cfg("team-dir")
        d = _first_line(cfg) if os.path.isfile(cfg) else ""
    if not d:
        return ""
    return d if os.path.isdir(d) else ""


def team_origin():
    """np_team_dir_origin: env | config | none."""
    if os.environ.get("NP_TEAM_DIR"):
        return "env"
    if os.path.isfile(_cfg("team-dir")):
        return "config"
    return "none"


# --- layer stack (np-layer-lib.sh) ------------------------------------------
def content_layers():
    """np_content_layers: overlay roots, team-first when the `team` toggle is on
    and a team dir resolves; deduped. [] when the personal dir fails to resolve."""
    personal = content_dir()
    if not personal:
        return []
    team = team_dir() if np_toggle.enabled("team") else ""
    if team and team != personal:
        return [team, personal]
    return [personal]


def merge_mode():
    """np_merge_mode: validated team.merge (override | concatenate | team-only)."""
    m = np_toggle.param("team.merge", "override")
    return m if m in ("override", "concatenate", "team-only") else "override"


def merge_roots():
    """np_merge_roots: the roots a reader scans for the current mode."""
    roots = content_layers()
    if merge_mode() == "team-only" and len(roots) > 1:
        return [roots[0]]
    return roots


if __name__ == "__main__":
    # CLI mirror used by the A/B parity harness. Each mirrors the matching bash
    # function's stdout (trailing newline where bash uses printf '\n') and exit.
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
                         "team_dir|team_origin|content_layers|merge_mode|merge_roots}\n")
        sys.exit(2)
