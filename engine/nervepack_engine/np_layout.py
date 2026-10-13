"""Content-layer layout resolver (nervepack#234).

The engine owns a fixed vocabulary of content KINDS. Each content layer declares
WHERE those kinds live, in a committed `.nervepack/layout.json`. This module loads
that manifest, validates it, and resolves a kind to a path that is guaranteed to
stay inside the layer root.

Before this module, `np-core-contribute` (an ENGINE skill) hardcoded one overlay's
`wiki/topics/` + `wiki/concepts/` tree, so every forker was told to build a
directory layout that meant nothing to them. Topics and concepts are now one
layer's stated preference, expressed as variants of the `knowledge` kind.

SECURITY: a manifest arrives inside a repo, and a team overlay syncs from a remote
other people write to. Route templates are therefore attacker-reachable input to a
file write, and the {name}/{topic} values come from model output. route() validates
every interpolated segment and confirms containment (symlinks resolved) before it
returns. Callers must not build paths from raw template strings. stdlib only.
"""
import hashlib
import json
import os
import posixpath
import sys
import tempfile

# engine/setup holds np_dirs (the XDG-aware state-directory resolver) alongside
# np_paths and the config files. Add it so this module resolves them whether it
# is imported in-process or run standalone, matching the sibling modules.
_SETUP = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import np_dirs

SCHEMA = 1

# The engine's fixed vocabulary. A layer maps these to its own paths; it never
# invents a kind, because contribute classifies against exactly this list.
KINDS = ("skill", "knowledge", "reference", "roadmap", "prompt")

_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class LayoutError(Exception):
    """A manifest is invalid, a kind is unrouted, or a path would escape the root."""


def manifest_path(root):
    """Where a layer's manifest lives."""
    return os.path.join(root, ".nervepack", "layout.json")


def _seg_ok(s):
    """One safe path segment: non-empty, only [A-Za-z0-9._-], not '.' or '..'.
    Mirrors np-mcp-server.py's _seg_ok so both write paths share one guarantee."""
    return bool(s) and s not in (".", "..") and all(c in _SAFE for c in s)


def _entries(spec):
    """The route entries of a route spec: its variants, or the spec itself."""
    if "variants" in spec:
        return spec.get("variants")
    return [spec]


def validate(layout):
    """Return `layout` when it is a well-formed manifest, else raise LayoutError."""
    if not isinstance(layout, dict):
        raise LayoutError("layout must be a JSON object")
    if layout.get("schema") != SCHEMA:
        raise LayoutError("unsupported schema %r (expected %d)"
                          % (layout.get("schema"), SCHEMA))
    routes = layout.get("routes")
    if not isinstance(routes, dict):
        raise LayoutError("layout.routes must be an object")
    for kind, spec in routes.items():
        if not isinstance(spec, dict):
            raise LayoutError("route %r must be an object" % kind)
        entries = _entries(spec)
        if not isinstance(entries, list) or not entries:
            raise LayoutError("route %r has no path or variants" % kind)
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("path"), str):
                raise LayoutError("route %r has an entry with no path string" % kind)
            if os.path.isabs(e["path"]) or e["path"].startswith("/"):
                raise LayoutError("route %r path must be relative: %s"
                                  % (kind, e["path"]))
    links = layout.get("links", "wikilink")
    if links not in ("wikilink", "path"):
        raise LayoutError("layout.links must be 'wikilink' or 'path'")
    return layout


def load(root):
    """Read + validate the manifest. None when neither the layer nor the per-machine
    cache holds one. Raises LayoutError on unparseable or invalid content (never
    silently ignored — a corrupt team manifest must be loud, not fall back to a
    guess that misplaces writes)."""
    p = manifest_path(root)
    if not os.path.isfile(p):
        p = cache_path(root)
        if not os.path.isfile(p):
            return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise LayoutError("cannot read %s: %s" % (p, exc))
    layout = validate(data)
    for item in _drift_items(root):
        add_route(layout, item)
    return validate(layout)


def variants(layout, kind):
    """The declared variants for `kind`, or [] when the route has no variants."""
    spec = (layout.get("routes") or {}).get(kind)
    if not isinstance(spec, dict):
        return []
    vs = spec.get("variants")
    return vs if isinstance(vs, list) else []


