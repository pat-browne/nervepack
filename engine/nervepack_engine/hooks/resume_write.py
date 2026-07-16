"""Bash-free port of np-resume-write.sh — deterministic resume-pointer writer
(no LLM calls). NOT a stdin-JSON hook: called in-process by resume_recall.py
and resume_sessionstart.py, and dispatched via `nervepack resume-write` for
the opt-in interval cron (70-install-memory-cron.sh), which has no stdin/hook
payload to source --session/--transcript/--cwd from.

Writes ${NP_RESUME_POINTER:-~/.cache/nervepack/resume-pointer.json} atomically
(tmp file + os.replace): {schema_version, session_id, ts, cwd, git_branch,
git_head, git_dirty, transcript_path, last_user_instruction, sdd_ledger,
sdd_plan}. git fields empty/false unless cwd is a git work-tree. Fail-open:
every failure path is a silent no-op (mirrors bash's bail(), which logs one
line and exits 0).
"""
import json
import os
import subprocess
import sys
import time

import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRANSCRIPT_EXTRACT = os.path.normpath(os.path.join(_HERE, "..", "..", "setup", "np-transcript-extract.py"))


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _log_path():
    return os.environ.get("NP_RESUME_LOG") or os.path.join(_home(), ".cache", "nervepack", "resume.log")


def _bail(msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fh.write("%s resume: %s\n" % (ts, msg))
    except OSError:
        pass


def _pointer_path():
    return os.environ.get("NP_RESUME_POINTER") or os.path.join(_home(), ".cache", "nervepack", "resume-pointer.json")


def _stamp_path():
    return os.environ.get("NP_RESUME_STAMP") or os.path.join(_home(), ".cache", "nervepack", "last-resume-write")


def _mtime(path):
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return None


def _discover_active(active_window):
    projects_dir = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.join(_home(), ".claude", "projects")
    if not os.path.isdir(projects_dir):
        return None, None, None
    candidates = []
    for root, _dirs, files in os.walk(projects_dir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            mt = _mtime(path) or 0
            candidates.append((mt, path))
    candidates.sort(reverse=True)
    for _mt, path in candidates:
        sid = os.path.basename(path)[:-len(".jsonl")]
        if sid.startswith("agent-"):
            continue
        now = int(time.time())
        mt = _mtime(path) or 0
        if now - mt >= active_window:
            return None, None, None  # stale sole candidate -> no active session
        cwd = _extract_cwd(path)
        return sid, path, cwd
    return None, None, None


def _extract_cwd(path):
    import re
    pat = re.compile(r'"cwd":"([^"]*)"')
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = pat.search(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _git_field(cwd, *args):
    try:
        result = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    except OSError:
        return ""


def write(session=None, transcript=None, cwd=None, throttle=False, active=False):
    if not np_toggle.enabled("resume"):
        return

    if active:
        try:
            window = int(np_toggle.param("resume.active_window", "900"))
        except (ValueError, TypeError):
            window = 900
        session, transcript, cwd = _discover_active(window)
        if not session:
            return
        if not cwd:
            cwd = _home()

    if not cwd:
        _bail("missing required cwd")
        return

    pointer_path = _pointer_path()
    stamp_path = _stamp_path()

    if throttle and os.path.isfile(stamp_path):
        try:
            interval = int(np_toggle.param("resume.interval", "300"))
        except (ValueError, TypeError):
            interval = 300
        try:
            with open(stamp_path, encoding="utf-8") as fh:
                last = int(fh.read().strip() or "0")
        except (OSError, ValueError):
            last = 0
        if int(time.time()) - last < interval:
            return

    try:
        os.makedirs(os.path.dirname(pointer_path), exist_ok=True)
    except OSError:
        _bail("mkdir failed for %s" % os.path.dirname(pointer_path))
        return

    git_branch = git_head = ""
    git_dirty = False
    repo_root = ""
    is_repo = subprocess.run(["git", "-C", cwd, "rev-parse", "--is-inside-work-tree"],
                              capture_output=True, text=True).returncode == 0
    if is_repo:
        git_branch = _git_field(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        git_head = _git_field(cwd, "rev-parse", "--short", "HEAD")
        status = _git_field(cwd, "status", "--porcelain")
        git_dirty = bool(status)
        repo_root = _git_field(cwd, "rev-parse", "--show-toplevel")

    last_user = ""
    if transcript and os.path.isfile(_TRANSCRIPT_EXTRACT):
        try:
            result = subprocess.run(
                [sys.executable, _TRANSCRIPT_EXTRACT, "--last-user", transcript],
                capture_output=True, text=True)
            if result.returncode == 0:
                last_user = result.stdout
        except OSError:
            last_user = ""

    sdd_ledger = sdd_plan = ""
    if repo_root:
        ledger = os.path.join(repo_root, ".superpowers", "sdd", "progress.md")
        if os.path.isfile(ledger):
            sdd_ledger = ledger
            try:
                with open(ledger, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("Plan:"):
                            sdd_plan = line[len("Plan:"):].strip()
                            break
            except OSError:
                pass

    record = {
        "schema_version": 1,
        "session_id": session or "",
        "ts": int(time.time()),
        "cwd": cwd,
        "git_branch": git_branch,
        "git_head": git_head,
        "git_dirty": git_dirty,
        "transcript_path": transcript or "",
        "last_user_instruction": last_user,
        "sdd_ledger": sdd_ledger,
        "sdd_plan": sdd_plan,
    }

    tmp_path = pointer_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, separators=(",", ":"))
        os.replace(tmp_path, pointer_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _bail("write failed")
        return

    try:
        os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
        with open(stamp_path, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass
