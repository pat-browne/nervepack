#!/usr/bin/env python3
# np-test: docs | failure
"""The change-spec id is the stable handle, and change-specs/README.md states the
rule: "Sequential, never reused. Zero-padded 4 digits."

Nothing enforced it, and two pairs collided (#312). A duplicate breaks the status
lifecycle, because `superseded by <NNNN>` names another spec by id and cannot say
which of two it means. It also breaks the sequential property that lets a reader
tell ordering from the number.

Repo-wide invariants, not diff-scoped, which is why this lives here rather than in
np-spec-guard.py: that gate reads only the files a pull request touched, so it can
never see a collision between two specs neither of which is in the diff.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
SPECS = os.path.join(REPO, "change-specs")
ID = re.compile(r"^id:\s*(\S+)\s*$", re.M)


def _specs():
    if not os.path.isdir(SPECS):
        return []
    return sorted(n for n in os.listdir(SPECS)
                  if n.endswith(".md") and n not in ("README.md", "TEMPLATE.md"))


class TestChangeSpecIds(unittest.TestCase):
    def _ids(self):
        out = {}
        for name in _specs():
            with open(os.path.join(SPECS, name), encoding="utf-8") as fh:
                match = ID.search(fh.read())
            out[name] = match.group(1) if match else None
        return out

    def test_there_are_specs_to_check(self):
        """A guard that silently matches nothing reads as a pass."""
        self.assertTrue(_specs(), "no change specs found at %s" % SPECS)

    def test_every_spec_declares_an_id(self):
        missing = sorted(n for n, i in self._ids().items() if not i)
        self.assertEqual(missing, [], "change specs with no `id:` front-matter field")

    def test_every_id_is_four_digits(self):
        bad = sorted("%s (%s)" % (n, i) for n, i in self._ids().items()
                     if i and not re.fullmatch(r"\d{4}", i))
        self.assertEqual(bad, [], "ids must be zero-padded 4 digits")

    def test_no_two_specs_share_an_id(self):
        seen = {}
        for name, spec_id in sorted(self._ids().items()):
            if spec_id:
                seen.setdefault(spec_id, []).append(name)
        clashes = ["%s: %s" % (i, ", ".join(f)) for i, f in sorted(seen.items()) if len(f) > 1]
        self.assertEqual(clashes, [],
                         "duplicate change-spec ids — renumber the later one and "
                         "update any inbound reference:\n  " + "\n  ".join(clashes))


if __name__ == "__main__":
    unittest.main()
