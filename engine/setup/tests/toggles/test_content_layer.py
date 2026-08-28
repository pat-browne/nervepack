#!/usr/bin/env python3
"""Unit tests for the content-overlay toggle layer (spec 0021).

Precedence under test, highest first:

    ~/.config/nervepack/toggles.local   (per machine, untracked)
    <content_dir>/config/toggles.conf   (personal, synced across machines)
    engine/setup/toggles.conf           (shipped defaults, shared with forkers)

The middle layer is the one this change adds. It exists so a preference can be
both portable and personal: the local file is portable to nothing, and the
engine file is personal to nobody.

Hermetic. Every path comes from an env override, so no test reads the real
config of the machine it runs on.
"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
# np_content lives beside np_toggle in nervepack_engine, and the lazy import in
# _content_conf_path resolves against sys.path the same way cli.py sets it up.
ENGINE = os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine"))
for _p in (SETUP, ENGINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_np_toggle():
    spec = importlib.util.spec_from_file_location(
        "np_toggle", os.path.join(SETUP, "..", "nervepack_engine", "np_toggle.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


np_toggle = _load_np_toggle()

ENGINE_CONF = (
    "# comment row\n"
    "turn_gate|shared|runtime|on|ui=block,diff=warn,form=warn,form_threshold=2.5\n"
    "form_gate|shared|runtime|on|categorical=warn,rate=warn,timeout_s=5\n"
    "focus|shared|runtime|off|\n"
)

# A partial row. It names two params and omits the rest on purpose: the engine
# row must still supply everything the content row does not mention.
CONTENT_CONF = (
    "turn_gate|shared|runtime|on|form=block,form_threshold=2.0\n"
    "focus|shared|runtime|on|\n"
)


class ContentLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.engine = os.path.join(d, "toggles.conf")
        self.content = os.path.join(d, "content-toggles.conf")
        self.local = os.path.join(d, "toggles.local")
        with open(self.engine, "w") as fh:
            fh.write(ENGINE_CONF)
        self._env = {}
        self._set("NP_TOGGLES_CONF", self.engine)
        self._set("NP_TOGGLES_LOCAL", self.local)
        self._set("NP_TOGGLES_CONTENT", "")      # explicit "no content layer"

    def _set(self, key, value):
        if key not in self._env:
            self._env[key] = os.environ.get(key)
            self.addCleanup(self._restore, key)
        os.environ[key] = value

    def _restore(self, key):
        prior = self._env.get(key)
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior

    def _write_content(self, text=CONTENT_CONF):
        with open(self.content, "w") as fh:
            fh.write(text)
        self._set("NP_TOGGLES_CONTENT", self.content)

    # --- no content layer: today's behavior, unchanged --------------------
    def test_absent_content_layer_resolves_from_engine(self):
        self.assertEqual(np_toggle.param("turn_gate.form", "x"), "warn")
        self.assertTrue(np_toggle.enabled("turn_gate"))
        self.assertFalse(np_toggle.enabled("focus"))

    def test_content_path_set_but_file_missing_is_not_an_error(self):
        self._set("NP_TOGGLES_CONTENT", os.path.join(self.tmp.name, "nope.conf"))
        self.assertEqual(np_toggle.param("turn_gate.form", "x"), "warn")

    # --- content layer overrides the engine -------------------------------
    def test_content_param_beats_engine_param(self):
        self._write_content()
        self.assertEqual(np_toggle.param("turn_gate.form", "x"), "block")

    def test_engine_supplies_params_the_content_row_omits(self):
        """The partial-row property. Without it the content file would have to
        restate every param of a family to change one of them, and would then
        silently freeze the others at whatever the engine shipped that day."""
        self._write_content()
        self.assertEqual(np_toggle.param("turn_gate.ui", "x"), "block")
        self.assertEqual(np_toggle.param("turn_gate.diff", "x"), "warn")
        self.assertEqual(np_toggle.param("turn_gate.form_threshold", "x"), "2.0")

    def test_content_state_beats_engine_state(self):
        self._write_content()
        self.assertTrue(np_toggle.enabled("focus"))

    def test_family_absent_from_content_still_resolves(self):
        self._write_content()
        self.assertEqual(np_toggle.param("form_gate.categorical", "x"), "warn")

    # --- local still wins -------------------------------------------------
    def test_local_beats_content(self):
        self._write_content()
        with open(self.local, "w") as fh:
            fh.write("turn_gate.form=off\n")
        self.assertEqual(np_toggle.param("turn_gate.form", "x"), "off")

    def test_local_state_beats_content_state(self):
        self._write_content()
        with open(self.local, "w") as fh:
            fh.write("focus=off\n")
        self.assertFalse(np_toggle.enabled("focus"))

    # --- surfaces that render the whole picture ---------------------------
    def test_features_are_not_duplicated_across_layers(self):
        self._write_content()
        feats = np_toggle.features()
        self.assertEqual(feats.count("turn_gate"), 1)
        self.assertEqual(feats.count("focus"), 1)
        self.assertIn("form_gate", feats)

    def test_all_params_merges_layers_with_content_winning(self):
        """all_params renders a dashboard panel. If it took only the first
        matching row it would show a partial content row as the whole truth."""
        self._write_content()
        params = np_toggle.all_params("turn_gate")
        self.assertEqual(params.get("form"), "block")
        self.assertEqual(params.get("form_threshold"), "2.0")
        self.assertEqual(params.get("ui"), "block")
        self.assertEqual(params.get("diff"), "warn")

    def test_all_params_local_override_still_applies(self):
        self._write_content()
        with open(self.local, "w") as fh:
            fh.write("turn_gate.ui=warn\n")
        self.assertEqual(np_toggle.all_params("turn_gate").get("ui"), "warn")

    def test_scope_prefers_the_content_row(self):
        self._write_content("turn_gate|local|runtime|on|form=block\n")
        self.assertEqual(np_toggle.scope("turn_gate"), "local")


class ContentLayerReentrancyTest(unittest.TestCase):
    """The latch in _content_conf_path.

    content_dir() does not read a toggle today. If it ever does, every param()
    call would recurse until the stack died, and the symptom (a hook that
    silently dies mid-session) points nowhere near the cause.
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "config"))
        with open(os.path.join(self.tmp.name, "config", "toggles.conf"), "w") as fh:
            fh.write("focus|shared|runtime|off|\n")
        for key, value in (("NP_CONTENT_DIR", self.tmp.name),
                           ("NP_TOGGLES_LOCAL", os.path.join(self.tmp.name, "none"))):
            prior = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(
                lambda k=key, p=prior: os.environ.__setitem__(k, p)
                if p is not None else os.environ.pop(k, None))
        prior = os.environ.pop("NP_TOGGLES_CONTENT", None)
        if prior is not None:
            self.addCleanup(os.environ.__setitem__, "NP_TOGGLES_CONTENT", prior)

    def test_layer_resolves_through_the_real_content_resolver(self):
        """Not just through the env override the other tests use."""
        self.assertFalse(np_toggle.enabled("focus"))

    def test_a_toggle_read_inside_content_dir_does_not_recurse(self):
        import np_content
        original = np_content.content_dir

        def chatty():
            np_toggle.param("team.merge", "override")
            return original()

        np_content.content_dir = chatty
        self.addCleanup(setattr, np_content, "content_dir", original)
        self.assertFalse(np_toggle.enabled("focus"))

    def test_the_latch_is_released_after_a_failed_lookup(self):
        import np_content
        original = np_content.content_dir
        np_content.content_dir = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, np_content, "content_dir", original)
        np_toggle.enabled("focus")                       # swallows the error
        np_content.content_dir = original
        self.assertFalse(np_toggle.enabled("focus"))     # layer works again


if __name__ == "__main__":
    unittest.main()
