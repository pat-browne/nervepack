"""Did each maintenance job actually run recently?

The maintenance crons are fail-open by design (ARCHITECTURE invariant 1), which
means every way they can die is silent. Three unrelated failures in 2026-07 each
stopped real work while every surface a human looks at still read "fine":

  * the host suspended across the 08:00-09:15 cron window, so the jobs never
    fired and no log line was written to say so;
  * memory-promote resolved its memory dir to the cron's own cwd project --
    empty -- and cheerfully reported "nothing to promote" on every run (#15);
  * headless auth expired; `claude -p` printed the error to stdout and exited
    0, so callers logged a generic parse bail and retried forever (#201).

None of those is detectable from the thing each job is supposed to produce, but
all three collapse into one observable: the job's last run is older than its
cadence allows. That is the only question this module answers.

Advisory only. Read by the doctor's `maintenance-freshness` check; never gates
anything and never raises.
"""
import datetime
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)   # np_dirs lives in engine/setup

import np_dirs
import np_toggle  # noqa: E402

# One row per scheduled maintenance job: (name, log basename, cadence in days,
# toggle key gating it). Cadence mirrors the installed schedule -- see
# ARCHITECTURE "Crons". A job whose toggle is off is not a fault and is skipped.
JOBS = (
    ("memory-promote",    "memory-promote.log",    1, "memory.promote"),
    ("episodic-maintain", "episodic-maintain.log", 1, "memory"),
    ("skill-maintain",    "skill-maintain.log",    1, "skills"),
    ("refine",            "refine.log",            7, "maintain.refine"),
    ("compact",           "compact.log",           7, "maintain.compact"),
)

_DEFAULT_GRACE_DAYS = "2"

# Both header shapes the logs contain: the Python bodies write
# "<stamp> === <name> run ===", the retired bash ones wrote
# "=== <stamp> <name> run ===". Match either by finding a run header, then
# pulling the ISO stamp out of that same line.
_HEADER = re.compile(r"===.*\brun\b.*===")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class Row(object):
    """One job's freshness verdict. `age_days` is None when it has never run."""

    __slots__ = ("name", "age_days", "stale", "cadence_days")

    def __init__(self, name, age_days, stale, cadence_days):
        self.name = name
        self.age_days = age_days
        self.stale = stale
        self.cadence_days = cadence_days


def _cache_dir():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return np_dirs.cache_dir()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def last_run(log_path):
    """The ISO stamp of the most recent run of the job that owns `log_path`, or
    None when the log is missing/unreadable or holds no stamp at all.

    Two log shapes exist and both must work. The agentic crons
    (np_agentic_cron) write a per-run header -- "<stamp> === <name> run ===" in
    the Python bodies, "=== <stamp> <name> run ===" in the retired bash ones.
    skill-maintain (np_skill_maintain) has no header and just writes stamped
    result lines. So: prefer the newest header, and fall back to the newest
    stamp anywhere in the file. Reading a headerless log as "never ran" would
    fire a false alarm on a perfectly healthy job -- which is worse than no
    alarm, because it teaches the reader to ignore the check."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    fallback = None
    for line in reversed(lines):
        found = _STAMP.search(line)
        if not found:
            continue
        if _HEADER.search(line):
            return found.group(0)
        if fallback is None:
            fallback = found.group(0)
    return fallback


def _age_days(stamp):
    try:
        when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return (_now() - when).total_seconds() / 86400.0


def _grace_days():
    try:
        return float(np_toggle.param("maintain.freshness_grace_days",
                                     _DEFAULT_GRACE_DAYS) or _DEFAULT_GRACE_DAYS)
    except (TypeError, ValueError):
        return float(_DEFAULT_GRACE_DAYS)


def survey():
    """One Row per *enabled* maintenance job. Never raises."""
    grace = _grace_days()
    try:
        cache = _cache_dir()
    except OSError:
        return []
    rows = []
    for name, basename, cadence, toggle_key in JOBS:
        try:
            if not np_toggle.enabled(toggle_key):
                continue
        except Exception:
            pass  # fail-open: an unresolvable toggle must not hide the job
        stamp = last_run(os.path.join(cache, basename))
        age = _age_days(stamp) if stamp else None
        # Never run counts as stale -- on a configured machine it means the
        # scheduler was never installed, which is exactly what we want surfaced.
        stale = age is None or age > (cadence + grace)
        rows.append(Row(name, age, stale, cadence))
    return rows


def report():
    """One doctor-style line: "PASS (...)" or "WARN (...)". Never raises."""
    try:
        rows = survey()
    except Exception:
        return "PASS (freshness survey unavailable)"
    if not rows:
        return "PASS (no maintenance jobs enabled)"
    stale = [r for r in rows if r.stale]
    if not stale:
        newest = max((r.age_days or 0.0) for r in rows)
        return "PASS (%d job(s) current; oldest %.1fd)" % (len(rows), newest)
    parts = []
    for r in stale:
        if r.age_days is None:
            parts.append("%s never ran" % r.name)
        else:
            parts.append("%s %.1fd ago (cadence %dd)" % (r.name, r.age_days, r.cadence_days))
    return ("WARN (%d stale: %s) — check ~/.cache/nervepack/<job>.log; a suspended "
            "host, an expired headless credential, or a disabled scheduler all "
            "look like this" % (len(stale), "; ".join(parts)))


if __name__ == "__main__":
    print(report())
