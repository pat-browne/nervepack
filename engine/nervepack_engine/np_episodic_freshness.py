"""Is the episodic pipeline actually DRAINING, not just running?

`np_maintenance_freshness` answers "did each cron fire recently?". That is a
different question, and it structurally cannot catch the failure in #113: the
`episodic-maintain` cron fired on schedule, wrote its run header, and exited 0
every single day for over a week -- while draining nothing, because the headless
`claude -p` call underneath it had no valid credential. Every surface a human
looks at read "fine": the cron was current, the hooks were registered, the logs
had fresh timestamps. Meanwhile the inbox grew and `episodic-recall` returned
nothing for recent work.

The observable that catches it is the pair, not either half:

    notes are QUEUED in the inbox   AND   the episodic layer has not moved

Either alone is normal. A non-empty inbox mid-session is just work in flight; a
stale INDEX with an empty inbox just means quiet days. Together they mean the
drain is broken -- work went in and nothing came out.

Advisory only. Read by the doctor's `episodic-freshness` check; never gates
anything and never raises.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)   # np_dirs lives in engine/setup

import np_dirs
import np_content  # noqa: E402
import np_toggle  # noqa: E402

# Grace before a non-draining inbox is called a fault. The drain runs on exit
# (session-flush) with a daily cron as backup, so anything past ~2 days of
# queued-but-unmoved work has missed both paths.
_DEFAULT_GRACE_DAYS = "2"


def _grace_days():
    try:
        return float(np_toggle.param("memory.drain_grace_days",
                                     _DEFAULT_GRACE_DAYS) or _DEFAULT_GRACE_DAYS)
    except (ValueError, TypeError):
        return float(_DEFAULT_GRACE_DAYS)


def _inbox_dir():
    return os.environ.get(
        "NP_EPISODIC_INBOX",
        np_dirs.cache_path("episodic-inbox"))


def _index_path():
    """The episodic layer's INDEX.md in the personal content overlay. Personal-only
    on purpose: a team overlay's episodic layer is written by other people's
    machines, so its staleness says nothing about whether THIS host is draining."""
    return os.path.join(np_content.content_dir(), "memory", "episodic", "INDEX.md")


def survey():
    """(queued, oldest_queued_days, index_age_days) for the local pipeline.

    `index_age_days` is None when the episodic INDEX has never been written;
    `oldest_queued_days` is None when nothing is queued."""
    now = time.time()
    try:
        entries = [os.path.join(_inbox_dir(), f) for f in os.listdir(_inbox_dir())]
    except OSError:
        entries = []
    entries = [p for p in entries if not os.path.basename(p).startswith(".")]

    oldest = None
    for p in entries:
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        age = (now - mt) / 86400.0
        if oldest is None or age > oldest:
            oldest = age

    try:
        index_age = (now - os.path.getmtime(_index_path())) / 86400.0
    except OSError:
        index_age = None

    return len(entries), oldest, index_age


def report():
    """One doctor-style line: "PASS (...)" or "WARN (...)". Never raises."""
    try:
        if not np_toggle.enabled("memory"):
            return "PASS (memory off)"
        queued, oldest, index_age = survey()
    except Exception:
        return "PASS (episodic survey unavailable)"

    if not queued:
        return "PASS (inbox empty; nothing queued)"

    grace = _grace_days()
    # Work in flight is normal -- only queued work that has outlived BOTH the
    # on-exit flush and the daily backup cron is evidence of a broken drain.
    if oldest is None or oldest <= grace:
        return "PASS (%d note(s) queued, newest activity within %.1fd)" % (queued, grace)

    if index_age is None:
        return ("WARN (%d note(s) queued, oldest %.1fd; episodic INDEX never written) "
                "— the drain has never run: check ~/.cache/nervepack/episodic-maintain.log "
                "and the headless credential (cli.py doctor scheduled-auth-token)"
                % (queued, oldest))
    if index_age > grace:
        return ("WARN (%d note(s) queued, oldest %.1fd; episodic INDEX %.1fd stale) "
                "— work is going in and nothing is coming out: check "
                "~/.cache/nervepack/episodic-maintain.log and the headless credential "
                "(cli.py doctor scheduled-auth-token)"
                % (queued, oldest, index_age))
    return ("PASS (%d note(s) queued, oldest %.1fd; INDEX moved %.1fd ago)"
            % (queued, oldest, index_age))


if __name__ == "__main__":
    print(report())
