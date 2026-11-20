# np-test: dashboard-creds-panel | credentials panel reads /api/credentials, flags due sources, escapes names and commands
"""Static guards on dashboard/index.html and the server for the Credentials panel."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
INDEX = os.path.join(ROOT, "dashboard", "index.html")
SERVER = os.path.join(ROOT, "engine", "setup", "np-dashboard-server.py")


class TestCredsPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()
        with open(SERVER, encoding="utf-8") as fh:
            cls.server = fh.read()
        m = re.search(r"function renderCreds\(.*?\n  \}\n", cls.html, re.S)
        cls.fn = m.group(0) if m else ""

    def test_fetches_endpoint_only_when_served(self):
        self.assertIn('fetch("/api/credentials", ', self.html)
        self.assertIn("if (SERVED) refreshCreds();", self.html)
        self.assertIn("if (!SERVED) renderCreds(null);", self.html)

    def test_render_covers_fields_and_escapes(self):
        self.assertTrue(self.fn, "renderCreds missing")
        for key in ("esc(c.name)", "esc(c.status)", "esc(c.command)", "credDays(c)"):
            self.assertIn(key, self.fn)

    def test_server_route_is_toggle_gated(self):
        self.assertIn('"/api/credentials"', self.server)
        self.assertIn('np_toggle.enabled("maintain.credentials")', self.server)
        self.assertIn("np_credentials.survey()", self.server)


if __name__ == "__main__":
    unittest.main()
