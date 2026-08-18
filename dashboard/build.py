#!/usr/bin/env python3
"""Dumb data transport for the P2 dashboard: read the append-only metrics JSONL
and write a metrics.js (`window.METRICS = [...]`) that index.html loads via a
<script> tag (file:// can't fetch a sibling .jsonl — CORS). No aggregation here;
index.html owns that. Deterministic, idempotent, fail-open (exit 0 on trouble),
per the harness language policy in CLAUDE.md.

Usage: build.py [input.jsonl] [output.js]
Defaults: dashboard/data/metrics.jsonl -> dashboard/data/metrics.js
"""
import calendar
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(HERE, "data", "metrics.jsonl")
DEFAULT_OUT = os.path.join(HERE, "data", "metrics.js")

# np_toggle was relocated into engine/nervepack_engine/ in phase 20b-2; import it from
# there in-process for toggle reads. (The layer-stack resolver np_content.py is invoked
# as a native subprocess below; engine/setup stays on the path for its stayed siblings.)
sys.path.insert(0, os.path.join(HERE, "..", "engine", "setup"))
sys.path.insert(0, os.path.join(HERE, "..", "engine", "nervepack_engine"))
import np_toggle  # noqa: E402


def default_resolved():
    """Default path for resolved-suggestions.txt: resolved through _content_dir() so a
    bare build.py invocation writes into the overlay root, not the engine tree.
    NP_RESOLVED_SUGGESTIONS env var still takes precedence (kept for tests + callers)."""
    return os.path.join(_content_dir(), "dashboard", "data", "resolved-suggestions.txt")


EMPTY_GRADUATION = {"candidates": [], "thresholds": {"graduate_seen": 10, "graduate_kb": 6}}


def default_graduation():
    """Default path for graduation-candidates.json: resolved through _content_dir() so a
    bare build.py invocation reads from the overlay root, not the engine tree (candidates
    derive from the personal content overlay — the engine stays PII-clean). The producer
    (np_skill_maintain.py) writes it there. NP_GRADUATION_CANDIDATES env var overrides."""
    return os.path.join(_content_dir(), "dashboard", "data", "graduation-candidates.json")


