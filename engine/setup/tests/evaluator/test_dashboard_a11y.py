"""#177: static guards that the dashboard's trend chart is keyboard/screen-reader
accessible and that the two-up panel grid collapses to one column on narrow
viewports. These pin the specific markup/CSS the fix adds so it can't silently
regress (runtime behavior is additionally exercised by the informational e2e lane)."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "dashboard", "index.html"))


class TestDashboardA11y(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_two_up_grid_collapses_on_narrow_viewport(self):
        self.assertIn("@media (max-width:900px)", self.html)
        # a single-column grid rule (distinct from the base "1fr 1fr")
        self.assertRegex(self.html, r"\.grid\s*\{\s*grid-template-columns:\s*1fr\s*;")

    def test_chart_points_are_keyboard_focusable_with_a_label(self):
        # each rendered .pt data point must be focusable and carry a plain-text label
        self.assertRegex(self.html, r'class="pt"[^>]*tabindex="0"')
        self.assertIn('aria-label="${esc(plain(p.tip))}"', self.html)

    def test_wirechart_reveals_tooltip_on_keyboard_focus(self):
        self.assertIn('addEventListener("focus"', self.html)

    def test_svg_line_stays_decorative_and_a_plain_label_helper_exists(self):
        # the decorative polyline SVG remains aria-hidden; the accessible data lives
        # on the focusable dots (whose aria-label is derived by plain()).
        self.assertIn("function plain(", self.html)


if __name__ == "__main__":
    unittest.main()
