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

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(HERE, "data", "metrics.jsonl")
DEFAULT_OUT = os.path.join(HERE, "data", "metrics.js")


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
    (75-skill-maintain.sh) writes it there. NP_GRADUATION_CANDIDATES env var overrides."""
    return os.path.join(_content_dir(), "dashboard", "data", "graduation-candidates.json")


def load_graduation(path):
    """Graduation candidates (strategies/playbooks overdue to become skills), as written
    by 75-skill-maintain.sh via np-graduation-detect.py. Shape:
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


def _topic_names(path):
    """Sorted <topic> names (filename minus .md) in a memory dir, excluding
    INDEX.md / README.md. Missing dir -> [] (fail-open)."""
    try:
        return sorted(f[:-3] for f in os.listdir(path)
                      if f.endswith(".md") and f not in ("INDEX.md", "README.md"))
    except OSError:
        return []


def _count_topics(path):
    """Count <topic>.md files in a memory dir, excluding INDEX.md / README.md."""
    return len(_topic_names(path))


def _content_dir():
    """Resolve the content-overlay root, mirroring np-content-lib.sh's precedence:
    $NP_CONTENT_DIR -> ~/.config/nervepack/content-dir (first line) -> engine root.
    Since the engine/content split, playbooks/ and strategies/ live in the overlay,
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
        r = subprocess.run(["bash", "-c", 'source "$1" 2>/dev/null; %s' % fn, "_", _np_layer_lib()],
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
    kind:reference sources; wiki/concepts/<name>.md holds concepts.
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
    concepts = []; seen_concept = set()
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

        cdir = os.path.join(cd, "wiki", "concepts")
        try:
            cfiles = sorted(os.listdir(cdir))
        except OSError:
            cfiles = []
        for f in cfiles:
            if not f.endswith(".md") or f in ("INDEX.md", "README.md"):
                continue
            p = _parse_wiki_page(os.path.join(cdir, f))
            if not p:
                continue
            if p["name"] in seen_concept:
                continue   # dedup by name (higher-precedence layer wins)
            seen_concept.add(p["name"])
            concepts.append({"name": p["name"], "kind": p["kind"], "excerpt": p["excerpt"],
                             "last_updated": p["last_updated"], "sources": p["sources"],
                             "html": "data/wiki/concepts/%s.html" % p["name"], "root": cd})

    for entry in topics.values():
        entry["sources"].sort(key=lambda s: (s["dir"], s["name"]))
    return {"topics": [topics[k] for k in sorted(topics)],
            "concepts": sorted(concepts, key=lambda x: x["name"])}


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
    for it in index.get("concepts", []):
        link_map[it["name"]] = it["html"][len("data/"):]
        pages.append((it["name"], it["html"], it.get("kind", "concept"), None, it.get("last_updated", ""), "", it.get("root")))

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


def learned_counts():
    """Accumulated memory the dashboard can show as a growth stat. strategy_names
    lets the Wins & learnings panel chip the learned strategies, not just count them.
    Layer-aware: with no explicit NP_PLAYBOOKS_DIR/NP_STRATEGIES_DIR override, unions
    topic names across the team>personal overlays (a count can't double-count an
    identity, so dedup applies in every mode; team-only is handled by _content_layers
    -> np_merge_roots)."""
    pb_env = os.environ.get("NP_PLAYBOOKS_DIR")
    st_env = os.environ.get("NP_STRATEGIES_DIR")
    if pb_env or st_env:
        cd = _content_dir()
        pb = pb_env or os.path.join(cd, "playbooks")
        st = st_env or os.path.join(cd, "strategies")
        names = _topic_names(st)
        return {"playbooks": _count_topics(pb), "strategies": len(names),
                "strategy_names": names}
    pb_names, st_names = set(), set()
    for cd in _content_layers():
        pb_names.update(_topic_names(os.path.join(cd, "playbooks")))
        st_names.update(_topic_names(os.path.join(cd, "strategies")))
    names = sorted(st_names)
    return {"playbooks": len(pb_names), "strategies": len(names), "strategy_names": names}


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
    with open(out, "w") as fh:
        fh.write(f"window.METRICS = {payload};\n")
        fh.write(f"window.LEARNED = {learned};\n")
        fh.write(f"window.TOKENS_SAVED = {saved};\n")
        fh.write(f"window.WIKI = {wiki};\n")
        fh.write(f"window.GRADUATION = {graduation};\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # fail-open: never break the cron
        sys.stderr.write(f"build.py: {exc}\n")
        sys.exit(0)
