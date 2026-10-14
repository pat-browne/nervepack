#!/usr/bin/env python3
"""Skill-listing lint: keep every skill description visible to the model.

Claude Code lists each skill as `- <name>: <description>`. It caps the listing
at 1% of the context window, at 4 chars per token. Over budget, it keeps names
and drops descriptions in priority order, so a bare skill never auto-triggers.

Per skill: frontmatter present, `name` and `description` non-empty, no plain
YAML scalar a strict parser rejects, description at or under the cap.
Per run: the summed listing of all roots at or under the budget.

Usage: np_skill_listing.py [--max-desc N] [--budget N] [--json] ROOT...
Env defaults: NP_SKILL_DESC_MAX (300), NP_SKILL_LISTING_BUDGET (6000).
Exit 0 clean, 1 on any finding. Stdlib only.
"""
import argparse
import json
import os
import re
import sys

DEFAULT_DESC_MAX = 300
DEFAULT_LAYER_BUDGET = 6000
# Claude Code defaults: skillListingMaxDescChars, skillListingBudgetFraction.
HOST_DESC_CAP = 1536
HOST_BUDGET_FRACTION = 0.01
HOST_CHARS_PER_TOKEN = 4

_KEY = re.compile(r"^([A-Za-z_][\w-]*):(?:\s+(.*))?$")
_PLAIN_BAD_START = tuple("[]{}*&!|>%@`,")


def host_budget(context_tokens=200000, fraction=HOST_BUDGET_FRACTION):
    """Listing budget in chars, as Claude Code computes it."""
    return max(1, int(context_tokens * HOST_CHARS_PER_TOKEN * fraction))


def _scalar(first, cont, key):
    """Return (value, error) for one top-level key's value lines."""
    first = (first or "").strip()
    rest = [ln.strip() for ln in cont]
    if first[:1] in ("|", ">"):
        sep = "\n" if first[0] == "|" else " "
        return sep.join(x for x in rest if x).strip(), None
    if first[:1] in ('"', "'"):
        q = first[0]
        joined = " ".join([first] + rest).strip()
        if len(joined) < 2 or not joined.endswith(q):
            return "", "%s: unterminated %s-quoted string" % (key, q)
        body = joined[1:-1]
        return (body.replace("''", "'") if q == "'" else body.replace('\\"', '"')), None
    if not first and not rest:
        return "", None
    if first.startswith(_PLAIN_BAD_START):
        return "", "%s: plain scalar starts with %r" % (key, first[0])
    joined = " ".join([first] + rest).strip()
    if ": " in joined or joined.endswith(":"):
        return joined, "%s: plain scalar holds ': ' (quote it or use >-)" % key
    if " #" in joined:
        return joined, "%s: plain scalar holds ' #' (YAML reads a comment)" % key
    return joined, None


def parse(text):
    """Return (fields, errors) for the first frontmatter block."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, ["no frontmatter block"]
    end = text.find("\n---", 3)
    if end == -1:
        return {}, ["frontmatter not closed"]
    lines = text[4:end].split("\n")
    fields, errors, i = {}, [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or ln.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY.match(ln)
        if not m:
            errors.append("bad frontmatter line %d: %s" % (i + 2, ln[:60]))
            i += 1
            continue
        j = i + 1
        while j < len(lines) and (lines[j][:1].isspace() or not lines[j].strip()):
            j += 1
        if m.group(1) in ("name", "description"):
            val, err = _scalar(m.group(2), lines[i + 1:j], m.group(1))
            fields[m.group(1)] = val
            if err:
                errors.append(err)
        i = j
    return fields, errors


def scan(roots, desc_max=DEFAULT_DESC_MAX, budget=DEFAULT_LAYER_BUDGET):
    """Lint every skill under roots. Returns a JSON-able report."""
    skills, findings, seen = [], [], set()
    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            findings.append("%s: not a readable directory" % root)
            continue
        for d in names:
            path = os.path.join(root, d, "SKILL.md")
            if d in seen or not os.path.isfile(path):
                continue
            seen.add(d)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    fields, errs = parse(fh.read())
            except OSError as e:
                fields, errs = {}, ["unreadable: %s" % e.strerror]
            name = fields.get("name") or d
            desc = fields.get("description", "")
            if not fields.get("name"):
                errs.append("missing or empty name")
            if not desc:
                errs.append("missing or empty description")
            elif len(desc) > desc_max:
                errs.append("description %d chars > %d cap" % (len(desc), desc_max))
            entry = len("- %s: %s" % (name, desc[:HOST_DESC_CAP]))
            skills.append({"skill": d, "desc_chars": len(desc),
                           "entry_chars": entry, "errors": errs})
            findings.extend("%s: %s" % (d, e) for e in errs)
    total = sum(s["entry_chars"] for s in skills) + max(0, len(skills) - 1)
    if total > budget:
        findings.append("listing %d chars > %d budget (%d skills)"
                        % (total, budget, len(skills)))
    return {"skills": skills, "total_chars": total, "budget": budget,
            "desc_max": desc_max, "findings": findings}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def main(argv):
    ap = argparse.ArgumentParser(description="Lint skill frontmatter and listing size.")
    ap.add_argument("roots", nargs="+", help="skills/ directories to lint")
    ap.add_argument("--max-desc", type=int,
                    default=_env_int("NP_SKILL_DESC_MAX", DEFAULT_DESC_MAX))
    ap.add_argument("--budget", type=int,
                    default=_env_int("NP_SKILL_LISTING_BUDGET", DEFAULT_LAYER_BUDGET))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv[1:])
    r = scan(a.roots, a.max_desc, a.budget)
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        for f in r["findings"]:
            print("FAIL " + f)
        print("listing %d/%d chars, %d skills, desc cap %d"
              % (r["total_chars"], r["budget"], len(r["skills"]), r["desc_max"]))
    return 1 if r["findings"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
