# np-test: dashboard-panels | proposals panel, graduation actions, suggestion paging, overlay viewer
"""Static guards on dashboard/index.html for the proposals panel, graduation
actions, suggestion pagination, and the sandboxed overlay viewer."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "dashboard", "index.html"))


class TestPanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()

    def _viewer(self):
        start = self.html.index('id="viewer-overlay"')
        return self.html[start:self.html.index("</div>\n  </div>", start)]

    def test_viewer_iframe_is_sandboxed_and_no_referrer(self):
        frame = re.search(r"<iframe[^>]*>", self._viewer(), re.S).group(0)
        self.assertIn('referrerpolicy="no-referrer"', frame)
        self.assertRegex(frame, r'sandbox="[^"]*"')
        self.assertNotIn("allow-top-navigation", self.html)

    def test_viewer_has_new_tab_and_close(self):
        v = self._viewer()
        self.assertIn('id="viewer-newtab"', v)
        self.assertIn('target="_blank"', v)
        self.assertIn('rel="noopener noreferrer"', v)
        self.assertIn('id="viewer-close"', v)

    def test_viewer_closes_on_escape_and_backdrop(self):
        self.assertIn('e.key === "Escape" && !viewerOverlay.hidden', self.html)
        self.assertIn("e.target === viewerOverlay", self.html)

    def test_sandbox_profiles_are_scoped(self):
        self.assertIn('PAGE: "allow-scripts allow-popups allow-popups-to-escape-sandbox"', self.html)
        self.assertIn('APP: "allow-scripts allow-same-origin allow-forms allow-modals"', self.html)

    def test_wiki_links_and_settings_use_the_viewer(self):
        self.assertIn('closest("a.wikiitem")', self.html)
        self.assertIn('openViewer("index.html?view=settings"', self.html)

    def test_proposals_panel(self):
        self.assertIn('id="panel-proposals"', self.html)
        self.assertIn("function renderProposals()", self.html)
        self.assertIn("/api/compact/reject", self.html)
        self.assertIn("/api/compact/apply", self.html)

    def test_graduation_actions(self):
        self.assertIn("/api/graduation/graduate", self.html)
        self.assertIn("/api/graduation/dismiss", self.html)
        self.assertIn("data-graduate", self.html)
        self.assertIn("data-dismiss", self.html)

    def test_suggestions_paginate_by_ten(self):
        self.assertIn("const SUG_PAGE = 10", self.html)
        self.assertIn('id="sug-prev"', self.html)
        self.assertIn('id="sug-next"', self.html)


if __name__ == "__main__":
    unittest.main()


class TestTwoUpRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()

    def _assert_two_up(self, a, b):
        m = re.search(r'<div class="grid"[^>]*>\s*<section class="panel" id="%s"></section>'
                      r'\s*<section class="panel" id="%s"></section>\s*</div>' % (a, b), self.html)
        self.assertIsNotNone(m, "%s and %s must share one .grid row" % (a, b))

    def test_perf_charts_side_by_side(self):
        self._assert_two_up("panel-trend", "panel-tokens")

    def test_ledger_and_latest_side_by_side(self):
        self._assert_two_up("panel-ledger", "panel-latest")

    def test_grid_stacks_on_narrow_viewports(self):
        m = re.search(r"@media \(max-width:(\d+)px\) \{\s*\.grid \{ grid-template-columns:1fr; \}", self.html)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 768)
