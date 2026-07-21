"""Python port of 70-install-memory-{cron,launchd,schtasks}.sh (phase 6 of the
bash->Python CLI consolidation -- see content-overlay spec
2026-07-15-nervepack-python-cli-consolidation-design.md). Installs the six
authoritative nervepack maintenance jobs (memory-promote, episodic-maintain,
aggregate-metrics, skill-maintain, refine, compact) on whichever OS scheduler is
native: user crontab (Linux/generic), launchd LaunchAgents (macOS), or Windows
Task Scheduler (schtasks.exe, run under Git-bash). Dispatched via
`cli.py setup install-memory-{cron,launchd,schtasks}`.

Every job target is `python3 <cli.py> cron <name>` -- no bash job bodies remain
(phase 5 already ported all six cron bodies). Each install_* function is
fail-open in the sense that OS refusal returns 1 (a real, intentional failure
np-onboard.sh's step_cli() logs and continues past) rather than raising; internal
subprocess/env calls are all through injectable seams for hermetic testing.
"""
import os
import re
import shutil
import subprocess

import np_toggle
import np_token_lib

_CRON_JOBS = [
    ("nervepack-memory-promote", "0 8 * * *", "memory-promote"),
    ("nervepack-episodic-maintain", "30 8 * * *", "episodic-maintain"),
    ("nervepack-aggregate-metrics", "0 9 * * *", "aggregate-metrics"),
    ("nervepack-skill-maintain", "15 9 * * *", "skill-maintain"),
    ("nervepack-refine", "30 9 * * 0", "refine"),
    ("nervepack-compact", "0 10 * * 3", "compact"),
]

_LAUNCHD_JOBS = [
    ("memory-promote", 8, 0, "memory-promote"),
    ("episodic-maintain", 8, 30, "episodic-maintain"),
    ("aggregate-metrics", 9, 0, "aggregate-metrics"),
    ("skill-maintain", 9, 15, "skill-maintain"),
    ("refine", 9, 30, "refine"),
    ("compact", 10, 0, "compact"),
]

_SCHTASKS_JOBS = [
    ("memory-promote", "DAILY", None, "08:00", "memory-promote"),
    ("episodic-maintain", "DAILY", None, "08:30", "episodic-maintain"),
    ("aggregate-metrics", "DAILY", None, "09:00", "aggregate-metrics"),
    ("skill-maintain", "DAILY", None, "09:15", "skill-maintain"),
    ("refine", "WEEKLY", "SUN", "09:30", "refine"),
    ("compact", "WEEKLY", "WED", "10:00", "compact"),
]

_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>%s</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>%d</integer>
    <key>Minute</key><integer>%d</integer>
  </dict>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict>
