#!/usr/bin/env python3
"""Data helpers behind the dashboard's compact-proposal and graduation panels.

Shared by dashboard/build.py (render) and np-dashboard-server.py (actions).
Stdlib only. Reads fail open.

Compact proposals live at <content>/compact-proposals/<YYYY-MM-DD>.md.
agents/np-flow-weekly-compact.md writes them.

Each `### a vs b` heading opens one proposal. It runs to the next heading.

REJECTED.md in the same dir holds one-line rejection notes.
The compact agent reads it so it does not re-propose a rejected pair.

Graduation dismissals sit next to graduation-candidates.json.
The file is graduation-dismissed.json, a JSON list of "<kind>:<name>" keys.

Compact entries a finished Apply job landed sit in compact-applied.json in the
per-machine cache dir, a JSON list of "<file> :: <title>" keys.
The job lands on the overlay's origin, which the local checkout may not have yet.
The panel hides the entry until the checkout catches up.

Every dashboard action shares one contract (see ActionError and self_check):
a failure carries a short code, a message and a hint, and the page shows all
three. Nothing fails silently.
"""
import hashlib
import json
import os
import re
import subprocess
import time

# Bumped when the route contract changes. The page compares it with /api/health
# so a server that predates the page is reported, not silently half-working.
API_VERSION = 2

PROPOSAL_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_HERE = os.path.dirname(os.path.abspath(__file__))
# The files that define the server's routes. A change to either means a
# running server is stale. A new route-defining file must be added here or
# the stale-server check will not notice changes to it.
_CODE_FILES = ("np-dashboard-server.py", "np_dashboard_actions.py", "np_implement_suggestion.py")


def code_fingerprint():
    """Short hash of the server's route code. Empty when a file is unreadable."""
    h = hashlib.sha256()
    try:
        for name in _CODE_FILES:
            with open(os.path.join(_HERE, name), "rb") as fh:
                h.update(fh.read())
    except OSError as exc:
        import sys
        sys.stderr.write("np-dashboard: code fingerprint unreadable: %s\n" % exc)
        return ""
    return h.hexdigest()[:16]


_HEAD_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
_REC_RE = re.compile(r"recommendation\s*:?\s*\**\s*:?\s*(.+)", re.I)


def _sections(lines):
    """[(title, start, end)] for each `### ` heading. End is exclusive."""
    heads = []
    for i, line in enumerate(lines):
        m = _HEAD_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))

    out = []
    for n, (i, level, title) in enumerate(heads):
        if level != 3:
            continue
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.append((title, i, end))
    return out


def _recommendation(body_lines):
    for line in body_lines:
        m = _REC_RE.search(line)
        if m:
            return m.group(1).strip().strip("*").strip().rstrip(".").strip()[:240]
    return ""


BODY_MAX_CHARS = 20000  # cap per entry so one long proposal can't bloat metrics.js
TRUNCATED_MARK = "\n[... truncated, open the file for the full text]"


