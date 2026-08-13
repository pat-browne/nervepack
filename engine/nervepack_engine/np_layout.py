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
    return validate(data)


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
        raise LayoutError("this layer declares no route for kind %r (declared: %s)"
                          % (kind, ", ".join(sorted(routes)) or "none"))
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
    return os.path.join(_home(), ".config", "nervepack", "layouts",
                        "%s-%s.json" % (base, slug))


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-nplayout"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def record(root, layout):
    """Validate + write the manifest. Falls back to the per-machine cache when the
    layer is not writable. Returns the path written."""
    data = {k: v for k, v in validate(layout).items() if not k.startswith("_")}
    try:
        return _write_atomic(manifest_path(root), data)
    except OSError:
        return _write_atomic(cache_path(root), data)