def load_graduation(path):
    """Graduation candidates (lessons overdue to become skills), as written
    by np_skill_maintain.py via np_graduation_detect.py. Shape:
    {candidates:[{kind,name,seen,bytes,reasons[]}], thresholds:{graduate_seen,graduate_kb}}.
    Fail-open: missing file (cloud/CI, or no candidates) or malformed JSON -> empty
    candidate list, so the panel renders its empty state and never crashes."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return dict(EMPTY_GRADUATION)
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return dict(EMPTY_GRADUATION)
    return data


def default_ledger():
    """Default path for ledger.jsonl: resolved through _content_dir(), same as
    metrics.jsonl and graduation-candidates.json - the change-keyed record
    (F5/#251) lives in the overlay, written locally by np-ledger-append.py
    (not from CI - see that script's own docstring for why). NP_LEDGER env
    var overrides, matching the NP_GRADUATION_CANDIDATES/NP_RESOLVED_SUGGESTIONS
    precedent above."""
    return os.path.join(_content_dir(), "dashboard", "data", "ledger.jsonl")


EMPTY_BACKLOG = {"pending": 0, "oldest_pending_days": None, "ceiling_days": 7.0,
                 "resolved_last_24h": 0}


def backlog_metrics():
    """Back-capture sweep backlog snapshot: how many prior sessions are queued but
    not yet processed by np-backcapture-sweep.sh, how stale the oldest pending one
    is relative to the memory.backcapture_days discovery ceiling, and how many were
    resolved (captured, or found already-in-metrics) in the last 24h. Reads the same
    local-cache dirs the sweep script uses; BACKCAPTURE_QUEUE_DIR/BACKCAPTURE_SEEN_DIR
    env overrides match the sweep script's own names so tests can point both at temp
    dirs. Fail-open: a missing dir or an unreadable/malformed queue entry is skipped,
    never crashes the build."""
    queue_dir = os.environ.get(
        "BACKCAPTURE_QUEUE_DIR", os.path.expanduser("~/.cache/nervepack/backcapture-queue"))
    seen_dir = os.environ.get(
        "BACKCAPTURE_SEEN_DIR", os.path.expanduser("~/.cache/nervepack/backcapture-seen"))
    try:
        ceiling_days = float(np_toggle.param("memory.backcapture_days", "7"))
    except (ValueError, TypeError):
        ceiling_days = 7.0

    try:
        queued = os.listdir(queue_dir)
    except OSError:
        queued = []
    try:
        seen = set(os.listdir(seen_dir))
    except OSError:
        seen = set()

    now = time.time()
    pending = 0
    oldest_mt = None
    for sid in queued:
        if sid in seen:
            continue
        pending += 1
        try:
            with open(os.path.join(queue_dir, sid), encoding="utf-8") as fh:
                mt = json.load(fh).get("mtime")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(mt, (int, float)) and (oldest_mt is None or mt < oldest_mt):
            oldest_mt = mt

    resolved_last_24h = 0
    for sid in seen:
        try:
            mt = os.path.getmtime(os.path.join(seen_dir, sid))
        except OSError:
            continue
        if now - mt < 86400:
            resolved_last_24h += 1

    return {
        "pending": pending,
        "oldest_pending_days": round((now - oldest_mt) / 86400, 1) if oldest_mt is not None else None,
        "ceiling_days": ceiling_days,
        "resolved_last_24h": resolved_last_24h,
    }


def _norm(s):
    """Normalize a suggestion for matching: collapse whitespace, lowercase."""
    return " ".join(str(s).split()).lower()


def load_resolved(path):
    """Resolved/acted-on suggestions to never resurface — one suggestion text per
    line (blank and #-comment lines ignored). Lines may carry an optional trailing
    tab+ISO-timestamp (appended by np_suggestion_resolve.py for retention pruning);
    the timestamp is stripped before normalization. Matched normalized. Missing = none."""
    resolved = set()
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    text = line.split("\t", 1)[0]  # strip optional \t<ts> suffix
                    if text:
                        resolved.add(_norm(text))
    except FileNotFoundError:
        pass
    return resolved


def drop_resolved(records, resolved):
    """Remove resolved suggestions from each record's suggestions[] (in place-safe)."""
    if not resolved:
        return records
    for r in records:
        sugg = r.get("suggestions")
        if isinstance(sugg, list):
            r["suggestions"] = [s for s in sugg
                                if _norm(s.get("text", "")) not in resolved]
    return records


def _content_dir():
    """Resolve the content-overlay root, mirroring np_content.py's precedence:
    $NP_CONTENT_DIR -> ~/.config/nervepack/content-dir (first line) -> engine root.
    Since the engine/content split, memory/lessons/ lives in the overlay,
    not the engine repo, so a bare build.py (manual open-dashboard, MCP summary) must
    resolve them here rather than defaulting to the now-empty engine paths. Unset
    config falls back to the engine root == byte-identical to the legacy layout."""
    d = os.environ.get("NP_CONTENT_DIR", "").strip()
    if not d:
        cfg = os.path.expanduser("~/.config/nervepack/content-dir")
        if os.path.isfile(cfg):
            with open(cfg, encoding="utf-8") as fh:
                d = fh.readline().strip()
    return d or os.path.join(HERE, "..")


def _np_content_py():
    return os.path.join(HERE, "..", "engine", "nervepack_engine", "np_content.py")


def _np_content_fn(verb):
    """Run `np_content.py <verb>` and return its stdout (empty on any failure). A
    native Python-to-Python subprocess — np-layer-lib.sh was retired in phase 18,
    so np_content.py is the sole layer-stack resolver (and this is now bash-free)."""
    try:
        r = subprocess.run([sys.executable, _np_content_py(), verb],
                           capture_output=True, text=True)
        return r.stdout
    except Exception:
        return ""


def _content_layers():
    """Overlay roots to scan (team then personal) for the current merge mode, via
    np_content.py merge_roots. Fail-open to [_content_dir()] when it yields nothing."""
    roots = [ln for ln in _np_content_fn("merge_roots").splitlines() if ln.strip()]
    return roots or [_content_dir()]


def _merge_mode():
    m = _np_content_fn("merge_mode").strip()
    return m if m in ("override", "concatenate", "team-only") else "override"


def _engine_dir():
    """Engine repo root — the lowest-precedence wiki layer. `NP_ENGINE_DIR` overrides
    it (tests); otherwise it is the repo this build.py ships in."""
    d = os.environ.get("NP_ENGINE_DIR", "").strip()
    return d or os.path.join(HERE, "..")


def _wiki_roots():
    """Wiki layers to scan, highest precedence first: the merge roots (team… then
    personal), plus the engine root appended last.

    The engine ships its own `wiki/topics/`, which `merge_roots()` never returns —
    without this the engine's pages are invisible in the dashboard (#142a). Skipped
    when the engine dir IS a content layer (the legacy single-repo layout, where
    _content_dir() falls back to the engine root), and under `team-only`, whose
    contract is team layers only."""
    roots = _content_layers()
    if _merge_mode() == "team-only":
        return roots
    eng = _engine_dir()
    try:
        seen = {os.path.realpath(r) for r in roots}
        dup = os.path.realpath(eng) in seen
    except OSError:                       # unresolvable path: fail open, don't add
        dup = True
    return roots if dup else roots + [eng]


_SLUG_UNSAFE = re.compile(r'[^A-Za-z0-9._-]+')


def _layer_slug(label):
    """Filesystem-safe single path segment for a layer's rendered pages. A team
    overlay's dir basename reaches this unfiltered, so anything that could escape
    the output tree (separators, '..') is neutralised here."""
    s = _SLUG_UNSAFE.sub("-", label or "").strip("-.")
    return s or "layer"


def _layer_label(root, personal):
    """Display name of the overlay a wiki entry came from: the personal content dir
    is the literal 'personal', any other merge root (a team overlay) is its dir
    basename, which stays self-describing with up to 4 team dirs stacked.
    Compared against _content_dir() rather than derived from the root's position in
    merge_roots(), because team-only mode drops personal from that list entirely."""
    if not root:
        return ""
    if personal and os.path.normpath(root) == os.path.normpath(personal):
        return "personal"
    return os.path.basename(os.path.normpath(root)) or "team"


# Allowed link targets: http(s)/mailto, root-relative (not protocol-relative //),
# fragment, or ./ ../ relative. Explicit alternation avoids \.{0,2}/ matching //.
_SAFE_HREF = re.compile(r'^(https?:|mailto:|/(?!/)|#|\./|\.\./)' , re.I)


def _safe_href(url):
    """Return url if it's an allowed scheme/relative target, else '' (drop it).
    Blocks javascript:/data: and anything else that could execute."""
    url = (url or "").strip()
    return url if _SAFE_HREF.match(url) else ""


def _render_inline(s, link_map=None, here=""):
    """Inline Markdown -> HTML on a single text run. Escapes first (so any literal
    HTML in content is inert), then applies code/bold/italic, [[wikilinks]] (resolved
    against link_map relative to `here`, dangling -> plain text), and [text](url)
    (href sanitized). All emitted text is already escaped."""
    s = html.escape(s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', s)

    def _wl(m):
        name = m.group(1)
        if link_map and name in link_map:
            target = link_map[name]
            href = posixpath.relpath(target, here) if here else target
            return '<a href="%s">%s</a>' % (html.escape(href), name)
        return name  # dangling link -> plain text (already escaped)
    s = re.sub(r'\[\[([^\]]+)\]\]', _wl, s)

    def _lk(m):
        text, url = m.group(1), _safe_href(m.group(2))
        return '<a href="%s">%s</a>' % (html.escape(url), text) if url else text
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _lk, s)
    return s


_PAGE_CSS = (
    "body{margin:0;background:#fbfaf8;color:#181614;"
    "font:15px/1.55 'Inter',system-ui,sans-serif}"
    "article{max-width:720px;margin:0 auto;padding:32px 20px}"
    "h1,h2,h3{font-weight:600;line-height:1.3}"
    "a{color:#406478}code{font-family:ui-monospace,Menlo,monospace;font-size:.92em;"
    "background:#f5f3ef;padding:1px 4px;border-radius:4px}"
    "pre{background:#f5f3ef;padding:12px;border-radius:9px;overflow:auto}"
    "pre code{background:none;padding:0}"
    "pre.mermaid{background:none;padding:0;text-align:center;overflow-x:auto}"
    "table{border-collapse:collapse;margin:14px 0;width:100%;font-size:.95em}"
    "th,td{border:1px solid #e3e0da;padding:6px 10px;text-align:left;vertical-align:top}"
    "th{background:#f5f3ef;font-weight:600}"
    "tbody tr:nth-child(even){background:#faf9f6}"
    "blockquote{border-left:3px solid #e8e5df;margin:0;padding:2px 14px;color:#5e5b56}"
    ".np-head{color:#9b9892;font-size:12px;border-bottom:1px solid #e8e5df;"
    "padding-bottom:8px;margin-bottom:18px;display:flex;justify-content:space-between}"
    ".np-head a{color:#476b51;text-decoration:none}"
)


def md_to_html(md, meta=None, link_map=None, here=""):
    """Render the Markdown subset nervepack content uses to a full styled HTML
    document (self-contained <style>, no external fetch). meta drives the page
    header; link_map/here resolve [[wikilinks]]. Pure + deterministic + escaped."""
    meta = meta or {}
    out, i = [], 0
    has_mermaid = False
    lines = md.split("\n")
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("```"):
            info = ln[3:].strip().lower()
            j = i + 1
            buf = []
            while j < n and not lines[j].startswith("```"):
                buf.append(html.escape(lines[j]))
                j += 1
            if info == "mermaid":
                # Browser-rendered via vendored mermaid.js; textContent un-escapes.
                has_mermaid = True
                out.append('<pre class="mermaid">' + "\n".join(buf) + "</pre>")
            else:
                out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r'(#{1,6})\s+(.*)', ln)
        if m:
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, _render_inline(m.group(2), link_map, here), lvl))
            i += 1
            continue
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(_render_inline(lines[i][1:].lstrip(), link_map, here))
                i += 1
            out.append("<blockquote><p>" + " ".join(buf) + "</p></blockquote>")
            continue
        if re.match(r'\s*[-*]\s+', ln):
            buf = []
            while i < n and re.match(r'\s*[-*]\s+', lines[i]):
                buf.append("<li>" + _render_inline(re.sub(r'\s*[-*]\s+', '', lines[i]), link_map, here) + "</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        if re.match(r'\s*\d+\.\s+', ln):
            buf = []
            while i < n and re.match(r'\s*\d+\.\s+', lines[i]):
                buf.append("<li>" + _render_inline(re.sub(r'\s*\d+\.\s+', '', lines[i]), link_map, here) + "</li>")
                i += 1
            out.append("<ol>" + "".join(buf) + "</ol>")
            continue
        # GFM table: a pipe row immediately followed by a |---|---| delimiter row.
        if ("|" in ln and i + 1 < n
                and re.match(r'^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$', lines[i + 1])):
            def _cells(row):
                row = row.strip()
                if row.startswith("|"):
                    row = row[1:]
                if row.endswith("|"):
                    row = row[:-1]
                return [c.strip() for c in row.split("|")]
            header = _cells(ln)
            i += 2  # consume header + delimiter
            body = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                body.append(_cells(lines[i]))
                i += 1
            thead = "".join("<th>%s</th>" % _render_inline(c, link_map, here) for c in header)
            rows = []
            for r in body:
                tds = "".join("<td>%s</td>" % _render_inline(r[k] if k < len(r) else "", link_map, here)
                              for k in range(len(header)))
                rows.append("<tr>" + tds + "</tr>")
            out.append("<table><thead><tr>" + thead + "</tr></thead><tbody>"
                       + "".join(rows) + "</tbody></table>")
            continue
        if ln.strip() == "":
            i += 1
            continue
        buf = [lines[i]]   # always consume the current line (avoids stalling on a stray '|')
        i += 1
        # stop before a line that opens a table (has '|') so the table branch can catch it
        while i < n and lines[i].strip() != "" and not lines[i].startswith(("#", ">", "```")) and "|" not in lines[i]:
            buf.append(lines[i])
            i += 1
        out.append("<p>" + _render_inline(" ".join(buf), link_map, here) + "</p>")

    name = html.escape(str(meta.get("name", "")))
    kind = html.escape(str(meta.get("kind", meta.get("topic", ""))))
    stamp = html.escape(str(meta.get("version") or meta.get("last_updated") or ""))
    layer = html.escape(str(meta.get("layer", "")))
    up = "../" * (here.count("/") + 2)
    back = up + "index.html"
    head = ('<div class="np-head"><span>%s%s%s</span>'
            '<a href="%s">&#8617; dashboard</a></div>') % (
        name, (" &middot; " + kind + (" &middot; " + stamp if stamp else "")) if kind else "",
        (" &middot; " + layer) if layer else "",
        back)
    # Mermaid: load the vendored (local, not CDN) lib only on pages that have a
    # diagram, keeping the no-external-fetch invariant. Gate: WIKI_MERMAID env
    # (set from the evaluator.wiki_mermaid param, mirroring WIKI_NAV).
    mermaid_js = ""
    if has_mermaid and os.environ.get("WIKI_MERMAID", "on") != "off":
        mermaid_js = (
            '<script src="' + up + 'vendor/mermaid.min.js"></script>\n'
            # securityLevel:'strict' (Mermaid default): diagram labels are HTML-escaped
            # and click/href/call directives are ignored. 'loose' would re-parse the
            # <pre class="mermaid"> textContent as live HTML, defeating the build-time
            # html.escape() of the fenced block -> stored XSS from model-authored pages. (#167)
            "<script>mermaid.initialize({startOnLoad:true,securityLevel:'strict'});</script>\n"
        )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>" + (name or "page") + "</title>\n<style>" + _PAGE_CSS + "</style>\n"
        "</head>\n<body>\n<article>\n" + head + "\n" + "\n".join(out) + "\n</article>\n"
        + mermaid_js + "</body>\n</html>\n"
    )


