"""Personal data catalog of identifiers a session touched.

Regex extraction, redaction, local inbox, then `drain()` into the overlay.
Names and addresses only. A secret value never enters.
"""
import os
import sys

_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import json
import re
import time

import np_content
import np_dirs
import np_scrub

MAX_ID = 300
MAX_PER_SESSION = 40

# Credential-shaped assignments, redacted from the text before extraction.
_CRED_ASSIGN = re.compile(
    r"(?i)\b(password|pwd|passwd|secret|client[_-]?secret|account[_-]?key|"
    r"shared[_-]?access[_-]?key|sig|signature|sas[_-]?token|access[_-]?token|"
    r"api[_-]?key|token|key)\b(\s*[=:]\s*)[\"']?[^\s;&\"',]+")
_LONG_B64 = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])")
_GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
_GUID_RE = re.compile("^" + _GUID + "$")

_TLDS = "com|net|org|io|dev|cloud|app|ai|co|us|edu|gov|internal|local|corp|lan"
_HOST = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:%s)" % _TLDS
_IP = r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"

_PATTERNS = [
    ("azure-resource-id", re.compile(
        r"/subscriptions/" + _GUID + r"(?:/resource[Gg]roups/[\w.()-]+(?:/providers/[\w./-]+)?)?")),
    ("arn", re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d*:[^\s\"'`,)\]]+")),
    ("keyvault-secret", re.compile(
        r"https://([a-z0-9-]{3,24})\.vault\.azure\.net/secrets/([A-Za-z0-9-]+)")),
    ("repo", re.compile(r"dev\.azure\.com/[\w.-]+/[\w.%-]+/_git/[\w.-]+")),
    ("repo", re.compile(r"github\.com/[\w.-]+/[\w.-]+")),
    ("url", re.compile(r"https?://[^\s\"'`<>)\]}]+")),
    ("pipeline-id", re.compile(r"(?i)\b(?:definitionId|pipelineId|buildId)=\d+")),
    ("cidr", re.compile(r"\b" + _IP + r"/(?:3[0-2]|[12]?\d)\b")),
    ("endpoint", re.compile(r"\b(?:%s|%s):\d{2,5}\b" % (_HOST, _IP))),
    ("ip", re.compile(r"(?<![\w.])" + _IP + r"(?![\w]|\.\d)")),
    ("hostname", re.compile(r"(?<![\w@./-])" + _HOST + r"(?![\w-])")),
    ("database", re.compile(r"(?i)\b(?:initial catalog|database)\s*=\s*([\w.-]{2,64})")),
    ("hostname-kv", re.compile(r"(?i)\b(?:server|data source|host)\s*=\s*(?:tcp:)?([\w.-]{3,100})")),
    ("db-object", re.compile(r"\[(\w+)\]\.\[(\w+)\]\.\[(\w+)\]")),
    ("db-object", re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+((?:\[?\w+\]?\.){1,2}\[?\w+\]?)")),
    ("keyvault-secret", re.compile(
        r"(?i)--vault-name[ =]+([\w-]{3,24})\s+.{0,40}?--name[ =]+([A-Za-z0-9-]+)")),
]
_PORT = re.compile(r"(?i)\bport[ =:]+(\d{2,5})\b")


def pre_redact(text):
    """Remove secret values from `text` before any extraction or model call."""
    text = np_scrub.scrub(text.encode("utf-8", "replace")).decode("utf-8", "replace")
    text = _CRED_ASSIGN.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED-SECRET]", text)
    return _LONG_B64.sub("[REDACTED-SECRET]", text)


def _clean_url(u):
    """Strip query and fragment. Drop URLs with userinfo or token-shaped path parts."""
    u = u.rstrip(".,;:'\"")
    u = re.split(r"[?#]", u, 1)[0]
    rest = u.split("://", 1)[1] if "://" in u else u
    if "@" in rest.split("/", 1)[0]:
        return None
    for seg in rest.split("/")[1:]:
        if _GUID_RE.match(seg):
            continue
        if len(seg) >= 24 and re.search(r"\d", seg) and re.search(r"[A-Za-z]", seg) \
                and re.fullmatch(r"[A-Za-z0-9_-]+", seg):
            return None
    return u.rstrip("/")


