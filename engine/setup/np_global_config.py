"""Project the overlay's config/global-rules.md and config/host-settings.json
onto this machine's hosts. Rules go in a managed block of each global
instruction file. Settings merge only allowlisted, non-secret keys.
Toggle: global-config (local, managed, default on). Stdlib only.
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_PKG = os.path.normpath(os.path.join(_HERE, "..", "nervepack_engine"))
for _p in (_HERE, _ENGINE_PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_content  # noqa: E402
import np_dirs  # noqa: E402
import np_hook  # noqa: E402
import np_host  # noqa: E402
import np_instruction_block  # noqa: E402
import np_toggle  # noqa: E402

FEATURE = "global-config"
TAG = "global-rules"
BASE_KEYS = ("enabledPlugins", "extraKnownMarketplaces", "theme",
             "skipWorkflowUsageWarning")
NEVER_KEYS = ("hooks", "permissions", "env")
CODE_KEYS = ("extraKnownMarketplaces", "enabledPlugins")
TRUST_FILE = "trusted-marketplaces"
_SECRET = re.compile(r"token|secret|passw|api[-_]?key|private[-_]?key|credential", re.I)
_WORDS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def is_secret_name(name):
    """True for a key name that looks like a secret: token, key, secret, password."""
    if _SECRET.search(name):
        return True
    return any(w.lower() in ("key", "keys") for w in _WORDS.findall(name))


def _secret_path(value, path=""):
    """The first dotted key path under `value` with a secret-like name, else ''."""
    if isinstance(value, dict):
        for k, v in value.items():
            here = "%s.%s" % (path, k) if path else str(k)
            if is_secret_name(str(k)):
                return here
            hit = _secret_path(v, here)
            if hit:
                return hit
    elif isinstance(value, list):
        for v in value:
            hit = _secret_path(v, path)
            if hit:
                return hit
    return ""


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def config_dir():
    root = np_content.content_dir()
    return os.path.join(root, "config") if root else ""


def _rules_file():
    d = config_dir()
    return os.path.join(d, "global-rules.md") if d else ""


def _settings_file():
    d = config_dir()
    return os.path.join(d, "host-settings.json") if d else ""


def _state_file():
    return np_dirs.cache_path("global-config-state.json")


def _adapter_files():
    """Extra instruction files from adapter.json global_config.instruction_files."""
    path = os.environ.get("NP_ADAPTER") or np_dirs.config_path("adapter.json")
    try:
        with open(path, encoding="utf-8") as fh:
            block = json.load(fh).get("global_config")
    except (OSError, ValueError, AttributeError):
        return []
    files = block.get("instruction_files") if isinstance(block, dict) else None
    if not isinstance(files, list):
        return []
    out = []
    for f in files:
        if not isinstance(f, str) or not f.strip():
            continue
        f = f.strip()
        if f == "~" or f.startswith("~/"):
            f = os.path.join(_home(), f[2:])
        if os.path.isabs(f):
            out.append(os.path.normpath(f))
    return out


def rules_targets():
    """Global instruction files that get the rules block.

    Claude's CLAUDE.md beside its settings file, Codex's AGENTS.md when
    ~/.codex exists, and any file the adapter names. The env var
    NP_GLOBAL_RULES_TARGETS (os.pathsep list) replaces all of them for tests.
    """
    env = os.environ.get("NP_GLOBAL_RULES_TARGETS")
    if env is not None:
        return [p for p in env.split(os.pathsep) if p]
    out = [os.path.join(os.path.dirname(np_host.settings_path()), "CLAUDE.md")]
    codex = os.path.join(_home(), ".codex")
    if os.path.isdir(codex):
        out.append(os.path.join(codex, "AGENTS.md"))
    for f in _adapter_files():
        if f not in out:
            out.append(f)
    return out


def _read_rules():
    try:
        with open(_rules_file(), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _load_overlay_settings():
    """Return (allowed, notes). Allowed is {key: value}. Notes name each refused key.

    A key passes when it is in BASE_KEYS or the file's top-level "allowlist",
    is not hooks, permissions or env, and has no secret-like name at any depth.
    """
    path = _settings_file()
    if not path or not os.path.isfile(path):
        return {}, []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {}, ["host-settings.json unreadable: %s" % exc]
    if not isinstance(data, dict):
        return {}, ["host-settings.json is not a JSON object"]
    extra = data.get("allowlist", [])
    if not isinstance(extra, list):
        extra = []
    listed = set(BASE_KEYS) | {k for k in extra if isinstance(k, str)}
    allowed, notes = {}, []
    for key, value in data.items():
        if key == "allowlist":
            continue
        if key in NEVER_KEYS:
            notes.append("refused %s: protected key" % key)
        elif key not in listed:
            notes.append("ignored %s: not in the allowlist" % key)
        elif is_secret_name(key):
            notes.append("refused %s: secret-like name" % key)
        else:
            hit = _secret_path(value)
            if hit:
                notes.append("refused %s: secret-like key %s" % (key, hit))
            else:
                allowed[key] = value
    return allowed, notes


def trust_file():
    """Per-machine list of trusted marketplace sources. Never synced."""
    return os.environ.get("NP_TRUSTED_MARKETPLACES") or np_dirs.config_path(TRUST_FILE)


def _trusted_lines():
    try:
        with open(trust_file(), encoding="utf-8") as fh:
            rows = [ln.strip() for ln in fh]
    except OSError:
        return set()
    return {r for r in rows if r and not r.startswith("#")}


def _canon(value):
    return json.dumps(value, sort_keys=True)


def _source_line(entry):
    """Trust line: kind:value for a plain source, else canonical JSON. "" if unusable."""
    src = entry.get("source") if isinstance(entry, dict) else None
    if not isinstance(src, dict):
        return ""
    kind = src.get("source")
    where = [k for k in ("repo", "url", "path") if k in src]
    if not isinstance(kind, str) or not kind or len(where) != 1:
        return ""
    value = src[where[0]]
    if not isinstance(value, str) or not value:
        return ""
    if set(src) == {"source", where[0]}:
        return "%s:%s" % (kind, value)
    return _canon(src)


def _known_marketplace_names():
    """Marketplace names the host already knows from its own plugin store."""
    path = os.path.join(os.path.dirname(np_host.settings_path()), "plugins",
                        "known_marketplaces.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return set(data) if isinstance(data, dict) else set()


def _apply_trust(allowed, current):
    """Return (kept, skipped). Skipped is (label, advice). Never trusts by name."""
    lines = _trusted_lines()
    local = current.get("extraKnownMarketplaces")
    local = local if isinstance(local, dict) else {}
    names = set(local) | _known_marketplace_names()
    kept, skipped = dict(allowed), []
    markets = allowed.get("extraKnownMarketplaces")
    if markets is not None and not isinstance(markets, dict):
        kept.pop("extraKnownMarketplaces")
        markets = None
    lines_for = {}
    if markets is not None:
        ok = {}
        for name, entry in markets.items():
            line = _source_line(entry)
            lines_for[name] = line
            if not line:
                skipped.append(("marketplace %s" % name,
                                "rejected: ambiguous or unexpected source keys"))
            elif name in local and _canon(local[name]) == _canon(entry):
                ok[name] = entry
            elif line in lines:
                ok[name] = entry
                names.add(name)
            else:
                skipped.append(("marketplace %s" % name,
                                "untrusted: add '%s' to %s" % (line, trust_file())))
        if ok:
            kept["extraKnownMarketplaces"] = ok
        else:
            kept.pop("extraKnownMarketplaces")
    plugins = allowed.get("enabledPlugins")
    if plugins is not None and not isinstance(plugins, dict):
        kept.pop("enabledPlugins")
        plugins = None
    if plugins is not None:
        ok = {}
        for key, flag in plugins.items():
            market = key.rsplit("@", 1)[1] if "@" in key else ""
            if market and market in names:
                ok[key] = flag
            elif lines_for.get(market):
                skipped.append(("plugin %s" % key, "untrusted: add '%s' to %s"
                                % (lines_for[market], trust_file())))
            else:
                skipped.append(("plugin %s" % key, "marketplace %s is not "
                                "trusted or defined on this machine" % (market or "?")))
        if ok:
            kept["enabledPlugins"] = ok
        else:
            kept.pop("enabledPlugins")
    return kept, skipped


def _merge(base, over):
    """Deep merge where over wins. Dicts merge, everything else is replaced."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base[k], v) if k in base else v
        return out
    return over


