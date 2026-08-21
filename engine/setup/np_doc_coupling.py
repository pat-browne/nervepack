#!/usr/bin/env python3
"""Documentation-coupling check (F10/#256).

Answers one question: did this change touch something whose documentation should
have moved with it, and did the documentation move.

**Two rules, because the two measured failure shapes need different rules.**

Rule 1, triggers. A changed path matches an enumerated trigger, so a
documentation change is expected in the same diff. The list lives in
doc-coupling.json, committed as data, GitLab-style, so it can be audited and
argued with instead of being a slogan.

Rule 2, dangling references. A file this diff deleted or renamed is still named
by a documentation file the diff did not touch. That document is now wrong.

Rule 2 is the important one. Wen et al. (ICPC 2019, 1.3 billion AST-level
changes across 1,500 systems) found that many documentation inconsistencies
arrive as a side effect of REFACTORING rather than of feature work: a magic
number removed from the code and left in the comment, a class hierarchy changed
and the type references left dangling. A check keyed only to feature paths
misses the dominant case.

Detecting "this diff looks like a refactor" heuristically was considered and
rejected. Balanced insert and delete counts, absence of new public names -- every
such rule is wrong often enough to be ignored, and a check that gets ignored
protects nothing. A removed path that a document still names is not a heuristic,
it is a fact about the tree.

**Advisory, permanently.** GitLab runs a hard documentation gate and still needed
the three-day escape hatch; Danger's canonical example ships a `#trivial` bypass.
Both are admissions that unconditional gates get disabled. With one maintainer
holding the admin bit, a blocking version would be overridden once and removed
twice. The consequence is instead cheap and non-negotiable: an issue that has to
be closed, opened at merge time by the caller.

Pure stdlib.
"""
import fnmatch
import json
import os
import re

SCHEMA = 1

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(_HERE, "doc-coupling.json")


class ConfigError(Exception):
    """The trigger list is missing, unparseable, or declares something unknown.

    Raised, not defaulted. An empty trigger list and an unreadable one look
    identical from the outside -- both check nothing -- and only one of them is
    a decision somebody made.
    """


def load(path=None):
    """Parse and validate the trigger list. Raises ConfigError on any problem."""
    path = path or DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise ConfigError("cannot read doc-coupling config at %s: %s" % (path, exc))
    except ValueError as exc:
        raise ConfigError("doc-coupling config at %s is not valid JSON: %s" % (path, exc))

    if not isinstance(data, dict):
        raise ConfigError("doc-coupling config must be a JSON object")
    if data.get("schema") != SCHEMA:
        raise ConfigError("doc-coupling schema %r is not the supported %d"
                          % (data.get("schema"), SCHEMA))
    if not isinstance(data.get("enabled"), bool):
        raise ConfigError("doc-coupling 'enabled' must be true or false")
    for field in ("doc_globs", "exempt_globs"):
        if not isinstance(data.get(field), list):
            raise ConfigError("doc-coupling %r must be a list" % field)
    triggers = data.get("triggers")
    if not isinstance(triggers, list):
        raise ConfigError("doc-coupling 'triggers' must be a list")
    for trigger in triggers:
        if not isinstance(trigger, dict) or not trigger.get("id"):
            raise ConfigError("every doc-coupling trigger needs an 'id': %r" % (trigger,))
        if not isinstance(trigger.get("globs"), list) or not trigger["globs"]:
            raise ConfigError("doc-coupling trigger %r needs a non-empty 'globs'"
                              % trigger.get("id"))
    return data


def _matches_any(rel, globs):
    return any(fnmatch.fnmatch(rel, g) for g in globs)


def is_doc(rel, config):
    return _matches_any(rel, config.get("doc_globs", []))


def is_exempt(rel, config):
    return _matches_any(rel, config.get("exempt_globs", []))


