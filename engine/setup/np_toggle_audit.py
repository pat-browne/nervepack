"""Report Nervepack hooks/cron commands not represented (by family) in
toggles.conf. Port of nervepack-toggle-audit.sh (phase 14) WITH the roadmap bug
fix: extract the feature key from BOTH the post-phase-13 cli.py-dispatched form
(`cli.py hook|cron <name>`) AND legacy `*.sh` basenames, then map each to a
toggle family. stdlib json only (no jq).

Sources scanned: every `.command` string in settings.json (walked recursively)
plus `crontab -l`. A command that mentions "nervepack" but whose extracted key
maps to no declared family is flagged UNMANAGED; a clean install prints the OK
summary. Ignore-list skips always-on infra + installers/utilities that carry no
toggle by design (session-flush, *install*, link/index/toggle scripts).
"""
import json
import os
import re
import subprocess
import sys

import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))

# Post-phase-13 CLI-dispatched form: capture the <name> after `cli.py hook|cron`.
# Mirrors np_hook._CLI_TAIL, but with a capture group for the third token.
_CLI_TAIL = re.compile(r"nervepack_engine/cli\.py\s+\w[\w-]*\s+(\S+)")
# Legacy form: the first `*.sh` basename token in the command.
_SH = re.compile(r"[A-Za-z0-9_-]+\.sh")

# name -> toggle family. Covers every current hook + cron + 40-sync, in BOTH the
# cli.py-dispatched <name> form and the legacy *.sh basenames the old audit knew
# (kept so the existing .sh-form tests still pass).
_MAP = {
    # cli.py-dispatched top-level + hook/cron names (post-phase-13/17 reality)
    "sync": "sync",                 # `cli.py sync` / `cli.py sync exit` (phase 17)
    "session-directive": "directive",
    "episodic-capture": "memory",
    "episodic-recall": "memory",
    "backcapture-sweep": "memory",
    "memory-promote": "memory",
    "episodic-maintain": "memory",
    "lesson-guard": "lessons",
    "lesson-recall": "lessons",
    "evaluator": "evaluator",
    "open-dashboard": "evaluator",
    "struggle-escalation": "evaluator",
    "aggregate-metrics": "evaluator",
    "skill-trigger-recall": "skills",
    "skill-maintain": "skills",
    "resume-sessionstart": "resume",
    "resume-recall": "resume",
    "open-artifact": "focus",
    "refine": "maintain",
    "compact": "maintain",
    # legacy *.sh aliases (the old map had these; keep for .sh-form tests + crons)
    "nervepack-session-directive.sh": "directive",
    "40-sync-nervepack.sh": "sync",
    "episodic-capture.sh": "memory",
    "episodic-recall.sh": "memory",
    "lesson-guard.sh": "lessons",
    "lesson-recall.sh": "lessons",
    "np-evaluator.sh": "evaluator",
    "73-aggregate-metrics.sh": "evaluator",
    "np-resume-sessionstart.sh": "resume",
    "np-resume-recall.sh": "resume",
    "np-resume-write.sh": "resume",
}


def map_fam(key):
    """The toggle family for a hook/cron key, or '' if unknown."""
    return _MAP.get(key, "")


def _ignored(key):
    """Skip (not flag): installers/utilities + always-on infra with no toggle.
    Mirrors the bash `case` ignore-list, plus session-flush (inbox-promotion
    infra, always on by design)."""
    # installers/utilities that carry no toggle by design — both the retired-.sh
    # basenames and the phase-17 cli.py-dispatched forms (link-skills/generate-index
    # regen INDEX/symlinks; mcp-install is a one-shot installer).
    if key in ("30-link-skills.sh", "60-generate-index.sh",
               "link-skills", "generate-index", "mcp-install"):
        return True
    if "install" in key:                        # *install*
        return True
    if key.startswith("nervepack-toggle"):      # nervepack-toggle*
        return True
    if key == "session-flush":                  # always-on infra, no toggle
        return True
    return False


def _extract_key(line):
    """Extract the feature key from a hook/cron command line: a top-level cli.py
    command (phase 17: `cli.py sync`), then the cli.py-dispatched hook/cron <name>
    (post-13), else the first *.sh basename (legacy). '' if none."""
    if re.search(r"nervepack_engine/cli\.py\s+sync(?:\s|$)", line):
        return "sync"
    m = _CLI_TAIL.search(line)
    if m:
        return m.group(1)
    m = _SH.search(line)
    return m.group(0) if m else ""


def _walk_commands(obj):
    """Every `.command` string reachable in a settings.json object (recursive).
    Mirrors jq `.. | objects | .command? // empty`."""
    out = []
    if isinstance(obj, dict):
        cmd = obj.get("command")
        if isinstance(cmd, str):
            out.append(cmd)
        for v in obj.values():
            out.extend(_walk_commands(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_walk_commands(item))
    return out


def _crontab():
    """`crontab -l` output (empty on any failure). Uses PATH so tests can shim it."""
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run(settings_path=None, crontab_fn=None, out=None):
    """Print UNMANAGED lines for any nervepack hook/cron whose key maps to no
    declared family, else the clean-install OK summary. Returns 1 when anything was
    flagged (matching bash), else 0. Emits LF."""
    out = out or sys.stdout
    if hasattr(out, "reconfigure"):
        try:
            out.reconfigure(newline="\n")
        except (ValueError, OSError):
            pass
    if settings_path is None:
        settings_path = os.environ.get("CLAUDE_SETTINGS") or os.path.join(
            os.environ.get("HOME") or os.path.expanduser("~"), ".claude", "settings.json")
    crontab_fn = crontab_fn or _crontab

    commands = []
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as fh:
                commands.extend(_walk_commands(json.load(fh)))
        except (OSError, ValueError):
            pass
    commands.extend(crontab_fn().splitlines())

    fams = set(np_toggle.features())
    flagged = False
    for line in commands:
        if "nervepack" not in line:             # only Nervepack-owned commands
            continue
        key = _extract_key(line)
        if not key:
            continue
        if _ignored(key):
            continue
        fam = map_fam(key)
        if not fam or fam not in fams:
            out.write("UNMANAGED: %s (no toggle family in toggles.conf)\n" % key)
            flagged = True
    if not flagged:
        out.write("OK: all Nervepack hooks/cron map to a toggle family.\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(run())