def _pick(layout, kind, variant):
    """The route entry to use for (kind, variant). Raises with the layer's own
    `when` rules in the message so the agent can choose."""
    routes = layout.get("routes") or {}
    if kind not in routes:
        raise LayoutError(
            "this layer declares no route for kind %r (declared: %s). Run the "
            "np-core-layout interview, or `cli.py layout infer` then "
            "`cli.py layout record`, to say where %s content lives."
            % (kind, ", ".join(sorted(routes)) or "none", kind))
    spec = routes[kind]
    vs = variants(layout, kind)
    if not vs:
        if variant:
            raise LayoutError("kind %r has no variants, but variant %r was requested"
                              % (kind, variant))
        return spec
    if not variant:
        choices = "; ".join("%s = %s" % (v.get("name"), v.get("when", "(no rule)"))
                            for v in vs)
        raise LayoutError("kind %r needs a variant. Choices: %s" % (kind, choices))
    for v in vs:
        if v.get("name") == variant:
            return v
    raise LayoutError("kind %r has no variant %r (declared: %s)"
                      % (kind, variant, ", ".join(str(v.get("name")) for v in vs)))


def _contained(root, rel):
    """True when root/rel stays inside root after symlinks resolve."""
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel))
    return target == base or target.startswith(base + os.sep)


def route(layout, kind, root, variant=None, values=None):
    """Resolve (kind, variant) to a forward-slash path relative to `root`.

    Every interpolated value must be one safe segment, and the resolved path must
    stay inside `root`. Raises LayoutError rather than returning an unsafe path."""
    entry = _pick(layout, kind, variant)
    template = entry["path"]
    values = values or {}
    out = template
    for key, val in values.items():
        if not _seg_ok(str(val)):
            raise LayoutError(
                "invalid %s %r -- must be one path segment ([A-Za-z0-9._-], "
                "no '/' or '..')" % (key, val))
        out = out.replace("{%s}" % key, str(val))
    if "{" in out or "}" in out:
        missing = out[out.index("{"):].split("}")[0].lstrip("{")
        raise LayoutError("route for %r needs a value for {%s}" % (kind, missing))
    if os.path.isabs(out):
        raise LayoutError("route for %r resolved to an absolute path: %s" % (kind, out))
    if not _contained(root, out):
        raise LayoutError("route for %r escapes the layer root: %s" % (kind, out))
    return posixpath.normpath(out.replace("\\", "/"))


def frontmatter(layout, kind, variant=None):
    """The frontmatter fields the layer wants stamped on this kind, or {}."""
    try:
        entry = _pick(layout, kind, variant)
    except LayoutError:
        return {}
    fm = entry.get("frontmatter")
    return fm if isinstance(fm, dict) else {}


# --- inference ---------------------------------------------------------------
# Probe only facts that are unambiguous. Anything a probe cannot settle becomes an
# open question for the discovery interview, never a guess. A wrong guess sends a
# durable write to the wrong place silently; a question costs one exchange.

_SKIP_DIRS = frozenset((
    ".git", ".nervepack", "node_modules", "__pycache__", "archive",
    "memory", "dashboard", ".github", ".claude", ".worktrees"))

# A knowledge page declares its own shape in frontmatter `kind:`. These values mean
# "curated source material", not "a page the user synthesized".
_REFERENCE_KINDS = frozenset(("reference", "source"))


def _read_head(path, limit=2048):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _fm_kind(head):
    """The frontmatter `kind:` value from a file's head text, or ""."""
    if not head.startswith("---"):
        return ""
    body = head.split("---", 2)
    if len(body) < 3:
        return ""
    for line in body[1].splitlines():
        if line.startswith("kind:"):
            return line[len("kind:"):].strip()
    return ""


def _md_files(root, rel, depth=3):
    """(relative_dir, filename) for markdown under root/rel, bounded depth."""
    base = os.path.join(root, rel) if rel else root
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _SKIP_DIRS
                       and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""
        if rel_dir.count("/") >= depth:
            dirnames[:] = []
        for f in sorted(filenames):
            if f.endswith(".md"):
                out.append((rel_dir, f))
    return out