def parse_proposals(path):
    """[{title, recommendation, keep_separate}] for one proposal file."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    out = []
    for title, start, end in _sections(lines):
        rec = _recommendation(lines[start + 1:end])
        # body: the entry text under its heading, shown in the dashboard detail row
        body = "\n".join(lines[start + 1:end]).strip()
        if len(body) > BODY_MAX_CHARS:
            body = body[:BODY_MAX_CHARS] + TRUNCATED_MARK
        out.append({"title": title, "recommendation": rec,
                    "keep_separate": "keep separate" in rec.lower(), "body": body})
    return out


def load_proposals(pdir):
    """[{file, date, proposals}] newest first. Files with no entries are skipped."""
    try:
        names = sorted((n for n in os.listdir(pdir) if PROPOSAL_FILE_RE.match(n)), reverse=True)
    except OSError:
        return []

    out = []
    for n in names:
        props = parse_proposals(os.path.join(pdir, n))
        if props:
            out.append({"file": n, "date": n[:-3], "proposals": props})
    return out


def find_proposal(pdir, fname, title):
    """The proposal dict, or None. Any name outside PROPOSAL_FILE_RE is refused."""
    if not PROPOSAL_FILE_RE.match(fname or ""):
        return None
    for p in parse_proposals(os.path.join(pdir, fname)):
        if p["title"] == title:
            return p
    return None


def reject_proposal(pdir, fname, title, today=None, action="rejected from dashboard"):
    """Note the rejection in REJECTED.md and drop the entry from its file.

    The file is deleted once no `###` entry remains.
    Returns True when the entry existed.
    """
    if not find_proposal(pdir, fname, title):
        return False

    path = os.path.join(pdir, fname)
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    sec = next((s for s in _sections(lines) if s[0] == title), None)
    if sec is None:  # entry vanished since find_proposal()
        return False
    rest = lines[:sec[1]] + lines[sec[2]:]
    rec = _recommendation(lines[sec[1] + 1:sec[2]])

    day = today or time.strftime("%Y-%m-%d")
    note = "- %s | %s | %s | %s%s\n" % (
        day, fname, title, action, (" (" + rec + ")") if rec else "")
    # Drop the entry first (atomic replace), then record it, so a failure
    # never leaves a recorded rejection whose entry still shows.
    if _sections(rest):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rest).rstrip("\n") + "\n")
        os.replace(tmp, path)
    else:
        os.remove(path)
    with open(os.path.join(pdir, "REJECTED.md"), "a", encoding="utf-8") as fh:
        fh.write(note)
    return True


def dismiss_key(kind, name):
    return "%s:%s" % (kind or "", name or "")


def load_dismissed(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [k for k in data if isinstance(k, str)] if isinstance(data, list) else []


def dismiss(path, kind, name):
    keys = load_dismissed(path)
    key = dismiss_key(kind, name)
    if key in keys:
        return keys

    keys.append(key)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keys, fh, indent=1)
    os.replace(tmp, path)
    return keys


def filter_candidates(grad, dismissed):
    """Graduation payload with dismissed candidates removed."""
    drop = set(dismissed)
    cands = [c for c in grad.get("candidates", [])
             if isinstance(c, dict) and dismiss_key(c.get("kind"), c.get("name")) not in drop]
    return dict(grad, candidates=cands)


def find_candidate(path, kind, name):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    for c in (data.get("candidates") or []) if isinstance(data, dict) else []:
        if isinstance(c, dict) and c.get("kind") == kind and c.get("name") == name:
            return c
    return None


# ---- shared action contract ----------------------------------------------

class ActionError(Exception):
    """A refused or failed dashboard action. The server turns it into
    {"ok": false, "error": message, "code": code, "hint": hint}."""

    def __init__(self, code, message, hint="", status=409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.status = status

    def payload(self):
        out = {"ok": False, "error": self.message, "code": self.code}
        if self.hint:
            out["hint"] = self.hint
        return out


APPLIED_NAME = "compact-applied.json"
_LESSON_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def applied_key(fname, title):
    return "%s :: %s" % (fname or "", title or "")


def filter_applied(proposal_files, applied):
    """Proposal files with entries a landed Apply job already handled removed."""
    drop = set(applied)
    out = []
    for f in proposal_files:
        keep = [p for p in f.get("proposals", [])
                if applied_key(f.get("file"), p.get("title")) not in drop]
        if keep:
            out.append(dict(f, proposals=keep))
    return out


def lesson_path(content_root, name):
    """memory/lessons/<name>.md under the overlay, or "" for an unsafe name."""
    if not _LESSON_NAME_RE.match(name or ""):
        return ""
    return os.path.join(content_root, "memory", "lessons", name + ".md")


def _vcs_out(repo, *args, timeout=15):
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _check(cid, ok, detail, hint="", level="fail"):
    return {"id": cid, "ok": bool(ok), "level": level, "detail": detail, "hint": hint}


def self_check(content_dir, engine_root, compact_dir, graduation_path, status_dir,
               env=None, toggle_param=None, deep=False, only=None):
    """[{id, ok, level, detail, hint}], one row per thing an action depends on.

    Pure inspection: it writes nothing. `deep` adds the one network probe, an
    ls-remote of the overlay's origin. `only` limits it to the named ids.
    The server runs it at startup (GET /api/doctor), before a dry run, and
    cli.py doctor runs it too, so a broken action is named before a click."""
    env = os.environ if env is None else env
    toggle_param = toggle_param or (lambda key, default: default)
    rows = []

    def want(cid):
        return only is None or cid in only

    if want("implement-toggle"):
        on = toggle_param("evaluator.implement", "on") == "on"
        rows.append(_check("implement-toggle", on,
                           "evaluator.implement is %s" % ("on" if on else "off"),
                           "" if on else "run: cli.py toggle evaluator.implement on"))
    if want("agent-env"):
        inside = bool(env.get("NERVEPACK_AGENT"))
        rows.append(_check("agent-env", not inside,
                           "NERVEPACK_AGENT is set in the server's environment" if inside
                           else "no agent re-entry guard in the server's environment",
                           "restart the dashboard from a normal shell: jobs refuse to run "
                           "inside an agent" if inside else ""))
    if want("overlay"):
        same = (bool(content_dir) and os.path.isdir(content_dir)
                and os.path.realpath(content_dir) == os.path.realpath(engine_root))
        if not content_dir or not os.path.isdir(content_dir):
            rows.append(_check("overlay", False, "no content overlay directory configured",
                               "set NP_CONTENT_DIR or ~/.config/nervepack/content-dir"))
        elif same:
            rows.append(_check("overlay", False,
                               "the content overlay resolves to the engine repo itself",
                               "compact and graduate jobs act on overlay content only: "
                               "set NP_CONTENT_DIR or ~/.config/nervepack/content-dir"))
        else:
            rc, _ = _vcs_out(content_dir, "rev-parse", "--git-dir")
            rrc, origin = _vcs_out(content_dir, "remote", "get-url", "origin")
            if rc != 0:
                rows.append(_check("overlay", False, "%s is not a repository" % content_dir,
                                   "clone the overlay there or fix NP_CONTENT_DIR"))
            elif rrc != 0:
                rows.append(_check("overlay", False, "the overlay has no origin remote",
                                   "jobs land on origin: add a remote named origin"))
            else:
                rows.append(_check("overlay", True, "overlay %s, origin %s" % (content_dir, origin.strip())))
                if deep and want("origin-reachable"):
                    lrc, lout = _vcs_out(content_dir, "ls-remote", "--exit-code", "origin", "HEAD", timeout=20)
                    rows.append(_check("origin-reachable", lrc == 0,
                                       "origin answered" if lrc == 0
                                       else "ls-remote of origin failed: %s" % lout.strip()[:160],
                                       "" if lrc == 0 else "check network and credentials for the overlay origin"))
    if want("proposals"):
        files = load_proposals(compact_dir)
        n = sum(len(f["proposals"]) for f in files)
        rows.append(_check("proposals", True, "%d proposal(s) in %s" % (n, compact_dir)))
    if want("graduation-file"):
        if not os.path.exists(graduation_path):
            rows.append(_check("graduation-file", True, "no %s yet (the daily skill-maintain run writes it)"
                               % os.path.basename(graduation_path)))
        else:
            try:
                with open(graduation_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                ok = isinstance(data, dict) and isinstance(data.get("candidates"), list)
                rows.append(_check("graduation-file", ok,
                                   "%d candidate(s)" % len(data["candidates"]) if ok
                                   else "%s has no candidates list" % graduation_path,
                                   "" if ok else "rerun cli.py cron skill-maintain"))
            except (OSError, ValueError) as exc:
                rows.append(_check("graduation-file", False, "unreadable: %s" % exc,
                                   "rerun cli.py cron skill-maintain"))
    if want("job-files"):
        missing = [p for p in (
            os.path.join(engine_root, "agents", "np-flow-apply-compact-proposal.md"),
            os.path.join(engine_root, "agents", "np-flow-graduate-candidate.md"),
            os.path.join(engine_root, "engine", "nervepack_engine", "cli.py"))
            if not os.path.isfile(p)]
        rows.append(_check("job-files", not missing,
                           "agent prompts and the job runner are present" if not missing
                           else "missing: " + ", ".join(missing),
                           "" if not missing else "resync the engine checkout: cli.py sync"))
    if want("status-dir"):
        try:
            os.makedirs(status_dir, exist_ok=True)
            ok = os.access(status_dir, os.W_OK)
        except OSError:
            ok = False
        rows.append(_check("status-dir", ok, "%s is %swritable" % (status_dir, "" if ok else "not "),
                           "" if ok else "fix permissions on the status directory"))
    return rows


def failing(rows):
    return [r for r in rows if not r["ok"] and r["level"] == "fail"]


def mark_applied(path, fname, title):
    """Record a compact entry a landed Apply job handled. Returns the key list."""
    keys = load_dismissed(path)          # same JSON list-of-strings file shape
    key = applied_key(fname, title)
    if key in keys:
        return keys
    keys.append(key)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keys, fh, indent=1)
    os.replace(tmp, path)
    return keys


def applied_path():
    """Where Apply markers live: per machine cache, never the overlay checkout.

    The job leaves the overlay checkout exactly as it found it, so a marker
    file there would turn a clean checkout dirty.
    """
    env = os.environ.get("NP_COMPACT_APPLIED")
    if env:
        return env
    import np_dirs
    return np_dirs.cache_path(APPLIED_NAME)
