#!/usr/bin/env python3
"""Is this diff a dependency version bump a bot opened? (#306, change spec 0033)

`spec-guard` and `tier-gate` both require `change-specs/<branch-slug>.md` for a
high-tier diff, and `.github/workflows/**` is high tier. Dependabot cannot write
a change spec, so every GitHub Actions update was permanently blocked. A spec
records a design decision and a version bump has no design to record.

The exemption is from the SPEC requirement only. Every other gate still runs:
the five deterministic ones, the adversarial lens, and tier-gate's requirement
that the lens actually RAN. `high` is not auto-merge eligible, so a human still
merges.

TWO conditions, both required:

  1. The PR author is an allowlisted bot, read from
     `github.event.pull_request.user.login`. NEVER `github.actor`, which is the
     last identity to ACT on the pull request rather than its author.
  2. Every changed line is a version bump in an allowlisted manifest.

Neither is sufficient alone, and that is the whole design. Condition 1 alone is
the confused deputy #255 warns about: a collaborator can push anything onto a
dependabot branch while `user.login` stays `dependabot[bot]`. Condition 2 alone
lets any human skip a spec by shaping a change to look like a bump.

Returns (bool, reason) so a caller can say WHY a diff was or was not exempt. An
exemption that prints nothing is indistinguishable from a gate that did not run.
"""
import fnmatch
import re

# Only GitHub's own dependency bot. Widening this list widens what can reach
# main without a spec, so it belongs in a reviewed diff, never in config.
BOT_AUTHORS = ("dependabot[bot]",)

# This repo's actual dependabot surface, nothing speculative: the workflows it
# bumps `uses:` refs in, and the e2e package manifests.
MANIFEST_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "*package.json",
    "*package-lock.json",
)

# `@v8`, `@v1.2.3`, a 40-hex pinned sha, and bare/prefixed semver in a manifest.
_VERSION = re.compile(
    r"@[0-9a-f]{40}"
    r"|@v?\d+(?:\.\d+)*(?:-[0-9A-Za-z.]+)?"
    r"|[~^]?\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?"
)
_PLACEHOLDER = "\x00VERSION\x00"


def normalize_versions(text):
    """Replace every version-looking token with one placeholder.

    Two lines that differ ONLY in a version become equal here. Anything else
    that differs stays different, which is what makes the comparison a real
    check rather than a shape test.
    """
    return _VERSION.sub(_PLACEHOLDER, text)


def _on_allowlist(path):
    return any(fnmatch.fnmatch(path, g) for g in MANIFEST_GLOBS)


def parse_diff(diff_text):
    """{path: (removed_lines, added_lines)} from a unified diff.

    Only +/- content lines are collected. `---`/`+++` headers are skipped, and
    so is every hunk header, so a rename or a mode change contributes nothing
    and therefore cannot look like a balanced bump.
    """
    files = {}
    path = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            path = parts[1].strip() if len(parts) == 2 else None
            if path:
                files.setdefault(path, ([], []))
            continue
        if path is None or line.startswith(("--- ", "+++ ", "@@", "index ",
                                            "new file", "deleted file",
                                            "similarity index", "rename ")):
            continue
        if line.startswith("-"):
            files[path][0].append(line[1:])
        elif line.startswith("+"):
            files[path][1].append(line[1:])
    return files


def is_spec_exempt(diff_text, author, bots=BOT_AUTHORS):
    """(exempt, reason). Exempt only when BOTH conditions hold."""
    if author not in bots:
        return False, ("author %r is not an allowlisted bot (allowed: %s)"
                       % (author, ", ".join(bots)))

    files = parse_diff(diff_text)
    changed = {p: (rem, add) for p, (rem, add) in files.items() if rem or add}
    if not changed:
        # Nothing to inspect is not the same as inspected and cleared. An empty
        # diff needs no exemption, and granting one here would make a parser
        # that silently matched nothing read as a clean pass.
        return False, "diff contains no changed lines to classify"

    for path, (removed, added) in sorted(changed.items()):
        if not _on_allowlist(path):
            return False, ("%s is not on the dependency-manifest allowlist"
                           % path)
        if len(removed) != len(added):
            return False, ("%s is not a version bump: %d line(s) removed, "
                           "%d added" % (path, len(removed), len(added)))
        for was, now in zip(removed, added):
            if normalize_versions(was) != normalize_versions(now):
                return False, ("%s is not a version bump: %r became %r, which "
                               "differs by more than a version"
                               % (path, was.strip(), now.strip()))

    return True, ("every changed line in %s is a version bump by %s"
                  % (", ".join(sorted(changed)), author))
