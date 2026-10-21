#!/usr/bin/env python3
"""Effectiveness tests for the paired-rule lesson format (change spec 0093).

Compares the CURRENT lesson shape (Symptom/Why/Do/Avoid, Title/When/Do bodies)
against the proposed paired-rule shape:

    - DON'T <x> → DO <y> — **when** <scope> — **why** <reason>. [[episodic/<t>]]

Three groups:

1. Baseline (passes today): measures what the current recall injects for a
   representative legacy lesson, so the comparison below has a fixed reference.
2. Recall against the current implementation (expectedFailure today): the
   current lesson_recall only keeps lines starting with a bold **Header:**, so a
   paired-rule line is silently dropped and only an empty "[topic]" tag is
   injected. These flip to unexpected-success once
   recall learns the format, which fails the suite and forces removing the
   decorator in the implementing change.
3. Format lint (skipped until engine/setup/np_lesson_format.py exists): the
   rules the distiller must satisfy -- every rule carries when + why, a lone
   DON'T is flagged, an entry stays within the two-line budget.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_FORMAT_MOD = os.path.join(_ENGINE_SETUP, "np_lesson_format.py")
_HAS_FORMAT = os.path.isfile(_FORMAT_MOD)

INDEX = ("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
         "| git-shared-tree |  | warn | git add, commit |\n")

# The same knowledge, written both ways.
LEGACY = """---
name: git-shared-tree
kind: lesson
provenance: failure
topic_triggers: git add, commit
seen: 3
---
**Symptom:** A cron's commit picked up files another session had staged, and the
metrics commit ended up carrying unrelated WIP under a misleading subject. It took
a reflog dig to work out which session owned which hunk.
**Why:** A bare `git commit` commits the whole shared index, and `git add -A` stages
every untracked file in the single working tree, including other sessions' work.
**Do:** Stage and commit explicit paths with `git commit -m "..." -- <paths>`.
**Avoid:** `git add -A`, `git add .`, `git commit -am`, or a pathspec-less commit.
"""

PAIRED = """---
name: git-shared-tree
kind: lesson
provenance: failure
topic_triggers: git add, commit
seen: 3
---
## Committing in a shared tree
- DON'T `git add -A` / bare `git commit` → DO `git commit -m "..." -- <paths>` — **when** another session or cron may share the tree — **why** it sweeps their staged work into your commit. [[episodic/nervepack-git]]
"""


class _RecallFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lessons = os.path.join(self.tmp, "lessons")
        os.makedirs(self.lessons)
        conf = os.path.join(self.tmp, "toggles.conf")
        with open(conf, "w") as fh:
            fh.write("lessons|shared|runtime|on|\npii_filter|shared|runtime|off|\n")
        env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
            "EPISODIC_LESSON_DIR": self.lessons,
            "EPISODIC_STATE_DIR": os.path.join(self.tmp, "state"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def recall(self, body, sid="s1"):
        with open(os.path.join(self.lessons, "INDEX.md"), "w", encoding="utf-8") as fh:
            fh.write(INDEX)
        with open(os.path.join(self.lessons, "git-shared-tree.md"), "w", encoding="utf-8") as fh:
            fh.write(body)
        from nervepack_engine.hooks import lesson_recall
        out = lesson_recall.run(json.dumps({"session_id": sid, "prompt": "git add then commit"}),
                                pii_filter_fn=lambda t: t)
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]


class TestBaseline(_RecallFixture):
    def test_legacy_lesson_is_recalled(self):
        ctx = self.recall(LEGACY)
        self.assertIn("git commit", ctx)
        self.assertIn("Avoid", ctx)

    def test_legacy_injects_narrative_but_truncates_wrapped_fields(self):
        # Current behavior: the Symptom story's first line is injected on every
        # matching prompt, while its wrapped continuation lines are dropped --
        # the field arrives cut mid-sentence. The paired format has no wrapped
        # fields to lose.
        ctx = self.recall(LEGACY)
        self.assertIn("A cron's commit picked up", ctx)
        self.assertNotIn("reflog dig", ctx)


class TestPairedRecallAgainstCurrent(_RecallFixture):
    def test_paired_rule_is_recalled(self):
        # Current recall keeps only **Header:** lines, so this comes back empty.
        ctx = self.recall(PAIRED)
        self.assertIn("DON'T `git add -A`", ctx)
        self.assertIn("**when**", ctx)
        self.assertIn("**why**", ctx)

    def test_paired_injection_is_at_most_half_the_legacy_size(self):
        legacy = self.recall(LEGACY, sid="a")
        paired = self.recall(PAIRED, sid="b")
        self.assertIn("DON'T", paired, "paired rule was not injected")
        self.assertLessEqual(len(paired), len(legacy) // 2)

    def test_paired_injection_omits_the_narrative(self):
        # Today a paired-format file injects only an empty "[topic]" tag.
        ctx = self.recall(PAIRED)
        self.assertIn("DON'T", ctx)
        self.assertNotIn("A cron's commit picked up", ctx)


def _load_format():
    spec = importlib.util.spec_from_file_location("np_lesson_format", _FORMAT_MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(_HAS_FORMAT, "np_lesson_format.py not implemented yet (spec 0093)")
class TestFormatLint(unittest.TestCase):
    def setUp(self):
        self.fmt = _load_format()

    def codes(self, text):
        return {p.code for p in self.fmt.lint(text)}

    def test_paired_rule_is_clean(self):
        self.assertEqual(self.codes(PAIRED), set())

    def test_missing_when_is_flagged(self):
        bad = PAIRED.replace(" — **when** another session or cron may share the tree", "")
        self.assertIn("missing-when", self.codes(bad))

    def test_missing_why_is_flagged(self):
        bad = PAIRED.replace(" — **why** it sweeps their staged work into your commit", "")
        self.assertIn("missing-why", self.codes(bad))

    def test_lone_dont_is_flagged(self):
        bad = PAIRED.replace(' → DO `git commit -m "..." -- <paths>`', "")
        self.assertIn("lone-dont", self.codes(bad))

    def test_lone_do_is_allowed(self):
        ok = PAIRED.replace('DON\'T `git add -A` / bare `git commit` → ', "")
        self.assertNotIn("lone-dont", self.codes(ok))

    def test_overlong_entry_is_flagged(self):
        long_rule = PAIRED.rstrip("\n") + " " + ("narrative " * 60) + "\n"
        self.assertIn("too-long", self.codes(long_rule))

    def test_legacy_body_is_flagged_for_migration(self):
        self.assertIn("legacy-format", self.codes(LEGACY))


if __name__ == "__main__":
    unittest.main()
