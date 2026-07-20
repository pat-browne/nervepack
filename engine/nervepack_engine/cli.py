"""nervepack CLI dispatcher — bash-free entrypoint for hooks/crons/setup.

Phase 1 of the bash-to-python migration (content overlay design spec
2026-07-15-nervepack-python-cli-consolidation-design.md): only `nervepack hook
<name>` is wired so far. Other groups (cron/setup/onboard/toggle/doctor/sync/
dashboard/mcp) are added as later phases port their scripts — see the spec's
"Sequenced phases".

Invoked today as a direct script path (no install step required):
    python3 engine/nervepack_engine/cli.py hook backcapture-sweep

Preserves invariant 1 (fail-open: every path returns 0, logs one dated bail
line) and invariant 2 (NERVEPACK_AGENT re-entry guard) exactly as the bash
hooks it replaces.
"""
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, ".."))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nervepack_engine.hooks import backcapture_sweep  # noqa: E402
from nervepack_engine.hooks import episodic_recall  # noqa: E402
from nervepack_engine.hooks import skill_trigger_recall  # noqa: E402
from nervepack_engine.hooks import struggle_escalation  # noqa: E402

_HOOKS = {
    "backcapture-sweep": backcapture_sweep.run,
    "episodic-recall": episodic_recall.run,
    "skill-trigger-recall": skill_trigger_recall.run,
    "struggle-escalation": struggle_escalation.run,
}


def _log_path():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.environ.get("NERVEPACK_CLI_LOG") or os.path.join(
        home, ".cache", "nervepack", "nervepack-cli.log")


def _bail(context, msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write("%s %s: %s\n" % (ts, context, msg))
    except OSError:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] != "hook" or len(argv) < 2:
        return 0

    name = argv[1]

    if os.environ.get("NERVEPACK_AGENT"):
        return 0

    fn = _HOOKS.get(name)
    if fn is None:
        _bail("cli", "unknown hook: %s" % name)
        return 0

    try:
        payload_text = sys.stdin.read()
    except (OSError, ValueError):
        payload_text = ""

    try:
        result = fn(payload_text)
        if result:
            sys.stdout.write(result)
    except Exception as exc:  # fail-open: invariant 1
        _bail(name, "unhandled exception: %r" % exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
