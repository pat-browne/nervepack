#!/usr/bin/env python3
"""Lossless-upgrade test for np-migrate-lessons.py (stdlib unittest).

Seeds a temp content root with the PREVIOUS two-layer shapes (memory/playbooks +
memory/strategies) -- including a same-topic collision and an enforcing entry --
and asserts the migration produces memory/lessons/ with every field intact:
provenance tagged, topic_triggers hoisted out of the playbook `enforce:` block to
the top level, the `enforce` block (tool_match/gate) preserved byte-for-byte for
the failure-derived entry, no `enforce` block on the success-derived entry,
bodies preserved, INDEX.md regenerated in the guard-compatible shape, old dirs
removed, and the whole migration is idempotent (a second run is a no-op).

Also covers the two fail-safe/edge requirements: a file that fails to parse
aborts the WHOLE migration (nothing written, source dirs untouched, non-zero
exit), and an advisory (empty tool_match) playbook still carries its (non-
enforcing) enforce block over -- enforce presence tracks the source block, not
whether tool_match happens to be non-empty.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "..", "np-migrate-lessons.py")

PLAYBOOK_GIT = """---
name: Grep combined short flags get silently dropped
kind: playbook
status: confirmed
seen: 7
last_updated: 2026-06-20
enforce:
  tool_match: "grep -[a-z]*l[a-z]*i"
  gate: ask
  topic_triggers: [git]