def _page_template(rel_dir, filename, owned_dirs):
    """The path template a single page implies.

    Three shapes, in order:
      wiki/topics/rust/rust.md  -> wiki/topics/{topic}/{topic}.md   (owns its folder)
      wiki/topics/rust/spec.md  -> wiki/topics/{topic}/{name}.md    (sits beside an
                                   owner, so the folder name is a variable)
      wiki/concepts/a.md        -> wiki/concepts/{name}.md          (flat)
    `owned_dirs` is the set of directories some page owns."""
    parent = rel_dir.rsplit("/", 1)[-1] if rel_dir else ""
    head = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
    stem = filename[:-3]
    if parent and stem == parent:
        return (head + "/" if head else "") + "{topic}/{topic}.md"
    if rel_dir in owned_dirs:
        return (head + "/" if head else "") + "{topic}/{name}.md"
    return (rel_dir + "/" if rel_dir else "") + "{name}.md"


def _majority_template(pages, owned_dirs):
    """The template a strict majority of `pages` agree on, or "".

    Generalizing from one sample page bakes that page's concrete directory into the
    template. Pages of one kind spread across unrelated trees are a real ambiguity,
    so no template wins and the caller emits an open question instead of a guess."""
    if not pages:
        return ""
    tally = {}
    for rel_dir, filename in pages:
        t = _page_template(rel_dir, filename, owned_dirs)
        tally[t] = tally.get(t, 0) + 1
    best = max(sorted(tally), key=lambda t: tally[t])
    return best if tally[best] * 2 > len(pages) else ""


def _candidate_docs(root):
    """Prose docs that describe this layer's organization, relative to root. The
    discovery interview reads these; Python only locates them."""
    out = []
    for name in ("README.md", "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md"):
        if os.path.isfile(os.path.join(root, name)):
            out.append(name)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return out
    for entry in entries:
        if entry in _SKIP_DIRS or entry.startswith("."):
            continue
        if os.path.isfile(os.path.join(root, entry, "README.md")):
            out.append("%s/README.md" % entry)
    return out


def infer(root):
    """Derive a provisional layout from what exists on disk. Never guesses: a
    directory that does not clearly declare its shape yields no route, and becomes
    an open question instead."""
    routes = {}

    # 1. skills/<name>/SKILL.md
    skills = os.path.join(root, "skills")
    if os.path.isdir(skills):
        for entry in sorted(os.listdir(skills)):
            if os.path.isfile(os.path.join(skills, entry, "SKILL.md")):
                routes["skill"] = {"path": "skills/{name}/SKILL.md"}
                break

    # 2. knowledge + reference, keyed by each page's own frontmatter `kind:`.
    # Collect every page first, then generalize per kind over the whole set.
    by_kind = {}
    owned_dirs = set()
    wikilink = False
    for rel_dir, filename in _md_files(root, ""):
        if not rel_dir:
            continue                      # root-level docs are not a knowledge tree
        head = _read_head(os.path.join(root, rel_dir, filename), 8192)
        kind_val = _fm_kind(head)
        if not kind_val:
            continue
        if "[[" in head:
            wikilink = True
        by_kind.setdefault(kind_val, []).append((rel_dir, filename))
        if filename[:-3] == rel_dir.rsplit("/", 1)[-1]:
            owned_dirs.add(rel_dir)

    templates = {}
    for kind_val, pages in by_kind.items():
        t = _majority_template(pages, owned_dirs)
        if t:
            templates[kind_val] = t

    ref_kinds = {k: t for k, t in templates.items() if k in _REFERENCE_KINDS}
    know_kinds = {k: t for k, t in templates.items() if k not in _REFERENCE_KINDS}
    if know_kinds:
        vs = [{"name": k, "when": "pages that declare kind: %s" % k, "path": t,
               "frontmatter": {"kind": k}} for k, t in sorted(know_kinds.items())]
        if len(vs) == 1:
            routes["knowledge"] = {"path": vs[0]["path"],
                                   "frontmatter": vs[0]["frontmatter"]}
        else:
            routes["knowledge"] = {"variants": vs}
    if ref_kinds:
        k, t = sorted(ref_kinds.items())[0]
        routes["reference"] = {
            "path": t.replace("{topic}/{topic}.md", "{topic}/{name}.md"),
            "frontmatter": {"kind": k}}

    # 3. roadmap, 4. prompts
    if os.path.isfile(os.path.join(root, "ROADMAP.md")):
        routes["roadmap"] = {"path": "ROADMAP.md", "append": True}
    agents = os.path.join(root, "agents")
    if os.path.isdir(agents) and any(f.endswith(".md") for f in os.listdir(agents)):
        routes["prompt"] = {"path": "agents/{name}.md"}

    return validate({
        "schema": SCHEMA,
        "routes": routes,
        "index": "INDEX.md" if os.path.isfile(os.path.join(root, "INDEX.md")) else "",
        "links": "wikilink" if wikilink else "path",
        "derived_from": _candidate_docs(root),
        "unmapped": [],
        "_source": "inferred",
    })


