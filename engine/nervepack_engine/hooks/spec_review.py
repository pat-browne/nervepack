"""PreToolUse hook on Write and Edit: the spec-review gate (spec 0027).

Asks once, before the first implementation edit on a branch whose governing
spec or plan has not been confirmed as reviewed in this session. It does not
gate the authoring of that document: writing a spec is the moment nothing has
gone wrong yet, and a permission dialog there asks a question whose answer is
always yes.

The THIRD hook in nervepack permitted to interrupt, per ARCHITECTURE invariant
1, and bounded the same four ways `drift_guard` is:

  - toggle-gated (`gates` / `gates.spec_review`, the latter LOCAL scope so one
    machine can opt out without changing what the others enforce),
  - silent wherever it has no jurisdiction (no repo, no branch, no governing
    document, or the document is the file being written),
  - one decision per governing document per session, never once per edit,
  - every one of its own error paths returns "" and allows.

It asks rather than denies. The reviewed-ness of a document is a fact only the
human holds, so the only correct verdict this hook can reach on its own is "I
cannot tell" -- which is a question, not a refusal. A receipt is written as the
question is asked, keyed on (session, document, mtime), so a rewritten document
is confirmed again and an unchanged one is never asked about twice.
"""
import datetime
import json
import os
import re

import np_change_spec
import np_toggle
import np_dirs

# Directories whose contents ARE the record, never the implementation.
_RECORD_DIRS = ("change-specs/", "docs/superpowers/specs/",
                "docs/superpowers/plans/")
# Fallback order when the repo has no change-specs/<branch-slug>.md. A plan is
# what implementation executes, so it outranks the design spec behind it.
_FALLBACK_DIRS = ("docs/superpowers/plans", "docs/superpowers/specs")
# A plan nobody has touched in this long is not the one this edit implements.
# Without the bound, every repo holding an old plan costs one prompt a session.
_STALE_DAYS = 14


def _log_path():
    return os.environ.get("NP_SPEC_REVIEW_LOG") or np_dirs.cache_path("spec-review.log")


def _seen_dir():
    return os.environ.get("NP_SPEC_REVIEW_DIR") or np_dirs.cache_path("spec-review-seen")


def _log(verdict, sid, detail):
    """One dated line per adjudication. Decoded by np-core-doctor's
    references/log-patterns.md.

    Only ever called once the gate has jurisdiction. "No governing document"
    is the common case in every repo that has not adopted the convention, and
    logging it would be one line per Write and Edit per session, machine-wide.
    """
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s spec-review %s sid=%s %s\n" % (ts, verdict, sid, detail))
    except OSError:
        pass  # a log that cannot be written must not change the decision


def _ask(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}, separators=(",", ":"))


def _is_record(rel):
    return any(rel.startswith(d) for d in _RECORD_DIRS)


def _newest_under(root, rel_dir):
    """(repo-relative path, mtime) of the most recently modified *.md under
    rel_dir, or (None, 0). Anything older than _STALE_DAYS is not a candidate."""
    d = os.path.join(root, rel_dir)
    if not os.path.isdir(d):
        return None, 0
    cutoff = _STALE_DAYS * 86400
    now = datetime.datetime.now().timestamp()
    try:
        names = os.listdir(d)
    except OSError:
        return None, 0  # unreadable directory is OUR error, not a policy failure
    best, best_mtime = None, 0
    for name in names:
        if not name.endswith(".md"):
            continue
        full = os.path.join(d, name)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if now - mtime > cutoff:
            continue
        if mtime > best_mtime:
            best, best_mtime = "%s/%s" % (rel_dir, name), mtime
    return best, best_mtime


def _governing_document(root, branch):
    """(repo-relative path, mtime) of what this branch is implementing.

    The branch-scoped change spec first -- it is the only candidate with a real
    link to the current branch. The superpowers plan and design spec are dated,
    not branch-named, so the newest recent one is the closest honest answer.
    """
    if branch:
        slug = np_change_spec.branch_slug(branch)
        spec_abs = np_change_spec.spec_path_for(root, slug)
        if os.path.isfile(spec_abs):
            try:
                return np_change_spec.spec_rel_for(slug), os.path.getmtime(spec_abs)
            except OSError:
                return None, 0
    for rel_dir in _FALLBACK_DIRS:
        rel, mtime = _newest_under(root, rel_dir)
        if rel:
            return rel, mtime
    return None, 0


# A receipt filename is built from the session id, which arrives in the hook
# payload. It is a UUID in practice, but nothing here should depend on that: an
# id of ".." or one carrying a separator would name a path outside the cache
# directory, and on Windows the separator is a backslash. Keep the safe
# characters rather than trying to strip the dangerous ones, then drop leading
# dots so no id can resolve to "." or "..".
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_sid(sid):
    return (_UNSAFE.sub("_", sid).lstrip(".") or "unknown")[:128]


def _receipt_path(sid):
    return os.path.join(_seen_dir(), _safe_sid(sid))


def _already_confirmed(sid, key):
    try:
        with open(_receipt_path(sid), encoding="utf-8") as fh:
            return key in fh.read().splitlines()
    except OSError:
        return False


def _record(sid, key):
    try:
        path = _receipt_path(sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(key + "\n")
    except OSError:
        pass  # a receipt that cannot be written costs another prompt, not a block


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
        return ""  # not in a git repo -- no branch, no spec, no policy

    try:
        rel = os.path.relpath(os.path.realpath(path), root).replace(os.sep, "/")
    except ValueError:
        return ""  # different drive on Windows -- not under this root after all
    if rel == ".." or rel.startswith("../"):
        return ""  # symlinked out of the tree; not this repo's business

    if _is_record(rel):
        return ""  # authoring the record is never gated, and leaves no receipt

    branch = np_change_spec.current_branch(root)
    doc_rel, mtime = _governing_document(root, branch)
    if not doc_rel:
        return ""  # this repo has adopted neither convention

    if not np_toggle.enabled("gates.spec_review"):
        _log("OFF", sid, "%s not confirmed; gate disabled on this machine" % doc_rel)
        return ""

    key = "%s@%d" % (doc_rel, int(mtime))
    if _already_confirmed(sid, key):
        _log("PASS", sid, "%s already confirmed for %s" % (doc_rel, rel))
        return ""

    _record(sid, key)
    _log("ASK", sid, "%s not yet confirmed; asked before %s" % (doc_rel, rel))
    return _ask(
        "Review gate: %s governs this branch and has not been confirmed as "
        "reviewed in this session. Read it before implementation continues. "
        "Approve to proceed, or deny and review it first. Asked once per "
        "revision of that document." % doc_rel
    )
