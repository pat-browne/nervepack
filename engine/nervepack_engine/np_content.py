"""Content-overlay + layer-stack resolver (formerly bash np-content-lib.sh +
np-layer-lib.sh, both retired in phase 18 — this module is now the sole resolver).

Resolves the content overlay root, the team>personal layer stack, and the merge
mode. The long-running MCP server, the recall hooks, and the setup steps all
import this in-process; there is no bash equivalent. Reuses np_toggle for the
`team` / `team.merge` decisions. stdlib only.
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

import os
import posixpath
import sys

import np_paths
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
# Bash: _npc_engine="$_npc_setup/../.." — the engine repo root (this file's dir is
# engine/setup, so two levels up is the repo root).
_ENGINE = np_paths.REPO_ROOT


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _cfg(name):
    return os.path.join(_home(), ".config", "nervepack", name)


def _first_line(path):
    # First line with the trailing EOL stripped. Strip BOTH \r and \n so a
    # CRLF-terminated config file (common on Windows — an editor, or a file
    # copied from Windows) resolves to the bare path, not "<path>\r" which would
    # fail os.path.isdir() and silently break content-dir/team-dir resolution.
    # (The retired bash lib kept the \r via `head -n1`; that was a latent bug the
    # Python resolver, now the sole one, fixes.)
    try:
        with open(path, "r", newline="") as f:
            return f.readline().rstrip("\r\n")
    except OSError:
        return ""


# --- content overlay (formerly np-content-lib.sh) ---------------------------
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


def layer_dir(layer):
    """np_layer_dir: single-root layer path (content_dir()/memory/<layer>).
    The non-merge-aware sibling of merge_roots() — used by callers (like
    lesson-guard.sh's Phase 1 Bash-command matching) that read one lesson/
    episodic dir without team merging."""
    return os.path.join(content_dir(), "memory", layer)


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


# --- layer stack (formerly np-layer-lib.sh) ---------------------------------
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


def unresolved_layers():
    """Reason string when a layer is ENABLED but does not resolve on this machine,
    else "" (nervepack#241).

    `team_dirs()` returns [] for unconfigured, over-cap, AND missing-dir alike, so a
    caller cannot tell "no team layer wanted" from "team layer wanted but absent".
    Any writer that regenerates a SHARED COMMITTED artifact from local state must
    know the difference: with the `team` toggle on and nothing resolvable, an
    authoritative regen deletes that layer's rows for everyone.

    Deliberately a separate helper rather than a warning inside team_dirs(): hooks
    and recall paths call that on nearly every turn, so warning there would be
    constant noise on any machine without a team layer."""
    if not np_toggle.enabled("team"):
        return ""
    if team_dirs():
        return ""
    origin = team_origin()
    if origin == "none":
        return ("the 'team' toggle is on but no team layer is configured "
                "(NP_TEAM_DIR / ~/.config/nervepack/team-dir)")
    return ("the 'team' toggle is on but the configured team layer does not "
            "resolve (missing dir, or more than the 4-dir cap)")


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


def layer_roots(layer):
    """np_layer_roots: one path per merge root, each suffixed memory/<layer>.
    The merge-aware sibling of layer_dir() — recall hooks scan these for the
    active team.merge mode. Joined with FORWARD slashes (posixpath), byte-for-byte
    matching the retired bash `np_layer_roots` (`printf '%s/memory/%s'`), since the
    output is a line-oriented text list consumed as display/paths that Python opens
    fine either way — os.path.join would emit backslashes on Windows and diverge."""
    return [posixpath.join(r, "memory", layer) for r in merge_roots()]


if __name__ == "__main__":
    # CLI mirror (the setup steps + tests call these verbs). Each writes the
    # matching function's stdout (trailing newline per line) and exit code.
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
    elif cmd == "layer_roots":
        for r in layer_roots(sys.argv[2] if len(sys.argv) > 2 else ""):
            sys.stdout.write(r + "\n")
    else:
        sys.stderr.write("usage: np_content.py {content_dir|content_origin|is_explicit|"
                         "team_dir|team_dirs|team_origin|content_layers|merge_mode|"
                         "merge_roots|layer_roots <layer>}\n")
        sys.exit(2)
