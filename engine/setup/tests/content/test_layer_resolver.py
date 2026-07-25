"""In-process coverage for the layer stack — the cases the retired bash test
tests/content/test_layer_lib.sh held (phase 18).

Ports every assertion of test_layer_lib.sh 1:1, driving
np_content.content_layers() / merge_mode() / merge_roots() / layer_roots()
(and layer_dir(), its single-root sibling) in-process against a hermetic
NP_CONTENT_DIR / NP_TEAM_DIR / toggles env (native tempfile paths, so
host-agnostic — no bash mktemp / MSYS, no comma-list dialect trap). This is
the content-overlay merge coverage that used to reach Python only through the
now-deleted A/B parity test: no-team, team + toggle on, team-only, invalid
mode -> override, toggle-off drops team, and multi-team ordering.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import np_content  # noqa: E402


class TestLayerResolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.personal = os.path.join(self.tmp, "personal")
        self.team = os.path.join(self.tmp, "team")
        self.teamB = os.path.join(self.tmp, "teamB")
        self.teamC = os.path.join(self.tmp, "teamC")
        for d in (self.personal, self.team, self.teamB, self.teamC):
            os.makedirs(d)
        self.conf = os.path.join(self.tmp, "toggles.conf")   # empty -> team default-on
        self.local = os.path.join(self.tmp, "local")
        open(self.conf, "w").close()
        open(self.local, "w").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self, team_dir=None):
        env = {
            "HOME": self.tmp,
            "NP_CONTENT_DIR": self.personal,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
        }
        if team_dir is not None:
            env["NP_TEAM_DIR"] = team_dir
        return mock.patch.dict(os.environ, env, clear=True)

    def _write_local(self, text):
        with open(self.local, "w") as fh:
            fh.write(text)

    # --- no team -> layers = [personal]; override; roots = [personal] -------
    def test_no_team_layers(self):
        with self._env():
            self.assertEqual(np_content.content_layers(), [self.personal])

    def test_no_team_default_mode_override(self):
        with self._env():
            self.assertEqual(np_content.merge_mode(), "override")

    def test_no_team_merge_roots(self):
        with self._env():
            self.assertEqual(np_content.merge_roots(), [self.personal])

    # --- team configured + toggle on (default) -> team then personal --------
    def test_team_on_layers(self):
        with self._env(team_dir=self.team):
            self.assertEqual(np_content.content_layers(), [self.team, self.personal])

    # --- team-only mode -> roots = team only --------------------------------
    def test_team_only_mode_and_roots(self):
        with self._env(team_dir=self.team):
            self._write_local("team=on\nteam.merge=team-only\n")
            self.assertEqual(np_content.merge_mode(), "team-only")
            self.assertEqual(np_content.merge_roots(), [self.team])

    # --- invalid mode -> override -------------------------------------------
    def test_invalid_mode_falls_back_to_override(self):
        with self._env(team_dir=self.team):
            self._write_local("team.merge=bogus\n")
            self.assertEqual(np_content.merge_mode(), "override")

    # --- team toggle OFF -> team dropped even though NP_TEAM_DIR set ---------
    def test_toggle_off_drops_team(self):
        with self._env(team_dir=self.team):
            self._write_local("team=off\n")
            self.assertEqual(np_content.content_layers(), [self.personal])

    # --- layer_roots maps each merge root to memory/<layer> -----------------
    def test_layer_roots_maps_to_memory_layer(self):
        ov = os.path.join(self.tmp, "layer-ov")
        os.makedirs(ov)
        env = {
            "HOME": self.tmp,
            "NP_CONTENT_DIR": ov,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(np_content.layer_roots("playbooks"),
                             [os.path.join(ov, "memory", "playbooks")])

    # --- layer_dir is the single-root form ----------------------------------
    def test_layer_dir_single_root(self):
        ov = os.path.join(self.tmp, "layer-ov2")
        os.makedirs(ov)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": ov,
                                          "NP_TOGGLES_CONF": self.conf,
                                          "NP_TOGGLES_LOCAL": self.local}, clear=True):
            self.assertEqual(np_content.layer_dir("strategies"),
                             os.path.join(ov, "memory", "strategies"))

    # --- multi-team stack ----------------------------------------------------
    def test_multi_team_layers_ordering(self):
        teams = "%s,%s,%s" % (self.team, self.teamB, self.teamC)
        with self._env(team_dir=teams):
            self._write_local("team=on\n")
            self.assertEqual(np_content.content_layers(),
                             [self.team, self.teamB, self.teamC, self.personal])

    def test_multi_team_team_only_roots(self):
        teams = "%s,%s,%s" % (self.team, self.teamB, self.teamC)
        with self._env(team_dir=teams):
            self._write_local("team=on\nteam.merge=team-only\n")
            self.assertEqual(np_content.merge_roots(),
                             [self.team, self.teamB, self.teamC])


if __name__ == "__main__":
    unittest.main()
