"""Shared agentic-cron helper -- in-process Python port of the near-identical
71/72/76/77-run-*.sh bash bodies (memory-promote, episodic-maintain, refine,
compact). All four do, in order: (1) toggle gate -> skip; (2) re-entrancy --
bail if NERVEPACK_AGENT is already set; (3) for content-committing crons only:
content-dir-explicit gate (issue #12 -- never write personal memory into the
PII-clean engine repo on the implicit engine-root fallback); (4) backend
pre-flight (claude backend needs the binary; a non-claude backend needs
NP_LLM_AGENT_CMD); (5) extract the `## Prompt` section from the prompt file;
(6) for extra-roots crons only: append an "Additional skill roots" overlay
note; (7) a dated log header; (8) cd into the commit target and run the
agent there.

This module builds ONE shared private `_run(cfg)` body plus a small
`CronConfig` per cron, so a later cron is a thin config addition, not a
re-derivation of the shared logic. Only `memory-promote` is wired here so
far; `episodic-maintain`/`refine`/`compact` each add a CronConfig + entrypoint
in their own port.

Fail-open throughout (ARCHITECTURE invariant 1): `_run` (and every
entrypoint built on it) returns a short status string and never raises.
"""
import dataclasses
import datetime
import os

import np_content
import np_llm_agent
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))       # engine/setup/
_NP = os.path.abspath(os.path.join(_HERE, "..", ".."))    # engine repo root


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


@dataclasses.dataclass(frozen=True)
class CronConfig:
    """One cron's shape -- the shared `_run` body only ever reads these fields.

    name            -- dispatch name; also the log run-header ("=== <name> run ===").
    toggle          -- toggle key gating the run (e.g. "memory.promote").
    prompt_rel_path -- prompt file, relative to the engine root (_NP).
    log_env         -- env var overriding the log path (e.g. "MEMORY_PROMOTE_LOG").
    log_basename    -- default log basename under ~/.cache/nervepack/.
    commit_target   -- "content" (content overlay, via np_content.content_dir())
                       or "engine" (the engine repo, _NP).
    content_gated   -- True: skip (issue #12) when np_content.content_is_explicit()
                       is False. Only memory-promote/episodic-maintain set this.
    extra_roots     -- True: append the "Additional skill roots" overlay note to
                       the prompt. Only refine/compact set this.
    """
    name: str
    toggle: str
    prompt_rel_path: str
    log_env: str
    log_basename: str
    commit_target: str = "content"
    content_gated: bool = False
    extra_roots: bool = False


def _log_path(cfg):
    override = os.environ.get(cfg.log_env)
    if override:
        return override
    return os.path.join(_home(), ".cache", "nervepack", cfg.log_basename)


def _log(cfg, msg):
    try:
        path = _log_path(cfg)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (_ts(), msg))
    except OSError:
        pass


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


def _extra_roots_note():
    """The '### Additional skill roots' overlay note appended for extra_roots
    configs (refine/compact). Mirrors 76-run-refine.sh's EXTRA_ROOTS
    construction (also np_skill_maintain._skill_roots()'s pattern): each merge
    root's skills/ that resolves to a real dir other than the engine itself.
    Returns "" when there's nothing to add (fail-open on any resolution error)."""
    roots = []
    try:
        for r in np_content.merge_roots():
            if r and r != _NP and os.path.isdir(os.path.join(r, "skills")):
                roots.append(r)
    except Exception:
        return ""
    if not roots:
        return ""
    lines = [
        "",
        "",
        "### Additional skill roots (content overlay)",
        "",
        "Besides `skills/` in this working directory, also apply steps 2-3 to "
        "the `skills/` directory under EACH of these paths -- content-overlay "
        "(and/or team) repos that hold the personal/knowledge skills relocated "
        "out of the engine:",
    ]
    for r in roots:
        lines.append(
            "- `%s/skills/` -- a SEPARATE git repo rooted at `%s`. Stage and "
            "commit ONLY the paths you changed there via `git -C \"%s\" add "
            "<paths> && git -C \"%s\" commit -m ... -- <paths>`, then "
            "`git -C \"%s\" push`. Never combine its commit with this repo's "
            "commit." % (r, r, r, r, r))
    return "\n".join(lines) + "\n"


