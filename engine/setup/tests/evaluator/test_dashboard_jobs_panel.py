# np-test: dashboard-jobs-panel | scheduled-jobs panel reads /api/jobs, flags problems, explains static mode
"""Static guards on dashboard/index.html for the Scheduled jobs panel."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "dashboard", "index.html"))


class TestJobsPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX, encoding="utf-8") as fh:
            cls.html = fh.read()
        m = re.search(r"function renderJobs\(.*?\n  \}\n", cls.html, re.S)
        cls.fn = m.group(0) if m else ""

    def test_panel_sits_in_a_grid_row(self):
        self.assertRegex(self.html, r'<div class="grid"[^>]*>\s*<section class="panel full" id="panel-jobs">')

    def test_fetches_jobs_endpoint_only_when_served(self):
        self.assertIn('fetch("/api/jobs", ', self.html)
        self.assertIn("if (SERVED) refreshJobs();", self.html)

    def test_render_function_covers_each_field(self):
        self.assertTrue(self.fn, "renderJobs missing")
        for key in ("j.status", "j.overdue", "j.enabled", "j.age_h", "j.name"):
            self.assertIn(key, self.fn)

    def test_flags_problem_rows_and_summarizes(self):
        self.assertIn("jobBad(j) ? \" bad\"", self.fn)
        self.assertIn("jobSummary(", self.fn)
        self.assertIn("function jobSummary(", self.html)

    def test_static_and_error_fallback_note(self):
        self.assertIn("needs the dashboard server", self.html)
        self.assertRegex(self.html, r"if \(!SERVED\)[^\n]*renderJobs\(null\)")

    def test_static_call_comes_after_empty_helper(self):
        # renderJobs(null) runs synchronously in static mode and calls empty().
        self.assertLess(self.html.index("const empty = msg =>"),
                        self.html.index("if (!SERVED) renderJobs(null)"))

    def test_server_error_has_its_own_message(self):
        self.assertIn("Could not load job health", self.fn)
        self.assertIn("AbortSignal.timeout(", self.html)

    def test_names_are_escaped(self):
        self.assertIn("esc(j.name)", self.fn)


if __name__ == "__main__":
    unittest.main()
