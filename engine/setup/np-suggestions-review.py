#!/usr/bin/env python3
"""Repeatable evaluator-suggestion review engine for nervepack.

Two deterministic operations (parsing/ranking only — no model calls here, per the
harness language policy in CLAUDE.md; the "which to implement" judgment is the
agent's job, or the dashboard server's single Haiku pass):

  list  [--top N] [--json]   rank the OPEN suggestions and print the top-N
  clear [--top N] [--no-build]
                             mark every open suggestion (top-N, default ALL) as
                             resolved — append to the ledger so the dashboard
                             resets and new suggestions accumulate — then rebuild
                             metrics.js so the dashboard reflects it now

OPEN = present in metrics.jsonl AND not already in resolved-suggestions.txt. Dedupe
is by normalized text (the SAME normalization build.py + the dashboard filter use,
imported here so the two never drift), keeping the max confidence and counting
occurrences. Fail-open: on trouble, exit 0 with a best-effort result.

Usage examples:
  np-suggestions-review.py list --top 10
  np-suggestions-review.py list --json
  np-suggestions-review.py clear            # clear ALL open (full reset)
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NP = os.path.dirname(os.path.dirname(HERE))
DASH = os.path.join(NP, "dashboard")
sys.path.insert(0, DASH)
import build as _build  # noqa: E402 — reuse _norm/load_resolved/load_records/DEFAULT_*

DEFAULT_METRICS = _build.DEFAULT_IN
DEFAULT_RESOLVED = os.environ.get("NP_RESOLVED_SUGGESTIONS", _build.default_resolved())


def open_suggestions(metrics_path, resolved_path):
    """Deduped, ranked OPEN suggestions, highest confidence first.

    Returns [{text, confidence, target, auto_safe, count}]. `count` is how many
    sessions raised the (normalized) suggestion — a weak signal of recurrence."""
    records = _build.load_records(metrics_path)
    resolved = _build.load_resolved(resolved_path)
    best = {}
    for r in records:
        for s in r.get("suggestions", []) or []:
            text = " ".join(str(s.get("text", "")).split())
            if not text:
                continue
            key = _build._norm(text)
            if key in resolved:
                continue
            conf = s.get("confidence", 0) or 0
            e = best.get(key)
            if e is None:
                best[key] = {
                    "text": text, "confidence": conf,
                    "target": s.get("target", "other"),
                    "auto_safe": bool(s.get("auto_safe")), "count": 1,
                }
            else:
                e["count"] += 1
                if conf > e["confidence"]:
                    e["confidence"] = conf
                    e["target"] = s.get("target", e["target"])
                e["auto_safe"] = e["auto_safe"] or bool(s.get("auto_safe"))
    return sorted(best.values(),
                  key=lambda x: (-x["confidence"], -x["count"], x["text"]))


def _topped(rows, top):
    return rows[:top] if top and top > 0 else rows


def cmd_list(args):
    rows = _topped(open_suggestions(args.metrics, args.resolved), args.top)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No open suggestions.")
        return 0
    for i, r in enumerate(rows, 1):
        flags = r["target"] + (", auto-safe" if r["auto_safe"] else "")
        seen = f" ×{r['count']}" if r["count"] > 1 else ""
        print(f"{i:2}. [{int(r['confidence'] * 100):3}% · {flags}]{seen} {r['text']}")
    return 0


def cmd_clear(args):
    rows = _topped(open_suggestions(args.metrics, args.resolved), args.top)
    os.makedirs(os.path.dirname(args.resolved), exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(args.resolved, "a") as fh:
        for r in rows:
            fh.write(r["text"] + "\t" + ts + "\n")
    if not args.no_build:
        try:  # rebuild metrics.js so the dashboard drops them immediately
            _build.main([_build.__file__, args.metrics, _build.DEFAULT_OUT])
        except Exception:
            pass  # fail-open — the ledger write is what matters
    print(f"cleared {len(rows)} suggestion(s)")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="nervepack evaluator-suggestion review")
    p.add_argument("--metrics", default=DEFAULT_METRICS)
    p.add_argument("--resolved", default=DEFAULT_RESOLVED)
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="rank and print open suggestions")
    pl.add_argument("--top", type=int, default=10, help="0 = all; default 10")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pc = sub.add_parser("clear", help="resolve open suggestions (default ALL)")
    pc.add_argument("--top", type=int, default=0, help="0 = all (default); N = top-N only")
    pc.add_argument("--no-build", action="store_true", help="skip the metrics.js rebuild")
    pc.set_defaults(func=cmd_clear)
    return p


def main(argv):
    args = build_parser().parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # fail-open: never hard-crash the caller
        sys.stderr.write(f"np-suggestions-review: {exc}\n")
        sys.exit(0)
