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


def _base_prompt(prompt_file):
    """The prompt body after the `## Prompt` heading line. Mirrors the bash
    `awk '/^## Prompt$/{p=1; next} p'`."""
    try:
        with open(prompt_file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ""
    out, started = [], False
    for ln in lines:
        if started:
            out.append(ln)
        elif ln == "## Prompt":
            started = True
    return "\n".join(out)


def _find_skill_root(skill, roots):
    """The roots entry whose <root>/<skill>/SKILL.md exists, or None."""
    for r in roots:
        if os.path.isfile(os.path.join(r, skill, "SKILL.md")):
            return r
    return None


def _snapshot(repo_root, skill, md_path):
    """Original SKILL.md bytes at HEAD (or the working copy if untracked),
    written to a temp file whose path is returned. Mirrors the bash
    `git show HEAD:skills/<skill>/SKILL.md > orig || cp md orig`."""
    fd, orig = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as out:
            rc = subprocess.run(
                ["git", "-C", repo_root, "show", "HEAD:skills/%s/SKILL.md" % skill],
                stdout=out, stderr=subprocess.DEVNULL).returncode
        if rc != 0:
            with open(md_path, "rb") as src, open(orig, "wb") as dst:
                dst.write(src.read())
    except OSError:
        pass
    return orig


def _split_one(skill, roots, base_prompt, split_kb):
    """Run one skill's split: locate its owning root, snapshot, agent-split,
    validate; commit path-limited into the OWNING repo on success, else revert.
    Returns the repo root that received a commit, or None."""
    skill_root = _find_skill_root(skill, roots)
    if not skill_root:
        return None
    repo_root = os.path.dirname(skill_root)   # <repo>/skills -> <repo>
    skill_dir = os.path.join(skill_root, skill)
    md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(md):
        return None
    orig = _snapshot(repo_root, skill, md)
    try:
        prompt = ("%s\n\nTARGET SKILL DIRECTORY: skills/%s\n"
                  "TARGET SKILL FILE: skills/%s/SKILL.md\n"
                  "Hard body budget: %sKB. Move overflow into skills/%s/references/."
                  % (base_prompt, skill, skill, split_kb, skill))
        np_llm_agent.run_agent(prompt, "Read Write Edit", cwd=repo_root)
        ok, reason = np_skill_validate.validate(skill_dir, orig)
        if ok:
            _git(repo_root, "add", "skills/%s" % skill)
            rc = _git(repo_root, "commit", "-q", "-m",
                      "skill(maintain): split %s into body+references (auto)" % skill,
                      "--", "skills/%s" % skill)
            if rc == 0:
                _log("split OK: %s (%s)" % (skill, repo_root))
                return repo_root
            return None
        _git(repo_root, "checkout", "--", "skills/%s" % skill)
        _git(repo_root, "clean", "-fdq", "skills/%s" % skill)
        _log("split ABORTED (reverted): %s -- %s" % (skill, reason))
        return None
    finally:
        try:
            os.remove(orig)
        except OSError:
            pass


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

    prompt_file = os.path.join(_NP, "agents", "np-flow-skill-maintain.md")
    if not os.path.isfile(prompt_file):
        _log("ERROR: prompt missing")
        return "skipped: prompt missing"

    # Backend availability (mirror bash): claude backend needs the binary; a
    # non-claude backend needs NP_LLM_AGENT_CMD.
    backend = os.environ.get("NP_LLM_BACKEND", "claude")
    claude = os.environ.get("CLAUDE_BIN") or os.path.join(
        _home(), ".local", "bin", "claude")
    ok_backend = ((backend == "claude" and os.access(claude, os.X_OK))
                  or (backend != "claude" and os.environ.get("NP_LLM_AGENT_CMD")))
    if not ok_backend:
        _log("ERROR: agent backend unavailable (backend=%s)" % backend)
        return "skipped: agent backend unavailable"

    base_prompt = _base_prompt(prompt_file)
    split_kb = os.environ["SKILL_SPLIT_KB"]
    commit_repos = []
    committed = 0
    for skill in cands[:max_per_run]:
        repo = _split_one(skill, roots, base_prompt, split_kb)
        if repo:
            committed += 1
            if repo not in commit_repos:
                commit_repos.append(repo)

    if os.environ.get("SKILL_MAINTAIN_NO_PUSH") != "1":
        for repo in commit_repos:
            _git(repo, "push", "-q", "origin", "HEAD:main")

    return "split %d skill(s) across %d repo(s)" % (committed, len(commit_repos))
