#!/usr/bin/env python3
# np-test: doc-paths | happy
"""No markdown command may hardcode the install path (F11/#257).

#295 removed the assumption from hook registration. The documentation kept it:
a reader or an agent who installed anywhere else copied a command naming a
directory that does not exist on their machine.

The rule is narrower than "never write the path", and the narrowing is the whole
design:

  A SHELL command gets ${NP_DIR:-$HOME/Code/nervepack}, because bash expands it
  and the engine already honours NP_DIR (np_doctor and np_link_skills read it).

  PROSE keeps `~/Code/nervepack`, because a path in prose is read by a human, or
  passed to a file-reading tool that expands `~` and does NOT expand a shell
  variable. Substituting there would break exactly the readers it meant to help.

change-specs/ is exempt. An accepted spec is a historical record that
change-specs/README.md forbids editing, and its mentions of the old path are the
explanation of what was removed.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))

LITERAL = "~/Code/nervepack"
# A line that RUNS something. A mention inside prose is not one of these.
INVOKES = re.compile(r"(^|[|`(\s\"'])(python3?|bash|sh|cd|find|ls|cat|git|export|rm|cp)\s")
SHELL_FENCES = ("bash", "sh", "shell", "console")
# `git clone <url> <dest>` is the one command whose path argument is the
# directory being CREATED, not a reference to an existing install. Writing
# ${NP_DIR:-...} there asks a first-time reader to reason about a variable that
# cannot be set yet, at the moment they have the least context. The default
# stays literal and GETTING-STARTED.md documents the override immediately below
# it. Deliberately narrow: only `git clone`.
CREATES_THE_CHECKOUT = re.compile(r"\bgit\s+clone\b")


def _markdown_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", ".worktrees", "node_modules", "archive")]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), REPO).replace(os.sep, "/")
            # Historical records, deliberately still naming the old path.
            if rel.startswith("change-specs/"):
                continue
            out.append(rel)
    return sorted(out)


def _offending_lines(rel):
    """Command lines in one file that still hardcode the install path."""
    bad, fence = [], None
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                fence = None if fence else (stripped[3:].strip().lower() or "text")
                continue
            if LITERAL not in line:
                continue
            if CREATES_THE_CHECKOUT.search(line):
                continue
            if fence in SHELL_FENCES or INVOKES.search(line):
                bad.append((number, line.rstrip()))
    return bad


class TestNoCommandHardcodesTheInstallPath(unittest.TestCase):
    def test_every_markdown_command_uses_the_variable(self):
        offenders = []
        for rel in _markdown_files():
            for number, line in _offending_lines(rel):
                offenders.append("%s:%d %s" % (rel, number, line.strip()[:90]))
        self.assertEqual(
            offenders, [],
            "these command lines hardcode the install path; use "
            "${NP_DIR:-$HOME/Code/nervepack} so a clone elsewhere works:\n  "
            + "\n  ".join(offenders))

    def test_the_check_finds_a_planted_offender(self):
        """A rule with no positive case is a rule nobody knows is running."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("```bash\npython3 ~/Code/nervepack/engine/x.py\n```\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(len(_offending_lines("x.md")), 1)
            finally:
                REPO = saved

    def test_the_clone_exemption_is_narrow(self):
        """It must cover `git clone` and nothing else. A broad exemption would
        quietly re-admit every command this check exists to catch."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("```bash\n"
                         "git clone https://x ~/Code/nervepack\n"
                         "git -C ~/Code/nervepack status\n"
                         "```\n")
            global REPO
            saved, REPO = REPO, d
            try:
                offenders = _offending_lines("x.md")
            finally:
                REPO = saved
        self.assertEqual(len(offenders), 1)
        self.assertIn("git -C", offenders[0][1])

    def test_prose_is_left_alone(self):
        """The variable must NOT spread into prose: a file-reading tool expands
        `~` and does not expand a shell variable."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("This repo (`~/Code/nervepack`) is the engine.\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(_offending_lines("x.md"), [])
            finally:
                REPO = saved


class TestEveryReferencedEnginePathExists(unittest.TestCase):
    """A substituted command that points at a path this repo does not have is
    worse than the literal it replaced: it looks resolved and is not.

    This is what surfaced `sources`, which named the ENGINE repo for a layer
    that resolves to <overlay>/memory/sources.
    """

    VAR = re.compile(r"\$\{NP_DIR:-\$HOME/Code/nervepack\}(/[\w./-]*)")

    def test_no_substituted_path_is_missing(self):
        missing = []
        for rel in _markdown_files():
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                for match in self.VAR.finditer(fh.read()):
                    target = match.group(1).rstrip("/")
                    # A placeholder like /skills/<name> is not a real path.
                    if not target or "<" in target:
                        continue
                    if not os.path.exists(os.path.join(REPO, target.lstrip("/"))):
                        missing.append("%s -> %s" % (rel, target))
        self.assertEqual(missing, [], "referenced paths that do not exist:\n  "
                         + "\n  ".join(missing))


if __name__ == "__main__":
    unittest.main()