wiki: [https://example.com/grep-flags]
---
**Symptom:** `grep -li` flags get silently reordered/dropped by a wrapping tool.
**Why:** Some shells alias grep in ways that eat combined short flags.
**Do:** Spell out `grep --files-with-matches --ignore-case` instead of `-li`.
**Avoid:** Trusting combined short flags survive every wrapper.
"""

STRATEGY_GIT = """---
name: Prefer long-form grep flags in wrapped contexts
kind: strategy
status: verified
seen: 3
last_updated: 2026-06-21
topic_triggers: [git]
wiki: [https://example.com/grep-flags, https://example.com/posix-flags]
---
**Title:** Prefer long-form grep flags in scripted/wrapped contexts.
**When:** A grep invocation runs inside another tool or shell wrapper.
**Do:** Use `--files-with-matches --ignore-case` instead of `-li` so wrapper-layer flag handling can't reorder/eat the combined short flags.
"""

PLAYBOOK_SED = """---
name: sed
kind: playbook
status: candidate
seen: 1
last_updated: 2026-06-19
enforce:
  tool_match: ""
  gate: warn
  topic_triggers: [sed, stream-editing]
wiki: []
---
**Symptom:** In-place `sed -i` edits silently no-op on macOS (BSD sed) because the
GNU `-i` (no backup suffix) syntax differs from BSD's mandatory suffix argument.
**Why:** BSD sed's `-i` requires a (possibly empty) suffix argument; GNU sed's
does not. A script written for one breaks silently or errors on the other.
**Do:** Pass an explicit empty suffix compatibly, or use the Edit tool instead of
shelling out to sed for portable edits.
**Avoid:** Bare `sed -i 's/x/y/' file` in cross-platform scripts.
"""

PLAYBOOK_INCOMPLETE_ENFORCE = """---
name: incomplete
kind: playbook
status: candidate
seen: 1
last_updated: 2026-06-22
enforce:
  tool_match: "foo.*"
  topic_triggers: [incomplete]
wiki: []
---
**Symptom:** placeholder.
**Why:** placeholder.
**Do:** placeholder.
"""

PLAYBOOK_EXTRA_KEY = """---
name: extra
kind: playbook
status: candidate
seen: 1
last_updated: 2026-06-22
custom_field: hello
enforce:
  tool_match: "bar.*"
  gate: block
  topic_triggers: [extra]
wiki: []
---
**Symptom:** placeholder.
**Why:** placeholder.
**Do:** placeholder.
"""


sys.path.insert(0, os.path.join(HERE, "..", ".."))
import np_lesson_format  # noqa: E402

FAIL_FM = """---
name: Grep combined flags dropped
kind: lesson
provenance: failure
status: confirmed
seen: 7
last_updated: 2026-06-20
topic_triggers: [git, grep]
enforce:
  tool_match: "grep -[a-z]*l[a-z]*i"
  gate: ask
  tool_name_match: Bash
wiki: []
---
"""
FAIL_BODY = """**Symptom:** `grep -li` flags get silently reordered by a wrapping tool
and the second line CONTINUATION-TEXT explains the wrapper. Extra sentence.
**Why:** Some shells alias grep in ways that eat combined short flags.
**Do:** Spell out `grep --files-with-matches --ignore-case` instead of `-li`.
**Avoid:** Trusting combined short flags survive every wrapper.
"""
SUCC_FM = """---
name: Prefer long grep flags
kind: lesson
provenance: success
status: verified
seen: 3
last_updated: 2026-06-21
topic_triggers: [git]
wiki: []
---
"""
SUCC_BODY = """**Title:** Prefer long-form grep flags in wrapped contexts.
**When:** A grep invocation runs inside another tool.
**Do:** Use `--files-with-matches` so wrappers cannot eat flags.
"""
PAIRED = SUCC_FM + """## Paired already
- DO use long flags \u2014 **when** wrapped \u2014 **why** it worked. [[episodic/git]]
"""


def run_bodies(root):
    return subprocess.run([sys.executable, SCRIPT, "--bodies", root],
                          capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run_migration(root):
    return subprocess.run([sys.executable, SCRIPT, root], capture_output=True, text=True)


class TestMigrateLessons(unittest.TestCase):
    def test_lossless_upgrade_and_idempotence(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "memory", "playbooks", "git.md"), PLAYBOOK_GIT)
            write(os.path.join(root, "memory", "strategies", "git.md"), STRATEGY_GIT)
            write(os.path.join(root, "memory", "playbooks", "sed.md"), PLAYBOOK_SED)

            proc = run_migration(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            lessons_dir = os.path.join(root, "memory", "lessons")
            git_path = os.path.join(lessons_dir, "git.md")
            sed_path = os.path.join(lessons_dir, "sed.md")
            self.assertTrue(os.path.isfile(git_path))
            self.assertTrue(os.path.isfile(sed_path))

            git_text = read(git_path)

            # Both entries present, both migrated to kind: lesson.
            self.assertEqual(git_text.count("provenance: failure"), 1)
            self.assertEqual(git_text.count("provenance: success"), 1)
            self.assertEqual(git_text.count("kind: lesson"), 2)

            # Failure entry: enforce block intact, tool_match byte-identical.
            self.assertIn('tool_match: "grep -[a-z]*l[a-z]*i"', git_text)
            self.assertIn("gate: ask", git_text)

            # name/status/seen/wiki survive verbatim for BOTH entries, with
            # non-trivial (distinct, non-placeholder) values -- proves these
            # fields aren't silently coerced/defaulted during migration.
            self.assertIn(
                "name: Grep combined short flags get silently dropped", git_text)
            self.assertIn("status: confirmed", git_text)
            self.assertIn("seen: 7", git_text)
            self.assertIn("wiki: [https://example.com/grep-flags]", git_text)

            self.assertIn(
                "name: Prefer long-form grep flags in wrapped contexts", git_text)
            self.assertIn("status: verified", git_text)
            self.assertIn("seen: 3", git_text)
            self.assertIn(
                "wiki: [https://example.com/grep-flags, https://example.com/posix-flags]",
                git_text,
            )

            # topic_triggers hoisted to TOP LEVEL (no leading whitespace) for both
            # entries -- and no longer nested inside enforce:.
            top_level_triggers = re.findall(r"^topic_triggers:.*$", git_text, re.M)
            self.assertEqual(len(top_level_triggers), 2)
            indented_triggers = re.findall(r"^[ \t]+topic_triggers:", git_text, re.M)
            self.assertEqual(indented_triggers, [])

            # Success entry carries NO enforce block (check the region from its
            # own start onward, so the failure entry's enforce: doesn't leak in).
            success_start = git_text.index("provenance: success")
            success_region = git_text[success_start:]
            self.assertNotIn("enforce:", success_region)

            # Bodies preserved byte-for-byte (both source bodies present intact).
            self.assertIn("Trusting combined short flags survive every wrapper.", git_text)
            self.assertIn(
                "wrapper-layer flag handling can't reorder/eat the combined short flags.",
                git_text,
            )

            sed_text = read(sed_path)
            self.assertIn("provenance: failure", sed_text)
            self.assertNotIn("provenance: success", sed_text)
            self.assertIn('tool_match: ""', sed_text)
            self.assertIn("gate: warn", sed_text)
            self.assertIn("BSD sed's `-i` requires a (possibly empty) suffix argument", sed_text)

            # Old dirs gone.
            self.assertFalse(os.path.isdir(os.path.join(root, "memory", "playbooks")))
            self.assertFalse(os.path.isdir(os.path.join(root, "memory", "strategies")))

            # INDEX.md regenerated in the guard-compatible shape: a topic/tool_match/
            # gate row for both git and sed. The guard's Phase-1 parser is
            # `while IFS='|' read -r _ topic tool_match gate _rest`, so fields 2/3/4
            # must be topic/tool_match/gate in that order.
            index_text = read(os.path.join(lessons_dir, "INDEX.md"))
            git_row = next(l for l in index_text.splitlines() if l.strip().startswith("| git "))
            self.assertIn("grep -[a-z]*l[a-z]*i", git_row)
            git_cells = [c.strip() for c in git_row.strip().strip("|").split("|")]
            self.assertEqual(git_cells[0], "git")
            self.assertEqual(git_cells[1], "grep -[a-z]*l[a-z]*i")
            self.assertEqual(git_cells[2], "ask")

            sed_row = next(l for l in index_text.splitlines() if l.strip().startswith("| sed "))
            sed_cells = [c.strip() for c in sed_row.strip().strip("|").split("|")]
            self.assertEqual(sed_cells[0], "sed")
            self.assertEqual(sed_cells[1], "")  # empty tool_match cell for advisory entry
            self.assertEqual(sed_cells[2], "warn")

            # Idempotent: re-running is a no-op (lessons/ untouched byte-for-byte).
            snapshot = {
                name: read(os.path.join(lessons_dir, name))
                for name in os.listdir(lessons_dir)
            }
            proc2 = run_migration(root)
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
            self.assertEqual(sorted(os.listdir(lessons_dir)), sorted(snapshot.keys()))
            for name, text in snapshot.items():
                self.assertEqual(read(os.path.join(lessons_dir, name)), text)

    def test_fail_safe_on_malformed_frontmatter(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "memory", "playbooks", "git.md"), PLAYBOOK_GIT)
            write(os.path.join(root, "memory", "playbooks", "broken.md"),
                  "not frontmatter at all\n")

            proc = run_migration(root)

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(os.path.isdir(os.path.join(root, "memory", "lessons")))
            # source dirs must be untouched -- fail-safe means write NOTHING.
            self.assertTrue(os.path.isdir(os.path.join(root, "memory", "playbooks")))
            self.assertTrue(
                os.path.isfile(os.path.join(root, "memory", "playbooks", "git.md")))

    def test_advisory_playbook_still_migrates_with_empty_enforce(self):
        """A conceptual-only (empty tool_match) playbook still lands as a lesson
        with its enforce block intact -- enforce presence tracks the source
        block, not whether tool_match happens to be non-empty."""
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "memory", "playbooks", "sed.md"), PLAYBOOK_SED)

            proc = run_migration(root)

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            text = read(os.path.join(root, "memory", "lessons", "sed.md"))
            self.assertIn("provenance: failure", text)
            self.assertIn("enforce:", text)
            self.assertIn('tool_match: ""', text)

    def test_idempotent_when_already_migrated(self):
        """Running against a root that has no memory/playbooks or
        memory/strategies at all (already migrated, or never had them) is a
        clean no-op success."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "memory"), exist_ok=True)
            proc = run_migration(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_fail_safe_on_incomplete_enforce_block(self):
        """A present enforce: block missing 'gate' (or tool_match) must abort
        the whole migration rather than fabricate a default -- fabricating a
        default would silently change what the entry's enforcement does once
        wired to the live guard."""
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "memory", "playbooks", "git.md"), PLAYBOOK_GIT)
            write(
                os.path.join(root, "memory", "playbooks", "incomplete.md"),
                PLAYBOOK_INCOMPLETE_ENFORCE,
            )

            proc = run_migration(root)

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(os.path.isdir(os.path.join(root, "memory", "lessons")))
            # source dirs must be untouched -- fail-safe means write NOTHING.
            self.assertTrue(os.path.isdir(os.path.join(root, "memory", "playbooks")))
            self.assertTrue(
                os.path.isfile(os.path.join(root, "memory", "playbooks", "git.md")))

    def test_unrecognized_top_level_key_survives(self):
        """An unrecognized top-level frontmatter key (outside the known
        schema) must carry through to the migrated lesson verbatim -- the
        migration's binding constraint is losslessness, so unanticipated
        data must not be dropped."""
        with tempfile.TemporaryDirectory() as root:
            write(
                os.path.join(root, "memory", "playbooks", "extra.md"),
                PLAYBOOK_EXTRA_KEY,
            )

            proc = run_migration(root)

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            text = read(os.path.join(root, "memory", "lessons", "extra.md"))
            self.assertIn("custom_field: hello", text)


class TestMigrateBodies(unittest.TestCase):
    def _tree(self, root, lesson_text, episodic=None):
        write(os.path.join(root, "memory", "lessons", "git.md"), lesson_text)
        if episodic is not None:
            write(os.path.join(root, "memory", "episodic", "git.md"), episodic)

    def test_converts_failure_and_stacked_success(self):
        with tempfile.TemporaryDirectory() as root:
            src = FAIL_FM + FAIL_BODY + SUCC_FM + SUCC_BODY
            self._tree(root, src)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            lp = os.path.join(root, "memory", "lessons", "git.md")
            ep = os.path.join(root, "memory", "episodic", "git.md")
            new = read(lp)
            self.assertEqual(np_lesson_format.lint(new), [])
            self.assertIn(FAIL_FM, new)
            self.assertIn(SUCC_FM, new)
            blocks = np_lesson_format.parse(new)
            self.assertEqual(len(blocks), 2)
            r = blocks[0].rules[0]
            self.assertEqual(r.objective, "Grep combined flags dropped")
            self.assertEqual(r.dont, "Trusting combined short flags survive every wrapper")
            self.assertTrue(r.do and r.when and r.why)
            self.assertIn("working with git, grep", r.when)
            self.assertEqual(r.links, ["episodic/git"])
            self.assertIn("DON'T", r.text)
            self.assertIn("**when**", r.text)
            self.assertIn("**why**", r.text)
            s = blocks[1].rules[0]
            self.assertEqual(s.objective, "Prefer long-form grep flags in wrapped contexts")
            self.assertEqual(s.dont, "")
            epi = read(ep)
            self.assertTrue(epi.startswith("---\nname: git\nkind: episodic\n"))
            self.assertIn("last_updated: 2026-06-21", epi)
            self.assertIn("CONTINUATION-TEXT explains the wrapper", epi)
            self.assertIn("migrated evidence: Grep combined flags dropped", epi)
            self.assertIn(FAIL_BODY, epi)
            self.assertIn(SUCC_BODY, epi)
            # idempotent
            proc2 = run_bodies(root)
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
            self.assertEqual(read(lp), new)
            self.assertEqual(read(ep), epi)

    def test_existing_episodic_gets_section_after_frontmatter(self):
        with tempfile.TemporaryDirectory() as root:
            epi_src = ("---\nname: git\nkind: episodic\nlast_updated: 2026-01-01\n"
                       "wiki: []\nprojects: []\n---\n## [2026-01-01] earlier\n\nold stuff\n")
            self._tree(root, FAIL_FM + FAIL_BODY, episodic=epi_src)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            epi = read(os.path.join(root, "memory", "episodic", "git.md"))
            fm_end = epi_src.index("---\n## [2026-01-01]")
            self.assertTrue(epi.startswith(epi_src[:fm_end + 4]))
            after = epi[fm_end + 4:]
            self.assertTrue(after.startswith(
                "## [2026-06-20] lessons \u2014 migrated evidence: Grep combined flags dropped"))
            self.assertIn(FAIL_BODY, after)
            self.assertTrue(after.endswith("## [2026-01-01] earlier\n\nold stuff\n"))

    def test_already_paired_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, PAIRED)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(read(os.path.join(root, "memory", "lessons", "git.md")), PAIRED)
            self.assertFalse(os.path.exists(os.path.join(root, "memory", "episodic")))

    def test_default_mode_leaves_legacy_bodies(self):
        with tempfile.TemporaryDirectory() as root:
            src = FAIL_FM + FAIL_BODY
            self._tree(root, src)
            proc = run_migration(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(read(os.path.join(root, "memory", "lessons", "git.md")), src)
            self.assertFalse(os.path.exists(os.path.join(root, "memory", "episodic")))

    def test_missing_last_updated_falls_back_to_today(self):
        with tempfile.TemporaryDirectory() as root:
            fm = FAIL_FM.replace("last_updated: 2026-06-20\n", "")
            self._tree(root, fm + FAIL_BODY)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            epi = read(os.path.join(root, "memory", "episodic", "git.md"))
            m = re.search(r"^last_updated: (\d{4}-\d\d-\d\d)$", epi, re.M)
            self.assertTrue(m, epi)
            self.assertIn("## [%s] lessons" % m.group(1), epi)

    def test_long_fields_shortened_to_fit(self):
        with tempfile.TemporaryDirectory() as root:
            long_do = "Do " + "very long " * 60
            src = FAIL_FM + "**Symptom:** s.\n**Why:** w.\n**Do:** %s.\n" % long_do
            self._tree(root, src)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            new = read(os.path.join(root, "memory", "lessons", "git.md"))
            self.assertEqual(np_lesson_format.lint(new), [])
            self.assertIn("\u2026", new)

    # --- stacked-entry shapes found in a real overlay (bare `---` separators) ---
    def _convert(self, src):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, src)
            proc = run_bodies(root)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            new = read(os.path.join(root, "memory", "lessons", "git.md"))
            self.assertEqual(np_lesson_format.lint(new), [])
            again = run_bodies(root)
            self.assertEqual(again.returncode, 0, msg=again.stderr)
            self.assertEqual(read(os.path.join(root, "memory", "lessons", "git.md")), new)
            return new, np_lesson_format.parse(new)

    def test_bare_separator_stacks_success_entry(self):
        new, blocks = self._convert(FAIL_FM + FAIL_BODY + "\n---\n\n" + SUCC_BODY)
        self.assertEqual([b.provenance for b in blocks], ["failure", "success"])
        # enforce gates the entry that earned it only, and survives byte-for-byte.
        self.assertEqual(new.count("enforce:"), 1)
        self.assertIn('  tool_match: "grep -[a-z]*l[a-z]*i"\n  gate: ask\n', new)

    def test_bare_separator_with_partial_keys(self):
        new, blocks = self._convert(
            FAIL_FM + FAIL_BODY + "\n---\nprovenance: success\n\n" + SUCC_BODY)
        self.assertEqual([b.provenance for b in blocks], ["failure", "success"])

    def test_bare_separator_with_prose_lead_and_doubled_separator(self):
        second = ("(failure entry: another angle)\n**Symptom:** s2.\n**Why:** w2.\n"
                  "**Do:** d2.\n**Avoid:** a2.\n")
        new, blocks = self._convert(
            FAIL_FM + FAIL_BODY + "\n---\n\n---\n\n" + second)
        self.assertEqual([b.provenance for b in blocks], ["failure", "failure"])
        self.assertIn("DON'T a2", new)

    def test_shortening_keeps_every_field_readable(self):
        # Overflow larger than the longest field used to cut fields to one char.
        f = lambda n: " ".join(["word%d" % i for i in range(n)])
        src = FAIL_FM + "**Symptom:** s.\n**Why:** %s.\n**Do:** %s.\n**Avoid:** %s.\n" % (
            f(40), f(40), f(40))
        new, blocks = self._convert(src)
        r = blocks[0].rules[0]
        for part in (r.dont, r.do, r.why):
            self.assertGreater(len(part.rstrip("\u2026")), 20, part)

    def test_stacked_entry_gets_provenance_when_first_head_has_none(self):
        head = FAIL_FM.replace("provenance: failure\n", "")
        new, blocks = self._convert(head + FAIL_BODY + "\n---\n\n" + SUCC_BODY)
        self.assertEqual(blocks[1].provenance, "success")

    def test_partial_key_value_is_not_read_as_a_regex_template(self):
        new, blocks = self._convert(
            FAIL_FM + FAIL_BODY + "\n---\nprovenance: success\\1\n\n" + SUCC_BODY)
        self.assertIn("provenance: success\\1", new)

    def test_many_doubled_separators(self):
        new, blocks = self._convert(FAIL_FM + FAIL_BODY + "\n---\n" * 3000 + "\n" + SUCC_BODY)
        self.assertEqual(len(blocks), 2)


if __name__ == "__main__":
    unittest.main()
