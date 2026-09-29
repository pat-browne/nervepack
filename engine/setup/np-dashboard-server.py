#!/usr/bin/env python3
"""Opt-in local backend for the nervepack performance dashboard.

The dashboard is normally a static file:// page. When `evaluator.dashboard_serve`
is on, the open scripts launch THIS tiny server instead and point the browser at
http://127.0.0.1:<port>/ so the dashboard's action buttons have a backend:

  GET  /                      -> dashboard/index.html
  GET  /<path>                -> static file under dashboard/ (path-sanitized)
  GET  /api/health            -> {"ok": true}
  POST /api/resolve {text}    -> mark one suggestion acted-on (np_suggestion_resolve.py)
  POST /api/review  {}        -> top-N open suggestions + a single Haiku verdict pass
  POST /api/clear   {}        -> resolve ALL open suggestions (reset), {ok, count}

This is a deliberate, documented exception to nervepack's "no service, no daemon"
invariant: it is OFF by default, binds to 127.0.0.1 ONLY, serves a fixed directory,
and exposes a fixed route allowlist (no arbitrary command exec; subprocess args are
passed as argv lists, never a shell string). Stdlib only (http.server), per the
harness language policy. Fail-open: a bad request returns an error response; the
server itself never crashes.

Env: NP_DASH_PORT (default 8787) · NP_SUGGESTIONS_TOP (default 10) · the review
pass calls np_model.complete() in-process (the backend-neutral LLM seam, which
sets NERVEPACK_AGENT and strips stale CLAUDE_CODE_* env -- load-bearing for
THIS long-lived server specifically, see np_model.py's docstring) and degrades
gracefully if it raises.
"""
import json
import os
import subprocess
import sys
import time
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
NP = os.path.dirname(os.path.dirname(HERE))

