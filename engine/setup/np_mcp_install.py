"""Bash-free port of np-mcp-install.sh — the guided one-line nervepack MCP install
(phase 17 of the bash->Python CLI migration). End to end:
  1. configure the content overlay        (~/.config/nervepack/content-dir)
  2. optionally configure a team overlay   (~/.config/nervepack/team-dir; the `team`
     toggle is on by default — configuring the dir activates the overlay)
  3. register the MCP server with the host  (Claude Code via 58-install-mcp.sh;
     otherwise print the generic mcpServers block)
  4. verify — the in-process doctor (np-doctor.sh was retired in phase 15) + a check
     that documented feature paths resolve (np-path-check.py)

Interactive, but falls back to safe defaults when stdin has no input (CI/headless):
a closed/empty stdin == "accept the default" for every prompt. Idempotent and
re-runnable. Reads answers line-by-line from stdin. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): np_toggle/np_content/np_model and the other library
# modules were relocated into engine/nervepack_engine/; add that package dir so this
# script's flat imports of them resolve whether run standalone or imported.
_ENGINE_PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

import os
import shutil
import np_dirs
import subprocess
import sys

import np_bashlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_NP = os.path.dirname(os.path.dirname(_HERE))            # engine repo root


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _cfg_dir():
    # np_content resolves config through np_dirs (XDG-aware since #299) — match it.
    return np_dirs.config_dir()


def _expand(s):
    """Expand a single leading ~ (mirrors bash `${1/#\\~/$HOME}`)."""
    return _home() + s[1:] if s.startswith("~") else s


class _Asker:
    """Line-by-line stdin reader with a per-prompt default. EOF/blank -> default.
    The prompt goes to stderr so it shows even when stdout is captured."""
    def __init__(self, stream=None, out=None, err=None):
        self._it = iter(stream if stream is not None else sys.stdin)
        self._out = out or sys.stdout
        self._err = err or sys.stderr

    def ask(self, prompt, default=""):
        self._err.write("%s [%s]: " % (prompt, default or "blank"))
        try:
            line = next(self._it)
        except StopIteration:
            return default
        ans = line.strip()                              # bash `read -r` trims IFS ws
        return ans or default


def _write_cfg(cfg, name, value):
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(value + "\n")


def _offer_starter_adopt(cfg, asker, out, err, state):
    """Optional, declinable adoption of the public nervepack-content-example pack as
    a ready-made starter overlay. Declining / empty stdin / already-configured is a
    clean no-op. NP_STARTER_ADOPT_FORCE={adopt,decline} drives it non-interactively;
    NP_STARTER_ADOPT_SOURCE/NP_STARTER_ADOPT_PATH override clone source/dest (tests)."""
    if os.path.isfile(os.path.join(cfg, "content-dir")):
        return                                          # already have an overlay
    repo_url = os.environ.get("NP_STARTER_ADOPT_SOURCE",
                              "https://github.com/pat-browne/nervepack-content-example.git")
    out.write("\n")
    out.write("Starter content: nervepack ships machinery-only, no personal skills.\n")
    out.write("The public 'nervepack-content-example' pack has generic skills you can adopt\n")
    out.write("as a starting content overlay (freely editable/replaceable afterward).\n")

    answer = os.environ.get("NP_STARTER_ADOPT_FORCE", "")
    if not answer:
        answer = asker.ask("Adopt the example content pack as your starter overlay? (adopt/decline)", "decline")
    if answer != "adopt":
        out.write("  - declined — no starter overlay adopted\n")
        return

    default_dest = os.path.join(_home(), "Code", "%s-content" % _username())
    dest = os.environ.get("NP_STARTER_ADOPT_PATH", "")
    if not dest:
        dest = _expand(asker.ask("Clone destination", default_dest))
    if os.path.exists(dest):
        err.write("  ! '%s' already exists — skipping starter adoption\n" % dest)
        return
    out.write("Cloning %s -> %s ...\n" % (repo_url, dest))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(np_bashlib.argv(["git", "clone", "-q", "--depth", "1", repo_url, dest]),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env)
    if r.returncode == 0:
        _write_cfg(cfg, "content-dir", dest)
        out.write("  ✓ wrote %s/content-dir -> %s\n" % (cfg, dest))
        state["content"] = dest                         # feed the rest of this run
    else:
        err.write("  ! clone failed — starter overlay not adopted\n")


def _username():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "user"


def install(argv=None, stdin=None, out=None, err=None):
    """Run the guided install. `argv` may carry --starter-only (exercise the starter
    step in isolation). Returns 0."""
    argv = list(argv or [])
    out = out or sys.stdout
    err = err or sys.stderr
    if hasattr(out, "reconfigure"):
        try:
            out.reconfigure(encoding="utf-8", newline="\n")
        except (ValueError, OSError):
            pass
    cfg = _cfg_dir()
    os.makedirs(cfg, exist_ok=True)
    asker = _Asker(stdin, out, err)
    state = {"content": "", "team": ""}

    if argv and argv[0] == "--starter-only":
        _offer_starter_adopt(cfg, asker, out, err, state)
        return 0

    out.write("── nervepack MCP install ──\n")
    out.write("Engine repo: %s\n" % _NP)

    # 1. Content overlay ----------------------------------------------------------
    out.write("\n")
    out.write("Content overlay: where your personal skills / memory / wiki live.\n")
    out.write("Leave blank to use the engine root (single-repo layout).\n")
    content = _expand(asker.ask("Content directory", ""))
    if content:
        if os.path.isdir(content):
            _write_cfg(cfg, "content-dir", content)
            out.write("  ✓ wrote %s/content-dir -> %s\n" % (cfg, content))
        else:
            err.write("  ! '%s' does not exist — skipping (engine root will be used)\n" % content)
            content = ""
    else:
        try:
            os.remove(os.path.join(cfg, "content-dir"))
        except OSError:
            pass
        out.write("  ✓ using the engine root (no content overlay configured)\n")
    state["content"] = content

    # 2. Team overlay (optional) --------------------------------------------------
    out.write("\n")
    out.write("Team overlay (optional): a shared content layer above your personal one.\n")
    out.write("Leave blank for none. Multiple team dirs may be given comma-separated, highest\n")
    out.write("precedence first (max 4) — e.g. squad-dir,division-dir.\n")
    team_raw = asker.ask("Team content directory", "")
    team = ""
    if team_raw:
        entries = []
        for p in team_raw.split(","):
            d = p.strip()
            if d:
                entries.append(_expand(d))
        team_err = ""
        if not entries:
            team_err = "no team dir given"
        elif len(entries) > 4:
            team_err = ">4 team dirs — max 4"
        else:
            for d in entries:
                if not os.path.isdir(d):
                    team_err = "'%s' does not exist" % d
                    break
        if not team_err:
            team = ",".join(entries)
            _write_cfg(cfg, "team-dir", team)
            out.write("  ✓ wrote %s/team-dir (the 'team' overlay is active by default)\n" % cfg)
        else:
            err.write("  ! %s — skipping team overlay\n" % team_err)
    state["team"] = team

    # Offer the starter overlay only after the content/team questions are resolved
    # (running it earlier would consume a stdin line meant for the team prompt). Its
    # own guard (content-dir already configured) makes this a no-op when a content
    # dir was supplied above.
    _offer_starter_adopt(cfg, asker, out, err, state)
    content = state["content"]

    # 3. Register the MCP server with the host ------------------------------------
    out.write("\n")
    if shutil.which("claude"):
        out.write("Registering the MCP server with Claude Code (user scope)…\n")
        out.flush()
        subprocess.run(np_bashlib.argv(["bash", os.path.join(_HERE, "58-install-mcp.sh")]),
                       stdin=subprocess.DEVNULL)
    else:
        out.write("Claude CLI not found — add this to your MCP client's config (absolute path):\n")
        block = ('  {\n    "mcpServers": {\n      "nervepack": {\n'
                 '        "command": "%s/engine/bin/nervepack-mcp"' % _NP)
        if content:
            block += ',\n        "env": { "NP_CONTENT_DIR": "%s" }' % content
        block += "\n      }\n    }\n  }\n"
        out.write(block)

    # 4. Verify -------------------------------------------------------------------
    out.write("\n")
    out.write("Running the doctor to verify the install…\n")
    out.write("\n")
    out.flush()
    try:
        import np_doctor
        text, _ = np_doctor.report()
        out.write(text if text.endswith("\n") else text + "\n")
    except Exception as exc:                            # fail-open: never block install
        err.write("  (doctor could not run: %r)\n" % exc)

    out.write("\n")
    out.write("Checking that documented feature paths resolve…\n")
    out.flush()
    roots = [_NP]
    if content and os.path.isdir(content):
        roots.append(content)
    if team and os.path.isdir(team):
        roots.append(team)
    try:
        subprocess.run([sys.executable, os.path.join(_HERE, "np-path-check.py"), *roots],
                       stdin=subprocess.DEVNULL)
    except OSError:
        pass

    out.write("\n")
    out.write("Done. Re-run any time:  python3 %s setup mcp-install\n"
              % os.path.join(_NP, "engine", "nervepack_engine", "cli.py"))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(install(sys.argv[1:]))
