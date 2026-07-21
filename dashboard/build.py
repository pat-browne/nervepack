#!/usr/bin/env python3
"""Dumb data transport for the P2 dashboard: read the append-only metrics JSONL
and write a metrics.js (`window.METRICS = [...]`) that index.html loads via a
<script> tag (file:// can't fetch a sibling .jsonl — CORS). No aggregation here;
index.html owns that. Deterministic, idempotent, fail-open (exit 0 on trouble),
per the harness language policy in CLAUDE.md.

Usage: build.py [input.jsonl] [output.js]
Defaults: dashboard/data/metrics.jsonl -> dashboard/data/metrics.js
"""
import html
import json
import os
import posixpath
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(HERE, "data", "metrics.jsonl")
DEFAULT_OUT = os.path.join(HERE, "data", "metrics.js")

# np_bashlib makes the bash shell-out below work under Git-bash on Windows (a bare
# `bash` resolves to System32 WSL there). It lives in engine/setup/ — no-op off Windows.
sys.path.insert(0, os.path.join(HERE, "..", "engine", "setup"))
import np_bashlib  # noqa: E402
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
    tab+ISO-timestamp (appended by np-suggestion-resolve.sh for retention pruning);
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
    """Resolve the content-overlay root, mirroring np-content-lib.sh's precedence:
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


def _np_layer_lib():
    return os.path.join(HERE, "..", "engine", "setup", "np-layer-lib.sh")


def _np_layer_fn(fn):
    """Run a np-layer-lib.sh function and return its stdout (empty string on any failure)."""
    try:
        r = subprocess.run(np_bashlib.argv(["bash", "-c", 'source "$1" 2>/dev/null; %s' % fn, "_", _np_layer_lib()]),
                           capture_output=True, text=True)
        return r.stdout
    except Exception:
        return ""


def _content_layers():
    """Overlay roots to scan (team then personal) for the current merge mode, via
    np_merge_roots. Fail-open to [_content_dir()] when the helper yields nothing."""
    roots = [ln for ln in _np_layer_fn("np_merge_roots").splitlines() if ln.strip()]
    return roots or [_content_dir()]


def _merge_mode():
    m = _np_layer_fn("np_merge_mode").strip()
    return m if m in ("override", "concatenate", "team-only") else "override"


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
    up = "../" * (here.count("/") + 2)
    back = up + "index.html"
    head = ('<div class="np-head"><span>%s%s</span>'
            '<a href="%s">&#8617; dashboard</a></div>') % (
        name, (" &middot; " + kind + (" &middot; " + stamp if stamp else "")) if kind else "",
        back)
    # Mermaid: load the vendored (local, not CDN) lib only on pages that have a
    # diagram, keeping the no-external-fetch invariant. Gate: WIKI_MERMAID env
    # (set from the evaluator.wiki_mermaid param, mirroring WIKI_NAV).
    mermaid_js = ""
    if has_mermaid and os.environ.get("WIKI_MERMAID", "on") != "off":
        mermaid_js = (
            '<script src="' + up + 'vendor/mermaid.min.js"></script>\n'
            "<script>mermaid.initialize({startOnLoad:true,securityLevel:'loose'});</script>\n"
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


def wiki_index():
    """Grouped wiki index for the dashboard left-nav, from the CONTENT overlay.
    NEW layout: wiki/topics/<topic>/ holds one kind:topic synthesis page + N
    kind:reference sources; wiki/concepts/<concept>/ is symmetric — one kind:concept
    synthesis page + N kind:reference sources.
    Gated by WIKI_NAV (default on, fail-open)."""
    empty = {"topics": [], "concepts": []}
    if os.environ.get("WIKI_NAV", "on").strip().lower() == "off":
        return empty

    roots = _content_layers()
    mode = _merge_mode()

    def _src_entry(p, topic, subdir, html, root):
        return {"name": p["name"], "topic": topic, "kind": p["kind"] or "reference",
                "dir": subdir, "excerpt": p["excerpt"], "version": p.get("version", ""),
                "html": html, "root": root}

    def _synth_entry(p, html, root):
        return {"name": p["name"], "kind": "topic", "excerpt": p["excerpt"],
                "last_updated": p["last_updated"], "sources": p["sources"],
                "html": html, "root": root}

    topics = {}             # topic -> entry (accumulated across layers)
    taken = {}              # topic -> set of page names already claimed (dedup)
    cmap = {}; ctaken = {}; seen_concept = set()
    for cd in roots:
        troot = os.path.join(cd, "wiki", "topics")
        try:
            tdirs = sorted(os.listdir(troot))
        except OSError:
            tdirs = []
        for topic in tdirs:
            td = os.path.join(troot, topic)
            if not os.path.isdir(td):
                continue
            if topic in topics and mode != "concatenate":
                continue   # higher-precedence (team) layer already owns this topic
            if topic not in topics:
                topics[topic] = {"topic": topic, "synthesis": None, "sources": []}
                taken[topic] = set()
            entry, claimed = topics[topic], taken[topic]
            # Walk the topic dir recursively: the relative subdir IS the nesting path.
            for dirpath, dirnames, filenames in os.walk(td):
                dirnames.sort()
                sub = os.path.relpath(dirpath, td)
                sub = "" if sub == "." else sub.replace(os.sep, "/")
                for f in sorted(filenames):
                    if not f.endswith(".md") or f in ("INDEX.md", "README.md"):
                        continue
                    p = _parse_wiki_page(os.path.join(dirpath, f))
                    if not p:
                        continue
                    rel = (sub + "/" + p["name"]) if sub else p["name"]
                    html = "data/wiki/topics/%s/%s.html" % (topic, rel)
                    # synthesis page: kind:topic at the topic root only
                    if p["kind"] == "topic" and sub == "":
                        if entry["synthesis"] is None:
                            entry["synthesis"] = _synth_entry(p, html, cd)
                            claimed.add(p["name"])
                        continue
                    if p["name"] in claimed:
                        continue   # page-level dedup across layers + subdirs
                    claimed.add(p["name"])
                    entry["sources"].append(_src_entry(p, topic, sub, html, cd))

        croot = os.path.join(cd, "wiki", "concepts")
        try:
            cdirs = sorted(os.listdir(croot))
        except OSError:
            cdirs = []
        for concept in cdirs:
            ccd = os.path.join(croot, concept)
            if not os.path.isdir(ccd):
                continue
            if concept in seen_concept and mode != "concatenate":
                continue
            if concept not in cmap:
                cmap[concept] = {"name": concept, "synthesis": None, "sources": []}
                ctaken[concept] = set()
            centry, cclaimed = cmap[concept], ctaken[concept]
            for dirpath, dirnames, filenames in os.walk(ccd):
                dirnames.sort()
                sub = os.path.relpath(dirpath, ccd)
                sub = "" if sub == "." else sub.replace(os.sep, "/")
                for f in sorted(filenames):
                    if not f.endswith(".md") or f in ("INDEX.md", "README.md"):
                        continue
                    p = _parse_wiki_page(os.path.join(dirpath, f))
                    if not p:
                        continue
                    rel = (sub + "/" + p["name"]) if sub else p["name"]
                    html = "data/wiki/concepts/%s/%s.html" % (concept, rel)
                    if p["kind"] == "concept" and sub == "":
                        if centry["synthesis"] is None:
                            centry["synthesis"] = {"name": p["name"], "kind": "concept",
                                "excerpt": p["excerpt"], "last_updated": p["last_updated"],
                                "sources": p["sources"], "html": html, "root": cd}
                            cclaimed.add(p["name"])
                        continue
                    if p["name"] in cclaimed:
                        continue
                    cclaimed.add(p["name"])
                    centry["sources"].append(_src_entry(p, concept, sub, html, cd))
            seen_concept.add(concept)

    for entry in topics.values():
        entry["sources"].sort(key=lambda s: (s["dir"], s["name"]))
    for entry in cmap.values():
        entry["sources"].sort(key=lambda s: (s["dir"], s["name"]))
    return {"topics": [topics[k] for k in sorted(topics)],
            "concepts": [cmap[k] for k in sorted(cmap)]}


def render_pages(index, out_dir):
    """Render every indexed page to <out_dir>/<its html path minus 'data/'>.
    Two-pass: link_map (name -> data-relative path) lets [[wikilinks]] resolve.
    Source .md path is recovered from the html path. Fail-open per file."""
    link_map = {}
    pages = []   # (name, html, kind, topic|None, last_updated, version, root)
    for t in index.get("topics", []):
        s = t.get("synthesis")
        if s:
            link_map[s["name"]] = s["html"][len("data/"):]
            pages.append((s["name"], s["html"], "topic", t["topic"], s.get("last_updated", ""), "", s.get("root")))
        for it in t.get("sources", []):
            link_map[it["name"]] = it["html"][len("data/"):]
            pages.append((it["name"], it["html"], "reference", t["topic"], "", it.get("version", ""), it.get("root")))
    for c in index.get("concepts", []):
        s = c.get("synthesis")
        if s:
            link_map[s["name"]] = s["html"][len("data/"):]
            pages.append((s["name"], s["html"], "concept", None, s.get("last_updated", ""), "", s.get("root")))
        for it in c.get("sources", []):
            link_map[it["name"]] = it["html"][len("data/"):]
            pages.append((it["name"], it["html"], "reference", None, "", it.get("version", ""), it.get("root")))

    default_cd = _content_dir()
    for name, html, kind, topic, last_updated, version, root in pages:
        rel_html = html[len("data/"):]                       # e.g. wiki/topics/aws/sub/aws.html
        # read the source from the layer it came from (team vs personal); nested
        # subdirs flow through unchanged since the md path mirrors the html path.
        src_md = os.path.join(root or default_cd, rel_html[:-5] + ".md")
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
    -> np_merge_roots)."""
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


def window_size():
    """How many most-recent sessions to render. From env DASHBOARD_SESSIONS (the
    cron resolves it from the `evaluator.dashboard_sessions` toggle param); default
    5; <=0 means all. Windowing the rendered metrics.js gives the dashboard a recent
    performance picture and bounds the file's growth — metrics.jsonl stays full."""
    try:
        return int(os.environ.get("DASHBOARD_SESSIONS", 5))
    except (TypeError, ValueError):
        return 5


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
    n = window_size()
    if n > 0:
        records = records[-n:]  # load_records sorts by ts asc -> last N = most recent
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
    with open(out, "w") as fh:
        fh.write(f"window.METRICS = {payload};\n")
        fh.write(f"window.LEARNED = {learned};\n")
        fh.write(f"window.TOKENS_SAVED = {saved};\n")
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
