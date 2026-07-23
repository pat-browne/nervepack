"""Python port of np-onboard.sh (phase 7 of the bash->Python CLI consolidation
-- content overlay spec 2026-07-15-nervepack-python-cli-consolidation-design.md).
The full-onboard orchestrator: link the skills, wire every lifecycle hook,
install the scheduler for this OS, register the MCP server, and verify with
the doctor. Dispatched as `cli.py onboard` -- the MCP `nervepack_onboard` tool
and a bare-CLI onboard share this one entry point (np-mcp-server.py's
_tool_onboard calls `cli.py onboard` instead of `bash np-onboard.sh` now).

Safe to re-run. A failing step logs a warning and the run continues (the
doctor's exit code is this function's return value). The scheduler backend is
chosen by `uname -s` (np_scheduler_install.uname_s, the SAME helper each
install_* function gates on, so this dispatch can never drift from theirs):
launchd on macOS, Task Scheduler on native Windows (Git-bash), cron elsewhere.

Most individual steps (link-skills, link-dashboard-data, every 5x/6x hook
installer, the doctor) are still bash -- this port is the ORCHESTRATION logic
only; it shells out to each exactly as np-onboard.sh did. Only the scheduler
step is a Python dispatch (`cli.py setup install-memory-*`, phase 6).
"""
import glob
import os
import subprocess
import sys

import np_bashlib
import np_scheduler_install

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.dirname(_HERE)


def _setup_dir():
    return _HERE


def _cli_path():
    return os.path.join(_ENGINE_DIR, "nervepack_engine", "cli.py")


def _default_run(cmd, **kwargs):
    kwargs.setdefault("check", False)
    # np_bashlib.argv(): every step here is either a bash script or already a
    # python3/sys.executable invocation -- on native Windows a bare `bash`
    # resolves to the WSL stub (System32), not Git-bash, so this normalization
    # is load-bearing, not cosmetic.
    return subprocess.run(np_bashlib.argv(cmd), **kwargs)


def _step_script(setup_dir, basename, run_fn):
    path = os.path.join(setup_dir, basename)
    if not os.path.exists(path):
        print("  · skip %s (not present)" % basename)
        return
    print("── %s" % basename)
    result = run_fn(["bash", path])
    if result.returncode != 0:
        print("  ! %s exited non-zero — continuing (the doctor will report the gap)" % basename,
              file=sys.stderr)


def _step_cli(cli, args, run_fn):
    print("── cli.py %s" % " ".join(args))
    result = run_fn([sys.executable, cli] + args)
    if result.returncode != 0:
        print("  ! cli.py %s exited non-zero — continuing (the doctor will report the gap)" % " ".join(args),
              file=sys.stderr)


def run(run_fn=None, uname_fn=None, setup_dir=None, glob_fn=None):
    # Force UTF-8: the step banners use "──" (em-dash box-drawing), and native
    # Windows Python defaults stdout to cp1252, which can't encode it -- that
    # would raise UnicodeEncodeError and abort the whole run. Same fix as
    # np_doctor.py/np_model.py/np_evaluator.py/np_sync.py/np_capture.py's
    # __main__ guards; this one lives in run() itself since onboard is always
    # invoked as a function call (via cli.py's dispatch), never as a script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    run_fn = run_fn or _default_run
    setup_dir = setup_dir or _setup_dir()
    cli = _cli_path()
    glob_fn = glob_fn or glob.glob

    # 1. Knowledge + the dashboard data bridge.
    _step_script(setup_dir, "30-link-skills.sh", run_fn)
    _step_cli(cli, ["setup", "link-dashboard-data"], run_fn)

    # 2. Every lifecycle hook installer (50-69). Globbed + numeric-sorted so a
    #    newly added hook is picked up automatically, in order.
    for path in sorted(glob_fn(os.path.join(setup_dir, "[56][0-9]-install-*.sh"))):
        _step_script(setup_dir, os.path.basename(path), run_fn)

    # 3. The scheduler, by OS (Python -- np_scheduler_install.py, phase 6).
    kernel = np_scheduler_install.uname_s(uname_fn)
    if kernel == "Darwin":
        step_args = ["setup", "install-memory-launchd"]
    elif kernel.startswith(("MINGW", "MSYS", "CYGWIN")):
        step_args = ["setup", "install-memory-schtasks"]
    else:
        step_args = ["setup", "install-memory-cron"]
    _step_cli(cli, step_args, run_fn)

    # 4. Verify. The doctor's exit status is this function's return value.
    print("── np-doctor.sh")
    result = run_fn(["bash", os.path.join(setup_dir, "np-doctor.sh")])
    return result.returncode
