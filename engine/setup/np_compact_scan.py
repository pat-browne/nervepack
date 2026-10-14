#!/usr/bin/env python3
"""Deterministic input for the weekly compact agent. Prints one JSON object:
skill pairs by Jaccard over description + `##` headings, skills whose SKILL.md
plus references/ exceed a total size, and the overlay proposals dir the
dashboard reads. Stdlib only.
"""
import itertools
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_PKG = os.path.normpath(os.path.join(_HERE, "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

AUTO_MERGE = 0.85
_STOP = set("the a an and or of to for in on with when use that this is are be".split())
_TOKEN = re.compile(r"[a-z0-9]+")
_DESC = re.compile(r"^description:\s*(.*)$", re.M)
_HEAD = re.compile(r"^##\s+(.+)$", re.M)
_NP = os.path.normpath(os.path.join(_HERE, "..", ".."))


def _tokens(text):
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def _read_skills(roots):
    out = []
    for root in roots:
        sdir = os.path.join(root, "skills")
        try:
            names = sorted(os.listdir(sdir))
        except OSError:
            continue
        for name in names:
            path = os.path.join(sdir, name, "SKILL.md")
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                continue
            total = len(text.encode("utf-8")) + _refs_bytes(os.path.join(sdir, name, "references"))
            m = _DESC.search(text)
            words = (m.group(1) if m else "") + " " + " ".join(_HEAD.findall(text))
            out.append({"name": name, "root": root, "path": path,
                        "bytes": total, "tokens": _tokens(words)})
    return out


def _refs_bytes(refs):
    total = 0
    for dirpath, _dirs, files in os.walk(refs):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _rejected(proposals_dir):
    try:
        with open(os.path.join(proposals_dir, "REJECTED.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return set()
    return {frozenset(m) for m in re.findall(r"([\w.-]+) vs ([\w.-]+)", text)}


def scan(roots, propose_min, split_total_kb, content_dir):
    proposals_dir = os.path.join(content_dir, "compact-proposals")
    skills = _read_skills(roots)
    rejected = _rejected(proposals_dir)
    pairs = []
    for a, b in itertools.combinations(skills, 2):
        union = a["tokens"] | b["tokens"]
        if not union or frozenset((a["name"], b["name"])) in rejected:
            continue
        score = len(a["tokens"] & b["tokens"]) / float(len(union))
        if score < propose_min:
            continue
        pairs.append({"a": a["name"], "b": b["name"], "root_a": a["root"], "root_b": b["root"],
                      "score": round(score, 3),
                      "band": "auto-merge" if score >= AUTO_MERGE else "propose"})
    pairs.sort(key=lambda p: -p["score"])
    # skill-maintain keeps each SKILL.md under split_kb by moving overflow into
    # references/, so only the total size shows a skill that outgrew one topic.
    limit = split_total_kb * 1024
    oversized = [{"name": s["name"], "path": s["path"], "bytes": s["bytes"]}
                 for s in skills if s["bytes"] > limit]
    return {"pairs": pairs, "oversized": oversized, "proposals_dir": proposals_dir,
            "roots": list(roots), "skills_scanned": len(skills),
            "thresholds": {"propose_min": propose_min, "auto_merge": AUTO_MERGE,
                           "split_total_kb": split_total_kb}}


def _roots():
    roots = [_NP]
    try:
        import np_content
        roots += [r for r in np_content.merge_roots() if r and r != _NP]
    except Exception:
        pass
    return roots


def _content_dir():
    try:
        import np_content
        return np_content.content_dir() or _NP
    except Exception:
        return _NP


def _param(key, default):
    try:
        import np_toggle
        return float(np_toggle.param(key, str(default)) or default)
    except Exception:
        return float(default)


def main(argv):
    out = scan(_roots(), _param("maintain.compact_propose_min", 0.3),
               int(_param("maintain.compact_split_total_kb", 40)), _content_dir())
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
