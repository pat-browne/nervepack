"""np_global_config: overlay rules and settings projected onto the host."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _SETUP)
sys.path.insert(0, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine")))

import np_global_config as gc  # noqa: E402
import np_instruction_block as ib  # noqa: E402

RULES = "# Rules\n\n- Be concise.\n"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        d = self._d.name
        self.overlay = os.path.join(d, "overlay")
        self.claude_dir = os.path.join(d, "home", ".claude")
        self.settings = os.path.join(self.claude_dir, "settings.json")
        self.claude_md = os.path.join(self.claude_dir, "CLAUDE.md")
        self.agents_md = os.path.join(d, "other", "AGENTS.md")
        os.makedirs(self.claude_dir)
        env = {
            "HOME": os.path.join(d, "home"),
            "NP_CONTENT_DIR": self.overlay,
            "CLAUDE_SETTINGS": self.settings,
            "NP_GLOBAL_RULES_TARGETS": os.pathsep.join([self.claude_md, self.agents_md]),
            "XDG_CACHE_HOME": os.path.join(d, "cache"),
            "XDG_CONFIG_HOME": os.path.join(d, "config"),
            "NP_TOGGLES_CONF": os.path.join(d, "toggles.conf"),
            "NP_TOGGLES_LOCAL": os.path.join(d, "toggles.local"),
            "NP_TOGGLES_CONTENT": "",
            "NP_ADAPTER": os.path.join(d, "no-adapter.json"),
            "NP_TRUSTED_MARKETPLACES": os.path.join(d, "config", "trusted-marketplaces"),
        }
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        _write(os.environ["NP_TOGGLES_CONF"], "global-config|local|managed|on|\n")

    def cfg(self, rules=RULES, settings=None):
        if rules is not None:
            _write(os.path.join(self.overlay, "config", "global-rules.md"), rules)
        if settings is not None:
            _write(os.path.join(self.overlay, "config", "host-settings.json"),
                   json.dumps(settings))

    def apply(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            gc.apply(out)
        return out.getvalue(), err.getvalue()

    def host_settings(self):
        if not os.path.exists(self.settings):
            return {}
        return json.loads(_read(self.settings))


class Rules(Base):
    def test_block_written_to_every_target(self):
        self.cfg()
        self.apply()
        for f in (self.claude_md, self.agents_md):
            self.assertEqual(ib.read_tagged(f, gc.TAG), RULES.strip())

    def test_user_text_kept_and_rerun_is_byte_identical(self):
        self.cfg()
        _write(self.claude_md, "# Mine\n\nkeep me\n")
        self.apply()
        first = _read(self.claude_md)
        self.assertTrue(first.startswith("# Mine\n\nkeep me\n"))
        out, _ = self.apply()
        self.assertEqual(_read(self.claude_md), first)
        self.assertIn("unchanged", out)

    def test_changed_rules_update_in_place(self):
        self.cfg()
        self.apply()
        self.cfg(rules="# Rules\n\n- Be brief.\n")
        out, _ = self.apply()
        self.assertIn("updated", out)
        self.assertEqual(_read(self.claude_md).count("nervepack:global-rules:begin"), 1)

    def test_directive_block_is_not_disturbed(self):
        _write(self.agents_md, "")
        ib.install(self.agents_md, directive_path="/x/directive.md")
        self.cfg()
        self.apply()
        text = _read(self.agents_md)
        self.assertIn("@/x/directive.md", text)
        self.assertIn(RULES.strip(), text)

    def test_no_overlay_files_does_nothing(self):
        out, _ = self.apply()
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.claude_md))
        self.assertFalse(os.path.exists(self.settings))


class Settings(Base):
    def test_listed_keys_merge_and_others_survive(self):
        _write(self.settings, json.dumps({
            "hooks": {"Stop": []}, "permissions": {"allow": ["Bash(ls)"]},
            "env": {"A": "1"}, "model": "x", "theme": "light",
            "enabledPlugins": {"local@m": True},
            "extraKnownMarketplaces": {"m": {"source": {"source": "github", "repo": "a/m"}}}}))
        self.cfg(rules=None, settings={
            "theme": "dark", "skipWorkflowUsageWarning": True,
            "enabledPlugins": {"p@m": True}})
        self.apply()
        s = self.host_settings()
        self.assertEqual(s["theme"], "dark")
        self.assertTrue(s["skipWorkflowUsageWarning"])
        self.assertEqual(s["enabledPlugins"], {"local@m": True, "p@m": True})
        self.assertEqual(s["hooks"], {"Stop": []})
        self.assertEqual(s["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(s["env"], {"A": "1"})
        self.assertEqual(s["model"], "x")

    def test_rerun_does_not_rewrite_settings(self):
        self.cfg(rules=None, settings={"theme": "dark"})
        self.apply()
        before = os.stat(self.settings).st_mtime_ns
        out, _ = self.apply()
        self.assertIn("unchanged", out)
        self.assertEqual(os.stat(self.settings).st_mtime_ns, before)

    def test_protected_unlisted_and_secret_keys_refused(self):
        self.cfg(rules=None, settings={
            "theme": "dark", "hooks": {"Stop": []}, "env": {"A": "1"},
            "permissions": {}, "model": "x",
            "apiKeyHelper": "x", "allowlist": ["apiKeyHelper", "hooks", "mcpToken"],
            "mcpToken": "t",
            "extraKnownMarketplaces": {"m": {"source": {"apiKey": "s"}}}})
        _, err = self.apply()
        self.assertEqual(self.host_settings(), {"theme": "dark"})
        for word in ("hooks", "env", "permissions", "model", "apiKeyHelper",
                     "mcpToken", "extraKnownMarketplaces"):
            self.assertIn(word, err)

    def test_allowlist_extends_the_key_set(self):
        self.cfg(rules=None, settings={"model": "m1", "allowlist": ["model"]})
        self.apply()
        self.assertEqual(self.host_settings(), {"model": "m1"})

    def test_malformed_host_settings_left_untouched(self):
        _write(self.settings, "{not json")
        self.cfg(rules=None, settings={"theme": "dark"})
        _, err = self.apply()
        self.assertEqual(_read(self.settings), "{not json")
        self.assertIn("left untouched", err)

    def test_secret_name_matcher(self):
        for bad in ("apiKey", "API_KEY", "authToken", "clientSecret", "password", "key"):
            self.assertTrue(gc.is_secret_name(bad), bad)
        for ok in ("enabledPlugins", "monkey-tools@m", "theme", "keyboard"):
            self.assertFalse(gc.is_secret_name(ok), ok)


MARKET = {"mk": {"source": {"source": "github", "repo": "acme/market"}}}
LINE = "github:acme/market"


class Trust(Base):
    def trust(self, text):
        _write(os.environ["NP_TRUSTED_MARKETPLACES"], text)

    def test_untrusted_marketplace_and_plugin_skipped_theme_kept(self):
        self.cfg(rules=None, settings={
            "theme": "dark", "extraKnownMarketplaces": MARKET,
            "enabledPlugins": {"p@mk": True}})
        _, err = self.apply()
        self.assertEqual(self.host_settings(), {"theme": "dark"})
        self.assertIn("add '%s'" % LINE, err)
        self.assertIn("plugin p@mk", err)

    def test_trusted_source_line_applies_marketplace_and_plugin(self):
        self.trust("# mine\n%s\n" % LINE)
        self.cfg(rules=None, settings={
            "extraKnownMarketplaces": MARKET, "enabledPlugins": {"p@mk": True}})
        self.apply()
        s = self.host_settings()
        self.assertEqual(s["extraKnownMarketplaces"], MARKET)
        self.assertEqual(s["enabledPlugins"], {"p@mk": True})

    def test_bare_value_or_name_does_not_trust(self):
        self.trust("acme/market\nmk\n")
        self.cfg(rules=None, settings={"extraKnownMarketplaces": MARKET})
        self.apply()
        self.assertNotIn("extraKnownMarketplaces", self.host_settings())

    def test_same_value_with_a_different_kind_is_skipped(self):
        self.trust(LINE + "\n")
        other = {"mk": {"source": {"source": "url", "url": "acme/market"}}}
        self.cfg(rules=None, settings={"extraKnownMarketplaces": other})
        self.apply()
        self.assertNotIn("extraKnownMarketplaces", self.host_settings())

    def test_same_name_with_a_different_repo_is_skipped(self):
        self.trust(LINE + "\n")
        other = {"mk": {"source": {"source": "github", "repo": "evil/market"}}}
        self.cfg(rules=None, settings={"extraKnownMarketplaces": other})
        self.apply()
        self.assertNotIn("extraKnownMarketplaces", self.host_settings())

    def test_extra_field_source_needs_the_full_json_line(self):
        src = {"source": "github", "repo": "acme/market", "ref": "evil"}
        entry = {"mk": {"source": src}}
        self.cfg(rules=None, settings={"extraKnownMarketplaces": entry})
        self.trust(LINE + "\n")
        self.apply()
        self.assertNotIn("extraKnownMarketplaces", self.host_settings())
        self.trust(json.dumps(src, sort_keys=True) + "\n")
        self.apply()
        self.assertEqual(self.host_settings()["extraKnownMarketplaces"], entry)

    def test_repo_and_url_together_is_rejected_and_reported(self):
        src = {"source": "github", "repo": "acme/market", "url": "https://x/y"}
        self.trust(LINE + "\n" + json.dumps(src, sort_keys=True) + "\n")
        self.cfg(rules=None, settings={"extraKnownMarketplaces": {"mk": {"source": src}}})
        _, err = self.apply()
        self.assertNotIn("extraKnownMarketplaces", self.host_settings())
        self.assertIn("rejected", err)
        self.assertIn("rejected", gc.doctor_status())

    def test_plugin_from_untrusted_marketplace_skipped_when_another_is_trusted(self):
        self.trust(LINE + "\n")
        other = {"source": {"source": "github", "repo": "evil/market"}}
        self.cfg(rules=None, settings={
            "extraKnownMarketplaces": dict(MARKET, bad=other),
            "enabledPlugins": {"p@mk": True, "q@bad": True}})
        _, err = self.apply()
        s = self.host_settings()
        self.assertEqual(list(s["extraKnownMarketplaces"]), ["mk"])
        self.assertEqual(s["enabledPlugins"], {"p@mk": True})
        self.assertIn("github:evil/market", err)

    def test_local_marketplace_with_same_source_is_trusted(self):
        _write(self.settings, json.dumps({"extraKnownMarketplaces": MARKET}))
        self.cfg(rules=None, settings={"enabledPlugins": {"p@mk": True}})
        self.apply()
        self.assertEqual(self.host_settings()["enabledPlugins"], {"p@mk": True})

    def test_overlay_cannot_swap_the_source_of_a_local_marketplace(self):
        _write(self.settings, json.dumps({"extraKnownMarketplaces": MARKET}))
        swapped = {"mk": {"source": {"source": "github", "repo": "evil/market"}}}
        self.cfg(rules=None, settings={"extraKnownMarketplaces": swapped})
        self.apply()
        self.assertEqual(self.host_settings()["extraKnownMarketplaces"], MARKET)

    def test_doctor_reports_each_skip_with_the_line_to_add(self):
        self.cfg(rules=None, settings={
            "extraKnownMarketplaces": MARKET, "enabledPlugins": {"p@mk": True}})
        status = gc.doctor_status()
        self.assertTrue(status.startswith("WARN"))
        self.assertIn("marketplace mk untrusted: add '%s'" % LINE, status)
        self.assertIn("plugin p@mk untrusted: add '%s'" % LINE, status)
        self.trust(LINE + "\n")
        self.apply()
        self.assertEqual(gc.doctor_status(), "PASS")


class RemoveAndDrift(Base):
    def test_toggle_off_removes_blocks_and_only_written_keys(self):
        _write(self.settings, json.dumps({"model": "x"}))
        _write(self.agents_md, "# Other\n")
        self.cfg(settings={"theme": "dark"})
        self.apply()
        with open(os.environ["NP_TOGGLES_CONF"], "w") as fh:
            fh.write("global-config|local|managed|off|\n")
        self.apply()
        self.assertEqual(self.host_settings(), {"model": "x"})
        self.assertEqual(_read(self.agents_md), "# Other\n")
        self.assertIsNone(ib.read_tagged(self.claude_md, gc.TAG))

    def test_toggle_flip_off_removes_at_once(self):
        import np_toggle
        self.cfg(rules=RULES, settings={"theme": "dark"})
        self.apply()
        self.assertIsNotNone(ib.read_tagged(self.claude_md, gc.TAG))
        np_toggle.flip("global-config", "off")
        self.assertIsNone(ib.read_tagged(self.claude_md, gc.TAG))
        self.assertNotIn("theme", self.host_settings())
        np_toggle.flip("global-config", "on")
        self.assertIsNotNone(ib.read_tagged(self.claude_md, gc.TAG))

    def test_non_object_marketplaces_and_plugins_are_reported(self):
        self.cfg(rules=None, settings={"enabledPlugins": ["x"], "extraKnownMarketplaces": 3})
        _, err = self.apply()
        self.assertIn("enabledPlugins", err)
        self.assertIn("extraKnownMarketplaces", err)

    def test_remove_keeps_a_key_the_user_changed_since(self):
        self.cfg(rules=None, settings={"theme": "dark"})
        self.apply()
        _write(self.settings, json.dumps({"theme": "light"}))
        gc.remove(io.StringIO())
        self.assertEqual(self.host_settings(), {"theme": "light"})

    def test_drift_reports_missing_stale_and_differing(self):
        self.cfg(settings={"theme": "dark"})
        found = " ".join(gc.drift())
        self.assertIn("rules missing", found)
        self.assertIn("setting theme differs", found)
        self.apply()
        self.assertEqual(gc.drift(), [])
        ib.sync_tagged(self.claude_md, gc.TAG, "old")
        self.assertIn("rules stale", " ".join(gc.drift()))

    def test_doctor_status(self):
        self.assertEqual(gc.doctor_status(), "PASS (no overlay config)")
        self.cfg()
        self.assertTrue(gc.doctor_status().startswith("WARN"))
        self.apply()
        self.assertEqual(gc.doctor_status(), "PASS")
        with open(os.environ["NP_TOGGLES_CONF"], "w") as fh:
            fh.write("global-config|local|managed|off|\n")
        self.assertEqual(gc.doctor_status(), "PASS (off)")


class TaggedBlock(unittest.TestCase):
    def test_remove_tagged_restores_the_original_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "AGENTS.md")
            _write(f, "# Mine\n")
            ib.sync_tagged(f, "t", "body")
            self.assertTrue(ib.remove_tagged(f, "t"))
            self.assertEqual(_read(f), "# Mine\n")
            self.assertFalse(ib.remove_tagged(f, "t"))


if __name__ == "__main__":
    unittest.main()
