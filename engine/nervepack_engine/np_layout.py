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
