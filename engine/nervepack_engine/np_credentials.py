"""Credential registry: expiry health and rotation for declared credentials.
Reads metadata only (dates, existence, file mode), never a secret value.
"""
import datetime
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_SETUP = os.path.normpath(os.path.join(_HERE, "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import np_bashlib  # noqa: E402
import np_content  # noqa: E402
import np_dirs  # noqa: E402
import np_toggle  # noqa: E402

ENGINE_FILE = os.path.join(_SETUP, "credentials.json")
LAYER_REL = os.path.join("config", "credentials.json")
WARN_DAYS = 30
CMD_TIMEOUT = 15
ROTATE_TIMEOUT = 600
_BAD = ("warn", "expired", "missing", "unknown")
# Commands run only from layers the user owns. A team layer is written by
# others, so its commands would run as this user unasked.
_TRUSTED = ("engine", "personal")
_errors = []


def _engine_file():
    return os.environ.get("NP_CREDENTIALS_ENGINE_FILE") or ENGINE_FILE


# Later layers win by name: engine default, then personal, then team overlays.
def _layers():
    out = [("engine", _engine_file())]
    personal = np_content.content_dir()
    if personal:
        out.append(("personal", os.path.join(personal, LAYER_REL)))
    for team in reversed(np_content.team_dirs()):
        out.append(("team", os.path.join(team, LAYER_REL)))
    return out


def load():
    """Merged entries, keyed by name. Unreadable files land in _errors."""
    del _errors[:]
    merged = {}
    seen = set()
    for layer, path in _layers():
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            with open(path, encoding="utf-8") as fh:
                entries = json.load(fh).get("credentials") or []
        except (OSError, ValueError, AttributeError) as exc:
            _errors.append("%s registry unreadable (%s)" % (layer, type(exc).__name__))
            continue
        for e in entries:
            if isinstance(e, dict) and e.get("name"):
                merged[e["name"]] = dict(e, _layer=layer)
    return list(merged.values())


def _expand(path):
    path = path.replace("{config}", np_dirs.config_dir())
    path = path.replace("{engine}", os.path.normpath(os.path.join(_HERE, "..", "..")))
    return os.path.expanduser(path)


def _location(store):
    if store.get("kind") == "file":
        env = store.get("path_env")
        if env and os.environ.get(env):
            return os.environ[env]
        return _expand(store.get("path", ""))
    bits = [store.get(k) for k in ("kind", "backend", "item") if store.get(k)]
    return store.get("location") or ":".join(bits) or "unspecified"


def _date(text):
    try:
        return datetime.datetime.strptime(str(text).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _read_date(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return _date(fh.read())
    except OSError:
        return None


def _run_capture(cmd):
    """Run a date-reporting command. Output is only parsed, never surfaced."""
    try:
        res = subprocess.run(np_bashlib.argv(["bash", "-c", cmd]), stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=CMD_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def _run_rotate(cmd):
    try:
        return subprocess.run(np_bashlib.argv(["bash", "-c", cmd]), stdin=subprocess.DEVNULL,
                              timeout=ROTATE_TIMEOUT).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def _issued_file(entry, loc):
    if entry.get("issued_file"):
        return _expand(entry["issued_file"].replace("{path}", loc))
    if (entry.get("store") or {}).get("kind") == "file":
        return loc + ".issued"
    return None


def _issued(entry, loc):
    raw = entry.get("issued")
    if raw == "mtime":
        try:
            return datetime.date.fromtimestamp(os.stat(loc).st_mtime)
        except OSError:
            return None
    return _date(raw) if raw else None


def _evaluate(entry, today, run):
    store = entry.get("store") or {}
    loc = _location(store)
    rotate = entry.get("rotate") or {}
    row = {"name": entry["name"], "description": entry.get("description", ""),
           "layer": entry["_layer"], "kind": store.get("kind", "unspecified"),
           "location": loc, "rotate_mode": rotate.get("mode", "manual"),
           "command": rotate.get("command", ""), "expires": None,
           "days_left": None, "status": "unknown", "problems": []}
    warn_days = int(entry.get("warn_days", WARN_DAYS))

    if store.get("kind") == "file":
        try:
            st = os.stat(loc)
            present = st.st_size > 0
        except OSError:
            present = False
        if not present:
            row["status"] = "missing"
            row["problems"].append("not found at %s" % loc)
            return row
        if st.st_mode & 0o077:
            row["problems"].append("mode %o, want 600" % (st.st_mode & 0o777))

    if str(entry.get("expires", "")).lower() == "never":
        row["status"] = "warn" if row["problems"] else "ok"
        return row
    expires = _date(entry["expires"]) if entry.get("expires") else None
    if expires is None and entry.get("expires_cmd") and entry["_layer"] not in _TRUSTED:
        row["problems"].append("expires_cmd from %s layer not run" % entry["_layer"])
    elif expires is None and entry.get("expires_cmd"):
        out = run(entry["expires_cmd"])
        expires = _date(out) if out else None
        if expires is None:
            row["problems"].append("expires_cmd gave no date")
    if expires is None and entry.get("ttl_days"):
        issued = _issued(entry, loc)
        side = _issued_file(entry, loc)
        if issued is None and side:
            issued = _read_date(side)
        if issued is not None:
            expires = issued + datetime.timedelta(days=int(entry["ttl_days"]))
        else:
            row["problems"].append("no issued date")
    if expires is None:
        if not row["problems"]:
            row["problems"].append("no expiry recorded")
        return row

    days = (expires - today).days
    row["expires"], row["days_left"] = expires.isoformat(), days
    if days < 0:
        row["status"] = "expired"
    elif days <= warn_days or row["problems"]:
        row["status"] = "warn"
    else:
        row["status"] = "ok"
    return row


def survey(today=None, run=None):
    today = today or datetime.date.today()
    run = run or _run_capture
    return [_evaluate(e, today, run) for e in load()]


def _describe(r):
    when = "" if r["days_left"] is None else " %dd" % r["days_left"]
    probs = (" (%s)" % ", ".join(r["problems"])) if r["problems"] else ""
    fix = (" -> %s" % r["command"]) if r["command"] else ""
    return "%s: %s%s%s%s" % (r["name"], r["status"], when, probs, fix)


def report(today=None, run=None):
    """One doctor line, PASS or WARN. Never raises."""
    try:
        if not np_toggle.enabled("maintain.credentials"):
            return "PASS (credentials disabled)"
        rows = survey(today, run)
    except Exception as exc:
        return "PASS (credential survey unavailable: %s)" % type(exc).__name__
    bad = [r for r in rows if r["status"] in _BAD]
    errs = list(_errors)
    if not bad and not errs:
        return "PASS (%d credential(s) healthy)" % len(rows)
    detail = "; ".join([_describe(r) for r in bad] + errs)
    return "WARN (%d of %d credential(s): %s). Details: python3 engine/nervepack_engine/cli.py credentials" % (
        len(bad), len(rows), detail)


def _stamp(path, today):
    old = os.umask(0o077)
    try:
        with open(path, "w") as fh:
            fh.write(today.isoformat() + "\n")
    finally:
        os.umask(old)
    os.chmod(path, 0o600)


def _rotate_one(entry, row, today, run_cmd):
    if row["rotate_mode"] != "auto":
        return 0, ("%s needs a manual rotation (%s). Run it yourself: %s"
                   % (row["name"], row["status"], row["command"] or "see its skill"))
    if not row["command"]:
        return 2, "%s is marked auto but declares no command" % row["name"]
    if entry["_layer"] not in _TRUSTED:
        return 2, ("%s comes from the %s layer, so its command is not run. Run it yourself: %s"
                   % (row["name"], entry["_layer"], row["command"]))
    code = run_cmd(row["command"])
    if code != 0:
        return code, "%s: rotation command failed, exit %s" % (row["name"], code)
    side = _issued_file(entry, row["location"])
    if side and entry.get("ttl_days"):
        _stamp(side, today)
    return 0, "%s: rotated" % row["name"]


def rotate(name, today=None, run_cmd=None, run=None):
    today = today or datetime.date.today()
    for entry in load():
        if entry["name"] == name:
            row = _evaluate(entry, today, run or _run_capture)
            return _rotate_one(entry, row, today, run_cmd or _run_rotate)
    return 2, "no credential named %s" % name


def rotate_due(today=None, run_cmd=None, run=None):
    """Rotate every due auto source. List due manual ones with their command."""
    today = today or datetime.date.today()
    code, lines = 0, []
    for entry in load():
        row = _evaluate(entry, today, run or _run_capture)
        if row["status"] not in ("warn", "expired", "missing"):
            continue
        c, msg = _rotate_one(entry, row, today, run_cmd or _run_rotate)
        code = code or c
        lines.append(msg)
    return code, "\n".join(lines) or "nothing due"


def table(rows):
    head = ("credential", "status", "days", "expires", "rotate", "location")
    out = [head] + [(r["name"], r["status"], "" if r["days_left"] is None else str(r["days_left"]),
                     r["expires"] or "", r["rotate_mode"], r["location"]) for r in rows]
    widths = [max(len(row[i]) for row in out) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in out)


USAGE = ("usage: cli.py credentials [--json]\n"
         "       cli.py credentials rotate <name>\n"
         "       cli.py credentials rotate --due\n")


def main(argv):
    if argv[:1] == ["rotate"]:
        if argv[1:2] == ["--due"]:
            code, msg = rotate_due()
        elif len(argv) == 2:
            code, msg = rotate(argv[1])
        else:
            sys.stderr.write(USAGE)
            return 2
        print(msg)
        return code
    if argv and argv[0] not in ("--json", "status"):
        sys.stderr.write(USAGE)
        return 2
    rows = survey()
    if "--json" in argv:
        print(json.dumps({"credentials": rows, "errors": list(_errors)}, indent=2))
        return 0
    print(table(rows))
    print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
