"""Bash-free Python doctor — the deterministic core onboard-contract checks, for
the MCP server on a host with no bash.

Mirrors np-doctor.sh's core checks (git-sync, toggles, content, team,
dashboard-data) using native git + np_toggle / np_content — no bash. The model
seam (llm-cli) and host-adapter checks (knowledge, session-*, scheduled-maint)
need bash / a shell / the model CLI, so they're reported **N/A** here and do NOT
count against the MUST gate; run np-doctor.sh on a host with bash for those (the
MCP server uses the full bash doctor whenever bash is available — this Python path
is the bash-free fallback). Slice 3 of the git-for-windows-free MCP work (#38).

Core-check lines are parity-locked to np-doctor.sh by
tests/mcp/parity/test_doctor_parity.sh. stdlib only.
"""
import json
import os
import subprocess
import sys

import np_toggle
import np_content

_HERE = os.path.dirname(os.path.abspath(__file__))


def _np_dir():
    # Mirror np-doctor.sh: NP="${NP_DIR:-<repo root>}".
    return os.environ.get("NP_DIR") or os.path.dirname(os.path.dirname(_HERE))


def _caps_path():
    return os.environ.get("NP_CAPABILITIES") or os.path.join(
        _np_dir(), "engine", "onboard", "capabilities.json")


def _git_ok(np):
    try:
        a = subprocess.run(["git", "-C", np, "rev-parse", "--git-dir"],
                           capture_output=True)
        b = subprocess.run(["git", "-C", np, "remote", "get-url", "origin"],
                           capture_output=True)
        return a.returncode == 0 and b.returncode == 0
    except OSError:
        return False


def _core_check(cap_id, np):
    if cap_id == "git-sync":
        return "PASS" if _git_ok(np) else "FAIL"
    if cap_id == "toggles":
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
                "WARN (dashboard/data dir missing — run 35-link-dashboard-data.sh)"
        if os.path.islink(ddlink):
            try:
                resolved = os.path.realpath(ddlink)
            except OSError:
                resolved = ""
            return "PASS" if resolved and os.path.isdir(resolved) else \
                "WARN (dashboard/data symlink exists but target does not resolve — run 35-link-dashboard-data.sh)"
        if os.path.isdir(ddlink):
            return ("WARN (dashboard/data is a real directory, not a symlink into the "
                    "content overlay — metrics may load from the wrong location)")
        return ("WARN (dashboard/data bridge missing — run 35-link-dashboard-data.sh to "
                "create the symlink into the content overlay; the dashboard will show no "
                "metrics until then)")
    return "SKIP"


# The model seam + host adapter checks can't be run bash-free; report them N/A and
# keep them out of the MUST gate (the full bash doctor verifies them when bash exists).
_NA = "N/A (not verified bash-free — run np-doctor.sh on a host with bash)"


def report():
    """Return (text, exit_code). exit_code is 1 iff a MUST *core* check failed."""
    np = _np_dir()
    caps_path = _caps_path()
    try:
        caps = json.load(open(caps_path, encoding="utf-8"))["capabilities"]
    except (OSError, ValueError, KeyError) as exc:
        return ("doctor: capabilities.json not readable at %s: %s\n" % (caps_path, exc), 2)
    lines = ["nervepack doctor (bash-free core checks) — contract: %s" % caps_path, ""]
    must_fail = 0
    for c in caps:
        cid = c.get("id", "")
        tier = c.get("tier", "")
        if c.get("check") == "core" and cid != "llm-cli":
            st = _core_check(cid, np)
        else:
            st = _NA   # llm-cli (model seam) + every adapter check
        lines.append("  [%-6s] %-22s %s" % (tier, cid, st))
        if tier == "MUST" and st != _NA and not st.startswith("PASS"):
            must_fail = 1
    lines.append("")
    if must_fail == 0:
        lines.append("doctor: MUST core checks OK ✓  (llm-cli + adapter shown N/A — "
                     "verify with np-doctor.sh on a host with bash)")
        return ("\n".join(lines) + "\n", 0)
    lines.append("doctor: MUST core checks FAILED ✗  — fix the items above and re-run")
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
