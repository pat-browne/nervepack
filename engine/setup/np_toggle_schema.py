"""Param schema for the dashboard's toggle-editing panel — dashboard/API-only,
NOT consulted by nervepack-toggle.sh (see the design spec, overlay
docs/superpowers/specs/2026-07-09-dashboard-toggle-controls-design.md).

Loads engine/setup/toggle-schema.json and validates a raw toggles.conf/
toggles.local string value against its entry. A param with no schema entry is
NOT auto-coerced or guessed at — the caller (np-dashboard-server.py) renders it
read-only instead. stdlib only.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _schema_path():
    return os.environ.get("NP_TOGGLE_SCHEMA") or os.path.join(_HERE, "toggle-schema.json")


def load():
    """dict[dotted_param_key] -> {type, min?, max?, options?, description}.
    Missing/invalid file -> {} (fail-open: every param just renders read-only)."""
    path = _schema_path()
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def validate(key, raw_value):
    """Validate `raw_value` (a string, exactly as stored in toggles.conf/
    toggles.local) against `key`'s schema entry.

    Returns (valid: bool, coerced, error: str|None). `coerced` is a JSON-safe
    value (bool/int/float/str) for the given type; on failure it is None.
    No schema entry for `key` -> (False, None, "no schema entry") — the caller
    must never edit a param it can't type-check."""
    entry = load().get(key)
    if not entry:
        return False, None, "no schema entry"
    t = entry.get("type")
    if t == "bool":
        if raw_value not in ("on", "off"):
            return False, None, "expected on/off, got %r" % (raw_value,)
        return True, raw_value == "on", None
    if t == "number":
        try:
            n = float(raw_value) if "." in raw_value else int(raw_value)
        except (TypeError, ValueError):
            return False, None, "expected a number, got %r" % (raw_value,)
        lo, hi = entry.get("min"), entry.get("max")
        if lo is not None and n < lo:
            return False, None, "%s is below min %s" % (n, lo)
        if hi is not None and n > hi:
            return False, None, "%s is above max %s" % (n, hi)
        return True, n, None
    if t == "enum":
        options = entry.get("options") or []
        if raw_value not in options:
            return False, None, "expected one of %s, got %r" % (options, raw_value)
        return True, raw_value, None
    if t == "string":
        return True, raw_value, None
    return False, None, "unknown schema type %r" % (t,)
