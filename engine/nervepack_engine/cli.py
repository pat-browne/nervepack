"""nervepack CLI dispatcher — bash-free entrypoint for hooks/crons/setup.

Bash-to-python migration (content overlay design spec
2026-07-15-nervepack-python-cli-consolidation-design.md): `hook`, `cron`, and
`resume-write` shipped in phases 1-5; `setup` (phase 6, OS-scheduler installers,
joined by phase 7's toolchain-baseline steps) and `onboard` (phase 7, the
full-onboard orchestrator) followed; `implement-suggestion` (phase 10, the
last and most security-sensitive script) joins them here. Remaining groups
(toggle/doctor/sync/dashboard/mcp) are added as later phases port their
scripts — see the spec's "Sequenced phases".

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
# _HERE (engine/nervepack_engine) is on the list so flat `import np_toggle`/np_doctor/
# np_sync/np_dashboard/np_hook (relocated into the package in phase 20b-2) resolve; the
# staying setup modules cli.py imports still resolve via _ENGINE_SETUP.
for _p in (_HERE, _ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_dirs
from nervepack_engine.hooks import backcapture_sweep  # noqa: E402
from nervepack_engine.hooks import drift_guard  # noqa: E402
from nervepack_engine.hooks import episodic_capture  # noqa: E402
from nervepack_engine.hooks import episodic_recall  # noqa: E402
from nervepack_engine.hooks import evaluator  # noqa: E402
from nervepack_engine.hooks import form_directive  # noqa: E402
from nervepack_engine.hooks import form_gate  # noqa: E402
from nervepack_engine.hooks import lesson_guard  # noqa: E402
from nervepack_engine.hooks import lesson_recall  # noqa: E402
from nervepack_engine.hooks import open_artifact  # noqa: E402
from nervepack_engine.hooks import open_dashboard  # noqa: E402
from nervepack_engine.hooks import resume_recall  # noqa: E402
from nervepack_engine.hooks import resume_sessionstart  # noqa: E402
from nervepack_engine.hooks import resume_write  # noqa: E402
from nervepack_engine.hooks import session_directive  # noqa: E402
from nervepack_engine.hooks import security_recall  # noqa: E402
from nervepack_engine.hooks import session_flush  # noqa: E402
from nervepack_engine.hooks import skill_trigger_recall  # noqa: E402
from nervepack_engine.hooks import struggle_escalation  # noqa: E402
from nervepack_engine.hooks import turn_gate  # noqa: E402
import np_aggregate  # noqa: E402
import np_agentic_cron  # noqa: E402
import np_bootstrap  # noqa: E402
import np_dashboard  # noqa: E402
import np_doctor  # noqa: E402
import np_generate_index  # noqa: E402
import np_hook  # noqa: E402
import np_implement_suggestion  # noqa: E402
import np_instruction_block  # noqa: E402
import np_link_dashboard_data  # noqa: E402
import np_layout_cli  # noqa: E402
import np_link_skills  # noqa: E402
import np_mcp_install  # noqa: E402
import np_merge_wait  # noqa: E402
import np_onboard  # noqa: E402
import np_scheduler_install  # noqa: E402
import np_skill_maintain  # noqa: E402
import np_suggestion_resolve  # noqa: E402
import np_sync  # noqa: E402
import np_toggle  # noqa: E402

_HOOKS = {
    "backcapture-sweep": backcapture_sweep.run,
    "drift-guard": drift_guard.run,
    "episodic-capture": episodic_capture.run,
    "episodic-recall": episodic_recall.run,
    "evaluator": evaluator.run,
    "form-directive": form_directive.run,
    "form-gate": form_gate.run,
    "lesson-guard": lesson_guard.run,
    "lesson-recall": lesson_recall.run,
    "open-artifact": open_artifact.run,
    "open-dashboard": open_dashboard.run,
    "resume-recall": resume_recall.run,
    "resume-sessionstart": resume_sessionstart.run,
    "session-directive": session_directive.run,
    "security-recall": security_recall.run,
    "session-flush": session_flush.run,
    "skill-trigger-recall": skill_trigger_recall.run,
    "struggle-escalation": struggle_escalation.run,
    "turn-gate": turn_gate.run,
}

_CRONS = {
    "aggregate-metrics": np_aggregate.aggregate,
    "skill-maintain": np_skill_maintain.maintain,
    "memory-promote": np_agentic_cron.memory_promote,
    "episodic-maintain": np_agentic_cron.episodic_maintain,
    "refine": np_agentic_cron.refine,
    "compact": np_agentic_cron.compact,
}

_SETUP = {
    "install-memory-cron": np_scheduler_install.install_cron,
    "install-memory-launchd": np_scheduler_install.install_launchd,
    "install-memory-schtasks": np_scheduler_install.install_schtasks,
    "install-hooks": np_hook.install_hooks,
    "link-skills": np_link_skills.link,
    "generate-index": np_generate_index.generate,
    "link-dashboard-data": np_link_dashboard_data.link,
    "install-apt-baseline": np_bootstrap.install_apt_baseline,
    "install-brew-baseline": np_bootstrap.install_brew_baseline,
    "install-rustup": np_bootstrap.install_rustup,
    "install-claude-plugins": np_bootstrap.install_claude_plugins,
    "prewarm-serena": np_bootstrap.prewarm_serena,
    "install-pii-deps": np_bootstrap.install_pii_deps,
    "install-vscode-extensions": np_bootstrap.install_vscode_extensions,
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


def _parse_merge_wait_args(argv):
    kwargs = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--repo", "--branch", "--base") and i + 1 < len(argv):
            kwargs[arg[2:]] = argv[i + 1]; i += 2
        elif arg in ("--interval", "--backoff", "--timeout", "--settle") and i + 1 < len(argv):
            kwargs[arg[2:]] = int(argv[i + 1]); i += 2
        else:
            raise ValueError("unknown arg: %s" % arg)
    kwargs.setdefault("repo", ".")
    return kwargs


def _log_path():
    return os.environ.get("NERVEPACK_CLI_LOG") or np_dirs.cache_path("nervepack-cli.log")


def _bail(context, msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write("%s %s: %s\n" % (ts, context, msg))
    except OSError:
        pass


def _warn_setup_failure(name, exc):
    """Report a failed setup step on stderr, whatever the stream can encode.

    A non-ASCII character in the exception text raises UnicodeEncodeError on a
    stream opened in a legacy code page, which is what a piped stderr still gets
    on Windows before 3.15. Raising HERE would replace the original failure with
    an unrelated one - the reporting path swallowing the thing it is reporting,
    which is the exact shape of bug this whole branch exists to surface.

    `print(..., file=sys.stderr)` is not a fix: it calls the same `write` and
    raises identically. Re-encoding with backslashreplace is, and it keeps the
    message readable: ValueError('caf\\xe9').
    """
    try:
        message = "cli.py setup %s: unhandled exception: %r\n" % (name, exc)
        try:
            sys.stderr.write(message)
        except UnicodeEncodeError:
            sys.stderr.write(message.encode("ascii", "backslashreplace").decode("ascii"))
    except Exception:                              # noqa: BLE001
        # Broad on purpose, and the breadth IS the contract. stderr can be closed,
        # a pipe can be broken, and `repr(exc)` runs user-defined `__repr__` that
        # may itself raise. Any of those escaping here would skip the `_bail()`
        # call that follows and lose the file log too - both channels gone
        # because reporting failed. Silence on one channel beats losing both.
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

    if argv[0] == "setup":
        if len(argv) < 2:
            return 0
        name = argv[1]
        if name == "mcp-install":
            # The guided MCP install takes trailing args (--starter-only) unlike the
            # other setup steps, so it is dispatched here with argv passthrough.
            try:
                return np_mcp_install.install(argv[2:])
            except Exception as exc:
                _bail("mcp-install", "unhandled exception: %r" % exc)
                return 1
        fn = _SETUP.get(name)
        if fn is None:
            _bail("setup", "unknown setup step: %s" % name)
            return 0
        # Unlike hook/cron, a setup step has a real, intentional non-zero exit
        # (wrong-OS refusal) that np-onboard.sh's step_cli() logs and continues
        # past -- not the hook/cron fail-open-to-0 contract.
        try:
            return fn()
        except Exception as exc:
            # stderr AS WELL AS the log. _bail writes only to a file, which is
            # right for a hook - a hook must not pollute the session's streams -
            # and wrong for a setup step, which a human or a CI job runs directly
            # and reads the output of. Without this a failed step exits 1 with no
            # explanation anywhere either of them will look. Cost two CI rounds
            # on #296 to rediscover.
            _warn_setup_failure(name, exc)
            _bail(name, "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "layout":
        # A real, intentional non-zero exit (invalid manifest, unrouted kind,
        # refused path) -- not the hook/cron fail-open-to-0 contract.
        try:
            return np_layout_cli.run(argv[1:])
        except Exception as exc:
            _bail("layout", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "onboard":
        # The doctor's exit status is the orchestrator's status (matches the
        # bash original) -- also a real, intentional non-zero exit, not fail-open.
        try:
            return np_onboard.run()
        except Exception as exc:
            _bail("onboard", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "implement-suggestion":
        # np_implement_suggestion.implement() is fail-open by design (every
        # problem logs one line and returns 0, releasing the lock so the
        # suggestion stays retryable) -- its own NERVEPACK_AGENT guard covers
        # the re-entrancy case, so no extra check needed here.
        text = argv[1] if len(argv) > 1 else ""
        try:
            # argv[2], when present, is the dashboard Modify box's rewrite of argv[1].
            return np_implement_suggestion.implement(text, argv[2] if len(argv) > 2 else None)
        except Exception as exc:
            _bail("implement-suggestion", "unhandled exception: %r" % exc)
            return 0

    if argv[0] == "merge-wait":
        try:
            kwargs = _parse_merge_wait_args(argv[1:])
            code, lines = np_merge_wait.wait_and_check(**kwargs)
            sys.stdout.write("\n".join(lines) + "\n")
            return code
        except ValueError as exc:
            sys.stderr.write("np-merge-wait: %s\n" % exc)
            return 1
        except Exception as exc:
            _bail("merge-wait", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "suggestion-resolve":
        text = argv[1] if len(argv) > 1 else ""
        try:
            message, code = np_suggestion_resolve.resolve(text)
            sys.stdout.write(message + "\n")
            return code
        except Exception as exc:
            _bail("suggestion-resolve", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "suggestion-unresolve":
        text = argv[1] if len(argv) > 1 else ""
        try:
            message, code = np_suggestion_resolve.unresolve(text)
            sys.stdout.write(message + "\n")
            return code
        except Exception as exc:
            _bail("suggestion-unresolve", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "toggle":
        # A user command (like setup/onboard), not a hook: a real, intentional
        # non-zero exit (bad on|off usage -> 2) is meaningful, so this is NOT the
        # hook/cron fail-open-to-0 path. np_toggle.cli() owns status/param/audit/
        # menu/<feature> [on|off] routing and prints its own output.
        try:
            return np_toggle.cli(argv[1:])
        except Exception as exc:
            _bail("toggle", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "doctor":
        # A user/verify command (like setup/onboard): the doctor's real exit code
        # (0 MUST-OK / 1 MUST-fail / 2 contract-unreadable) is meaningful, so this
        # is NOT the hook/cron fail-open-to-0 path. Force UTF-8+LF: the report
        # contains ✓/✗ + em-dash (native-Windows Python defaults to cp1252).
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        try:
            text, code = np_doctor.report()
            sys.stdout.write(text)
            return code
        except Exception as exc:
            _bail("doctor", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "instruction-block":
        if len(argv) < 3 or argv[1] not in ("install", "remove"):
            sys.stderr.write("usage: cli.py instruction-block {install|remove} <file>\n")
            return 2
        action, file_path = argv[1], argv[2]
        try:
            (np_instruction_block.install if action == "install" else np_instruction_block.remove)(file_path)
            return 0
        except ValueError as exc:
            sys.stderr.write("np-instruction-block: %s\n" % exc)
            return 2
        except Exception as exc:
            _bail("instruction-block", "unhandled exception: %r" % exc)
            return 1

    if argv[0] == "sync":
        # The defensive engine sync (np_sync.py, phase 17 — 40-sync-nervepack.sh
        # retired). `cli.py sync` = backup mode (throttled); `cli.py sync exit` =
        # exit mode (always syncs). Registered on SessionStart/SessionEnd via
        # hooks.manifest and invoked by the np-core-sync skill. Fail-open like a
        # hook: the SessionStart/SessionEnd rows background it and discard output.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        mode = "exit" if "exit" in argv[1:] else "backup"
        verbose = "--verbose" in argv[1:]
        try:
            sys.stdout.write(np_sync.sync(mode, verbose) + "\n")
        except Exception as exc:
            _bail("sync", "unhandled exception: %r" % exc)
        return 0

    if argv[0] == "open-dashboard":
        # The MANUAL, on-demand dashboard open -- a distinct top-level command
        # from the SessionStart hook `cli.py hook open-dashboard`: no boot guard,
        # always rebuilds + opens, prints "opened <url>". Fail-open like the bash
        # open-dashboard.sh it replaces: always 0, even on an unhandled exception.
        try:
            return np_dashboard.open_manual()
        except Exception as exc:
            _bail("open-dashboard", "unhandled exception: %r" % exc)
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