# Make the bash/.sh shell-outs below run under Git-bash on Windows (a bare `bash`
# resolves to System32 WSL; .sh can't be exec'd directly). No-op off Windows.
sys.path.insert(0, HERE)
# np_model / np_toggle were relocated into engine/nervepack_engine/ in phase 20b-2;
# add that package dir so their flat imports resolve (HERE/setup stays on sys.path
# for np_bashlib + np_toggle_schema + np_suggestion_resolve).
_ENGINE_PKG = os.path.normpath(os.path.join(HERE, "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)
import np_bashlib  # noqa: E402
import np_dirs
import np_implement_suggestion  # noqa: E402
import np_model  # noqa: E402
import np_suggestion_resolve  # noqa: E402
import np_toggle  # noqa: E402
import np_toggle_schema  # noqa: E402
# Static root + data source are env-overridable so the server is isolatable in tests
# (NP_DASH_ROOT / NP_METRICS / NP_RESOLVED_SUGGESTIONS), same pattern as build.py.
DASH = os.path.realpath(os.environ.get("NP_DASH_ROOT") or os.path.join(NP, "dashboard"))
# Since the engine/content split, dashboard/data is a symlink into the content
# overlay, so its canonical path is outside DASH. Allow that one extra subtree as a
# served root; ../ escaping BOTH roots is still rejected (see _safe_path).
DATA = os.path.realpath(os.path.join(DASH, "data"))
REVIEW = os.path.join(HERE, "np-suggestions-review.py")
# NP_IMPLEMENT overrides with a single script path (test seam -- e2e/test stubs use
# this); the real default is np_implement_suggestion.py (phase 10) dispatched via
# cli.py, not the retired bash np-implement-suggestion.sh.
_IMPLEMENT_OVERRIDE = os.environ.get("NP_IMPLEMENT")
IMPLEMENT_ARGV = ([_IMPLEMENT_OVERRIDE] if _IMPLEMENT_OVERRIDE else
                  [sys.executable, os.path.join(os.path.dirname(HERE), "nervepack_engine", "cli.py"),
                   "implement-suggestion"])
TOGGLES_LOCAL = os.environ.get("NP_TOGGLES_LOCAL") or np_dirs.config_path("toggles.local")
# Toggles the dashboard's OWN gating — flipping any of these from the panel would
# disable the very server/panel serving that click, so the panel renders them
# read-only and the server refuses to write them even if asked directly.
SELF_LOCKOUT_FEATURES = {"evaluator"}
SELF_LOCKOUT_PARAMS = {"evaluator.dashboard_open", "evaluator.dashboard_serve", "evaluator.toggle_ui"}
IMPLEMENT_STATUS_DIR = os.environ.get("NP_IMPLEMENT_STATUS_DIR") or np_dirs.cache_path("implement-status")
IMPLEMENT_QUEUE_DIR = (os.environ.get("NP_IMPLEMENT_QUEUE_DIR")
                       or np_implement_suggestion.queue_dir(IMPLEMENT_STATUS_DIR))
LOG = np_dirs.cache_path("dashboard-server.log")

PORT = int(os.environ.get("NP_DASH_PORT", "8787") or "8787")
TOP = int(os.environ.get("NP_SUGGESTIONS_TOP", "10") or "10")
_METRICS = os.environ.get("NP_METRICS")
_RESOLVED = os.environ.get("NP_RESOLVED_SUGGESTIONS")
_NO_BUILD = os.environ.get("NP_RESOLVE_NO_BUILD") == "1"


def _review_args(*extra):
    """Build the np-suggestions-review.py argv, threading through any test overrides."""
    args = [sys.executable, REVIEW]
    if _METRICS:
        args += ["--metrics", _METRICS]
    if _RESOLVED:
        args += ["--resolved", _RESOLVED]
    return args + list(extra)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript",
    ".css": "text/css", ".json": "application/json", ".txt": "text/plain",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
}


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def implement_status(text):
    """The job's per-suggestion status (busy|running|done|not_implementable|failed),
    keyed by a hash of the exact text — the same key np_implement_suggestion.py writes.
    Missing -> {'state':'none'}. Lets the dashboard poll a row to completion."""
    if not text:
        return {"state": "none"}
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        with open(os.path.join(IMPLEMENT_STATUS_DIR, key + ".json")) as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return {"state": "none"}
    if st.get("state") == "queued":
        # The position shifts as the queue drains, so read it live.
        pos = np_implement_suggestion.queue_position(IMPLEMENT_QUEUE_DIR, key)
        if pos:
            st["position"] = pos
    return st


def implement_queue():
    """The running job (or None) plus queued entries in FIFO order."""
    running = np_implement_suggestion.running_job(IMPLEMENT_QUEUE_DIR)
    queued = [{"text": e.get("text", ""), "position": i, "enqueued_at": e.get("enqueued_at", ""),
               "target": e.get("target", "")}
              for i, (_, e) in enumerate(np_implement_suggestion.queue_entries(IMPLEMENT_QUEUE_DIR), 1)]
    run = ({"text": running.get("text", ""), "started_at": running.get("started_at", "")}
           if running else None)
    return {"running": run, "queued": queued, "count": len(queued)}


def already_pending(text):
    """True when `text` is queued or is the live running job (click dedupe)."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    if np_implement_suggestion.queue_position(IMPLEMENT_QUEUE_DIR, key):
        return True
    running = np_implement_suggestion.running_job(IMPLEMENT_QUEUE_DIR)
    return bool(running and running.get("key") == key)


# --- models ------------------------------------------------------------------
# (feature name, tier). Each maps to the models.<feature_key> toggle param.
MODEL_FEATURES = (
    ("implement", "agent"), ("episodic-maintain", "agent"), ("memory-promote", "agent"),
    ("skill-maintain", "agent"), ("refine", "agent"), ("compact", "agent"),
    ("kb-promote-scan", "agent"), ("evaluator", "cheap"), ("capture", "cheap"),
    ("review", "cheap"), ("diff-review", "cheap"), ("doctor", "cheap"),
)
_TIER_ENV = {"cheap": "NP_LLM_MODEL_CHEAP", "agent": "NP_LLM_MODEL_AGENT"}


def _recent_model_errors(max_age=86400):
    """Status files flagged model_error in the last `max_age` seconds."""
    out = []
    cutoff = time.time() - max_age
    try:
        names = os.listdir(IMPLEMENT_STATUS_DIR)
    except OSError:
        return out
    for n in names:
        path = os.path.join(IMPLEMENT_STATUS_DIR, n)
        try:
            if not n.endswith(".json") or os.stat(path).st_mtime < cutoff:
                continue
            with open(path) as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            continue
        if st.get("model_error"):
            out.append({"model": st.get("model", ""), "ts": st.get("ts", ""),
                        "feature": "implement", "reason": st.get("ref", "")})
    return out


def _model_row(feature, key, tier, is_tier):
    return {"feature": feature, "key": key, "tier": tier, "is_tier": is_tier,
            "selected": np_toggle.param("models." + key, ""),
            "effective": np_model.resolve_model(tier, None if is_tier else feature),
            "env_override": bool(os.environ.get(_TIER_ENV[tier]))}


def models_view():
    """Inventory, per-feature selection + effective model, and probe results."""
    rows = [_model_row(t, t, t, True) for t in ("cheap", "agent")]
    rows += [_model_row(f, np_model.feature_key(f), t, False) for f, t in MODEL_FEATURES]
    return {"enabled": np_toggle.enabled("models"), "inventory": np_model.inventory(),
            "features": rows, "probe": np_model.load_probe_cache(),
            "model_errors": _recent_model_errors()}


def _model_keys():
    return {"cheap", "agent"} | {np_model.feature_key(f) for f, _ in MODEL_FEATURES}


def current_mode():
    """Resolve evaluator.implement_mode via np_toggle.param (single source of truth,
    in-process — no bash). Default pr; coerce anything unexpected to pr."""
    try:
        m = np_toggle.param("evaluator.implement_mode", "pr")
        return m if m in ("pr", "direct") else "pr"
    except Exception:
        return "pr"


def set_implement_mode(mode):
    """Write the per-machine LOCAL override (not committed) so the dashboard can flip
    pr<->direct without a commit — in-process via np_toggle.set_local (single source
    of truth; honors NP_TOGGLES_LOCAL identically to TOGGLES_LOCAL above)."""
    np_toggle.set_local("evaluator.implement_mode", mode)


def toggle_ui_enabled():
    return np_toggle.param("evaluator.toggle_ui", "on") == "on"


def toggle_families():
    """Every declared feature, schema-annotated for the dashboard panel. See
    np_toggle.all_params() (Task 2) and np_toggle_schema.validate() (Task 1)."""
    out = []
    for feat in np_toggle.features():
        params = []
        for key, raw in sorted(np_toggle.all_params(feat).items()):
            dotted = feat + "." + key
            valid, coerced, error = np_toggle_schema.validate(dotted, raw)
            params.append({
                "key": key, "value": raw, "valid": valid, "coerced": coerced,
                "error": error, "schema": np_toggle_schema.load().get(dotted),
                "self_lockout": dotted in SELF_LOCKOUT_PARAMS,
            })
        out.append({
            "feature": feat, "scope": np_toggle.scope(feat),
            "enabled": np_toggle.enabled(feat),
            "self_lockout": feat in SELF_LOCKOUT_FEATURES,
            "description": (np_toggle_schema.load().get(feat) or {}).get("description"),
            "params": params,
        })
    return out


def review_rows():
    """Top-N open suggestions (deterministic) annotated with a single Haiku verdict
    pass. Returns (rows, degraded) — degraded=True if the LLM seam was unavailable,
    in which case rows carry no `verdict`."""
    out = subprocess.run(
        _review_args("list", "--top", str(TOP), "--json"),
        capture_output=True, text=True, timeout=30)
    rows = json.loads(out.stdout or "[]")
    if not rows:
        return [], False
    listing = "\n".join(f"{i}. {r['text']}" for i, r in enumerate(rows))
    prompt = (
        "You triage nervepack evaluator suggestions. For EACH numbered suggestion, "
        "decide whether it is worth implementing now. Reply with ONLY a JSON array "
        "of objects {\"i\": <index>, \"decision\": \"implement\"|\"skip\", "
        "\"reason\": \"<=12 words\"}. No prose, no code fence.\n\n" + listing)
    try:
        out = np_model.complete(prompt, timeout=120, feature="review")
        verdicts = json.loads(_strip_fence(out))
        by_i = {int(v["i"]): v for v in verdicts if "i" in v}
        for i, r in enumerate(rows):
            v = by_i.get(i)
            if v:
                r["verdict"] = {"decision": v.get("decision", "skip"),
                                "reason": v.get("reason", "")}
        return rows, False
    except Exception as exc:  # seam offline / unparseable -> degrade, keep ranking
        log(f"review degraded: {exc}")
        return rows, True


def _strip_fence(s):
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence default stderr noise
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safe_path(self):
        """Map the URL path to a real file UNDER dashboard/ or return None."""
        rel = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(DASH, rel))
        for root in (DASH, DATA):  # DATA covers the symlinked-out content data dir
            if full == root or full.startswith(root + os.sep):
                return full
        return None  # path traversal attempt

    def do_GET(self):
        if not self._host_ok():  # anti-DNS-rebinding: GET reads are loopback-Host only
            return self._json({"error": "forbidden"}, 403)
        try:
            if self.path.split("?")[0] == "/api/health":
                return self._json({"ok": True})
            if self.path.split("?")[0] == "/api/config":
                return self._json({"implement_mode": current_mode()})
            if self.path.split("?")[0] == "/api/implement-status":
                text = (parse_qs(urlparse(self.path).query).get("text") or [""])[0]
                return self._json(implement_status(text))
            if self.path.split("?")[0] == "/api/implement-queue":
                return self._json(implement_queue())
            if self.path.split("?")[0] == "/api/models":
                return self._json(models_view())
            if self.path.split("?")[0] == "/api/toggles":
                if not toggle_ui_enabled():
                    return self._json({"error": "not found"}, 404)
                return self._json({"families": toggle_families()})
            full = self._safe_path()
            if not full or not os.path.isfile(full):
                return self._json({"error": "not found"}, 404)
            ext = os.path.splitext(full)[1]
            with open(full, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # fail-open: report, stay up
            log(f"GET {self.path}: {exc}")
            try: self._json({"error": str(exc)}, 500)
            except Exception: pass

    def _host_ok(self):
        """Loopback-Host check — the anti-DNS-rebinding piece. A rebinding page
        sees the server as same-origin, but the browser still sends the attacker's
        hostname in Host, so requiring a loopback Host defeats it. Applied to BOTH
        GET (data reads: metrics/config/toggles/static) and POST (state changes) —
        previously only POST was guarded, leaking local data to a rebinding page."""
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _origin_ok(self):
        """CSRF guard for the state-changing POST routes: a loopback Host
        (_host_ok, defeats DNS-rebinding), a loopback Origin when one is sent, and a
        custom header the dashboard JS sets — which a simple cross-origin form POST
        cannot add without a preflight this server never approves."""
        if not self._host_ok():
            return False
        origin = self.headers.get("Origin") or ""
        if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            return False
        return self.headers.get("X-Requested-With") == "nervepack"

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_POST(self):
        if not self._origin_ok():
            return self._json({"error": "forbidden"}, 403)
        route = self.path.split("?", 1)[0]
        try:
            if route == "/api/resolve":
                text = (self._body().get("text") or "").strip()
                if not text:
                    return self._json({"error": "missing text"}, 400)
                np_suggestion_resolve.resolve(text, ledger_path=_RESOLVED or None, no_build=_NO_BUILD or None)
                return self._json({"ok": True})
            if route == "/api/implement":
                body = self._body()
                text = (body.get("text") or "").strip()
                if not text:
                    return self._json({"error": "missing text"}, 400)
                # Optional Modify-box rewrite. Capped like the suggestion text itself —
                # it reaches the agent prompt, which caps and data-fences it again.
                edited = (body.get("edited") or "").strip()[:2000]
                extra = [edited] if edited and edited != text else []
                # The evaluator's own layer classification, forwarded so the job
                # can try the right repo first. The job allowlists it.
                target = (body.get("target") or "").strip()[:32]
                if target:
                    extra = extra + ["--target=" + target]
                # A second click on a queued or running row is a no-op.
                if already_pending(text):
                    return self._json({"ok": True, "deduped": True,
                                       "status": implement_status(text)})
                # Spawn the agentic job DETACHED — it takes minutes; never block the
                # request. The job owns the lock, clean-tree check, branch/mode, agent
                # call, push, and resolve. argv list (no shell) per the §10 lockdown.
                # preexec_fn: reset SIGCHLD to default in this child so its own
                # subprocess tree (git, the agent) doesn't inherit this process's
                # SIG_IGN and misreport exit statuses on Linux — see
                # implement_job_preexec()'s docstring.
                subprocess.Popen(np_bashlib.argv(IMPLEMENT_ARGV + [text] + extra), cwd=NP, start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 preexec_fn=implement_job_preexec if os.name != "nt" else None)
                return self._json({"ok": True, "started": True})
            if route == "/api/models/select":
                body = self._body()
                key = np_model.feature_key(body.get("feature") or "")
                model = (body.get("model") or "").strip()
                if key not in _model_keys():
                    return self._json({"error": "unknown feature"}, 400)
                ids = {m.get("id") for m in np_model.inventory()}
                if model and model not in ids:
                    return self._json({"error": "model not in inventory"}, 400)
                # Empty clears the override, so the feature inherits its tier.
                np_toggle.set_local("models." + key, model)
                return self._json({"ok": True, "models": models_view()})
            if route == "/api/models/probe":
                if not np_toggle.enabled("models"):
                    return self._json({"error": "models toggle is off"}, 400)
                model = (self._body().get("model") or "").strip()
                ids = [m.get("id") for m in np_model.inventory() if m.get("id")]
                if model and model not in ids:
                    return self._json({"error": "model not in inventory"}, 400)
                results = {m: np_model.probe(m, timeout=45) for m in ([model] if model else ids)}
                return self._json({"ok": True, "results": results, "models": models_view()})
            if route == "/api/implement-mode":
                mode = (self._body().get("mode") or "").strip()
                if mode not in ("pr", "direct"):
                    return self._json({"error": "mode must be pr or direct"}, 400)
                set_implement_mode(mode)
                return self._json({"ok": True, "mode": mode})
            if route == "/api/toggle":
                if not toggle_ui_enabled():
                    return self._json({"error": "not found"}, 404)
                body = self._body()
                key = (body.get("key") or "").strip()
                value = body.get("value")
                if not key or value is None:
                    return self._json({"error": "missing key or value"}, 400)
                value = str(value)
                if key in SELF_LOCKOUT_FEATURES or key in SELF_LOCKOUT_PARAMS:
                    return self._json({"error": "this toggle controls the dashboard itself — "
                                                 "use the CLI (cli.py toggle)"}, 400)
                if key in np_toggle.features():
                    # A bare feature — note some feature NAMES contain a dot themselves
                    # (e.g. "maintain.refine"), so membership in features() is checked
                    # BEFORE falling back to "contains a dot -> dotted param" below.
                    # Flip in-process (single call path — no bash): shared-scope writes
                    # commit+push (gated by NP_TOGGLE_NO_COMMIT), managed installs perms.
                    if value not in ("on", "off"):
                        return self._json({"error": "value must be on or off"}, 400)
                    try:
                        np_toggle.flip(key, value)
                    except Exception as exc:
                        return self._json({"error": str(exc) or "toggle failed"}, 500)
                    return self._json({"ok": True, "key": key, "value": value})
                if "." in key:
                    valid, coerced, error = np_toggle_schema.validate(key, value)
                    if not valid:
                        return self._json({"error": error}, 400)
                    np_toggle.set_local(key, value)
                    return self._json({"ok": True, "key": key, "value": value})
                return self._json({"error": "unknown feature %r" % (key,)}, 400)
            if route == "/api/review":
                rows, degraded = review_rows()
                return self._json({"rows": rows, "degraded": degraded})
            if route == "/api/clear":
                before = json.loads(subprocess.run(
                    _review_args("list", "--top", "0", "--json"),
                    capture_output=True, text=True, timeout=30).stdout or "[]")
                clear = _review_args("clear") + (["--no-build"] if _NO_BUILD else [])
                subprocess.run(clear, capture_output=True, text=True, timeout=60)
                return self._json({"ok": True, "count": len(before)})
            return self._json({"error": "no such route"}, 404)
        except Exception as exc:  # fail-open
            log(f"POST {route}: {exc}")
            return self._json({"error": str(exc)}, 500)


def _autoreap_children():
    """Reap detached children (the implement jobs) as they exit.

    We Popen() those jobs fire-and-forget and never wait() on them, so each one
    lingers as a zombie for the server's whole lifetime. A zombie keeps its
    pid-table entry, so a lock left behind by a job that died before cleanup
    looks permanently owned and every later Implement click bails "busy".
    _pid_alive() now detects zombies directly; this stops producing them at all.
    POSIX only — SIGCHLD does not exist on Windows. Fail-open."""
    if os.name == "nt":
        return
    try:
        import signal
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    except (ImportError, OSError, ValueError, AttributeError):
        pass


def implement_job_preexec():
    """preexec_fn for the implement job's own Popen call — resets SIGCHLD to
    SIG_DFL in that child before it execs np_implement_suggestion.py.

    subprocess.Popen's restore_signals (default True) resets SIGPIPE/SIGXFSZ/
    SIGXFZ before exec but deliberately NOT SIGCHLD, so the SIG_IGN set by
    _autoreap_children() above survives exec() and is inherited by the whole
    descendant tree — the spawned cli.py process AND every git/agent
    subprocess it spawns in turn. On Linux, SIG_IGN for SIGCHLD makes the
    KERNEL auto-reap children immediately, which races any explicit waitpid()
    in that subtree: git's own internal helper-process reap (surfacing as
    git's own "waitpid for branch failed: No child processes" stderr) AND
    Python's subprocess.communicate() in np_implement_suggestion.py, which can
    then report returncode=0 for a git command that never actually ran —
    observed live as `git worktree add` reporting success while never
    creating the worktree. Only this one child's disposition is reset; the
    server's own SIG_IGN (needed so IT doesn't zombie this direct child) is
    untouched. POSIX only — the caller must not pass this on Windows."""
    import signal
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def main():
    _autoreap_children()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"serving dashboard on http://127.0.0.1:{PORT}/ (top={TOP})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
