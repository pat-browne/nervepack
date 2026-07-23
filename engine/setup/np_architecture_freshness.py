"""Pure-Python port of np-architecture-freshness.sh -- advisory freshness
check for ARCHITECTURE.md (the cheap high-level map). Flags live subsystems
that exist in the repo but are NOT referenced in the map. Deterministic, no
LLM. Always advisory (never raises to signal a gap) -- returns a list of
output lines: zero or more "STALE: ..." lines, then one final
"architecture-freshness: N gap(s)" summary line, mirroring the bash
original's stdout exactly.

Called in-process by np_skill_maintain.py's daily cron; also run standalone
by a human after editing ARCHITECTURE.md.
"""
import glob
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_NP = os.path.dirname(os.path.dirname(_HERE))


def check(arch_file=None, toggles_file=None, specs_dir=None):
    arch_file = arch_file or os.environ.get("ARCH_FILE") or os.path.join(_NP, "docs", "ARCHITECTURE.md")
    toggles_file = toggles_file or os.environ.get("ARCH_TOGGLES") or os.path.join(
        _NP, "engine", "setup", "toggles.conf")
    specs_dir = specs_dir if specs_dir is not None else os.environ.get("ARCH_SPECS_DIR", "")

    if not os.path.isfile(arch_file):
        return ["architecture-freshness: ARCHITECTURE.md missing at %s" % arch_file]

    with open(arch_file, "r", encoding="utf-8") as fh:
        arch_text = fh.read()

    lines = []
    gaps = 0

    # 1. Every declared feature toggle must be named in the map's feature catalog.
    if os.path.isfile(toggles_file):
        with open(toggles_file, "r", encoding="utf-8") as fh:
            for row in fh:
                feat = row.split("|", 1)[0].strip()
                if not feat or feat.startswith("#"):
                    continue
                if ("`%s`" % feat) not in arch_text:
                    lines.append("STALE: feature '%s' (toggles.conf) not in ARCHITECTURE.md" % feat)
                    gaps += 1

    # 2. Every design spec must be referenced.
    if specs_dir and os.path.isdir(specs_dir):
        for spec_path in sorted(glob.glob(os.path.join(specs_dir, "*-design.md"))):
            basename = os.path.basename(spec_path)
            if basename not in arch_text:
                lines.append("STALE: spec '%s' not referenced in ARCHITECTURE.md" % basename)
                gaps += 1

    lines.append("architecture-freshness: %d gap(s)" % gaps)
    return lines


if __name__ == "__main__":
    for ln in check():
        print(ln)
