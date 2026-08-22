"""Bash-free Python doctor — the sole implementation of nervepack's install
health check (phase 15; np-doctor.sh retired). Verifies an install against the
onboard contract (engine/onboard/capabilities.json), running ALL 16 capabilities
in-process: the host-neutral `check:core` checks (llm-cli, git-sync, toggles,
content, team, dashboard-data, hook-scripts, resume-pointer, scheduled-auth-token,
pii_filter_full) via native git + np_toggle / np_content / np_model / np_token_lib,
and the host-specific `check:adapter` checks (knowledge, session-*, scheduled-maint)
by running the `verify` command the onboarding agent recorded in adapter.json.

Exit code: 1 iff any MUST capability is not PASS* (a "PASS…" prefix counts as
pass); SHOULD shortfalls warn only. capabilities.json unreadable -> exit 2.

Config (env, for tests + alt installs): NP_DIR · NP_CAPABILITIES · NP_ADAPTER ·
CLAUDE_SETTINGS · CLAUDE_BIN / NP_LLM_BACKEND (llm-cli smoke) ·
NP_CLAUDE_TOKEN_FILE. The MCP server (`nervepack_doctor`) and the onboard
orchestrator both call report() in-process — no bash. stdlib only.
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
import subprocess
import sys

import np_paths
import np_dirs
import np_toggle
import np_content
import np_model
import np_token_lib
import np_maintenance_freshness
import np_episodic_freshness
import np_layout


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _np_dir():
    # Mirror np-doctor.sh: NP="${NP_DIR:-<repo root>}".
    return os.environ.get("NP_DIR") or np_paths.REPO_ROOT


def _caps_path():
    return os.environ.get("NP_CAPABILITIES") or os.path.join(
        _np_dir(), "engine", "onboard", "capabilities.json")


def _adapter_path():
    # Mirror np-doctor.sh: ADAPTER="${NP_ADAPTER:-$HOME/.config/nervepack/adapter.json}",
    # with the base directory now resolved through np_dirs (XDG-aware, #299).
    return os.environ.get("NP_ADAPTER") or np_dirs.config_path("adapter.json")


def _git_ok(np):
    try:
        a = subprocess.run(["git", "-C", np, "rev-parse", "--git-dir"],
                           capture_output=True)
        b = subprocess.run(["git", "-C", np, "remote", "get-url", "origin"],
                           capture_output=True)
        return a.returncode == 0 and b.returncode == 0
    except OSError:
        return False


def _walk_commands(node, out):
    """Mirror the bash jq walk `.. | objects | select(.type?=="command") | .command`
    over a settings.json `.hooks` subtree: collect every command string."""
    if isinstance(node, dict):
        if node.get("type") == "command" and "command" in node:
            out.append(node["command"])
        for v in node.values():
            _walk_commands(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_commands(v, out)
    return out


def _core_check(cap_id, np):
    if cap_id == "layer-layout":
        # SHOULD: a layer with no manifest still contributes fine (np_layout infers
        # its routes), so "inferred" is an advisory PASS. Only a corrupt or invalid
        # manifest is a FAIL -- that one silently misplaces durable writes.
        roots = np_content.content_layers()
        if not roots:
            return "PASS (no content layer configured)"
        inferred = 0
        pending = 0
        for r in roots:
            try:
                layout, source = np_layout.resolve(r)
            except np_layout.LayoutError as exc:
                return "FAIL (%s: %s)" % (os.path.basename(r), exc)
            if source == "inferred":
                inferred += 1
            pending += len(np_layout.open_questions(r, layout))
        if inferred == 0 and pending == 0:
            return "PASS"
        return "PASS (inferred: %d layer(s), %d open question(s))" % (inferred, pending)
    if cap_id == "llm-cli":
        # In-process np_model.complete("ping") — the bash `printf 'ping' |
        # np_model.py complete` smoke, without a subprocess. PASS iff the call
        # returns non-empty text (command-substitution strips trailing newlines,
        # so mirror that before the -n test); any backend error -> FAIL.
        try:
            out = np_model.complete("ping")
        except np_model.AuthError as exc:
            return "FAIL (auth: %s -- re-login with `claude setup-token`)" % exc
        except Exception:
            return "FAIL"
        out = out.rstrip("\n") if out else out
        return "PASS" if out else "FAIL"
    if cap_id == "hook-scripts":
        settings_path = os.environ.get("CLAUDE_SETTINGS") or os.path.join(
            os.path.expanduser("~"), ".claude", "settings.json")
        if not os.path.isfile(settings_path):
            return "PASS (no settings.json at %s)" % settings_path
        try:
            settings = _load_json(settings_path)
        except (OSError, ValueError):
            # bash: a jq parse failure yields an empty command stream -> PASS.
            settings = {}
        home = os.environ.get("HOME") or os.path.expanduser("~")
        broken = []
        for cmd in _walk_commands(settings.get("hooks") or {}, []):
            if not cmd:
                continue
            cmd = cmd.rstrip("\r")          # jq on Windows emits \r\n
            if cmd.startswith("~"):         # ${cmd/#\~/$HOME}: expand a leading ~ only
                cmd = home + cmd[1:]
            script = cmd.split(" ", 1)[0]   # ${cmd%% *}: first space-delimited token
            if "/" not in script:           # skip bare command names
                continue
            if not os.path.exists(script):
                broken.append(script)
        if not broken:
            return "PASS"
        return "FAIL (%d missing script(s): %s)" % (len(broken), " ".join(broken))
    if cap_id == "scheduled-auth-token":
        st = np_token_lib.claude_token_status()
        word = st.split(" ", 1)[0]
        if word == "ok":
            return "PASS (%s)" % st
        if word == "warn":
            return ("WARN (rotation window — run engine/setup/"
                    "62-install-scheduled-auth-token.sh --rotate; %s)" % st)
        return ("WARN (no scheduled-auth token — run engine/setup/"
                "62-install-scheduled-auth-token.sh; scheduled memory-promote/refine/"
                "compact crons fail 'Not logged in' without it)")
    if cap_id == "maintenance-freshness":
        # Advisory: every maintenance cron is fail-open, so a suspended host, an
        # expired headless credential (#201) and a mis-resolved input path (#15)
        # all die silently and identically. "When did each job last run?" is the
        # one observable that catches all three.
        return np_maintenance_freshness.report()
    if cap_id == "episodic-freshness":
        # Advisory, and deliberately NOT the same question as maintenance-freshness:
        # that one asks "did the cron fire", this asks "did anything come out". The
        # #113 failure passed the first and would have failed this one — the cron ran
        # daily for a week while the drain underneath it was dead.
        return np_episodic_freshness.report()
    if cap_id == "pii_filter_full":
        try:
            import presidio_analyzer  # noqa: F401
            return "PASS"
        except ImportError:
            return "FAIL (run: python3 engine/nervepack_engine/cli.py setup install-pii-deps)"
    if cap_id == "git-sync":
        return "PASS" if _git_ok(np) else "FAIL"
    if cap_id == "toggles":
        # Resolve both state directories so legacy_overrides() has something to
        # report, then say so. "My XDG_CACHE_HOME is being ignored" has to be
        # answerable without reading source (#299), and this is the check that
        # already proves the config layer is reachable.
        try:
            np_dirs.cache_dir()
            np_dirs.config_dir()
        except np_dirs.DirectoryError as exc:
            # A relative XDG_* value raises by design. Crashing here would make
            # the doctor die on precisely the misconfiguration it exists to
            # report, which is the worst possible moment for it to stop working.
            return "FAIL (%s)" % exc
        ignored = np_dirs.legacy_overrides()
        if ignored:
            return ("PASS (%s set but ignored: an existing directory takes "
                    "precedence, so nothing moved. Move it to relocate.)"
                    % ", ".join(ignored))
        return "PASS"  # np_toggle imported successfully -> the resolver is reachable
    if cap_id == "content":
        cdir = np_content.content_dir()
        if not cdir or not os.path.isdir(cdir):
            return "FAIL"
        if np_content.content_origin() == "default":
            return ("PASS (implicit engine-root fallback — set NP_CONTENT_DIR or "
                    "~/.config/nervepack/content-dir; writers skip commits until then)")
        return "PASS"
    if cap_id == "team":
        tdirs = np_content.team_dirs()
        if not tdirs:
            torigin = np_content.team_origin()
            if torigin != "none":
                return ("WARN (team layer configured (origin %s) but invalid — over-cap "
                         "(>4) or a missing dir; falling back to personal-only)" % torigin)
            return "PASS (no team layer configured)"
        tlist = ",".join(tdirs)
        tcount = len(tdirs)
        if np_toggle.enabled("team"):
            return "PASS (team layers (%d): %s — origin %s, merge %s)" % (
                tcount, tlist, np_content.team_origin(), np_content.merge_mode())
        return "PASS (team layers (%d): %s but the 'team' toggle is OFF — not merged)" % (
            tcount, tlist)
    if cap_id == "dashboard-data":
        cdir = np_content.content_dir()
        ddlink = os.path.join(np, "dashboard", "data")
        if not cdir:
            return "WARN (content dir unresolvable — cannot verify dashboard data bridge)"
        if cdir == np:
            return "PASS" if os.path.isdir(ddlink) else \
                "WARN (dashboard/data dir missing — run: cli.py setup link-dashboard-data)"
        if os.path.islink(ddlink):
            try:
                resolved = os.path.realpath(ddlink)
            except OSError:
                resolved = ""
            return "PASS" if resolved and os.path.isdir(resolved) else \
                "WARN (dashboard/data symlink exists but target does not resolve — run: cli.py setup link-dashboard-data)"
        if os.path.isdir(ddlink):
            return ("WARN (dashboard/data is a real directory, not a symlink into the "
                    "content overlay — metrics may load from the wrong location)")
        return ("WARN (dashboard/data bridge missing — run: cli.py setup link-dashboard-data "
                "to create the symlink into the content overlay; the dashboard will show no "
                "metrics until then)")
    if cap_id == "resume-pointer":
        writer = os.path.join(np, "engine", "nervepack_engine", "hooks", "resume_write.py")
        if not os.path.isfile(writer):
            return ("WARN (resume_write.py missing — run: "
                    "python3 engine/nervepack_engine/cli.py setup install-hooks)")
        settings_path = os.environ.get("CLAUDE_SETTINGS") or os.path.join(
            os.path.expanduser("~"), ".claude", "settings.json")
        if not os.path.isfile(settings_path):
            return ("WARN (no settings.json at %s — run: "
                    "python3 engine/nervepack_engine/cli.py setup install-hooks)" % settings_path)
        try:
            settings = _load_json(settings_path)
        except (OSError, ValueError):
            return ("WARN (resume-pointer hooks not registered in %s — run: "
                    "python3 engine/nervepack_engine/cli.py setup install-hooks)" % settings_path)
        cmds = []
        def _walk(node):  # mirror the bash jq walk: `.. | objects | select(.type?=="command")`
            if isinstance(node, dict):
                if node.get("type") == "command" and "command" in node:
                    cmds.append(node["command"])
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for v in node:
                    _walk(v)
        _walk(settings.get("hooks") or {})
        has_session = any("np-resume-sessionstart.sh" in c or "cli.py hook resume-sessionstart" in c for c in cmds)
        has_recall = any("np-resume-recall.sh" in c or "cli.py hook resume-recall" in c for c in cmds)
        if has_session and has_recall:
            return "PASS"
        return ("WARN (resume-pointer hooks not registered in %s — run: "
                "python3 engine/nervepack_engine/cli.py setup install-hooks)" % settings_path)
    return "SKIP"


# ============================================================================
# SECURITY / TRUST BOUNDARY — `_adapter_check` runs a host-authored shell snippet
# via subprocess.run(verify, shell=True). This is DELIBERATE and BOUNDED:
#
#   * `verify` originates ONLY from adapter.json (NP_ADAPTER, default
#     ~/.config/nervepack/adapter.json), which the onboarding agent writes ONCE
#     during setup to record HOW this host proves its own wiring. It is host/
#     operator-authored configuration, never user prompt / session / tool / model
#     input. No other source reaches this function — do NOT widen it.
#   * shell=True is REQUIRED to match the bash original's `eval "$verify"`: the
#     idiomatic verify is a host-native shell pipe/grep boolean
#     (`launchctl list | grep -q com.nervepack`, `crontab -l | grep -q …`), which
#     needs the host's shell to run. An argv-list (shell=False) cannot express a
#     pipe and would break every real adapter.
#   * Default pipe semantics (exit = last command's status) match the bash
#     `set +o pipefail` inside `( … )`: a `producer | grep -q PAT` that SIGPIPEs
#     the producer (141) still reports PASS on a match, as a boolean check should.
#
# A code scanner will (correctly) flag shell=True here; the justification above is
# the reason it stays. The reviewer's job is to confirm no untrusted path can set
# `verify` — it can't: this is the same trust boundary `eval "$verify"` relied on,
# not a new one.
# ============================================================================
def _run_verify(verify):
    """Run a host-authored adapter `verify` snippet; True iff it exits 0.
    See the trust-boundary block above for why shell=True is safe and required."""
    try:
        r = subprocess.run(
            verify, shell=True,  # noqa: S602 — bounded to operator-authored adapter.json
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except OSError:
        return False


def _adapter_check(cap_id):
    """Port of np-doctor.sh's adapter_check: verify a host-specific capability by
    running the `verify` the onboarding agent recorded in adapter.json."""
    adapter_path = _adapter_path()
    if not os.path.isfile(adapter_path):
        return "MISSING"
    try:
        adapter = _load_json(adapter_path)
    except (OSError, ValueError):
        return "MISSING"
    cap = (adapter.get("capabilities") or {}).get(cap_id) or {}
    status = cap.get("status") or "missing"
    verify = cap.get("verify") or ""
    if status == "unsupported":
        return "UNSUPPORTED"
    if status == "wired":
        return "PASS" if (verify and _run_verify(verify)) else "FAIL"
    return "MISSING"


def report():
    """Run every capability in the contract and return (text, exit_code).
    exit_code is 1 iff any MUST capability is not PASS*; 2 if the contract is
    unreadable."""
    np = _np_dir()
    caps_path = _caps_path()
    adapter_path = _adapter_path()
    try:
        caps = _load_json(caps_path)["capabilities"]
    except (OSError, ValueError, KeyError) as exc:
        return ("doctor: capabilities.json not readable at %s: %s\n" % (caps_path, exc), 2)
    lines = ["nervepack doctor — contract: %s" % caps_path]
    if os.path.isfile(adapter_path):
        lines.append("adapter: %s" % adapter_path)
    else:
        lines.append("adapter: (none at %s)" % adapter_path)
    lines.append("")
    must_fail = 0
    for c in caps:
        cid = c.get("id", "")
        tier = c.get("tier", "")
        if c.get("check") == "core":
            st = _core_check(cid, np)
        else:
            st = _adapter_check(cid)
        lines.append("  [%-6s] %-22s %s" % (tier, cid, st))
        # A status may carry an advisory suffix after PASS — treat any "PASS…" as pass.
        if tier == "MUST" and not st.startswith("PASS"):
            must_fail = 1
    lines.append("")
    if must_fail == 0:
        lines.append("doctor: MUST tier OK ✓  (SHOULD shortfalls above are advisory)")
        return ("\n".join(lines) + "\n", 0)
    lines.append("doctor: MUST tier FAILED ✗  — fix the items above and re-run")
    return ("\n".join(lines) + "\n", 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        # Force UTF-8 + LF: the report contains non-ASCII (✓, em-dash), and native
        # Windows Python defaults stdout to cp1252 which can't encode ✓ — that would
        # fail the whole write and emit nothing. bash np-doctor.sh already emits UTF-8.
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    text, code = report()
    sys.stdout.write(text)
    sys.exit(code)