def is_dangling_exempt(rel, config):
    """True for documents that count as docs but are never scanned for stale
    references.

    `change-specs/**` is the case. A change spec counts as documentation for
    satisfying a trigger, because it is where a change explains itself. It is
    never scanned for dangling references, because change-specs/README.md
    forbids editing an accepted spec into the new answer -- so reporting one for
    naming a path that has since been renamed would demand an edit the process
    prohibits, and an unresolvable finding is worse than no finding.
    """
    return _matches_any(rel, config.get("dangling_exempt_globs", []))


def triggers_fired(changed, config):
    """[(trigger_id, [paths])] for every trigger this diff touched.

    Exempt paths are removed before matching rather than after, so a trigger
    whose only match was a test file does not fire at all -- a test-only diff is
    backend-only by definition and cannot introduce user-facing behavior.
    """
    subject = [p for p in changed if not is_exempt(p, config)]
    fired = []
    for trigger in config.get("triggers", []):
        hits = [p for p in subject if _matches_any(p, trigger["globs"])]
        if hits:
            fired.append((trigger["id"], sorted(hits)))
    return fired


def _reference_pattern(rel):
    """Match the path, or its basename, as a whole token.

    Bare `re.escape(rel) in text` would miss `np_foo.py` referenced without its
    directory, which is how documents usually name a script. The word boundaries
    stop `np_foo.py` from matching inside `np_foobar.py`.
    """
    base = os.path.basename(rel)
    return re.compile(r"(?<![\w/.-])(%s|%s)(?![\w-])"
                      % (re.escape(rel), re.escape(base)))


def dangling_references(root, removed, changed, config, doc_files=None):
    """[(removed_path, doc_path)] for documents left naming a path that is gone.

    `removed` is what the diff deleted or renamed away. A document the same diff
    also touched is not reported: the author already had it open, and flagging it
    would train people to ignore the check.

    Documents are read from the working tree, so this must run against the tree
    the diff produced.
    """
    touched = set(changed)
    if doc_files is None:
        doc_files = _walk_docs(root, config)
    out = []
    for rel in removed:
        pattern = _reference_pattern(rel)
        for doc in doc_files:
            if doc in touched:
                continue
            try:
                with open(os.path.join(root, doc), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if pattern.search(text):
                out.append((rel, doc))
    return sorted(out)


def _walk_docs(root, config):
    """Every documentation file the dangling-reference rule may scan.

    Walks rather than shelling out to git, so this stays importable and testable
    against a plain directory.
    """
    docs = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            if (is_doc(rel, config) and not is_exempt(rel, config)
                    and not is_dangling_exempt(rel, config)):
                docs.append(rel)
    return sorted(docs)


def evaluate(root, changed, removed, config, doc_files=None):
    """The coupling decision for one diff.

    `changed` is every path the diff touched, `removed` the subset it deleted or
    renamed away. The returned dict is written as the artifact and read by the
    merge-time issue opener, so its shape is a contract.
    """
    if not config.get("enabled"):
        return {"schema": SCHEMA, "enabled": False, "satisfied": True,
                "triggers": [], "dangling": [], "docs_changed": [], "problems": []}

    docs_changed = sorted(p for p in changed if is_doc(p, config))
    fired = triggers_fired(changed, config)
    dangling = dangling_references(root, removed, changed, config, doc_files=doc_files)

    problems = []
    if fired and not docs_changed:
        for trigger_id, paths in fired:
            problems.append(
                "trigger '%s' fired on %s and this change carries no documentation"
                % (trigger_id, ", ".join(paths[:5])))
    for removed_path, doc in dangling:
        problems.append(
            "%s names %s, which this change removed or renamed" % (doc, removed_path))

    return {
        "schema": SCHEMA,
        "enabled": True,
        "satisfied": not problems,
        "triggers": [{"id": t, "paths": p} for t, p in fired],
        "dangling": [{"removed": r, "doc": d} for r, d in dangling],
        "docs_changed": docs_changed,
        "problems": problems,
    }
