"""Static guards: the Models section lives in the settings modal, and model-row
links (banner, hash) open that modal instead of scrolling the main page."""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "dashboard", "index.html"))


class TestModelsInSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()

    def _overlay(self):
        start = self.html.index('id="settings-overlay"')
        end = self.html.index("<script", start)
        return self.html[start:end]

    def _main(self):
        return self.html[self.html.index('<main class="content">'):self.html.index("</main>")]

    def test_models_section_is_inside_settings_modal(self):
        overlay = self._overlay()
        self.assertIn('id="panel-models"', overlay)
        self.assertIn('id="panel-toggles"', overlay)
        self.assertNotIn('id="panel-models"', self._main())

    def test_modal_title_and_cog_cover_both_sections(self):
        overlay = self._overlay()
        self.assertRegex(overlay, r'id="settings-title">Settings<')
        self.assertIn(">Feature toggles<", overlay)
        cog = re.search(r'<button[^>]*id="btn-settings"[^>]*>', self.html, re.S).group(0)
        self.assertIn("models", cog.lower())
        self.assertIn("toggles", cog.lower())

    def test_banner_stays_on_main_page(self):
        self.assertIn('id="model-banner"', self._main())

    def test_model_row_links_and_hash_open_the_modal(self):
        self.assertIn("async function openModelRow(hash)", self.html)
        self.assertIn('closest(\'a[href^="#model-row-"]\')', self.html)
        self.assertIn('if (location.hash.startsWith("#model-row-")) openModelRow(location.hash);', self.html)
        open_fn = self.html[self.html.index("function openSettings()"):]
        self.assertIn("refreshModels()", open_fn[:200])

    def test_models_family_params_have_one_editor(self):
        self.assertIn('fam.feature === "models"', self.html)

    def test_help_tooltip_is_clamped_to_viewport(self):
        self.assertIn('id="tiptip"', self.html)
        self.assertIn("window.innerWidth - t.width - m", self.html)
        self.assertNotIn(".tighelp::after", self.html)


class TestToggleDescriptions(unittest.TestCase):
    """Every family, sub-toggle and param the settings UI shows needs help text.
    models.* params are edited in the Models section, not the toggle list."""

    def test_every_toggle_and_param_has_a_description(self):
        setup = os.path.normpath(os.path.join(HERE, "..", ".."))
        with open(os.path.join(setup, "toggle-schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        missing = []
        with open(os.path.join(setup, "toggles.conf"), encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                feat, _scope, _enf, _state, params = line.rstrip("\n").split("|")
                keys = [feat]
                if feat != "models":
                    keys += [feat + "." + kv.split("=")[0] for kv in params.split(",") if kv]
                missing += [k for k in keys if not (schema.get(k) or {}).get("description", "").strip()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