def resolve(root):
    """(layout, source) — the manifest when present, else inference."""
    got = load(root)
    if got is not None:
        return got, "manifest"
    return infer(root), "inferred"


# --- discovery questions -----------------------------------------------------
# open_questions() is a PURE FUNCTION of (disk, layout). The interview answers one
# question by editing `layout`, then calls this again. An answer that happens to
# settle three questions makes all three disappear, so the interview never asks a
# question a prior answer already resolved (nervepack#234).

# Kinds a layer is expected to route. `prompt` and `reference` are optional: plenty
# of layers hold no agent prompts and no curated source material, so a missing route
# for either is not a gap worth a question.
_EXPECTED_KINDS = ("knowledge", "skill", "roadmap")


def _routed_dirs(layout):
    """Every top-level directory some route writes into."""
    out = set()
    for spec in (layout.get("routes") or {}).values():
        if not isinstance(spec, dict):
            continue
        for e in _entries(spec) or []:
            path = (e or {}).get("path") or ""
            head = path.split("/", 1)[0]
            if head and "{" not in head and not head.endswith(".md"):
                out.add(head)
    return out


def open_questions(root, layout=None):
    """What inference could not settle, as stable {id, question, evidence} dicts."""
    if layout is None:
        layout, _ = resolve(root)
    routes = layout.get("routes") or {}
    unmapped = {u.rstrip("/") for u in (layout.get("unmapped") or [])}
    routed = _routed_dirs(layout) | unmapped
    questions = []

    for kind in _EXPECTED_KINDS:
        if kind in routes:
            continue
        questions.append({
            "id": "missing-kind:%s" % kind,
            "question": ("Where does %s content live in this layer? Give a path "
                         "template, for example notes/{name}.md." % kind),
            "evidence": "no directory in this layer declares %s content" % kind,
        })

    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for entry in entries:
        if entry in _SKIP_DIRS or entry.startswith(".") or entry in routed:
            continue
        if not os.path.isdir(os.path.join(root, entry)):
            continue
        found = _md_files(root, entry)
        if not found:
            continue
        sample = ["%s/%s" % (d, f) if d else f for d, f in found[:3]]
        questions.append({
            "id": "unmapped-dir:%s" % entry,
            "question": ("What does %s/ hold, and should contributions ever land "
                         "there? Answer with a kind, or say it is not a "
                         "contribution target." % entry),
            "evidence": "contains markdown: %s" % ", ".join(sample),
        })

    seen = {q["id"] for q in questions}
    try:
        report = drift(root, layout)
    except Exception:
        report = {"clear": [], "ambiguous": []}
    for item in report["ambiguous"]:
        qid = "unmapped-dir:%s" % item["dir"]
        if qid in seen:
            continue
        seen.add(qid)
        questions.append({
            "id": qid,
            "question": ("What does %s/ hold, and should contributions ever land "
                         "there? Answer with a kind, or say it is not a "
                         "contribution target." % item["dir"]),
            "evidence": "pages declare mixed or no type: %s"
                        % (", ".join(item["values"]) or "none"),
        })

    return questions


# --- drift -------------------------------------------------------------------
# Content added after the interview lands in directories no route names. drift()
# finds them from page frontmatter heads only (no full content scan), so sync can
# run it every pass. A directory whose pages all declare one `type:`/`kind:` value
# is clear and gets a route automatically. Anything else becomes an open question.

