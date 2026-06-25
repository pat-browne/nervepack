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
def run(cmd, stdin=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=e)
    return r.returncode, r.stdout, r.stderr


# --- toggle resolution (single source of truth: the bash resolver) ----------
def np_enabled(feature):
    lib = os.path.join(SETUP, "np-toggle-lib.sh")
    rc, _, _ = run(["bash", "-c", 'source "$1"; np_enabled "$2"', "_", lib, feature])
    return rc == 0


def np_param(key, default):
    lib = os.path.join(SETUP, "np-toggle-lib.sh")
    _, out, _ = run(["bash", "-c", 'source "$1"; np_param "$2" "$3"', "_", lib, key, default])
    return out.strip() or default


_content_dir_cache = None
_content_layers_cache = None
_merge_mode_cache = None

def content_dir():
    global _content_dir_cache
    if _content_dir_cache is None:
        lib = os.path.join(SETUP, "np-content-lib.sh")
        rc, out, _ = run(["bash", "-c", 'source "$1"; np_content_dir', "_", lib])
        _content_dir_cache = out.strip() or REPO
    return _content_dir_cache


def _content_layers():
    """Overlay roots (team>personal) for merge-aware MCP reads, via np_merge_roots.
    Fail-open to [content_dir()] when the helper yields nothing. Cached per process."""
    global _content_layers_cache
    if _content_layers_cache is None:
        lib = os.path.join(SETUP, "np-layer-lib.sh")
        _, out, _ = run(["bash", "-c", 'source "$1" 2>/dev/null; np_merge_roots', "_", lib])
        roots = [ln for ln in out.splitlines() if ln.strip()]
        _content_layers_cache = roots or [content_dir()]
    return _content_layers_cache


def _merge_mode():
    """Validated team.merge mode (override|concatenate|team-only). Cached per process."""
    global _merge_mode_cache
    if _merge_mode_cache is None:
        lib = os.path.join(SETUP, "np-layer-lib.sh")
        _, out, _ = run(["bash", "-c", 'source "$1" 2>/dev/null; np_merge_mode', "_", lib])
        m = out.strip()
        _merge_mode_cache = m if m in ("override", "concatenate", "team-only") else "override"
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
def _tool_doctor(args):
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
        rc, out, err = run(["bash", os.path.join(SETUP, "nervepack-toggle.sh"), "status"])
        return (out + err).strip()
    require_writes()
    if action == "set":
        feat = args["feature"]
        if "." in feat:  # param, e.g. sync.interval
            rc, out, err = run(["bash", os.path.join(SETUP, "nervepack-toggle.sh"),
                                "param", feat, args["state"]])
        else:
            rc, out, err = run(["bash", os.path.join(SETUP, "nervepack-toggle.sh"),
                                feat, args["state"]])
        return (out + err).strip() or f"set {feat}={args.get('state')}"
    raise ValueError(f"unknown toggle action: {action}")


_RECALL_DIRS = {"episodic": "episodic", "playbook": "playbooks", "strategy": "strategies"}


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
            rc, out, _ = run(["bash", os.path.join(SETUP, "episodic-match.sh"), index], stdin=query)
            for topic in [t for t in out.splitlines() if t.strip()][:top]:
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
     "description": "Recall topic-matched episodic notes / playbooks / strategies for a query.",
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
    rc, out, err = run(["bash", os.path.join(SETUP, "40-sync-nervepack.sh")])
    return (out + err).strip() or f"sync exit {rc}"


def _tool_capture(args):
    require_writes()
    payload = {"transcript_path": args.get("transcript_path", ""),
               "cwd": args.get("cwd", REPO),
               "session_id": args.get("session_id", "mcp")}
    rc, out, err = run(["bash", os.path.join(SETUP, "episodic-capture.sh"), "session-end"],
                       stdin=json.dumps(payload))
    return (out + err).strip() or "captured"


def _tool_evaluate(args):
    require_writes()
    payload = {"transcript_path": args.get("transcript_path", ""),
               "cwd": args.get("cwd", REPO),
               "session_id": args.get("session_id", "mcp")}
    rc, out, err = run(["bash", os.path.join(SETUP, "np-evaluator.sh")], stdin=json.dumps(payload))
    return (out + err).strip() or "evaluated"


def _tool_flush(args):
    require_writes()
    rc, out, err = run(["bash", os.path.join(SETUP, "np-session-flush.sh")])
    return (out + err).strip() or "flushed"


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
        rc, out, err = run(["bash", os.path.join(SETUP, "np-suggestion-resolve.sh"), args["text"]])
        return (out + err).strip() or f"{action}d"
    if action == "implement":
        require_contribute()
        # async, detached — mirrors the dashboard server's /api/implement route.
        # mode is governed by the evaluator.implement_mode param (set via nervepack_toggle).
        subprocess.Popen(["bash", os.path.join(SETUP, "np-implement-suggestion.sh"), args["text"]],
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
    script = {"promote": "71-run-memory-promote.sh", "maintain": "72-run-episodic-maintain.sh",
              "aggregate": "73-aggregate-metrics.sh", "skills": "75-skill-maintain.sh"}[job]
    rc, out, err = run(["bash", os.path.join(SETUP, script)])
    return (out + err).strip() or f"{job} done"


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
    ("sources", "sources", "*/*.md"),
    ("wiki", "wiki", "*/*.md"),
    ("playbooks", "playbooks", "*.md"),
    ("strategies", "strategies", "*.md"),
    ("episodic", "episodic", "*.md"),
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
    return rest  # sources/<topic>/<name>, wiki/<kind>/<name>, playbooks/<topic>, ...


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
            for path in sorted(glob.glob(os.path.join(base, pat))):
                rel = os.path.relpath(path, base)
                uri = f"nervepack://{prefix}/{rel[:-3] if rel.endswith('.md') else rel}"
                items.append({"uri": uri, "name": uri, "mimeType": "text/markdown"})
    return items


_CONTENT_PREFIXES = ("skills/", "sources/", "wiki/", "playbooks/", "strategies/", "episodic/", "dashboard/")


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