def _resolve_commit_dir(cfg):
    if cfg.commit_target == "engine":
        return _NP
    return np_content.content_dir()


def _run(cfg):
    """Shared 8-step agentic-cron body. Returns a short status string; never
    raises (ARCHITECTURE invariant 1 -- fail-open)."""
    # 1. Toggle gate.
    if not np_toggle.enabled(cfg.toggle):
        return "skipped: %s disabled" % cfg.toggle

    # 2. Re-entrancy: bail if already running inside a nervepack agent context.
    # np-llm.sh's own agent call sets NERVEPACK_AGENT=1; this explicit check
    # mirrors the bash bodies' belt-and-suspenders guard, and matters when this
    # entrypoint is invoked directly (bypassing cli.py's own cron-dispatch guard).
    if os.environ.get("NERVEPACK_AGENT"):
        return "skipped: NERVEPACK_AGENT already set (re-entrant)"

    # 3. Content-dir-explicit gate (issue #12) -- content-gated crons only.
    if cfg.content_gated:
        try:
            explicit = np_content.content_is_explicit()
        except Exception:
            explicit = False
        if not explicit:
            _log(cfg, "skipped: content dir is the implicit engine-root fallback -- "
                       "set NP_CONTENT_DIR or ~/.config/nervepack/content-dir to enable "
                       "memory promotion")
            return "skipped: content dir is the implicit engine-root fallback"

    # 4. Backend pre-flight (ARCHITECTURE invariant 13).
    backend = os.environ.get("NP_LLM_BACKEND", "claude")
    claude = os.environ.get("CLAUDE_BIN") or os.path.join(_home(), ".local", "bin", "claude")
    if backend == "claude" and not os.access(claude, os.X_OK):
        _log(cfg, "ERROR: claude CLI not found at %s" % claude)
        return "skipped: claude CLI not found"
    if backend != "claude" and not os.environ.get("NP_LLM_AGENT_CMD"):
        _log(cfg, "ERROR: local backend agent mode needs NP_LLM_AGENT_CMD")
        return "skipped: NP_LLM_AGENT_CMD unset"

    # 5. Extract the "## Prompt" section onward.
    prompt_file = os.path.join(_NP, cfg.prompt_rel_path)
    if not os.path.isfile(prompt_file):
        _log(cfg, "ERROR: prompt file missing at %s" % prompt_file)
        return "skipped: prompt missing"
    prompt = _base_prompt(prompt_file)
    if not prompt:
        _log(cfg, "ERROR: empty prompt extracted from %s" % prompt_file)
        return "skipped: empty prompt"

    # 6. EXTRA_ROOTS overlay note -- extra_roots crons only.
    if cfg.extra_roots:
        note = _extra_roots_note()
        if note:
            prompt += note

    # 7. Dated log header.
    _log(cfg, "=== %s run ===" % cfg.name)

    # 8. Resolve the commit target and run the agent there.
    target = _resolve_commit_dir(cfg)
    if not target:
        _log(cfg, "ERROR: commit target could not be resolved")
        return "skipped: commit target unresolved"
    ok = np_llm_agent.run_agent(prompt, "Bash Read Write Edit Glob Grep", cwd=target)
    if not ok:
        _log(cfg, "ERROR: agent run exited non-zero")
        return "agent run failed"
    return "ok: agent run completed"


# --- memory-promote (Task 0) -------------------------------------------------
_MEMORY_PROMOTE = CronConfig(
    name="memory-promote",
    toggle="memory.promote",
    prompt_rel_path=os.path.join("agents", "np-flow-memory-promote.md"),
    log_env="MEMORY_PROMOTE_LOG",
    log_basename="memory-promote.log",
    commit_target="content",
    content_gated=True,
    extra_roots=False,
)


def memory_promote():
    """Cron entrypoint (dispatched by cli.py as `cron memory-promote`).
    Returns a short status string; never raises."""
    return _run(_MEMORY_PROMOTE)