def _load_state():
    try:
        with open(_state_file(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state):
    path = _state_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        _err("state not saved to %s: %s" % (path, exc))


def _err(msg):
    sys.stderr.write("np-global-config: %s\n" % msg)


def _sync_rules(state):
    body = _read_rules()
    if not body:
        return []
    done = []
    targets = rules_targets()
    for target in targets:
        try:
            verdict = np_instruction_block.sync_tagged(target, TAG, body)
            done.append("rules %s: %s" % (target, verdict))
        except (OSError, ValueError) as exc:
            _err("rules %s: %s" % (target, exc))
    state["rules"] = targets
    return done


def _sync_settings(state):
    allowed, notes = _load_overlay_settings()
    for n in notes:
        _err(n)
    if not allowed:
        return []
    path = np_host.settings_path()
    try:
        current = np_hook._load(path)
    except (OSError, ValueError) as exc:
        _err("settings %s unreadable, left untouched: %s" % (path, exc))
        return []
    allowed, skipped = _apply_trust(allowed, current)
    for label, advice in skipped:
        _err("skipped %s: %s" % (label, advice))
    if not allowed:
        return []
    applied = dict(state.get("settings") or {})
    changed = []
    for key, value in allowed.items():
        merged = _merge(current[key], value) if key in current else value
        if key not in current or current[key] != merged:
            current[key] = merged
            changed.append(key)
        applied[key] = merged
    if changed:
        np_hook._dump(path, current)
    state["settings"] = applied
    return ["settings %s: %s" % (path, ", ".join(changed) if changed else "unchanged")]


def apply(out=None):
    """Sync rules and settings from the overlay. Idempotent and fail-open.

    A machine with the toggle off converges to removed.
    """
    out = out or sys.stdout
    try:
        if not np_toggle.enabled(FEATURE):
            return remove(out)
        state = _load_state()
        lines = []
        for phase, step in (("rules", _sync_rules), ("settings", _sync_settings)):
            try:
                lines += step(state)
            except Exception as exc:  # one phase must not stop the other
                _err("%s sync failed: %r" % (phase, exc))
        if lines:
            _save_state(state)
        for line in lines:
            out.write("np-global-config: %s\n" % line)
    except Exception as exc:  # a sync must never break the caller
        _err("apply failed: %r" % exc)
    return 0


def remove(out=None):
    """Paired removal of the rules blocks and the settings keys this sync wrote.

    A settings key goes only while its value is still the one the sync wrote.
    """
    out = out or sys.stdout
    try:
        state = _load_state()
        targets = set(rules_targets()) | set(state.get("rules") or [])
        for target in sorted(targets):
            if os.path.isfile(target) and np_instruction_block.remove_tagged(target, TAG):
                out.write("np-global-config: rules %s: removed\n" % target)
        applied = state.get("settings") or {}
        path = np_host.settings_path()
        if applied and os.path.isfile(path):
            current = np_hook._load(path)
            gone = [k for k, v in applied.items() if k in current and current[k] == v]
            for k in gone:
                del current[k]
            if gone:
                np_hook._dump(path, current)
                out.write("np-global-config: settings removed: %s\n" % ", ".join(gone))
        try:
            os.remove(_state_file())
        except OSError:
            pass
    except Exception as exc:
        _err("remove failed: %r" % exc)
    return 0


def drift():
    """Differences between the overlay and this machine, one string each."""
    found = []
    body = _read_rules()
    if body:
        for target in rules_targets():
            have = np_instruction_block.read_tagged(target, TAG)
            if have is None:
                found.append("rules missing in %s" % target)
            elif have != body:
                found.append("rules stale in %s" % target)
    allowed, _ = _load_overlay_settings()
    if allowed:
        try:
            current = np_hook._load(np_host.settings_path())
        except (OSError, ValueError):
            return found + ["settings.json unreadable"]
        allowed, skipped = _apply_trust(allowed, current)
        for label, advice in skipped:
            found.append("%s %s" % (label, advice))
        for key, value in allowed.items():
            if key not in current or _merge(current[key], value) != current[key]:
                found.append("setting %s differs" % key)
    return found


def doctor_status():
    """Doctor line: PASS, or WARN with the drift. Advisory, never FAIL."""
    if not np_toggle.enabled(FEATURE):
        return "PASS (off)"
    if not _read_rules() and not _load_overlay_settings()[0]:
        return "PASS (no overlay config)"
    found = drift()
    if not found:
        return "PASS"
    return "WARN (drift: %s. Run cli.py setup sync-global-config)" % "; ".join(found)


if __name__ == "__main__":
    sys.exit(apply())
