#!/usr/bin/env python3
"""Rotation status for the scheduled-auth claude token (stdlib only).

Usage: np_token_status.py <token_file> [--ttl-days N] [--warn-days N]
Prints exactly one line: "missing" | "ok <days_left>" | "warn <days_left>".

The token file holds the raw `CLAUDE_CODE_OAUTH_TOKEN` value; a sibling
"<token_file>.issued" holds the YYYY-MM-DD mint date written by
np_claude_token_store() in np-token-lib.sh. If the token file exists but the
issued sidecar is missing or unparsable, age is unknowable — reported as
"warn 0" (never silently claim freshness) rather than "ok".
"""
import os
import sys
# self-bootstrap (phase 20b-2): engine/setup holds np_paths, np_bashlib, the config
# files, and the stayed sibling modules; add it so this relocated module resolves them
# whether imported in-process or run standalone. Its own dir (nervepack_engine) is
# already on sys.path[0] when run directly, so moved-sibling imports resolve too.
_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import sys
from datetime import date, datetime

TTL_DAYS_DEFAULT = 365
WARN_DAYS_DEFAULT = 30


def status(token_file, ttl_days=TTL_DAYS_DEFAULT, warn_days=WARN_DAYS_DEFAULT, today=None):
    try:
        with open(token_file, "rb") as f:
            has_token = len(f.read().strip()) > 0
    except OSError:
        has_token = False

    if not has_token:
        return "missing"

    try:
        with open(token_file + ".issued", "r") as f:
            issued = datetime.strptime(f.read().strip(), "%Y-%m-%d").date()
    except (OSError, ValueError):
        return "warn 0"

    days_elapsed = ((today or date.today()) - issued).days
    days_left = ttl_days - days_elapsed
    return f"{'warn' if days_left <= warn_days else 'ok'} {days_left}"


def main(argv):
    if not argv:
        print("missing")
        return 0
    token_file = argv[0]
    ttl_days, warn_days = TTL_DAYS_DEFAULT, WARN_DAYS_DEFAULT
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--ttl-days" and i + 1 < len(rest):
            ttl_days = int(rest[i + 1]); i += 2
        elif rest[i] == "--warn-days" and i + 1 < len(rest):
            warn_days = int(rest[i + 1]); i += 2
        else:
            i += 1
    print(status(token_file, ttl_days, warn_days))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
