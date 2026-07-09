#!/usr/bin/env python3
"""Opt-in local backend for the nervepack performance dashboard.

The dashboard is normally a static file:// page. When `evaluator.dashboard_serve`
is on, the open scripts launch THIS tiny server instead and point the browser at
http://127.0.0.1:<port>/ so the dashboard's action buttons have a backend:

  GET  /                      -> dashboard/index.html
  GET  /<path>                -> static file under dashboard/ (path-sanitized)
  GET  /api/health            -> {"ok": true}
  POST /api/resolve {text}    -> mark one suggestion acted-on (np-suggestion-resolve.sh)
  POST /api/review  {}        -> top-N open suggestions + a single Haiku verdict pass
  POST /api/clear   {}        -> resolve ALL open suggestions (reset), {ok, count}

This is a deliberate, documented exception to nervepack's "no service, no daemon"
invariant: it is OFF by default, binds to 127.0.0.1 ONLY, serves a fixed directory,
and exposes a fixed route allowlist (no arbitrary command exec; subprocess args are
passed as argv lists, never a shell string). Stdlib only (http.server), per the
harness language policy. Fail-open: a bad request returns an error response; the
server itself never crashes.

Env: NP_DASH_PORT (default 8787) · NP_SUGGESTIONS_TOP (default 10) · the review
pass shells out to setup/np-llm.sh (the backend-neutral LLM seam, which sets
NERVEPACK_AGENT) and degrades gracefully if it's unavailable.
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
import np_bashlib  # noqa: E402
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
RESOLVE = os.path.join(HERE, "np-suggestion-resolve.sh")
IMPLEMENT = os.environ.get("NP_IMPLEMENT") or os.path.join(HERE, "np-implement-suggestion.sh")
NPLLM = os.path.join(HERE, "np-llm.sh")
TOGGLES_LIB = os.path.join(HERE, "np-toggle-lib.sh")
TOGGLE_CLI = os.path.join(HERE, "nervepack-toggle.sh")
TOGGLES_LOCAL = os.environ.get("NP_TOGGLES_LOCAL") or os.path.expanduser("~/.config/nervepack/toggles.local")
# Toggles the dashboard's OWN gating — flipping any of these from the panel would
# disable the very server/panel serving that click, so the panel renders them
# read-only and the server refuses to write them even if asked directly.
SELF_LOCKOUT_FEATURES = {"evaluator"}
SELF_LOCKOUT_PARAMS = {"evaluator.dashboard_open", "evaluator.dashboard_serve", "evaluator.toggle_ui"}
IMPLEMENT_STATUS_DIR = os.environ.get("NP_IMPLEMENT_STATUS_DIR") or os.path.expanduser("~/.cache/nervepack/implement-status")
LOG = os.path.join(os.path.expanduser("~"), ".cache", "nervepack", "dashboard-server.log")

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
    keyed by a hash of the exact text — the same key np-implement-suggestion.sh writes.
    Missing -> {'state':'none'}. Lets the dashboard poll a row to completion."""
    if not text:
        return {"state": "none"}
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        with open(os.path.join(IMPLEMENT_STATUS_DIR, key + ".json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"state": "none"}


def current_mode():
    """Resolve evaluator.implement_mode via np_param (single source of truth). Default pr."""
    try:
        r = subprocess.run(
            np_bashlib.argv(["bash", "-c", 'source "$0"; np_param evaluator.implement_mode pr', TOGGLES_LIB]),
            capture_output=True, text=True, timeout=5)
        m = (r.stdout or "").strip()
        return m if m in ("pr", "direct") else "pr"
    except Exception:
        return "pr"


def set_implement_mode(mode):
    """Write the per-machine LOCAL override (not committed) so the dashboard can flip
    pr<->direct without a commit. Mirrors nervepack-toggle's _set_local."""
    key = "evaluator.implement_mode"
    lines = []
    try:
        with open(TOGGLES_LOCAL) as fh:
            lines = [ln for ln in fh if ln.split("=", 1)[0].strip() != key]
    except FileNotFoundError:
        os.makedirs(os.path.dirname(TOGGLES_LOCAL), exist_ok=True)
    lines.append(f"{key}={mode}\n")
    with open(TOGGLES_LOCAL, "w") as fh:
        fh.writelines(lines)


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
        p = subprocess.run(np_bashlib.argv([NPLLM, "complete"]), input=prompt,
                           capture_output=True, text=True, timeout=120)
        verdicts = json.loads(_strip_fence(p.stdout))
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
        try:
            if self.path.split("?")[0] == "/api/health":
                return self._json({"ok": True})
            if self.path.split("?")[0] == "/api/config":
                return self._json({"implement_mode": current_mode()})
            if self.path.split("?")[0] == "/api/implement-status":
                text = (parse_qs(urlparse(self.path).query).get("text") or [""])[0]
                return self._json(implement_status(text))
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

    def _origin_ok(self):
        """CSRF/DNS-rebinding guard for the state-changing POST routes. Even though
        the server binds to loopback, a web page the user visits could POST to
        127.0.0.1:<port>. Require: a loopback Host (defeats DNS-rebinding, where Host
        is the attacker's name), a loopback Origin when one is sent, and a custom
        header the dashboard JS sets — which a simple cross-origin form POST cannot
        add without a preflight this server never approves."""
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
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
                subprocess.run(np_bashlib.argv([RESOLVE, text]), capture_output=True, text=True, timeout=30)
                return self._json({"ok": True})
            if route == "/api/implement":
                text = (self._body().get("text") or "").strip()
                if not text:
                    return self._json({"error": "missing text"}, 400)
                # Spawn the agentic job DETACHED — it takes minutes; never block the
                # request. The job owns the lock, clean-tree check, branch/mode, agent
                # call, push, and resolve. argv list (no shell) per the §10 lockdown.
                subprocess.Popen(np_bashlib.argv([IMPLEMENT, text]), cwd=NP, start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return self._json({"ok": True, "started": True})
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
                                                 "use the CLI (nervepack-toggle.sh)"}, 400)
                if key in np_toggle.features():
                    # A bare feature — note some feature NAMES contain a dot themselves
                    # (e.g. "maintain.refine"), so membership in features() is checked
                    # BEFORE falling back to "contains a dot -> dotted param" below.
                    if value not in ("on", "off"):
                        return self._json({"error": "value must be on or off"}, 400)
                    r = subprocess.run(np_bashlib.argv([TOGGLE_CLI, key, value]), cwd=NP,
                                       capture_output=True, text=True, timeout=30)
                    if r.returncode != 0:
                        return self._json({"error": (r.stderr or "toggle failed").strip()}, 500)
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


def main():
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
