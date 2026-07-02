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
name: git
kind: playbook
status: candidate
seen: 4
last_updated: 2026-06-20
enforce:
  tool_match: "grep -[a-z]*l[a-z]*i"
  gate: ask
  topic_triggers: [git]
wiki: []
---
**Symptom:** `grep -li` flags get silently reordered/dropped by a wrapping tool.
**Why:** Some shells alias grep in ways that eat combined short flags.
**Do:** Spell out `grep --files-with-matches --ignore-case` instead of `-li`.
**Avoid:** Trusting combined short flags survive every wrapper.
"""

STRATEGY_GIT = """---
name: git
kind: strategy
status: candidate
seen: 2
last_updated: 2026-06-21
topic_triggers: [git]
wiki: []
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


if __name__ == "__main__":
    unittest.main()