def _safe(ident):
    if not ident or len(ident) > MAX_ID or "REDACTED" in ident:
        return False
    return np_scrub.scrub(ident.encode("utf-8", "replace")).decode("utf-8", "replace") == ident


def extract(text):
    """Return [{"id", "type"}] for identifiers found in `text`.

    Secret values are redacted first. A candidate that still looks like a
    credential is dropped.
    """
    text = pre_redact(text or "")
    found, seen = [], set()

    def add(ident, typ):
        if ident and _safe(ident) and ident not in seen:
            seen.add(ident)
            found.append({"id": ident, "type": typ})

    url_spans = []
    for typ, rx in _PATTERNS:
        for m in rx.finditer(text):
            if typ == "url":
                url_spans.append(m.span())
                add(_clean_url(m.group(0)), "url")
            elif typ == "keyvault-secret":
                add("%s/%s" % (m.group(1), m.group(2)), typ)
            elif typ == "database":
                add(m.group(1), typ)
            elif typ == "hostname-kv":
                add(m.group(1).lower(), "hostname")
            elif typ == "db-object":
                parts = m.groups() if len(m.groups()) == 3 else m.group(1).split(".")
                add(".".join(p.strip("[]") for p in parts), typ)
            elif typ == "hostname":
                if not any(s <= m.start() < e for s, e in url_spans):
                    add(m.group(0).lower(), typ)
            else:
                add(m.group(0).rstrip(".,;"), typ)
    for m in _PORT.finditer(text):
        add("port %s" % m.group(1), "port")
    return found[:MAX_PER_SESSION]


