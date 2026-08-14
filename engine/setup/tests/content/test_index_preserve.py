# np-test: content | failure
"""nervepack#241: INDEX.md regen deleted every row belonging to a layer the current
machine could not resolve, and a cron committed the deletion. Observed live: the
`team` toggle was ON with no team-dir configured, so team_dirs() returned [] in
silence and 20 dp-* rows vanished from a shared committed file.

Preservation is gated on the precise condition (an ENABLED layer that does not
resolve). With the toggle off, the regen stays fully authoritative so a genuinely
deleted skill is still pruned."""
import io
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..",
                                                 "nervepack_engine")))
import np_content        # noqa: E402
import np_generate_index  # noqa: E402


def write_skill(base, name, desc):
    d = os.path.join(base, "skills", name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: %s\ndescription: %s\n---\nbody\n" % (name, desc))


class TestIndexPreservesUnresolvableLayers(unittest.TestCase):
    def setUp(self):
        self.engine = tempfile.mkdtemp(prefix="npidx-eng-")
        self.overlay = tempfile.mkdtemp(prefix="npidx-ovl-")
        self.home = tempfile.mkdtemp(prefix="npidx-home-")
        self._saved = {k: os.environ.get(k) for k in
                       ("NP_DIR", "NP_CONTENT_DIR", "NP_TEAM_DIR", "HOME",
                        "NP_TOGGLES_CONF", "NP_TOGGLES_LOCAL")}
        os.environ["NP_DIR"] = self.engine
        os.environ["NP_CONTENT_DIR"] = self.overlay
        os.environ["HOME"] = self.home
        os.environ.pop("NP_TEAM_DIR", None)
        os.environ["NP_TOGGLES_CONF"] = os.path.join(
            os.path.normpath(os.path.join(_HERE, "..", "..")), "toggles.conf")
        self.local = os.path.join(self.home, "toggles.local")
        os.environ["NP_TOGGLES_LOCAL"] = self.local
        write_skill(self.engine, "np-core-x", "engine skill")

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for d in (self.engine, self.overlay, self.home):
            shutil.rmtree(d, ignore_errors=True)

    def _team(self, state):
        with open(self.local, "w", encoding="utf-8") as fh:
            fh.write("team=%s\n" % state)

    def _seed_index_with_team_rows(self):
        """An INDEX.md as a machine WITH the team layer would have committed it."""
        p = os.path.join(self.overlay, "INDEX.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# nervepack — skill index\n\n"
                     "| Skill | Lines | Description |\n|---|---:|---|\n"
                     "| [dp-alpha](skills/dp-alpha/SKILL.md) | 10 | team skill A |\n"
                     "| [dp-beta](skills/dp-beta/SKILL.md) | 12 | team skill B |\n"
                     "| [np-core-x](skills/np-core-x/SKILL.md) | 5 | engine skill |\n"
                     "\n## Archived skills\n\n_(none yet)_\n")
        return p

    def _regen(self):
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            np_generate_index.generate(np_dir=self.engine, out=io.StringIO())
        finally:
            sys.stderr = old
        with open(os.path.join(self.overlay, "INDEX.md"), encoding="utf-8") as fh:
            return fh.read(), err.getvalue()

    # --- the bug ------------------------------------------------------------
    def test_enabled_but_unresolvable_layer_keeps_its_rows(self):
        self._team("on")                       # toggle on, no team dir configured
        self._seed_index_with_team_rows()
        text, _err = self._regen()
        self.assertIn("dp-alpha", text)
        self.assertIn("dp-beta", text)

    def test_it_warns_when_it_preserves(self):
        self._team("on")
        self._seed_index_with_team_rows()
        _text, err = self._regen()
        self.assertIn("team", err.lower())
        self.assertIn("preserv", err.lower())

    def test_locally_resolvable_rows_are_still_regenerated(self):
        self._team("on")
        self._seed_index_with_team_rows()
        write_skill(self.overlay, "np-kb-new", "a new local skill")
        text, _err = self._regen()
        self.assertIn("np-kb-new", text)
        self.assertIn("dp-alpha", text)

    # --- the guard against over-correcting ----------------------------------
    def test_toggle_off_still_prunes_a_removed_skill(self):
        self._team("off")
        self._seed_index_with_team_rows()
        text, err = self._regen()
        self.assertNotIn("dp-alpha", text)     # authoritative regen, as today
        self.assertEqual(err, "")

    def test_resolvable_team_layer_does_not_trigger_preservation(self):
        team = tempfile.mkdtemp(prefix="npidx-team-")
        self.addCleanup(shutil.rmtree, team, True)
        write_skill(team, "dp-alpha", "team skill A")
        os.environ["NP_TEAM_DIR"] = team
        self._team("on")
        self._seed_index_with_team_rows()
        text, err = self._regen()
        self.assertIn("dp-alpha", text)        # from the real layer
        self.assertNotIn("dp-beta", text)      # genuinely gone from that layer
        self.assertEqual(err, "")

    def test_no_seed_file_is_not_an_error(self):
        self._team("on")
        text, _err = self._regen()
        self.assertIn("np-core-x", text)

    # --- the resolver helper ------------------------------------------------
    def test_unresolved_layers_reports_the_enabled_missing_layer(self):
        self._team("on")
        self.assertIn("team", np_content.unresolved_layers().lower())

    def test_unresolved_layers_empty_when_toggle_off(self):
        self._team("off")
        self.assertEqual(np_content.unresolved_layers(), "")

    def test_unresolved_layers_empty_when_layer_resolves(self):
        team = tempfile.mkdtemp(prefix="npidx-team-")
        self.addCleanup(shutil.rmtree, team, True)
        os.environ["NP_TEAM_DIR"] = team
        self._team("on")
        self.assertEqual(np_content.unresolved_layers(), "")

    def test_link_skills_the_unattended_path_also_preserves(self):
        # link-skills is what actually caused the incident: it runs automatically on
        # every sync fast-forward, so nobody is watching when it rewrites INDEX.md.
        import np_link_skills
        self._team("on")
        self._seed_index_with_team_rows()
        os.environ["NP_SKILLS_DST"] = os.path.join(self.home, ".claude", "skills")
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            np_link_skills.link(np_dir=self.engine, out=io.StringIO())
        finally:
            sys.stderr = old
        with open(os.path.join(self.overlay, "INDEX.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("dp-alpha", text)
        self.assertIn("preserv", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
