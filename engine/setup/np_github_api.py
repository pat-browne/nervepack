"""Shared GitHub REST API fetch helper (stdlib urllib only, no `gh` CLI, no
third-party requests lib).

Factored out of np-gate-verdicts-comment.py (F4/#250) once np-ledger-append.py
(F5/#251) needed the identical plumbing - two real callers, not a speculative
extraction. Import-only module (underscore name), unlike the hyphenated
`np-*.py` entry-point scripts that use it.
"""
import json
import urllib.request


def default_fetch(url, token, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer %s" % token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None