def inbox_dir():
    return os.environ.get("NP_RESOURCES_INBOX") or np_dirs.cache_path("resources-inbox")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stage(items, session, repo):
    """Append resource records to the local inbox.

    Returns the count staged, or -1 when the inbox write failed.
    """
    lines = []
    for it in items or []:
        ident = (it.get("id") or "").strip()
        if not _safe(ident):
            continue
        purpose = np_scrub.scrub((it.get("purpose") or "")[:160].encode("utf-8", "replace")).decode(
            "utf-8", "replace")
        lines.append(json.dumps({"id": ident, "type": it.get("type") or "other", "purpose": purpose,
                                 "ts": _now(), "session": session, "repo": repo or ""},
                                ensure_ascii=False, separators=(",", ":")))
    if not lines:
        return 0
    try:
        os.makedirs(inbox_dir(), exist_ok=True)
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with open(os.path.join(inbox_dir(), day + ".jsonl"), "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        _log("stage: write to %s failed: %s" % (inbox_dir(), exc))
        return -1
    return len(lines)


def catalog_dir():
    """Overlay catalog path, or "" when no content dir resolves."""
    root = np_content.content_dir()
    return os.path.join(root, "memory", "resources") if root else ""


def _valid_record(r):
    """Same safety check as new records, plus shape. Coerces fields to text."""
    if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not _safe(r["id"]):
        return False
    for k in ("type", "purpose", "repo", "first_seen", "last_seen", "session"):
        if not isinstance(r.get(k, ""), str):
            return False
    if not isinstance(r.get("seen", 1), int) or isinstance(r.get("seen", 1), bool):
        return False
    purpose = r.get("purpose") or ""
    return not purpose or (len(purpose) <= MAX_ID and _safe(purpose))


def _log(msg):
    try:
        path = os.environ.get("NP_RESOURCES_LOG") or np_dirs.cache_path("resources-drain.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s resources: %s\n" % (_now(), msg))
    except OSError:
        pass


def _load_catalog(cdir):
    """Return {id: (filename, record)}. Malformed or unsafe rows are skipped and counted."""
    recs, skipped = {}, 0
    try:
        names = sorted(n for n in os.listdir(cdir) if re.fullmatch(r"\d{4}-\d{2}\.jsonl", n))
    except OSError:
        return recs
    for name in names:
        try:
            with open(os.path.join(cdir, name), encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        skipped += 1
                        continue
                    if _valid_record(r):
                        recs[r["id"]] = (name, r)
                    else:
                        skipped += 1
        except (OSError, UnicodeDecodeError):
            skipped += 1
    if skipped:
        _log("skipped %d malformed catalog row(s) in %s" % (skipped, cdir))
    return recs


_LOCK_STALE = 600


def _acquire(cdir):
    """Take the catalog lock. Returns the lock path, or None when another drain holds it."""
    path = os.path.join(cdir, ".drain.lock")
    for _ in range(2):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > _LOCK_STALE:
                    os.remove(path)
                    continue
            except OSError:
                pass
            return None
    return None


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


_MD_SPECIAL = re.compile(r"([\\`|*_<>\[\]#~!])")


def _cell(s):
    """Escape markdown control characters so a value cannot break the table."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(s or "").split()))


def render_index(records):
    by_type = {}
    for r in records:
        by_type.setdefault(r.get("type") or "other", []).append(r)
    out = ["# Resources catalog", "",
           "Identifiers seen in sessions. Names and addresses only, never secret values.", ""]
    for typ in sorted(by_type):
        out += ["## %s" % typ, "", "| identifier | purpose | repo | last seen |", "|---|---|---|---|"]
        for r in sorted(by_type[typ], key=lambda x: x.get("id", "")):
            out.append("| %s | %s | %s | %s |" % (_cell(r["id"]), _cell(r.get("purpose")),
                                                    _cell(r.get("repo")), (r.get("last_seen") or "")[:10]))
        out.append("")
    return "\n".join(out) + "\n"


def _merge(idir, files, cdir):
    recs = _load_catalog(cdir)
    month = time.strftime("%Y-%m", time.gmtime()) + ".jsonl"
    dirty, merged = set(), 0
    for f in files:
        with open(os.path.join(idir, f), encoding="utf-8") as fh:
            for line in fh:
                try:
                    n = json.loads(line)
                except ValueError:
                    continue
                ident = n.get("id") if isinstance(n, dict) else None
                if not _safe(ident or ""):
                    continue
                ts = n.get("ts") or _now()
                merged += 1
                if ident in recs:
                    fname, r = recs[ident]
                    r["last_seen"] = max(r.get("last_seen") or "", ts)
                    r["seen"] = r.get("seen", 1) + 1
                    if not r.get("purpose") and n.get("purpose"):
                        r["purpose"] = n["purpose"]
                else:
                    fname = month
                    recs[ident] = (fname, {"id": ident, "type": n.get("type") or "other",
                                           "purpose": n.get("purpose") or "", "first_seen": ts,
                                           "last_seen": ts, "session": n.get("session") or "",
                                           "repo": n.get("repo") or "", "seen": 1})
                dirty.add(fname)
    for fname in dirty:
        rows = sorted((r for fn, r in recs.values() if fn == fname), key=lambda r: r.get("first_seen", ""))
        _write_atomic(os.path.join(cdir, fname),
                      "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                              for r in rows))
    _write_atomic(os.path.join(cdir, "INDEX.md"), render_index([r for _, r in recs.values()]))
    for f in files:
        os.remove(os.path.join(idir, f))
    return merged


def drain():
    """Merge the inbox into the overlay catalog and rewrite INDEX.md.

    Returns the number of inbox records merged. Never raises. A lock file
    serializes concurrent drains; the loser keeps its inbox for the next run.
    """
    try:
        idir = inbox_dir()
        files = sorted(f for f in os.listdir(idir) if f.endswith(".jsonl"))
    except OSError:
        return 0
    if not files:
        return 0
    try:
        cdir = catalog_dir()
        if not cdir:
            return 0
        os.makedirs(cdir, exist_ok=True)
        lock = _acquire(cdir)
        if not lock:
            _log("drain: another drain holds the lock, inbox kept")
            return 0
        try:
            return _merge(idir, files, cdir)
        finally:
            try:
                os.remove(lock)
            except OSError:
                pass
    except Exception as exc:
        _log("drain: failed, inbox kept: %r" % (exc,))
        return 0
