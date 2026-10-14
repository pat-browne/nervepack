"""Health of every scheduled nervepack job, for the doctor and GET /api/jobs.
Jobs come from np_scheduler_install plus extra com.nervepack.* launchd agents.
"""
import datetime
import os
import plistlib
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import np_dirs  # noqa: E402
import np_maintenance_freshness  # noqa: E402
import np_scheduler_install  # noqa: E402
import np_toggle  # noqa: E402

DAY = 86400
_LABEL = "com.nervepack."
_ERROR = re.compile(r"\bERROR\b|Traceback|agent run failed|auth failed|exited non-zero")
_WARN = re.compile(r"NOT PUBLISHED|\brefused\b|\bWARN\b")
_HEADER = re.compile(r"===.*\brun\b.*===")
_TAIL_LINES = 20
_STAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


def managed_jobs():
    out = []
    for name, hh, mm, weekly in np_scheduler_install._JOBS:
        when = "weekly dow=%s" % weekly[0] if weekly else "daily"
        out.append({"name": name, "managed": True,
                    "cadence_s": 7 * DAY if weekly else DAY,
                    "schedule": "%s %02d:%02d" % (when, hh, mm),
                    "toggle": np_scheduler_install.JOB_TOGGLES.get(name)})
    return out


def _plist_cadence(data):
    if data.get("StartInterval"):
        return int(data["StartInterval"]), "every %ss" % data["StartInterval"]
    cal = data.get("StartCalendarInterval")
    if isinstance(cal, dict) and "Weekday" in cal:
        return 7 * DAY, "weekly"
    return DAY, "daily"