_IGNORED_PAGES = frozenset(("README.md", "INDEX.md"))
_DRIFT_SKIP = _SKIP_DIRS | frozenset(("worktrees",))


def _fm_field(head, key):
    """One frontmatter scalar from a file's head text, unquoted, or ""."""
    if not head.startswith("---"):
        return ""
    parts = head.split("---", 2)
    if len(parts) < 3:
        return ""
    for line in parts[1].splitlines():
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip().strip("'\"")
    return ""


def _containers(layout):
    """[(container_dir, deep)] for every route path. `deep` is True when the
    template has a directory segment after the container, so the whole subtree
    belongs to the route. A flat `dir/{name}.md` owns only `dir` itself."""
    out = []
    for spec in (layout.get("routes") or {}).values():
        if not isinstance(spec, dict):
            continue
        for e in _entries(spec) or []:
            path = (e or {}).get("path") or ""
            if "{" not in path:
                continue
            head, rest = path.split("{", 1)
            head = head.rstrip("/")
            if head:
                out.append((head, "/" in rest))
    return out


def _under(rel, base):
    return rel == base or rel.startswith(base + "/")


def _covered(rel, containers, unmapped):
    if any(_under(rel, u) for u in unmapped):
        return True
    for head, deep in containers:
        if rel == head or (deep and _under(rel, head)):
            return True
    return False


def _drift_dirs(root, containers, depth=4):
    """{rel_dir: [filename]} for markdown pages, bounded depth. Dot-dirs are walked
    only along the paths some route points into."""
    heads = [h for h, _d in containers]

    def _on_route(rel):
        return any(_under(rel, h) or _under(h, rel) for h in heads)

    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            child = (rel_dir + "/" + d) if rel_dir else d
            if d in _DRIFT_SKIP and not (d.startswith(".") and _on_route(child)):
                continue
            hidden = d.startswith(".") or any(
                seg.startswith(".") for seg in rel_dir.split("/") if seg)
            if hidden and not _on_route(child):
                continue
            keep.append(d)
        dirnames[:] = keep if rel_dir.count("/") < depth - 1 or not rel_dir else []
        if not rel_dir:
            continue
        pages = [f for f in sorted(filenames)
                 if f.endswith(".md") and f not in _IGNORED_PAGES]
        if pages:
            out[rel_dir] = pages
    return out


def drift(root, layout):
    """Directories holding pages no route or `unmapped` entry covers.

    Returns {"clear": [...], "ambiguous": [...]}. A clear item names the one
    frontmatter field + value every page shares and the kind it maps to. Reads
    only each page's head, never its body."""
    containers = _containers(layout)
    unmapped = [u.rstrip("/") for u in (layout.get("unmapped") or [])]
    clear, ambiguous = [], []
    for rel_dir, pages in sorted(_drift_dirs(root, containers).items()):
        if _covered(rel_dir, containers, unmapped):
            continue
        decl = []
        for f in pages:
            head = _read_head(os.path.join(root, rel_dir, f))
            t = _fm_field(head, "type")
            decl.append(("type", t) if t else ("kind", _fm_field(head, "kind")))
        values = sorted({v for _f, v in decl})
        if len(set(decl)) == 1 and decl[0][1]:
            field, value = decl[0]
            clear.append({"dir": rel_dir, "field": field, "value": value,
                          "kind": "reference" if value in _REFERENCE_KINDS
                          else "knowledge", "pages": len(pages)})
        else:
            ambiguous.append({"dir": rel_dir, "values": [v for v in values if v],
                              "pages": len(pages)})
    return {"clear": clear, "ambiguous": ambiguous}


