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
from nervepack_engine.hooks import episodic_capture  # noqa: E402
from nervepack_engine.hooks import episodic_recall  # noqa: E402
from nervepack_engine.hooks import evaluator  # noqa: E402
from nervepack_engine.hooks import lesson_guard  # noqa: E402
from nervepack_engine.hooks import lesson_recall  # noqa: E402
from nervepack_engine.hooks import open_artifact  # noqa: E402
from nervepack_engine.hooks import open_dashboard  # noqa: E402
from nervepack_engine.hooks import resume_recall  # noqa: E402
from nervepack_engine.hooks import resume_sessionstart  # noqa: E402
from nervepack_engine.hooks import resume_write  # noqa: E402
from nervepack_engine.hooks import session_directive  # noqa: E402
from nervepack_engine.hooks import session_flush  # noqa: E402
from nervepack_engine.hooks import skill_trigger_recall  # noqa: E402
from nervepack_engine.hooks import struggle_escalation  # noqa: E402
import np_aggregate  # noqa: E402
import np_agentic_cron  # noqa: E402
import np_skill_maintain  # noqa: E402

_HOOKS = {
    "backcapture-sweep": backcapture_sweep.run,
    "episodic-capture": episodic_capture.run,
    "episodic-recall": episodic_recall.run,
    "evaluator": evaluator.run,
    "lesson-guard": lesson_guard.run,
    "lesson-recall": lesson_recall.run,
    "open-artifact": open_artifact.run,
    "open-dashboard": open_dashboard.run,
    "resume-recall": resume_recall.run,
    "resume-sessionstart": resume_sessionstart.run,
    "session-directive": session_directive.run,
    "session-flush": session_flush.run,
    "skill-trigger-recall": skill_trigger_recall.run,
    "struggle-escalation": struggle_escalation.run,
}

_CRONS = {
    "aggregate-metrics": np_aggregate.aggregate,
    "skill-maintain": np_skill_maintain.maintain,
    "memory-promote": np_agentic_cron.memory_promote,
    "episodic-maintain": np_agentic_cron.episodic_maintain,
    "refine": np_agentic_cron.refine,
    "compact": np_agentic_cron.compact,
}


def _parse_resume_write_args(argv):
    kwargs = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--session" and i + 1 < len(argv):
            kwargs["session"] = argv[i + 1]; i += 2
        elif arg == "--transcript" and i + 1 < len(argv):
            kwargs["transcript"] = argv[i + 1]; i += 2
        elif arg == "--cwd" and i + 1 < len(argv):
            kwargs["cwd"] = argv[i + 1]; i += 2
        elif arg == "--throttle":
            kwargs["throttle"] = True; i += 1
        elif arg == "--active":
            kwargs["active"] = True; i += 1
        else:
            i += 1
    return kwargs


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

    if not argv:
        return 0

    if argv[0] == "resume-write":
        if os.environ.get("NERVEPACK_AGENT"):
            return 0
        try:
            kwargs = _parse_resume_write_args(argv[1:])
            resume_write.write(**kwargs)
        except Exception as exc:
            _bail("resume-write", "unhandled exception: %r" % exc)
        return 0

    if argv[0] == "cron":
        if len(argv) < 2:
            return 0
        name = argv[1]
        if os.environ.get("NERVEPACK_AGENT"):
            return 0
        fn = _CRONS.get(name)
        if fn is None:
            _bail("cron", "unknown cron: %s" % name)
            return 0
        try:
            result = fn()
            if result:
                sys.stdout.write(str(result) + "\n")
        except Exception as exc:
            _bail(name, "unhandled exception: %r" % exc)
        return 0

    if argv[0] != "hook" or len(argv) < 2:
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
        result = fn(payload_text, *argv[2:])
        if result:
            sys.stdout.write(result)
    except Exception as exc:  # fail-open: invariant 1
        _bail(name, "unhandled exception: %r" % exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