def _read_plist(path):
    try:
        with open(path, "rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return {}


def _unmanaged_jobs(la_dir, known):
    out = []
    try:
        files = sorted(os.listdir(la_dir))
    except OSError:
        return out

    for f in files:
        if not (f.startswith(_LABEL) and f.endswith(".plist")):
            continue
        name = f[len(_LABEL):-len(".plist")]
        if name in known:
            continue

        data = _read_plist(os.path.join(la_dir, f))
        cadence, sched = _plist_cadence(data)
        out.append({"name": name, "managed": False, "cadence_s": cadence,
                    "schedule": sched, "toggle": None,
                    "stdout": data.get("StandardOutPath")})
    return out


def backend():
    kernel = np_scheduler_install.uname_s()
    if kernel == "Darwin":
        return "launchd"
    if re.match(r"^(MINGW|MSYS|CYGWIN)", kernel or ""):
        return "schtasks"
    return "cron" if kernel else "none"


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None


def _launchctl_exits():
    res = _run(["launchctl", "list"])
    out = {}
    for line in (res.stdout if res else "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith(_LABEL) and parts[1].lstrip("-").isdigit():
            out[parts[2]] = int(parts[1])
    return out


def _crontab():
    res = _run(["crontab", "-l"])
    return res.stdout if res and res.returncode == 0 else ""


def _schtasks_has(name):
    res = _run(["schtasks", "/Query", "/TN", "nervepack\\%s" % name])
    return None if res is None else res.returncode == 0


def _last_block(log_path):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None

    for i in range(len(lines) - 1, -1, -1):
        if _HEADER.search(lines[i]):
            return lines[i + 1:]
    return lines[-_TAIL_LINES:]


def _status(block):
    if block is None:
        return "unknown"
    text = "\n".join(block)
    if _ERROR.search(text):
        return "error"
    if _WARN.search(text):
        return "warn"
    return "ok" if text.strip() else "unknown"


def _last_run(log_path):
    stamp = np_maintenance_freshness.last_run(log_path)
    if stamp:
        return stamp
    try:
        mtime = os.path.getmtime(log_path)
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).strftime(_STAMP_FMT)


def _age_s(stamp):
    try:
        when = datetime.datetime.strptime(stamp, _STAMP_FMT).replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds()


def _grace_s():
    try:
        return float(np_toggle.param("maintain.freshness_grace_days", "2") or "2") * DAY
    except (TypeError, ValueError):
        return 2.0 * DAY


def _log_for(job, log_dir):
    own = os.path.join(log_dir, "%s.log" % job["name"])
    if os.path.exists(own) or not job.get("stdout"):
        return own
    return job["stdout"]


def _installed(name, kind, la_dir, cron, schtasks_fn):
    if kind == "launchd":
        return os.path.isfile(os.path.join(la_dir, "%s%s.plist" % (_LABEL, name)))
    if kind == "cron":
        return ("nervepack-%s" % name) in cron
    if kind == "schtasks":
        return schtasks_fn(name)
    return None


def _enabled(toggle):
    if not toggle:
        return True
    try:
        return np_toggle.enabled(toggle)
    except Exception:
        return True


def _row(job, kind, la_dir, log_dir, cron, exits, schtasks_fn, grace):
    enabled = _enabled(job["toggle"])
    log = _log_for(job, log_dir)
    last = _last_run(log)
    age = _age_s(last) if last else None
    limit = job["cadence_s"] + min(grace, job["cadence_s"])

    return {"name": job["name"], "managed": job["managed"], "schedule": job["schedule"],
            "cadence_s": job["cadence_s"], "toggle": job["toggle"], "enabled": enabled,
            "installed": _installed(job["name"], kind, la_dir, cron, schtasks_fn),
            "backend": kind, "log": log, "last_run": last,
            "age_h": None if age is None else round(age / 3600.0, 1),
            "status": _status(_last_block(log)), "exit": exits.get(_LABEL + job["name"]),
            "overdue": bool(enabled) and (age is None or age > limit)}


# Every OS call goes through a seam so tests run on any platform.
def survey(backend=None, la_dir=None, log_dir=None, launchctl_fn=None,
           crontab_fn=None, schtasks_fn=None):
    kind = backend or os.environ.get("NP_JOB_HEALTH_BACKEND") or globals()["backend"]()
    la_dir = la_dir or os.environ.get("NP_LAUNCHAGENTS_DIR") or os.path.join(
        os.path.expanduser("~"), "Library", "LaunchAgents")
    log_dir = log_dir or os.environ.get("NP_JOB_HEALTH_LOG_DIR") or np_dirs.cache_dir()

    exits = (launchctl_fn or _launchctl_exits)() if kind == "launchd" else {}
    cron = (crontab_fn or _crontab)() if kind == "cron" else ""
    jobs = managed_jobs()
    if kind == "launchd":
        jobs += _unmanaged_jobs(la_dir, {j["name"] for j in jobs})

    grace = _grace_s()
    return [_row(j, kind, la_dir, log_dir, cron, exits, schtasks_fn or _schtasks_has, grace)
            for j in jobs]


def _problems(row):
    if not row["enabled"]:
        return []
    out = []
    if row["installed"] is False:
        out.append("not installed")
    if row["status"] in ("error", "warn"):
        out.append("last run %s" % row["status"])
    if row["exit"] not in (None, 0):
        out.append("exit %s" % row["exit"])
    if row["overdue"]:
        out.append("overdue")
    return out


# One doctor line, PASS or WARN. Never raises.
def report():
    try:
        if not np_toggle.enabled("maintain.job_health"):
            return "PASS (job-health disabled)"
        rows = survey()
    except Exception:
        return "PASS (job-health survey unavailable)"

    bad = [(r["name"], _problems(r)) for r in rows]
    bad = [(n, p) for n, p in bad if p]
    if not bad:
        return "PASS (%d job(s) healthy)" % len(rows)
    detail = "; ".join("%s: %s" % (n, ", ".join(p)) for n, p in bad)
    return "WARN (%d of %d job(s): %s). Details: python3 engine/nervepack_engine/np_job_health.py" % (
        len(bad), len(rows), detail)


def _cells(r):
    return (r["name"] + ("" if r["managed"] else " *"),
            {True: "yes", False: "no", None: "?"}[r["installed"]],
            "on" if r["enabled"] else "off", r["last_run"] or "never",
            "" if r["age_h"] is None else str(r["age_h"]), r["status"],
            "" if r["exit"] is None else str(r["exit"]),
            "YES" if r["overdue"] else "no")


def table(rows):
    head = ("job", "inst", "toggle", "last run (UTC)", "age h", "status", "exit", "overdue")
    out = [head] + [_cells(r) for r in rows]
    widths = [max(len(row[i]) for row in out) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in out)


def main(argv):
    import json
    rows = survey()
    if "--json" in argv:
        print(json.dumps({"jobs": rows}, indent=2))
        return 0
    print(table(rows))
    print("\n* = not installed by the nervepack scheduler installer")
    print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
