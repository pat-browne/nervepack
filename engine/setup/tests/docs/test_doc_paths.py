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
# A command WORD. Scoped to the enclosing code span, never to the whole line:
# a prose sentence may mention `git` while the path beside it is just a location.
# Line-scoped matching is what wrongly rewrote three prose references on #298,
# including one that inverted the rationale it was explaining.
COMMAND_WORD = re.compile(r"\b(python3?|bash|sh|cd|find|ls|cat|git|export|rm|cp|gh)\b")
CODE_SPAN = re.compile(r"`[^`]*`")
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
            if fence in SHELL_FENCES:
                bad.append((number, line.rstrip()))
                continue
            # Outside a fence, judge each occurrence by the code span holding it.
            for match in re.finditer(re.escape(LITERAL), line):
                span = next((m for m in CODE_SPAN.finditer(line)
                             if m.start() <= match.start() < m.end()), None)
                context = span.group(0) if span else line
                if COMMAND_WORD.search(context):
                    bad.append((number, line.rstrip()))
                    break
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

    def test_prose_mentioning_a_command_word_is_left_alone(self):
        """The case that actually went wrong. A sentence may say `git HEAD`
        while the path beside it is a location, not an argument. Judging the
        whole LINE rewrote three prose references on #298, one of which
        inverted the history it was explaining."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.md"), "w", encoding="utf-8") as fh:
                fh.write("`~/Code/nervepack` is a single working tree with one "
                         "git HEAD.\n"
                         "Before #257 the rows carried `~/Code/nervepack` and a "
                         "`git worktree remove` broke them.\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(_offending_lines("x.md"), [])
            finally:
                REPO = saved

    def test_a_command_inside_a_code_span_is_still_caught(self):
        """The span-scoped rule must not become a blanket prose exemption."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.md"), "w", encoding="utf-8") as fh:
                fh.write("Show the user `git -C ~/Code/nervepack log` first.\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(len(_offending_lines("x.md")), 1)
            finally:
                REPO = saved

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


class TestTheVariableIsAlwaysQuoted(unittest.TestCase):
    """An unquoted expansion word-splits and glob-expands.

    It does NOT allow command substitution: bash does not re-evaluate the RESULT
    of a parameter expansion, so a `$(id)` inside NP_DIR reaches the program as
    literal text. Measured, because the difference decides how alarmed to be.

    What is real: NP_DIR=/opt/my nervepack becomes two arguments, and a `*` in
    the value expands against the filesystem. Both break the command rather than
    escalate anything, and quoting fixes both.
    """

    VAR_AT = re.compile(r"\$\{NP(?:_CONTENT)?_DIR:-")

    @staticmethod
    def _quoted_at(line, idx):
        """Quote state RESETS at `$(`. Command substitution parses its body as
        fresh shell input, so enclosing quotes do not protect an expansion
        inside it - which is how CONTENT="$(python3 ${VAR}/x)" slipped past the
        first version of this check."""
        opened = line.rfind("$(", 0, idx)
        start = opened + 2 if opened >= 0 else 0
        return line[start:idx].count('"') % 2 == 1

    def test_a_non_shell_fence_is_not_checked(self):
        """A ```text block showing the pattern is documentation about the rule,
        not an instance of it."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.md"), "w", encoding="utf-8") as fh:
                fh.write("```text\nuse ${NP_DIR:-$HOME/Code/nervepack}/engine\n```\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(self._unquoted_in(["x.md"]), [])
            finally:
                REPO = saved

    def test_an_inline_span_outside_a_fence_is_still_checked(self):
        """Skipping everything outside a shell fence would miss these."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.md"), "w", encoding="utf-8") as fh:
                fh.write("Run `git -C ${NP_DIR:-$HOME/Code/nervepack} status`.\n")
            global REPO
            saved, REPO = REPO, d
            try:
                self.assertEqual(len(self._unquoted_in(["x.md"])), 1)
            finally:
                REPO = saved

    def test_no_shell_line_leaves_the_variable_unquoted(self):
        offenders = self._unquoted_in(_markdown_files())
        self.assertEqual(offenders, [],
                         "quote the expansion so a path with a space or a glob "
                         "character still works:\n  " + "\n  ".join(offenders))

    def _unquoted_in(self, rels):
        offenders = []
        for rel in rels:
            fence = None
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if stripped.startswith("```"):
                        fence = None if fence else (stripped[3:].strip().lower() or "text")
                        continue
                    # Inside a NON-shell fence (```text, ```json) a variable is
                    # illustrative, not executable, so quoting means nothing
                    # there. Outside any fence is still checked: an inline span
                    # like `git -C "${NP_DIR:-...}" log` is a real command.
                    if fence and fence not in SHELL_FENCES:
                        continue
                    if "${NP_DIR:-" not in line and "${NP_CONTENT_DIR:-" not in line:
                        continue
                    for match in self.VAR_AT.finditer(line):
                        if not self._quoted_at(line, match.start()):
                            offenders.append("%s:%d %s"
                                             % (rel, number, stripped[:88]))
                            break
        return offenders


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
