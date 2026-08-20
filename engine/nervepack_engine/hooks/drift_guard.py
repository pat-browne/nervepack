"""PreToolUse hook on Write and Edit: the spec-drift gate (F3, #249).

Blocks an edit whose path falls outside the declared `blast_radius` of
`change-specs/<branch-slug>.md`. `spec-guard` (F2) enforces the same policy in
CI, but CI runs after the work is done -- by then the drift is a finished
branch, not one edit. This catches it at the tool call.

The SECOND hook in nervepack permitted to block, per ARCHITECTURE invariant 1,
and bounded the same four ways `turn_gate` is:

  - toggle-gated (`gates` / `gates.drift_guard.enforce`),
  - silent wherever it has no jurisdiction (no repo, no branch, no spec),
  - one decision per tool call, never a loop,
  - every one of its own error paths returns "" and allows.

Fails CLOSED on a policy violation, OPEN on its own error -- the same dual-mode
posture as np-pii-filter.py. A guard that bricks a session gets deleted, and
then nothing is enforced at all.

It never widens the blast radius. Silent widening is the exact failure the hook
exists to prevent, so the denial message names the two legal responses and
leaves both to the human.
"""
import datetime
import json
import os

import np_change_spec
import np_toggle

_RESPONSES = ("Either widen the spec's blast_radius and record why in its "
              "## Deviations section, or supersede the spec with a new one. "
              "Do not widen it silently.")


def _log_path():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.environ.get("NP_DRIFT_GUARD_LOG") or os.path.join(
        home, ".cache", "nervepack", "drift-guard.log")


def _log(verdict, sid, detail):
    """One dated line per adjudication. Decoded by np-core-doctor's
    references/log-patterns.md.

    Only ever called once the guard has jurisdiction. "No spec in this repo" is
    not a bail worth a line -- it is the common case on every repo that has not
    adopted the convention, and logging it would be one line per Write and Edit
    per session, machine-wide.
    """
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s drift-guard %s sid=%s %s\n" % (ts, verdict, sid, detail))
    except OSError:
        pass  # a log that cannot be written must not change the decision


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, separators=(",", ":"))


def _warn(context):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": context,
    }}, separators=(",", ":"))


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    if not np_toggle.enabled("gates"):
        return ""

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    path = tool_input.get("file_path") or ""
    if not path or not os.path.isabs(path):
        return ""

    sid = payload.get("session_id") or "unknown"

    root = np_change_spec.repo_root(os.path.dirname(path))
    if not root:
        return ""  # not in a git repo -- no policy to enforce

    branch = np_change_spec.current_branch(root)
    if not branch:
        return ""  # detached HEAD or unreadable HEAD -- fail open, our error

    spec_rel, globs = np_change_spec.load(root, branch)
    if not spec_rel:
        return ""  # this repo has not adopted change-specs/

    try:
        rel = os.path.relpath(os.path.realpath(path), root).replace(os.sep, "/")
    except ValueError:
        return ""  # different drive on Windows -- not under this root after all
    if rel == ".." or rel.startswith("../"):
        return ""  # symlinked out of the tree; not this repo's business

    if not globs:
        # A spec with no blast_radius is a spec-authoring error, and spec-guard
        # already fails the PR for it. Denying every edit in the repo over it
        # would brick the session.
        _log("WARN", sid, "%s declares no blast_radius; not adjudicating" % spec_rel)
        return _warn("%s declares no blast_radius, so drift cannot be checked. "
                     "spec-guard will fail this branch in CI until the field is "
                     "filled in." % spec_rel)

    if np_change_spec.in_radius(rel, globs):
        _log("PASS", sid, "%s in radius of %s" % (rel, spec_rel))
        return ""

    message = ("Spec drift: %s is outside the blast_radius declared by %s "
               "(%s). %s" % (rel, spec_rel, ", ".join(globs), _RESPONSES))

    if (np_toggle.param("gates.drift_guard.enforce", "on") or "on") != "on":
        _log("WARN", sid, "%s outside radius of %s (enforce off)" % (rel, spec_rel))
        return _warn(message)

    _log("DENY", sid, "%s outside radius of %s" % (rel, spec_rel))
    return _deny(message)