</plist>
"""


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _nervepack_root(override=None):
    return override or os.path.join(_home(), "Code", "nervepack")


def _cli_path(nervepack_root):
    return os.path.join(nervepack_root, "engine", "nervepack_engine", "cli.py")


def _uname_s(uname_fn=None):
    if uname_fn is not None:
        return uname_fn()
    try:
        result = subprocess.run(["uname", "-s"], capture_output=True, text=True, timeout=2)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- cron (Linux/generic) ---------------------------------------------------

def _default_crontab_list():
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
        return result.stdout if result.returncode == 0 else ""
    except OSError:
        return ""


def _default_crontab_set(text):
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def _install_line(lines, marker, line):
    return [ln for ln in lines if marker not in ln and ln.strip()] + [line]


def _remove_line(lines, marker):
    return [ln for ln in lines if marker not in ln and ln.strip()]


def install_cron(nervepack_root=None, crontab_list_fn=None, crontab_set_fn=None,
                  token_prefix_fn=None, have_crontab_fn=None):
    have_crontab_fn = have_crontab_fn or (lambda: shutil.which("crontab") is not None)
    if not have_crontab_fn():
        print("crontab not available — install cron (sudo apt install -y cron) and retry")
        return 1

    nervepack_root = _nervepack_root(nervepack_root)
    crontab_list_fn = crontab_list_fn or _default_crontab_list
    crontab_set_fn = crontab_set_fn or _default_crontab_set
    token_prefix_fn = token_prefix_fn or np_token_lib.claude_token_env_prefix
    cli = _cli_path(nervepack_root)

    lines = [ln for ln in crontab_list_fn().splitlines() if ln.strip()]

    for marker, schedule, cron_name in _CRON_JOBS:
        line = "%s %spython3 %s cron %s # %s" % (schedule, token_prefix_fn(), cli, cron_name, marker)
        lines = _install_line(lines, marker, line)
        print("Installed cron entry: %s" % line)

    resume_marker = "nervepack-resume-cron"
    if np_toggle.param("resume.cron", "off") == "on":
        # .strip(): a conf value can carry a stray trailing \r (e.g. a toggles.conf
        # written/edited on Windows with universal-newline translation on) that
        # would otherwise fail .isdigit() and silently fall back to the default.
        cron_min = np_toggle.param("resume.cron_min", "5").strip()
        if not cron_min.isdigit():
            cron_min = "5"
        line = "*/%s * * * * python3 %s resume-write --active --throttle # %s" % (cron_min, cli, resume_marker)
        lines = _install_line(lines, resume_marker, line)
        print("Installed cron entry: %s" % line)
    else:
        lines = _remove_line(lines, resume_marker)

    crontab_set_fn("\n".join(lines) + "\n")
    return 0


# --- launchd (macOS) ---------------------------------------------------------

def _default_launchctl(plist_path):
    if not shutil.which("launchctl"):
        return
    subprocess.run(["launchctl", "unload", plist_path], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["launchctl", "load", "-w", plist_path], check=False)


def install_launchd(la_dir=None, log_dir=None, setup_dir=None, force=None,
                     token_prefix_fn=None, launchctl_fn=None, uname_fn=None):
    force = force if force is not None else bool(os.environ.get("NP_LAUNCHD_FORCE"))
    if _uname_s(uname_fn) != "Darwin" and not force:
        print("install-memory-launchd is the macOS path — on Linux use install-memory-cron")
        return 1

    home = _home()
    la_dir = la_dir or os.environ.get("NP_LAUNCHAGENTS_DIR") or os.path.join(home, "Library", "LaunchAgents")
    log_dir = log_dir or os.environ.get("NP_LAUNCHD_LOG_DIR") or os.path.join(home, ".cache", "nervepack")
    setup_dir = setup_dir or os.environ.get("NP_LAUNCHD_SETUP_DIR") or os.path.join(home, "Code", "nervepack", "engine", "setup")
    os.makedirs(la_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    token_prefix_fn = token_prefix_fn or np_token_lib.claude_token_env_prefix
    launchctl_fn = launchctl_fn or _default_launchctl
    cli = _cli_path(os.path.dirname(setup_dir))

    for suffix, hour, minute, cron_name in _LAUNCHD_JOBS:
        label = "com.nervepack.%s" % suffix
        plist_path = os.path.join(la_dir, "%s.plist" % label)
        log_path = os.path.join(log_dir, "%s.log" % suffix)
        exec_cmd = "%sexec python3 %s cron %s" % (token_prefix_fn(), cli, cron_name)
        content = _PLIST_TEMPLATE % (label, _xml_escape(exec_cmd), hour, minute, log_path, log_path)
        with open(plist_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        launchctl_fn(plist_path)
        print("Installed launchd agent: %s (%d:%02d -> cron %s)" % (label, hour, minute, cron_name))
    return 0


# --- schtasks (native Windows) ------------------------------------------------

def _default_cygpath(path):
    try:
        result = subprocess.run(["cygpath", "-w", path], capture_output=True, text=True, timeout=2)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _default_schtasks_create(args):
    subprocess.run(["schtasks"] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def install_schtasks(setup_dir=None, force=None, uname_fn=None, schtasks_fn=None,
                      bash_path_fn=None, cygpath_fn=None):
    # Deliberately NO token_prefix_fn, unlike install_cron/install_launchd: the
    # scheduled-auth token snippet's embedded double quotes would collide with
    # the nested //TR "..." quoting schtasks.exe already requires, and that risk
    # is unverified on a real Windows/Git-bash host (docs/ARCHITECTURE.md's
    # scheduled-auth-token catalog row + change-impact map). Wire it only after
    # testing on real Windows, updating this function AND both ARCHITECTURE.md
    # notes in the same change.
    force = force if force is not None else bool(os.environ.get("NP_SCHTASKS_FORCE"))
    kernel = _uname_s(uname_fn)
    if not re.match(r"^(MINGW|MSYS|CYGWIN)", kernel) and not force:
        print("install-memory-schtasks is the native-Windows path — "
              "on Linux use install-memory-cron, on macOS use install-memory-launchd")
        return 1

    setup_dir = setup_dir or os.environ.get("NP_SCHTASKS_SETUP_DIR") or os.path.join(
        _home(), "Code", "nervepack", "engine", "setup")
    cli = _cli_path(os.path.dirname(setup_dir))
    schtasks_fn = schtasks_fn or _default_schtasks_create

    bash_path = (bash_path_fn or (lambda: shutil.which("bash")))() or "bash"
    cygpath_fn = cygpath_fn or _default_cygpath
    bash_win = cygpath_fn(bash_path) or bash_path

    for suffix, sched, day, time_, cron_name in _SCHTASKS_JOBS:
        tn = "nervepack\\%s" % suffix
        exec_cmd = "exec python3 %s cron %s" % (cli, cron_name)
        tr = "\"%s\" -lc \"%s\"" % (bash_win, exec_cmd)
        args = ["//Create", "//TN", tn, "//TR", tr, "//SC", sched]
        if sched == "WEEKLY":
            args += ["//D", day]
        args += ["//ST", time_, "//F"]
        schtasks_fn(args)
        print("Installed scheduled task: %s (%s%s %s -> cron %s)" % (
            tn, sched, (" " + day) if day else "", time_, cron_name))
    return 0
