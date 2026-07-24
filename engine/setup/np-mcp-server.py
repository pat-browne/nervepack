#!/usr/bin/env python3
"""nervepack MCP server — pure-stdlib JSON-RPC 2.0 over stdio.

Thin dispatcher: every tool shells out to an existing nervepack script; every
resource reads a committed repo file. No business logic lives here — git stays
the source of truth. Toggle-gated (`mcp` family), fail-open.
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# HERE is engine/setup; REPO is the repo root (two levels up). Engine code that
# moved into engine/ (e.g. dashboard) is reached via REPO/engine/...; root-level
# content that stayed put (skills/, INDEX.md, the git repo) is reached via REPO.
REPO = os.path.dirname(os.path.dirname(HERE))
SETUP = HERE
SERVER_INFO = {"name": "nervepack", "version": "0.1.0"}
DEFAULT_PROTOCOL = "2025-06-18"


def log(msg):
    sys.stderr.write(f"[np-mcp] {msg}\n")
    sys.stderr.flush()


# --- JSON-RPC writers -------------------------------------------------------
def _write(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def respond(mid, result):
    _write({"jsonrpc": "2.0", "id": mid, "result": result})


def error(mid, code, message):
    _write({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


# --- subprocess helper ------------------------------------------------------
# np_bashlib.argv() makes the bash shell-outs work under Git-bash on Windows (a bare
# `bash` would resolve to System32 WSL, and .sh/backslash paths break). No-op off
# Windows. HERE is on sys.path (this runs as a script), so a plain import resolves it.
import np_bashlib  # noqa: E402
import np_toggle    # noqa: E402  in-process toggle resolver (bash-free, parity-locked)
import np_content   # noqa: E402  in-process content/team/merge resolver (bash-free)
import np_episodic_match  # noqa: E402  in-process keyword matcher for recall (bash-free)
import np_doctor  # noqa: E402  bash-free core-check doctor (fallback when no bash)
import np_sync    # noqa: E402  bash-free engine sync (fallback when no bash)
import np_capture  # noqa: E402  capture pipeline (episodic-capture.sh retired; this is now the only implementation)
import np_evaluator  # noqa: E402  evaluator pipeline (np-evaluator.sh retired; this is now the only implementation)
import np_aggregate  # noqa: E402  aggregate-metrics pipeline (73-aggregate-metrics.sh retired; this is now the only implementation)
import np_skill_maintain  # noqa: E402  skill-maintenance orchestrator (75-skill-maintain.sh retired; this is now the only implementation)
import np_agentic_cron  # noqa: E402  shared agentic-cron helper (71/72-run-*.sh retired; memory_promote()/episodic_maintain() are now the only implementations)
import np_suggestion_resolve  # noqa: E402  in-process resolve/reject (np-suggestion-resolve.sh retired; this is now the only implementation)
import shutil    # noqa: E402

# nervepack_engine.hooks.* (e.g. session_flush) live under REPO/engine, a sibling
# of this SETUP dir, not on sys.path by default the way SETUP itself is (this
# runs as a script) -- add it explicitly, mirroring cli.py's own sys.path insert.
_ENGINE_DIR = os.path.dirname(HERE)
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)


def run(cmd, stdin=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(np_bashlib.argv(cmd), input=stdin, capture_output=True, text=True, env=e)
    return r.returncode, r.stdout, r.stderr


# --- toggle resolution ------------------------------------------------------
# The toggle / content / merge / episodic-match resolvers are FULLY ported to Python
# (np_toggle.py / np_content.py / np_episodic_match.py, parity-locked by
# tests/mcp/parity/*) and are the SINGLE call path — resolved in-process on every
# host, no bash fallback. That's what lets this long-running server gate + recall
# with no bash subprocess per request (the whole point on a git-for-windows-free host).
#
# USE_PY still governs the not-yet-fully-ported doctor / sync / toggle-write tools
# below, which prefer bash when available and fall back to their partial Python
# modules only when it isn't; NP_MCP_PURE_PYTHON=0 forces bash for those. Those
# escape-hatch branches disappear as phases 14/15/17 finish their ports.
USE_PY = os.environ.get("NP_MCP_PURE_PYTHON", "1") == "1"


def np_enabled(feature):
    return np_toggle.enabled(feature)


def np_param(key, default):
    return np_toggle.param(key, default)


_content_dir_cache = None
_content_layers_cache = None
_merge_mode_cache = None

# Content/team/merge resolution runs in-process via np_content.py (bash-free,
# parity-locked by test_content_parity.sh) — the single call path, no bash fallback.
def content_dir():
    global _content_dir_cache
    if _content_dir_cache is None:
        _content_dir_cache = np_content.content_dir() or REPO
    return _content_dir_cache


def _content_layers():
    """Overlay roots (team>personal) for merge-aware MCP reads, via np_merge_roots.
    Fail-open to [content_dir()] when the helper yields nothing. Cached per process."""
    global _content_layers_cache
    if _content_layers_cache is None:
        _content_layers_cache = np_content.merge_roots() or [content_dir()]
    return _content_layers_cache


def _merge_mode():
    """Validated team.merge mode (override|concatenate|team-only). Cached per process."""
    global _merge_mode_cache
    if _merge_mode_cache is None:
        _merge_mode_cache = np_content.merge_mode()
    return _merge_mode_cache


class Disabled(Exception):
    pass


def require_writes():
    if np_param("mcp.writes", "on") != "on":
        raise Disabled("mcp.writes is disabled on this machine")


# reserved for the durable-write tools (nervepack_contribute, suggestions implement) — see plan Tasks 10-11
def require_contribute():
    if np_param("mcp.contribute", "off") != "on":
        raise Disabled("mcp.contribute is disabled (durable auto-commit is opt-in)")


# --- tool registry ----------------------------------------------------------
def _bash_available():
    b = np_bashlib.bash()
    return os.path.exists(b) if os.path.isabs(b) else shutil.which(b) is not None


def _tool_doctor(args):
    # Full bash doctor whenever bash exists (no fidelity loss — covers llm-cli +
    # adapter checks); the bash-free Python doctor (core checks only) is the
    # fallback on a host with no bash so the tool works at all there.
    if USE_PY and not _bash_available():
        text, _ = np_doctor.report()
        return text.strip()
    rc, out, err = run(["bash", os.path.join(SETUP, "np-doctor.sh")])
    return (out + err).strip() or f"(doctor produced no output, exit {rc})"


TOOLS = [
    {
        "name": "nervepack_doctor",
        "description": "Run np-doctor.sh: verify this install against the nervepack onboard contract.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_doctor,
    },
]

# --- vertical-slice tools ---------------------------------------------------
def _tool_toggle(args):
    action = args.get("action", "get")
    if action in ("get", "list"):
        if USE_PY:
            return "\n".join(np_toggle.status_lines())   # in-process status table (bash-free)
        rc, out, err = run(["bash", os.path.join(SETUP, "nervepack-toggle.sh"), "status"])
        return (out + err).strip()
    require_writes()
    if action == "set":
        feat = args["feature"]
        state = args["state"]
        # Local-file writes happen in-process (bash-free). Shared-feature writes
        # (toggles.conf + git commit/push) and managed-permission scripts still need
        # bash — route them to nervepack-toggle.sh, or refuse if no bash is present.
        if USE_PY and np_toggle.is_local_set(feat):
            np_toggle.set_local(feat, state)
            return f"{feat} = {state}" if "." in feat else f"{feat} -> {state}"
        if USE_PY and not _bash_available():
            raise Disabled("setting '%s' needs bash/git (shared or managed scope) — "
                           "not supported on a bash-free host yet" % feat)
        sub = ["param", feat, state] if "." in feat else [feat, state]
        rc, out, err = run(["bash", os.path.join(SETUP, "nervepack-toggle.sh")] + sub)
        return (out + err).strip() or f"set {feat}={state}"
    raise ValueError(f"unknown toggle action: {action}")


_RECALL_DIRS = {"episodic": "memory/episodic", "lesson": "memory/lessons"}


def _tool_recall(args):
    query = args.get("query", "")
    kinds = args.get("kinds") or list(_RECALL_DIRS)
    top = int(args.get("top", 3))
    roots = _content_layers()
    mode = _merge_mode()
    chunks = []
    for kind in kinds:
        d = _RECALL_DIRS.get(kind)
        if not d:
            continue
        seen = set()
        for cd in roots:
            index = os.path.join(cd, d, "INDEX.md")
            if not os.path.exists(index):
                continue
            # In-process matcher (bash-free, parity-locked to episodic-match.sh) —
            # the single call path, no bash fallback.
            topic_list = np_episodic_match.match(index, query)
            for topic in topic_list[:top]:
                if mode != "concatenate" and topic in seen:
                    continue   # higher-precedence (team) layer already supplied this topic
                try:
                    path = _safe_path(os.path.join(d, topic + ".md"), base=cd)
                except ValueError:
                    continue
                if os.path.exists(path):
                    seen.add(topic)
                    with open(path, encoding="utf-8") as fh:
                        chunks.append("## %s: %s\n%s" % (kind, topic, fh.read()))
    return "\n\n".join(chunks) if chunks else "(no matches)"


def _tool_dashboard(args):
    view = args.get("view", "summary")
    cd = content_dir()
    metrics = os.path.join(cd, "dashboard", "data", "metrics.jsonl")
    if view == "metrics":
        if not os.path.exists(metrics):
            return "[]"
        with open(metrics, encoding="utf-8") as fh:
            return fh.read()
    # summary: reuse build.py's loaders via a tiny inline python call (no logic dup)
    # engine code lives under REPO/dashboard; content metrics live under content_dir
    code = (
        "import sys, os, json; sys.path.insert(0, os.path.join(%r, 'dashboard'));"
        "import build;"
        "recs = build.load_records(%r);"
        "lc = build.learned_counts();"
        "print(json.dumps({'sessions': len(recs), 'learned': lc}))"
    ) % (REPO, metrics)
    rc, out, err = run([sys.executable, "-c", code])
    return out.strip() or f"(no dashboard data; {err.strip()})"


TOOLS += [
    {"name": "nervepack_toggle",
     "description": "Get/set nervepack feature toggles. action: get|list|set; feature; state (on|off|value).",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["get", "list", "set"]},
         "feature": {"type": "string"}, "state": {"type": "string"}},
         "additionalProperties": False},
     "handler": _tool_toggle},
    {"name": "nervepack_recall",
     "description": "Recall topic-matched episodic notes / lessons for a query.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "kinds": {"type": "array", "items": {"type": "string"}},
         "top": {"type": "integer"}},
         "required": ["query"], "additionalProperties": False},
     "handler": _tool_recall},
    {"name": "nervepack_dashboard",
     "description": "Read dashboard data. view: summary (counts) | metrics (raw jsonl).",
     "inputSchema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": ["summary", "metrics"]}},
         "additionalProperties": False},
     "handler": _tool_dashboard},
]
def _tool_sync(args):
    require_writes()
    # Full bash sync when bash exists (also does the team-layer ff + skill relink);
    # the bash-free Python engine-sync is the fallback on a host with no bash.
    if USE_PY and not _bash_available():
        return np_sync.sync()
    rc, out, err = run(["bash", os.path.join(SETUP, "40-sync-nervepack.sh")])
    return (out + err).strip() or f"sync exit {rc}"


def _tool_capture(args):
    require_writes()
    payload = {"transcript_path": args.get("transcript_path", ""),
               "cwd": args.get("cwd", REPO),
               "session_id": args.get("session_id", "mcp")}
    # episodic-capture.sh (the bash original) is retired -- np_capture.capture()
    # is now the only implementation, called in-process (no subprocess/bash).
    return np_capture.capture(payload)


def _tool_evaluate(args):
    require_writes()
    payload = {"transcript_path": args.get("transcript_path", ""),
               "cwd": args.get("cwd", REPO),
               "session_id": args.get("session_id", "mcp")}
    # np-evaluator.sh (the bash original) is retired -- np_evaluator.evaluate()
    # is now the only implementation, called in-process (no subprocess/bash).
    return np_evaluator.evaluate(payload)


def _require_bash(tool):
    # nervepack_flush's own glue is bash-free (nervepack_engine.hooks.session_flush,
    # called in-process below) -- this gate now covers the agentic maintenance crons
    # (memory_promote()/episodic_maintain(), both np_agentic_cron.py -- their bash
    # originals, 71/72-run-*.sh, are retired) and skill-maintain: each calls
    # np_llm_agent.run_agent() -> np_model.agent() for its Sonnet pass. As of phase 9
    # of the bash->Python migration, np_model.agent()'s DEFAULT (claude) backend is
    # itself bash-free (calls the `claude` binary directly, no `bash -c` wrapper) --
    # this gate is conservative on purpose: NP_LLM_BACKEND=local with NP_LLM_AGENT_CMD
    # still shells via `bash -c`, and that combination hasn't been verified safe to
    # allow through on a bash-free host. Revisit narrowing this to the actual
    # configured backend once that path is tested (73-aggregate-metrics.sh is
    # retired; its np_aggregate.py replacement is called in-process and needs no
    # bash at all, hence its own tool has no gate). On a bash-free host, refuse
    # cleanly (like the toggle shared-write path) instead of emitting a raw
    # subprocess error.
    if USE_PY and not _bash_available():
        raise Disabled("%s needs bash — not supported on a bash-free host yet "
                       "(it runs the agent-mode maintenance crons)" % tool)


def _tool_flush(args):
    require_writes()
    _require_bash("nervepack_flush")
    # np-session-flush.sh (the bash original) is retired -- session_flush.run()
    # is now the only implementation, called in-process (no subprocess/bash); it
    # itself handles the detach-and-return-quickly behavior, so no special-casing
    # is needed for the MCP path.
    from nervepack_engine.hooks import session_flush
    session_flush.run("")
    return "flushed"


TOOLS += [
    {"name": "nervepack_sync",
     "description": "Fast-forward sync the nervepack repo with origin (git).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "handler": _tool_sync},
    {"name": "nervepack_capture",
     "description": "Capture a session to the episodic inbox. Args: transcript_path, cwd, session_id.",
     "inputSchema": {"type": "object", "properties": {
         "transcript_path": {"type": "string"}, "cwd": {"type": "string"},
         "session_id": {"type": "string"}}, "additionalProperties": False},
     "handler": _tool_capture},
    {"name": "nervepack_evaluate",
     "description": "Score a session (evaluator inbox). Args: transcript_path, cwd, session_id.",
     "inputSchema": {"type": "object", "properties": {
         "transcript_path": {"type": "string"}, "cwd": {"type": "string"},
         "session_id": {"type": "string"}}, "additionalProperties": False},
     "handler": _tool_evaluate},
    {"name": "nervepack_flush",
     "description": "Promote the local inboxes into the committed episodic + metrics layers.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "handler": _tool_flush},
]
def _tool_suggestions(args):
    action = args.get("action", "list")
    rev = os.path.join(SETUP, "np-suggestions-review.py")
    if action in ("list", "review"):  # review currently aliases list (no LLM pass in v1)
        rc, out, err = run([sys.executable, rev, "list", "--json", "--top", str(args.get("top", 10))])
        return out.strip() or "[]"
    require_writes()
    if action == "clear":
        rc, out, err = run([sys.executable, rev, "clear"])
        return (out + err).strip() or "cleared"
    if action in ("resolve", "reject"):
        message, _rc = np_suggestion_resolve.resolve(args["text"])
        return message or f"{action}d"
    if action == "implement":
        require_contribute()
        # async, detached — mirrors the dashboard server's /api/implement route.
        # mode is governed by the evaluator.implement_mode param (set via nervepack_toggle).
        # np_implement_suggestion.py (phase 10 -- the last script ported): dispatched
        # via cli.py, no more bash np-implement-suggestion.sh.
        cli = os.path.join(_ENGINE_DIR, "nervepack_engine", "cli.py")
        subprocess.Popen([sys.executable, cli, "implement-suggestion", args["text"]],
                         cwd=REPO, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "implement job started (async; mode from evaluator.implement_mode)"
    raise ValueError(f"unknown suggestions action: {action}")


TOOLS += [
    {"name": "nervepack_suggestions",
     "description": "Dashboard evaluator-suggestions: list|review|resolve|clear|implement|reject. text for resolve/reject/implement; top for list.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "review", "resolve", "clear", "implement", "reject"]},
         "text": {"type": "string"}, "top": {"type": "integer"}},
         "additionalProperties": False},
     "handler": _tool_suggestions},
]


def _tool_contribute(args):
    require_contribute()
    kind = args["kind"]            # skill | source | wiki
    name = args["name"]
    body = args["body"]
    topic = args.get("topic", "misc")
    rel = {
        "skill": f"skills/{name}/SKILL.md",
        "source": f"sources/{topic}/{name}.md",
        "wiki": f"wiki/{args.get('wiki_kind', 'concepts')}/{name}.md",
    }[kind]
    cd = content_dir()
    full = _safe_path(rel, base=cd)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(body if body.endswith("\n") else body + "\n")
    subject = {
        "skill": f"skill({name}): add via MCP contribute",
        "source": f"source({topic}): add {name} via MCP contribute",
        "wiki": f"wiki({name}): add via MCP contribute",
    }[kind]
    run(["git", "-C", cd, "add", rel])  # explicit path only
    rc, out, err = run(["git", "-C", cd, "commit", "-m", subject])
    _, sha, _ = run(["git", "-C", cd, "rev-parse", "--short", "HEAD"])
    return f"committed {rel} @ {sha.strip()}" if rc == 0 else f"commit failed: {(out + err).strip()}"


def _tool_maintain(args):
    require_writes()
    job = args.get("job", "aggregate")
    if job == "aggregate":
        # 73-aggregate-metrics.sh (the bash original) is retired -- np_aggregate.aggregate()
        # is now the only implementation, called in-process (no subprocess/bash).
        return np_aggregate.aggregate()
    if job == "skills":
        # 75-skill-maintain.sh (the bash original) is retired -- np_skill_maintain.maintain()
        # is now the only implementation. Its split pass calls np_llm_agent.run_agent()
        # (np_model.agent(), phase 9 -- bash-free for the default claude backend), but
        # it stays gated by _require_bash like promote/maintain below (see that
        # function's docstring for why the gate isn't narrowed to the backend yet).
        _require_bash("nervepack_maintain")
        return np_skill_maintain.maintain()
    if job == "promote":
        # 71-run-memory-promote.sh (the bash original) is retired -- np_agentic_cron
        # .memory_promote() is now the only implementation. Like skills, its agent
        # call runs through np_model.agent() (phase 9), but stays gated by
        # _require_bash (see that function's docstring).
        _require_bash("nervepack_maintain")
        return np_agentic_cron.memory_promote()
    if job == "maintain":
        # 72-run-episodic-maintain.sh (the bash original) is retired -- np_agentic_cron
        # .episodic_maintain() is now the only implementation. Like promote, its agent
        # call runs through np_model.agent() (phase 9), but stays gated by
        # _require_bash (see that function's docstring).
        _require_bash("nervepack_maintain")
        return np_agentic_cron.episodic_maintain()
    raise ValueError(f"unknown maintain job: {job}")


def _tool_onboard(args):
    # Bootstrap the whole install: link skills, wire the lifecycle hooks, install the
    # scheduler, register the MCP, run the doctor. Dispatches to `cli.py onboard`
    # (np_onboard.py, phase 7 of the bash->Python migration) -- that orchestrator is
    # Python now, but most of its individual steps (link-skills, dashboard-data,
    # every 5x/6x hook installer, the doctor) are still bash it shells out to, so
    # this still refuses cleanly on a bash-free host like flush/maintain.
    require_writes()
    if USE_PY and not _bash_available():
        raise Disabled("nervepack_onboard needs bash — its steps are setup/installer "
                       "scripts (not supported on a bash-free host)")
    # Optionally point at the overlays first, mirroring ~/.config/nervepack/{content,team}-dir.
    cfg = os.path.join(os.path.expanduser("~"), ".config", "nervepack")
    for key, fname in (("content_dir", "content-dir"), ("team_dir", "team-dir")):
        val = (args.get(key) or "").strip()
        if val:
            os.makedirs(cfg, exist_ok=True)
            with open(os.path.join(cfg, fname), "w", encoding="utf-8") as fh:
                fh.write(val + "\n")
    cli = os.path.join(_ENGINE_DIR, "nervepack_engine", "cli.py")
    rc, out, err = run([sys.executable, cli, "onboard"])
    return (out + err).strip() or "onboarded"


TOOLS += [
    {"name": "nervepack_contribute",
     "description": "Write a durable skill/source/wiki page and git-commit it (bypasses human review — gated by mcp.contribute, default off). kind: skill|source|wiki; name; topic (source); body; wiki_kind.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["skill", "source", "wiki"]},
         "name": {"type": "string"}, "topic": {"type": "string"},
         "wiki_kind": {"type": "string"}, "body": {"type": "string"}},
         "required": ["kind", "name", "body"], "additionalProperties": False},
     "handler": _tool_contribute},
    {"name": "nervepack_maintain",
     "description": "Run a maintenance job: promote|maintain|aggregate|skills (idempotent cron bodies).",
     "inputSchema": {"type": "object", "properties": {
         "job": {"type": "string", "enum": ["promote", "maintain", "aggregate", "skills"]}},
         "additionalProperties": False},
     "handler": _tool_maintain},
    {"name": "nervepack_onboard",
     "description": "Bootstrap the full nervepack install on this host: link skills, wire all lifecycle hooks, install the scheduler, register the MCP, and run the doctor (idempotent). Optional args: content_dir, team_dir — point at your overlay(s) first. Needs bash.",
     "inputSchema": {"type": "object", "properties": {
         "content_dir": {"type": "string"}, "team_dir": {"type": "string"}},
         "additionalProperties": False},
     "handler": _tool_onboard},
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def _tool_def(t):
    return {k: t[k] for k in ("name", "description", "inputSchema")}


def handle_tool_call(mid, params):
    name = (params or {}).get("name")
    args = (params or {}).get("arguments") or {}
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return error(mid, -32602, f"unknown tool: {name}")
    try:
        text = tool["handler"](args)
        respond(mid, {"content": [{"type": "text", "text": text}], "isError": False})
    except Exception as exc:  # tool errors are results, not protocol errors
        respond(mid, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})


# --- resources --------------------------------------------------------------
# (uri-suffix dir, file-glob) — static singletons first, then dir collections.
RESOURCE_DIRS = [
    ("skills", "skills", "*/SKILL.md"),
    # wiki entries are nested folders now (wiki/topics/<t>/<f>.md, wiki/concepts/<c>/<f>.md,
    # with co-located sources) — recurse. There is no separate top-level sources/ dir.
    ("wiki", "wiki", "**/*.md"),
    ("memory/episodic", "memory/episodic", "*.md"),
    ("memory/lessons", "memory/lessons", "*.md"),
]
STATIC_RESOURCES = {
    "nervepack://index": "INDEX.md",
    "nervepack://dashboard/metrics": "dashboard/data/metrics.jsonl",
}


def _safe_path(rel, base=None):
    """Resolve rel under base (default REPO); refuse traversal/escape."""
    base = os.path.realpath(base or REPO)
    full = os.path.realpath(os.path.join(base, rel))
    if full != base and not full.startswith(base + os.sep):
        raise ValueError("path escapes base")
    return full


def _uri_to_relpath(uri):
    if uri in STATIC_RESOURCES:
        return STATIC_RESOURCES[uri]
    if not uri.startswith("nervepack://"):
        raise ValueError(f"unknown uri scheme: {uri}")
    rest = uri[len("nervepack://"):]
    if ".." in rest.split("/"):
        raise ValueError("path traversal rejected")
    if rest.startswith("skills/"):
        return os.path.join("skills", rest[len("skills/"):], "SKILL.md")
    return rest  # wiki/topics/<t>/<name>, wiki/concepts/<c>/<name>, memory/lessons/<topic>, ...


def list_resources():
    items = [{"uri": u, "name": u, "mimeType": "text/markdown"} for u in STATIC_RESOURCES]
    cd = content_dir()
    for prefix, d, pat in RESOURCE_DIRS:
        if prefix == "skills":
            # Merge engine skills and overlay skills; overlay-wins by skill name.
            skills_map = {}  # name -> uri (ordered: engine first, overlay overwrites)
            for skills_base in (os.path.join(REPO, d), os.path.join(cd, d)):
                for path in sorted(glob.glob(os.path.join(skills_base, pat))):
                    rel = os.path.relpath(path, skills_base)
                    skill_name = os.path.dirname(rel)  # <name>/SKILL.md -> <name>
                    skills_map[skill_name] = f"nervepack://skills/{skill_name}"
            for uri in skills_map.values():
                items.append({"uri": uri, "name": uri, "mimeType": "text/markdown"})
        else:
            # Content dirs: resolve under content_dir()
            base = os.path.join(cd, d)
            for path in sorted(glob.glob(os.path.join(base, pat), recursive=True)):
                rel = os.path.relpath(path, base).replace(os.sep, "/")  # URIs use "/" on every OS (Windows relpath yields "\")
                uri = f"nervepack://{prefix}/{rel[:-3] if rel.endswith('.md') else rel}"
                items.append({"uri": uri, "name": uri, "mimeType": "text/markdown"})
    return items


_CONTENT_PREFIXES = ("skills/", "wiki/", "memory/episodic/", "memory/lessons/", "dashboard/")


def read_resource(uri):
    rel = _uri_to_relpath(uri)
    if not rel.endswith(".md") and not rel.endswith(".jsonl"):
        rel = rel + ".md"
    # nervepack://index stays anchored to REPO (engine file)
    if uri == "nervepack://index":
        full = _safe_path(rel, base=REPO)
    elif any(rel.startswith(p) for p in _CONTENT_PREFIXES):
        cd = content_dir()
        if rel.startswith("skills/"):
            # Overlay-wins: prefer content_dir copy, fall back to engine copy
            overlay_full = _safe_path(rel, base=cd)
            engine_full = _safe_path(rel, base=REPO)
            full = overlay_full if os.path.exists(overlay_full) else engine_full
        else:
            full = _safe_path(rel, base=cd)
    else:
        full = _safe_path(rel, base=REPO)
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read()


def handle_resource_read(mid, params):
    uri = (params or {}).get("uri", "")
    try:
        text = read_resource(uri)
    except Exception as exc:
        return error(mid, -32602, f"cannot read {uri}: {exc}")
    mime = "application/x-ndjson" if uri.endswith("metrics") else "text/markdown"
    respond(mid, {"contents": [{"uri": uri, "mimeType": mime, "text": text}]})


# --- prompts ----------------------------------------------------------------
def _directive_text():
    with open(os.path.join(SETUP, "nervepack-session-directive.md"), encoding="utf-8") as fh:
        return fh.read()


PROMPTS = [{
    "name": "nervepack-directive",
    "description": "The 'consult nervepack first' session directive — inject at session start.",
}]


def handle_prompt_get(mid, params):
    name = (params or {}).get("name")
    if name != "nervepack-directive":
        return error(mid, -32602, f"unknown prompt: {name}")
    try:
        text = _directive_text()
    except OSError as exc:
        return error(mid, -32603, f"cannot read directive: {exc}")
    respond(mid, {
        "description": "consult-nervepack directive",
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    })


# --- dispatch ---------------------------------------------------------------
def dispatch(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    if is_notification:
        return  # JSON-RPC: never reply to a notification (no id)

    if method == "initialize":
        respond(mid, {
            "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL),
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        })
    elif method == "ping":
        respond(mid, {})
    elif method == "tools/list":
        respond(mid, {"tools": [_tool_def(t) for t in TOOLS]})
    elif method == "tools/call":
        handle_tool_call(mid, params)
    elif method == "resources/list":
        respond(mid, {"resources": list_resources()})
    elif method == "resources/read":
        handle_resource_read(mid, params)
    elif method == "resources/templates/list":
        respond(mid, {"resourceTemplates": []})
    elif method == "prompts/list":
        respond(mid, {"prompts": PROMPTS})
    elif method == "prompts/get":
        handle_prompt_get(mid, params)
    else:
        error(mid, -32601, f"method not found: {method}")


def main():
    if not np_enabled("mcp"):
        log("mcp feature disabled; exiting")
        return 0
    if np_enabled("pii_filter"):
        os.environ["NP_PII_FILTER"] = "1"
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            dispatch(msg)
        except Exception as exc:  # never let one bad message kill the loop
            log(f"dispatch error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
