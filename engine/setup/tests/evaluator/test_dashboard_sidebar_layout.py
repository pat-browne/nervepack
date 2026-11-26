# np-test: dashboard-sidebar-layout | wiki list keeps its height, health panels start collapsed
"""Static guards: the health panels must not squeeze the wiki list, and
both health panels render folded so the topics stay visible."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "dashboard", "index.html"))


def rule(html, selector):
    m = re.search(r"^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", html, re.M)
    return m.group(1) if m else ""


class TestSidebarLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()
        m = re.search(r"function renderCreds\(.*?\n  \}\n", cls.html, re.S)
        cls.creds = m.group(0) if m else ""
        m = re.search(r"function renderJobs\(.*?\n  \}\n", cls.html, re.S)
        cls.jobs = m.group(0) if m else ""

    def test_wiki_list_has_a_floor(self):
        self.assertRegex(rule(self.html, ".wikilist"), r"min-height:\s*min\(")

    def test_health_panels_shrink_before_the_wiki_list(self):
        body = rule(self.html, ".sidehealth")
        self.assertRegex(body, r"flex:\s*0 1 auto")
        self.assertRegex(body, r"min-height:\s*0")

    def assert_folded(self, fn, name):
        self.assertTrue(fn, name + " missing")
        self.assertIn('<details class="sidefold"', fn)
        self.assertNotRegex(fn, r'<details class="sidefold" open')
        self.assertIn("<summary>", fn)
        # A refresh keeps a fold the user opened.
        self.assertIn('querySelector("details.sidefold[open]")', fn)

    def test_credentials_render_folded(self):
        self.assert_folded(self.creds, "renderCreds")

    def test_health_checks_render_folded(self):
        self.assert_folded(self.jobs, "renderJobs")


if __name__ == "__main__":
    unittest.main()
