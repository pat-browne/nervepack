"""nervepack cron: skill-maintenance orchestrator -- in-process Python port of
75-skill-maintain.sh. Detects over-budget skills across every skill root (engine
+ content overlay [+ team]), splits overflow into references/ via a gated agent
pass, validates-or-aborts each split, and commits path-limited into the repo that
OWNS the skill (never $NP by default), pushing each touched repo once. Runs two
deterministic advisories first (docs/ARCHITECTURE.md freshness; lesson graduation
candidates) with no model call. Fail-open throughout; gated by the `skills`
toggle (+ `skills.split`). Returns a short status string (the cron dispatcher
prints it). Thresholds via toggle params.
"""
import datetime
import json
import os
import subprocess
import tempfile

import np_content
import np_graduation_detect
import np_llm_agent
import np_skill_budget
import np_skill_validate
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))       # engine/setup/
_NP = os.path.abspath(os.path.join(_HERE, "..", ".."))   # engine repo root


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _log_path():
    return os.environ.get("SKILL_MAINTAIN_LOG") or os.path.join(
        _home(), ".cache", "nervepack", "skill-maintain.log")


def _log(msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (_ts(), msg))
    except OSError:
        pass


def _write(path, content):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        pass


def _git(repo, *args):
    """git -C <repo> <args>, output discarded, never raises. Returns returncode
    (1 on OSError)."""
    try:
        return subprocess.run(
            ["git", "-C", repo] + list(args),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except OSError:
        return 1


def _skill_roots():
    """Skill roots to scan: the engine's skills/ ALWAYS, plus each merge root's
    skills/ (content overlay [+ team]) that resolves to a real dir other than the
    engine itself. Mirrors 75-skill-maintain.sh's ROOTS construction."""
    roots = [os.path.join(_NP, "skills")]
    try:
        for r in np_content.merge_roots():
            if r and r != _NP and os.path.isdir(os.path.join(r, "skills")):
                roots.append(os.path.join(r, "skills"))
    except Exception:
        pass
    return roots


def _architecture_freshness():
    """Advisory, deterministic: run np-architecture-freshness.sh, log its last
    line, and mirror its STALE verdict into ~/.cache/nervepack/architecture-stale
    (written on drift, removed when clean). Never blocks. Bash subprocess -- this
    separate script keeps its own future port slot; skill-maintain is an agent
    cron that already requires bash for np-llm.sh."""
    script = os.path.join(_HERE, "np-architecture-freshness.sh")
    try:
        out = subprocess.run(
            ["bash", script], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True).stdout or ""
    except OSError:
        out = ""
    lines = out.splitlines()
    _log(lines[-1] if lines else "")
    stale = [ln for ln in lines if ln.startswith("STALE:")]
    marker = os.path.join(_home(), ".cache", "nervepack", "architecture-stale")
    if stale:
        for ln in stale:
            _log(ln)
        _write(marker, out if out.endswith("\n") else out + "\n")
    else:
        try:
            os.remove(marker)
        except OSError:
            pass


def _graduation_scan():
    """Advisory, deterministic: surface lessons overdue to GRADUATE into a
    human-reviewed skill (seen >= graduate_seen or bytes > graduate_kb KB). Only
    SURFACES (marker + content-routed data file + log); never auto-promotes.
    Skipped on the implicit engine-root content fallback (issue #12: would write
    personal-content data into the PII-clean engine repo)."""
    try:
        if not np_content.content_is_explicit():
            return
        content = np_content.content_dir()
        if not content:
            return
        os.environ["GRADUATE_SEEN"] = np_toggle.param("skills.graduate_seen", "10")
        os.environ["GRADUATE_KB"] = np_toggle.param("skills.graduate_kb", "6")
        result = np_graduation_detect.scan(os.path.join(content, "memory", "lessons"))
    except Exception:
        return
    cands = result.get("candidates", [])
    marker = os.environ.get("GRADUATION_MARKER") or os.path.join(
        _home(), ".cache", "nervepack", "graduation-candidates")
    data = os.path.join(content, "dashboard", "data", "graduation-candidates.json")
    blob = json.dumps(result, separators=(",", ":"))
    if cands:
        for c in cands:
            _log("GRADUATE: %s %s (seen=%s, bytes=%s) [%s] -> promote to a skill" % (
                c.get("kind"), c.get("name"), c.get("seen"), c.get("bytes"),
                "+".join(c.get("reasons", []))))
        _write(marker, blob + "\n")
        _write(data, blob + "\n")
        _log("graduation: %d candidate(s) -- see %s" % (len(cands), marker))
    else:
        try:
            os.remove(marker)
        except OSError:
            pass
        # Only refresh an existing panel dir (don't create it on hosts that don't
        # dashboard) -- mirrors the bash `[[ -d ... ]]` guard.
        if os.path.isdir(os.path.dirname(data)):
            _write(data, blob + "\n")


def maintain():
    """Cron entrypoint. Returns a short status string; never raises."""
    if not np_toggle.enabled("skills"):
        return "skipped: skills disabled"

    # Advisories first (deterministic, no model call).
    _architecture_freshness()

    _graduation_scan()

    # Resolve tunable thresholds -> env for the in-process budget helper.
    os.environ["SKILL_SPLIT_KB"] = np_toggle.param("skills.split_kb", "8")
    os.environ["SKILL_SOFT_KB"] = np_toggle.param("skills.soft_kb", "6")
    os.environ["SKILL_CATALOG_TOK"] = np_toggle.param("skills.catalog_tok", "4000")
    try:
        max_per_run = int(np_toggle.param("skills.max_per_run", "2") or "2")
    except ValueError:
        max_per_run = 2

    roots = _skill_roots()
    report = np_skill_budget.scan(roots)
    if not report:
        _log("detector produced no output")
        return "no-op: detector produced no output"

    if report.get("catalog_over"):
        _log("NOTE: catalog over budget (%s tok) -- tree restructure due "
             "(manual/future)" % report.get("catalog_tokens"))

    cands = [c["skill"] for c in report.get("split_candidates", []) if c.get("skill")]
    if not cands:
        _log("no skills over split threshold (%sKB)" % os.environ["SKILL_SPLIT_KB"])
        return "no-op: no skills over split threshold"

    if not np_toggle.enabled("skills.split"):
        _log("skills.split disabled; detected: %s" % " ".join(cands))
        return "detected %d, skills.split disabled" % len(cands)

    # (Task 4 replaces the line below with the prompt/backend guards + split loop.)
    return "no-op: split loop not yet implemented"