def _parse_wiki_page(path):
    """Parse one wiki/<kind>/<name>.md: pull frontmatter (name/kind/last_updated/
    sources[]) + a short excerpt (first body paragraph, leading heading skipped).
    Stdlib only — a tiny line scanner, not a YAML lib (frontmatter here is flat).
    Returns a dict, or None if the file can't be read (fail-open)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    fm, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            body = text[end + 4:]
            for line in block.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    # sources: ["a", "b"] -> ["a","b"] (flat JSON list; fail-open to []).
    sources = []
    raw = fm.get("sources", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                sources = [str(s) for s in parsed]
        except ValueError:
            sources = []
    # Excerpt: first non-empty paragraph that isn't a markdown heading.
    excerpt = ""
    for para in body.split("\n\n"):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        excerpt = " ".join(para.split())
        break
    name = fm.get("name") or os.path.basename(path)[:-3]
    return {"name": name, "kind": fm.get("kind", ""),
            "last_updated": fm.get("last_updated", ""),
            "sources": sources, "excerpt": excerpt, "path": path,
            "version": fm.get("version", "").strip('"')}


def _group_label(key):
    """Nav heading for a variant key: 'topic' -> 'Topics', 'note' -> 'Notes'."""
    k = (key or "").replace("-", " ").replace("_", " ").strip()
    if not k:
        return "Pages"
    label = k[:1].upper() + k[1:]
    return label if label.endswith("s") else label + "s"


def _variant_plan(cd):
    """[(kind, container_subdir, group_key, folder_owning)] from the layer's declared
    knowledge/reference routes (nervepack#234).

    The nav used to scan literal `wiki/topics` + `wiki/concepts`, so a layer that
    keeps knowledge anywhere else rendered an empty nav even though contribution
    wrote there happily. `container_subdir` is the path prefix before the first
    template variable; `folder_owning` marks a `<dir>/{topic}/{topic}.md` shape,
    where each subdirectory is one synthesis page plus co-located sources."""
    try:
        import np_layout
        layout, _src = np_layout.resolve(cd)
    except Exception:
        return []
    spec = (layout.get("routes") or {}).get("knowledge")
    if not isinstance(spec, dict):
        return []
    entries = spec.get("variants") if "variants" in spec else [spec]
    plan = []
    for e in entries or []:
        path = (e or {}).get("path") or ""
        if "{" not in path:
            continue
        head = path.split("{", 1)[0].rstrip("/")
        if not head:
            continue
        kind = ((e.get("frontmatter") or {}).get("kind")
                or e.get("name") or "").strip()
        if not kind:
            continue
        folder_owning = "{topic}/{topic}" in path
        key = e.get("name") or kind
        plan.append((kind, head, key, folder_owning))
    return plan


def _scan_plan(cd, groups):
    """Adapt _variant_plan into the (kind, subdir, holder, synth_fn, key) tuples the
    indexing loop consumes, creating one group holder per variant."""
    variants = _variant_plan(cd)
    if not variants:
        # A layer that declares no knowledge route (never onboarded, or an empty
        # fixture) keeps the conventional split, so the nav never regresses to blank.
        variants = [("topic", "wiki/topics", "topic", True),
                    ("concept", "wiki/concepts", "concept", True)]
    plan = []
    for kind, subdir, key, folder_owning in variants:
        holder = groups.setdefault(key, [])
        # The rendered-page path keeps only the container's LAST segment, so
        # `wiki/topics` still renders under data/wiki/<layer>/topics/… as before.
        html_seg = subdir.rstrip("/").rsplit("/", 1)[-1]

        def synth_fn(p, html, root, layer, _kind=kind):
            return {"name": p["name"], "kind": _kind, "excerpt": p["excerpt"],
                    "last_updated": p["last_updated"], "sources": p["sources"],
                    "html": html, "root": root, "layer": layer, "shadowed": False,
                    "src": p["path"]}

        # Entry key is "topic" ONLY for the conventional `topic` variant; every
        # other variant (concepts included) keys on "name". That asymmetry predates
        # #234 and is the contract index.html and the build tests both read.
        plan.append((kind, subdir, html_seg, holder, synth_fn,
                     "topic" if key == "topic" else "name", folder_owning))
    return plan


def wiki_index():
    """Grouped wiki index for the dashboard left-nav, from the CONTENT overlay.
    NEW layout: wiki/topics/<topic>/ holds one kind:topic synthesis page + N
    kind:reference sources; wiki/concepts/<concept>/ is symmetric — one kind:concept
    synthesis page + N kind:reference sources.
    Gated by WIKI_NAV (default on, fail-open)."""
    empty = {"topics": [], "concepts": [], "layers": []}
    if os.environ.get("WIKI_NAV", "on").strip().lower() == "off":
        return empty

    roots = _wiki_roots()
    personal = _content_dir()

    def _src_entry(p, topic, subdir, html, root, layer):
        return {"name": p["name"], "topic": topic, "kind": p["kind"] or "reference",
                "dir": subdir, "excerpt": p["excerpt"], "version": p.get("version", ""),
                "html": html, "root": root, "layer": layer, "shadowed": False,
                "src": p["path"]}

    def _synth_entry(p, html, root, layer):
        return {"name": p["name"], "kind": "topic", "excerpt": p["excerpt"],
                "last_updated": p["last_updated"], "sources": p["sources"],
                "html": html, "root": root, "layer": layer, "shadowed": False,
                "src": p["path"]}

    def _concept_synth(p, html, root, layer):
        return {"name": p["name"], "kind": "concept", "excerpt": p["excerpt"],
                "last_updated": p["last_updated"], "sources": p["sources"],
                "html": html, "root": root, "layer": layer, "shadowed": False,
                "src": p["path"]}

    def _index_container(container, kind, subdir, name, root, layer, slug, entry, synth_fn,
                         landing=None):
        """Walk one topic/concept container dir (recursively) for ONE layer, mutating
        `entry` (its 'synthesis' + 'sources'). Shared by the topic and concept passes.
        `synth_fn(page, html, root, layer)` builds the synthesis entry; `subdir` is
        'topics'/'concepts' for the HTML path. (#176)

        `landing` picks the synthesis page BY NAME instead of by `kind`, for a flat
        route's landing subdirectory (`docs/systems/data-mcp/data-mcp.md`): those
        pages carry no `kind:` frontmatter to match on, so name-vs-dirname is the
        only signal. Absent it, no page is promoted and every page nests as a
        source — a directory with no landing page still renders.

        Dedup here is WITHIN this layer only (a page name repeated across the topic's
        subdirs). Cross-layer precedence is the caller's job now: since #142 every
        layer is indexed and lower-precedence copies are MARKED shadowed rather than
        dropped, so provenance stays legible in the nav."""
        claimed = set()
        for dirpath, dirnames, filenames in os.walk(container):
            dirnames.sort()
            sub = os.path.relpath(dirpath, container)
            sub = "" if sub == "." else sub.replace(os.sep, "/")
            for f in sorted(filenames):
                if not f.endswith(".md") or f in ("INDEX.md", "README.md"):
                    continue
                p = _parse_wiki_page(os.path.join(dirpath, f))
                if not p:
                    continue
                rel = (sub + "/" + p["name"]) if sub else p["name"]
                # Layer-qualified: two layers may hold the same topic+page name, and
                # unqualified paths would render both to one file (last writer wins).
                html = "data/wiki/%s/%s/%s/%s.html" % (slug, subdir, name, rel)
                is_synth = (p["name"] == landing) if landing else (p["kind"] == kind)
                if is_synth and sub == "":              # synthesis page at the root only
                    if entry["synthesis"] is None:
                        entry["synthesis"] = synth_fn(p, html, root, layer)
                        claimed.add(p["name"])
                    continue
                if p["name"] in claimed:
                    continue                            # within-layer dedup
                claimed.add(p["name"])
                entry["sources"].append(_src_entry(p, name, sub, html, root, layer))

    def _mark(entry, owned):
        """Flag any page this entry holds whose name a higher-precedence layer already
        owns, then report the names it contributes. Topic-level `shadowed` follows the
        synthesis page — that is what the nav dims."""
        names = []
        s = entry.get("synthesis")
        if s:
            s["shadowed"] = s["name"] in owned
            entry["shadowed"] = s["shadowed"]
            names.append(s["name"])
        for src in entry["sources"]:
            src["shadowed"] = src["name"] in owned
            names.append(src["name"])
        return names

    groups = {}                 # variant key -> entries, one nav group each (#234)
    layers = []
    owned = set()               # page names claimed by a higher-precedence layer
    used = {}                   # label -> count, so two same-basename dirs stay distinct
    for cd in roots:
        label = _layer_label(cd, personal)
        used[label] = used.get(label, 0) + 1
        if used[label] > 1:
            label = "%s (%d)" % (label, used[label])
        slug = _layer_slug(label)
        fresh = []              # names this layer contributes, merged into `owned` after
        got = False             # did this layer contribute anything worth a nav section?

        plan = list(_scan_plan(cd, groups))
        # Containers another declared variant owns. A flat route descends one level
        # (below), and a layer may nest one route inside another's dir --
        # `.claude/references/{name}.md` (convention) contains
        # `.claude/references/data-model/{name}.md` (data-model). Without this the
        # outer route swallows the inner route's pages and reports them twice.
        route_dirs = {os.path.normpath(os.path.join(cd, sd)) for (_k, sd, *_r) in plan}

        for (kind, subdir, html_seg, holder, synth_fn, key,
             folder_owning) in plan:
            root_dir = os.path.join(cd, subdir)
            if not folder_owning:
                # Flat variant (`notes/{name}.md`): a page at the container's top
                # level is its own entry. A SUBDIRECTORY is a landing group --
                # `<dir>/<dir>.md` is its landing page and every other page inside
                # nests under it, the same synthesis+sources shape the folder-owning
                # path produces, so the nav mirrors the tree on disk. Before this the
                # scan was a bare os.listdir and never descended at all, so a nested
                # page was silently dropped from the nav entirely.
                try:
                    top = sorted(os.listdir(root_dir))
                except OSError:
                    top = []
                for f in top:
                    full = os.path.join(root_dir, f)
                    if os.path.isdir(full):
                        if f.startswith(".") or os.path.normpath(full) in route_dirs:
                            continue
                        entry = {key: f, "layer": label, "shadowed": False,
                                 "synthesis": None, "sources": []}
                        _index_container(full, kind, html_seg, f, cd, label, slug,
                                         entry, synth_fn, landing=f)
                        if entry["synthesis"] is None and not entry["sources"]:
                            continue                    # empty dir: nothing to show
                        fresh.extend(_mark(entry, owned))
                        entry["sources"].sort(key=lambda s: (s["dir"], s["name"]))
                        holder.append(entry)
                        got = True
                        continue
                    if not f.endswith(".md") or f in ("INDEX.md", "README.md"):
                        continue
                    p = _parse_wiki_page(full)
                    if not p or (p["kind"] and p["kind"] != kind):
                        continue
                    html = "data/wiki/%s/%s/%s.html" % (slug, html_seg, p["name"])
                    entry = {key: p["name"], "layer": label, "shadowed": False,
                             "synthesis": synth_fn(p, html, cd, label), "sources": []}
                    fresh.extend(_mark(entry, owned))
                    holder.append(entry)
                    got = True
                continue
            try:
                names = sorted(os.listdir(root_dir))
            except OSError:
                names = []
            for nm in names:
                container = os.path.join(root_dir, nm)
                if not os.path.isdir(container):
                    continue
                entry = {key: nm, "layer": label, "shadowed": False,
                         "synthesis": None, "sources": []}
                _index_container(container, kind, html_seg, nm, cd, label, slug,
                                 entry, synth_fn)
                if entry["synthesis"] is None and not entry["sources"]:
                    continue                            # empty dir: nothing to show
                fresh.extend(_mark(entry, owned))
                entry["sources"].sort(key=lambda s: (s["dir"], s["name"]))
                holder.append(entry)
                got = True
        owned.update(fresh)
        # Only layers that actually contributed pages become nav sections — an
        # engine or team root with no wiki/ would otherwise render as an empty group.
        if got:
            layers.append(label)

    # `groups` is the general shape (one per declared knowledge variant). `topics`
    # and `concepts` stay populated as back-compat aliases so an index.html or a
    # metrics.js built before #234 keeps rendering the conventional split.
    # Conventional order first (topics open at the top, then concepts), everything
    # else alphabetical — so a layer using the usual split keeps the nav it had.
    _RANK = {"topic": 0, "concept": 1}
    out_groups = [{"key": k, "label": _group_label(k), "entries": groups[k]}
                  for k in sorted(groups, key=lambda k: (_RANK.get(k, 2), k))
                  if groups[k]]
    return {"groups": out_groups,
            "topics": groups.get("topic", []),
            "concepts": groups.get("concept", []),
            "layers": layers}


def render_pages(index, out_dir):
    """Render every indexed page to <out_dir>/<its html path minus 'data/'>.
    Two-pass: link_map (name -> data-relative path) lets [[wikilinks]] resolve.
    Source .md path is recovered from the html path. Fail-open per file."""
    # Clear the previous render first: page paths carry a layer slug since #142, so
    # an upgrade (or a renamed/removed topic, or a dropped team overlay) would
    # otherwise leave orphaned .html from the old scheme behind forever. The tree is
    # fully regenerated below, and fail-open — a prune error must not break the build.
    try:
        shutil.rmtree(os.path.join(out_dir, "wiki"))
    except (OSError, FileNotFoundError):
        pass

    link_map = {}
    pages = []   # (name, html, kind, topic|None, last_updated, version, src, layer)
    for t in index.get("topics", []):
        s = t.get("synthesis")
        if s:
            link_map[s["name"]] = s["html"][len("data/"):]
            pages.append((s["name"], s["html"], "topic", t["topic"], s.get("last_updated", ""), "", s.get("src"), s.get("layer", "")))
        for it in t.get("sources", []):
            link_map[it["name"]] = it["html"][len("data/"):]
            pages.append((it["name"], it["html"], "reference", t["topic"], "", it.get("version", ""), it.get("src"), it.get("layer", "")))
    for c in index.get("concepts", []):
        s = c.get("synthesis")
        if s:
            link_map[s["name"]] = s["html"][len("data/"):]
            pages.append((s["name"], s["html"], "concept", None, s.get("last_updated", ""), "", s.get("src"), s.get("layer", "")))
        for it in c.get("sources", []):
            link_map[it["name"]] = it["html"][len("data/"):]
            pages.append((it["name"], it["html"], "reference", None, "", it.get("version", ""), it.get("src"), it.get("layer", "")))

    for name, html, kind, topic, last_updated, version, src_md, layer in pages:
        rel_html = html[len("data/"):]        # e.g. wiki/personal/topics/aws/sub/aws.html
        # The source path is recorded at index time rather than reconstructed from the
        # html path: since #142 that path carries a layer slug the source tree has no
        # counterpart for, so recovery-by-string no longer round-trips.
        if not src_md:
            continue
        try:
            with open(src_md, encoding="utf-8") as fh:
                md = fh.read()
        except OSError:
            continue
        if md.startswith("---"):
            end = md.find("\n---", 3)
            if end != -1:
                md = md[end + 4:]
        meta = {"name": name, "kind": kind, "last_updated": last_updated}
        if version:
            meta["version"] = version
        if topic:
            meta["topic"] = topic
        if layer:
            meta["layer"] = layer
        here = posixpath.dirname(rel_html)
        dest = os.path.join(out_dir, rel_html)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(md_to_html(md, meta=meta, link_map=link_map, here=here))


def _lesson_names_by_provenance(d):
    """(failure_topic_names, success_topic_names) for the memory/lessons/*.md files
    in one overlay root. A merged topic file can carry both provenances, so it can
    appear in both sets."""
    fails, succ = set(), set()
    try:
        names = os.listdir(d)
    except OSError:
        return fails, succ
    for name in names:
        if not name.endswith(".md") or name in ("INDEX.md", "README.md") or name.startswith("."):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        topic = name[:-3]
        if "provenance: failure" in text:
            fails.add(topic)
        if "provenance: success" in text:
            succ.add(topic)
    return fails, succ


def learned_counts():
    """Accumulated memory the dashboard shows as a growth stat, split by the lesson's
    provenance so the Wins & learnings panel keeps its two tiles: failure-derived
    lessons feed `playbooks`, success-derived feed `strategies` (+ `strategy_names`
    for the chips). Layer-aware: with no explicit NP_LESSONS_DIR override, unions
    topic names across the team>personal overlays (a count can't double-count an
    identity, so dedup applies in every mode; team-only is handled by _content_layers
    -> np_content.py merge_roots)."""
    le_env = os.environ.get("NP_LESSONS_DIR")
    if le_env:
        fails, succ = _lesson_names_by_provenance(le_env)
        names = sorted(succ)
        return {"playbooks": len(fails), "strategies": len(names),
                "strategy_names": names}
    fails, succ = set(), set()
    for cd in _content_layers():
        f, s = _lesson_names_by_provenance(os.path.join(cd, "memory", "lessons"))
        fails |= f
        succ |= s
    names = sorted(succ)
    return {"playbooks": len(fails), "strategies": len(names), "strategy_names": names}


def load_records(path):
    records = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # skip malformed line, fail-open
    except FileNotFoundError:
        pass
    records.sort(key=lambda r: r.get("ts", ""))
    return records


def drop_agent_sessions(records):
    """Exclude agent-* subagent sessions from the dashboard window. They record
    asset presence but never mark usefulness (used=False) and carry low/zero
    scores — internal machinery, not user-facing sessions — so including them skews
    every panel (observed: the window filled entirely with one subagent run, making
    trend/tokens/assets all read as "missing"). metrics.jsonl stays full; this only
    shapes what the dashboard renders. Fail-open: a record with no project is kept."""
    return [r for r in records if not str(r.get("project", "")).startswith("agent-")]


def min_tool_calls():
    """Fewest tool calls a session needs to appear in the rendered trend. From
    env DASHBOARD_MIN_TOOL_CALLS (the cron resolves it from the
    `evaluator.min_tool_calls` toggle param); default 1; <=0 keeps everything."""
    try:
        return int(os.environ.get("DASHBOARD_MIN_TOOL_CALLS", 1))
    except (TypeError, ValueError):
        return 1


def drop_idle_sessions(records, floor=None):
    """Exclude sessions that did no work from the rendered window.

    A session with zero tool calls is one where a window was opened and nothing
    substantive happened. It scores ~0 correctly — Nervepack had nothing to
    contribute — but it is noise in a "did Nervepack help" trend. These went from
    48% to 83% of the scored population once the back-capture sweep began
    evaluating every prior session rather than only the ones SessionEnd caught,
    dragging the rendered average from 38.0 to 16.6 with no change in how much
    the pack actually helped. metrics.jsonl stays full; this only shapes what the
    dashboard renders (same contract as drop_agent_sessions).

    Fail-open: a record carrying no `signals` dict at all is KEPT — absent
    telemetry is not evidence the session was idle (see np-eval-signals.py's
    signals_present)."""
    floor = min_tool_calls() if floor is None else floor
    if floor <= 0:
        return records
    kept = []
    for r in records:
        sig = r.get("signals")
        if not isinstance(sig, dict) or "tool_calls" not in sig:
            kept.append(r)
            continue
        try:
            if int(sig.get("tool_calls") or 0) >= floor:
                kept.append(r)
        except (TypeError, ValueError):
            kept.append(r)
    return kept


def window_size():
    """Ceiling on how many sessions to render. From env DASHBOARD_SESSIONS (the
    cron resolves it from the `evaluator.dashboard_sessions` toggle param); default
    50; <=0 means no cap. This is now a *bound*, not the primary selector — see
    window_days(). Windowing the rendered metrics.js bounds the file's growth;
    metrics.jsonl stays full."""
    try:
        return int(os.environ.get("DASHBOARD_SESSIONS", 50))
    except (TypeError, ValueError):
        return 50


def window_days():
    """How many days of activity to render. From env DASHBOARD_DAYS (the cron
    resolves it from the `evaluator.dashboard_days` toggle param); default 14;
    <=0 means no time bound. 14 rather than 7 because drop_idle_sessions() removes
    ~80% of records: on real data a 7-day window left 9 sessions across 3 distinct
    days, where 14 gives 30 across 7 — enough for a trend to mean anything.

    Time, not count, is the primary selector because sessions do not arrive at a
    steady rate. The back-capture sweep replays whole batches of old transcripts
    seconds apart, so a fixed "last N records" window collapses onto one sweep:
    observed live, the rendered window was 5 sessions spanning 73 seconds, four
    of them near-empty sweep artifacts, while 711 records sat in metrics.jsonl.
    A day-based window can't be crowded out that way."""
    try:
        return int(os.environ.get("DASHBOARD_DAYS", 14))
    except (TypeError, ValueError):
        return 14


def _ts_epoch(rec):
    """Parse a record's ts to epoch seconds; None when absent/unparseable."""
    raw = str(rec.get("ts") or "")
    try:
        return calendar.timegm(time.strptime(raw, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def window_records(records, days=None, cap=None):
    """Apply the render window: keep sessions within `days` of the NEWEST record,
    then cap at `cap` most-recent.

    Anchored to the newest record rather than wall-clock on purpose: after a few
    days away from the machine a wall-clock window would render an empty
    dashboard, which reads exactly like the breakage this window was added to
    fix. Anchoring means "the last N days you actually worked".

    Records with an unparseable ts are kept (fail-open) — the cap still bounds them.
    """
    days = window_days() if days is None else days
    cap = window_size() if cap is None else cap
    if days > 0 and records:
        stamps = [t for t in (_ts_epoch(r) for r in records) if t is not None]
        if stamps:
            cutoff = max(stamps) - days * 86400
            records = [r for r in records
                       if (_ts_epoch(r) is None or _ts_epoch(r) >= cutoff)]
    if cap > 0:
        records = records[-cap:]   # load_records sorts ts asc -> last N = newest
    return records


def tokens_saved(records):
    """Deterministic lower-bound estimate of tokens nervepack saved via the KV cache.

    For each session: savings = max(0, cache_read - directive_tokens)
      cache_read      — tokens served from cache, not reprocessed at full price.
      directive_tokens — nervepack's own injection overhead (subtracted so the
                         stat doesn't count what nervepack itself costs as a saving).
    directive_tokens defaults to 0 when absent (fail-open; conservative for old records).

    Returns {total, per_session} where per_session is the floor-rounded per-session
    average over the windowed sessions. Both are 0 when there are no records.
    """
    total = 0
    for r in records:
        sig = r.get("signals") or {}
        cr = (sig.get("tokens") or {}).get("cache_read") or 0
        dt = sig.get("directive_tokens") or 0
        total += max(0, cr - dt)
    n = len(records)
    per_session = total // n if n else 0
    return {"total": total, "per_session": per_session}


def main(argv):
    inp = argv[1] if len(argv) > 1 else DEFAULT_IN
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT
    records = load_records(inp)
    records = drop_agent_sessions(records)  # internal subagent runs skew the panels
    records = drop_idle_sessions(records)   # zero-tool-call sessions are trend noise
    records = window_records(records)   # last N days of activity, capped at N sessions
    resolved = load_resolved(os.environ.get("NP_RESOLVED_SUGGESTIONS", default_resolved()))
    records = drop_resolved(records, resolved)
    payload = json.dumps(records, indent=2) if records else "[]"
    learned = json.dumps(learned_counts())
    saved = json.dumps(tokens_saved(records))
    wiki_obj = wiki_index()
    wiki = json.dumps(wiki_obj)
    try:
        render_pages(wiki_obj, os.path.dirname(os.path.abspath(out)))
    except Exception as exc:  # fail-open: never break the build over a render error
        sys.stderr.write("build.py render_pages: %s\n" % exc)
    graduation = json.dumps(load_graduation(
        os.environ.get("NP_GRADUATION_CANDIDATES", default_graduation())))
    backlog = json.dumps(backlog_metrics())
    # F5/#251: the change-keyed ledger, distinct from the session-keyed METRICS
    # above. load_records() already does exactly what's needed here (parse
    # JSONL, sort by ts, fail-open on missing/malformed) - no new loader.
    # Rendered rows capped to the most recent 50 for UI sanity; the underlying
    # file itself is retained indefinitely (see np-ledger-append.py).
    ledger_records = load_records(os.environ.get("NP_LEDGER", default_ledger()))
    ledger = json.dumps(ledger_records[-50:])
    with open(out, "w") as fh:
        fh.write(f"window.METRICS = {payload};\n")
        fh.write(f"window.LEARNED = {learned};\n")
        fh.write(f"window.TOKENS_SAVED = {saved};\n")
        fh.write(f"window.LEDGER = {ledger};\n")
        fh.write(f"window.WIKI = {wiki};\n")
        fh.write(f"window.GRADUATION = {graduation};\n")
        fh.write(f"window.BACKLOG = {backlog};\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # fail-open: never break the cron
        sys.stderr.write(f"build.py: {exc}\n")
        sys.exit(0)