def add_route(layout, item):
    """Add a variant for one clear drift item, in place. Converts a single-path
    route into variants form without dropping its fields. Returns the variant
    added, or None when a variant of that name or path already exists."""
    routes = layout.setdefault("routes", {})
    value = item["value"]
    variant = {"name": value, "path": "%s/{name}.md" % item["dir"],
               "frontmatter": {item["field"]: value},
               "when": "pages declaring %s: %s (added by sync)"
                       % (item["field"], value)}
    spec = routes.get(item["kind"])
    if not isinstance(spec, dict):
        routes[item["kind"]] = {"variants": [variant]}
        return variant
    if "variants" not in spec:
        first = dict(spec)
        fm = first.get("frontmatter") or {}
        first["name"] = (fm.get("type") or fm.get("kind") or item["kind"])
        spec.clear()
        spec["variants"] = [first]
    for v in spec["variants"]:
        if v.get("name") == value or v.get("path") == variant["path"]:
            return None
    spec["variants"].append(variant)
    return variant


def apply_drift(root, cache_only=False):
    """Run drift on one layer and record clear cases through record().

    Only a layer with a manifest is changed: an inferred layout has no interview
    yet, so writing one here would skip it. Returns (changes, questions) as
    human-readable lines. Never commits or pushes. `cache_only` records new
    routes in the per-machine drift file (drift_path), never the layer repo."""
    layout, source = resolve(root)
    report = drift(root, layout)
    changes = []
    if source == "manifest" and report["clear"]:
        added = []
        for item in report["clear"]:
            if add_route(layout, item):
                added.append({k: item[k] for k in _ITEM_KEYS})
                changes.append("%s: routed %s/ as %s (%s: %s)"
                               % (root, item["dir"], item["kind"], item["field"],
                                  item["value"]))
        if added and cache_only:
            _write_atomic(drift_path(root), _drift_items(root) + added)
        elif added:
            record(root, layout)
    elif report["clear"]:
        for item in report["clear"]:
            changes.append("%s: %s/ looks like %s (%s: %s), not recorded: no manifest"
                           % (root, item["dir"], item["kind"], item["field"],
                              item["value"]))
    questions = ["%s: %s/ holds mixed or untyped pages, run np-core-layout"
                 % (root, a["dir"]) for a in report["ambiguous"]]
    return changes, questions


# --- recording ---------------------------------------------------------------
def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def cache_path(root):
    """Per-machine fallback for a layer whose repo is not writable (a vendored or
    read-only team overlay). Keyed by a hash of the real root so two layers with
    the same basename never collide."""
    real = os.path.realpath(root)
    slug = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
    base = os.path.basename(real) or "layer"
    return np_dirs.config_path("layouts", "%s-%s.json" % (base, slug))


def _write_atomic(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-nplayout-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _check_manifest_target(root):
    """Refuse a manifest write a layer's own files could redirect. A team layer
    syncs from a remote, so a committed `.nervepack` symlink is attacker input."""
    d = os.path.join(root, ".nervepack")
    p = manifest_path(root)
    if os.path.islink(d) or os.path.islink(p):
        raise LayoutError("refusing to write layout: %s is a symlink" % (
            d if os.path.islink(d) else p))
    if not _contained(root, ".nervepack"):
        raise LayoutError("refusing to write layout: .nervepack escapes %s" % root)


def drift_path(root):
    """Per-machine record of drift routes added for a layer sync must not write
    to (a team layer). load() replays them on top of the layer's own manifest, so
    the committed manifest stays authoritative and is never touched."""
    real = os.path.realpath(root)
    slug = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
    base = os.path.basename(real) or "layer"
    return np_dirs.config_path("layouts", "%s-%s.drift.json" % (base, slug))


_ITEM_KEYS = ("dir", "field", "value", "kind")


def _drift_items(root):
    """Valid drift items recorded for `root`, or []. Corrupt entries are dropped."""
    try:
        with open(drift_path(root), "r", encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if (isinstance(it, dict) and all(isinstance(it.get(k), str) for k in _ITEM_KEYS)
                and it["kind"] in KINDS and all(_seg_ok(x) for x in it["dir"].split("/"))):
            out.append({k: it[k] for k in _ITEM_KEYS})
    return out


def record(root, layout):
    """Validate + write the manifest. Falls back to the per-machine cache when the
    layer is not writable. Raises LayoutError when the manifest path is a symlink
    or escapes the layer. Returns the path written."""
    data = {k: v for k, v in validate(layout).items() if not k.startswith("_")}
    _check_manifest_target(root)
    try:
        return _write_atomic(manifest_path(root), data)
    except OSError:
        return _write_atomic(cache_path(root), data)
