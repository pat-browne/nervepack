"""`cli.py layout ...` — the operator/agent surface for np_layout.

Kept out of cli.py so the dispatcher stays a dispatcher. Every verb writes JSON or
a bare path to stdout and a human-readable reason to stderr. Unlike the hook/cron
groups, a non-zero exit here is real and intentional (invalid manifest, unrouted
kind, refused path), not the fail-open-to-0 contract. stdlib only.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
for _p in (_HERE, _SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_content  # noqa: E402
import np_layout  # noqa: E402

_VERBS = ("show", "infer", "questions", "record", "route")


def _root(layer):
    """The layer root to operate on, or None after writing a reason to stderr."""
    if layer == "engine":
        import np_paths
        return np_paths.REPO_ROOT
    if layer == "team":
        d = np_content.team_dir()
        if not d:
            sys.stderr.write("layout: no team layer configured "
                             "(NP_TEAM_DIR / ~/.config/nervepack/team-dir)\n")
            return None
        return d
    d = np_content.content_dir()
    if not d:
        sys.stderr.write("layout: content overlay does not resolve\n")
        return None
    return d


def _parse(argv):
    """--layer X --kind K --variant V --value k=v (repeatable)."""
    opts = {"layer": "personal", "kind": None, "variant": None, "values": {}}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--layer", "--kind", "--variant") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 2
        elif a == "--value" and i + 1 < len(argv):
            k, _, v = argv[i + 1].partition("=")
            opts["values"][k] = v
            i += 2
        else:
            i += 1
    return opts


def _dump(obj):
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def run(argv):
    if not argv or argv[0] not in _VERBS:
        if argv:
            sys.stderr.write("layout: unknown verb %r\n" % argv[0])
        sys.stderr.write("usage: cli.py layout {%s} [--layer personal|team|engine]\n"
                         % "|".join(_VERBS))
        return 2
    verb = argv[0]
    opts = _parse(argv[1:])
    root = _root(opts["layer"])
    if root is None:
        return 1
    try:
        if verb == "show":
            layout, source = np_layout.resolve(root)
            _dump({"root": root, "source": source, "layout": layout})
        elif verb == "infer":
            _dump(np_layout.infer(root))
        elif verb == "questions":
            layout, _source = np_layout.resolve(root)
            _dump(np_layout.open_questions(root, layout))
        elif verb == "record":
            _dump_path = np_layout.record(root, json.load(sys.stdin))
            sys.stdout.write(_dump_path + "\n")
        elif verb == "route":
            if not opts["kind"]:
                sys.stderr.write("layout: route needs --kind\n")
                return 1
            layout, _source = np_layout.resolve(root)
            sys.stdout.write(np_layout.route(layout, opts["kind"], root,
                                             variant=opts["variant"],
                                             values=opts["values"]) + "\n")
    except np_layout.LayoutError as exc:
        sys.stderr.write("layout: %s\n" % exc)
        return 1
    except ValueError as exc:
        sys.stderr.write("layout: bad JSON on stdin: %s\n" % exc)
        return 1
    return 0
