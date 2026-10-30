# np-test: dashboard | happy
"""E2e tests: the Graduate, Apply, Dismiss and Reject buttons (Playwright, quarantined).

Each test boots the real server against a fixture overlay and a stub job, then
clicks the button in a real browser. A failure must show on the row and in the
banner. A native dialog or a silent no-op fails the test.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright

import harness as harness_mod

GRAD_ROW = '#panel-graduation .sug[data-name="s1"]'
PROP_ROW = '#panel-proposals .sug[data-file="2026-09-30.md"]'
BANNER = "#action-banner .banner"


class TestActionButtons(unittest.TestCase):

    def _open(self, stub_state="done"):
        ctx = {}
        base_url, stop = harness_mod.start(stub_state=stub_state, overlay=True, ctx=ctx)
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        page = browser.new_page()
        self.dialogs = []
        page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        page.goto(base_url, wait_until="networkidle")
        self.addCleanup(lambda: (browser.close(), pw.stop(), stop()))
        return page, ctx

    def _no_dialogs(self):
        self.assertEqual(self.dialogs, [], "an action used a native dialog: %r" % self.dialogs)

    def test_graduate_runs_the_job_and_removes_the_row(self):
        page, _ = self._open("done")
        page.locator(GRAD_ROW + " [data-graduate]").click()
        page.locator(GRAD_ROW + " .pill.pos").wait_for(state="visible", timeout=15000)
        page.locator(GRAD_ROW).wait_for(state="detached", timeout=15000)
        self.assertEqual(page.locator(BANNER).count(), 0)
        self._no_dialogs()

    def test_apply_runs_the_job_and_removes_the_row(self):
        page, _ = self._open("done")
        page.locator(PROP_ROW + " [data-apply]").click()
        page.locator(PROP_ROW + " .pill.pos").wait_for(state="visible", timeout=15000)
        page.locator(PROP_ROW).wait_for(state="detached", timeout=15000)
        self.assertEqual(page.locator(BANNER).count(), 0)
        self._no_dialogs()

    def test_failed_job_shows_on_the_row_and_in_the_banner(self):
        page, _ = self._open("failed")
        for row, button in ((GRAD_ROW, "[data-graduate]"), (PROP_ROW, "[data-apply]")):
            page.locator(row + " " + button).click()
            page.locator(row + " .pill.neg").wait_for(state="visible", timeout=15000)
            self.assertIn("Failed", page.locator(row + " .pill.neg").inner_text())
            self.assertTrue(page.locator(row + " " + button).is_visible(), "button must come back")
        page.locator(BANNER).first.wait_for(state="visible", timeout=5000)
        self.assertGreaterEqual(page.locator(BANNER).count(), 2)
        self._no_dialogs()

    def test_stale_entry_says_so_instead_of_doing_nothing(self):
        page, ctx = self._open("done")
        os.remove(os.path.join(ctx["overlay"], "compact-proposals", "2026-09-30.md"))
        os.remove(os.path.join(ctx["overlay"], "dashboard", "data", "graduation-candidates.json"))
        for row, button in ((PROP_ROW, "[data-apply]"), (GRAD_ROW, "[data-graduate]")):
            page.locator(row + " " + button).click()
            page.locator(row + " .pill.neg").wait_for(state="visible", timeout=8000)
            self.assertIn("no longer", page.locator(row + " .pill.neg").inner_text())
        self.assertGreaterEqual(page.locator(BANNER).count(), 2)
        self._no_dialogs()

    def test_dead_server_says_so(self):
        page, ctx = self._open("done")
        ctx["proc"].terminate()
        ctx["proc"].wait(timeout=5)
        page.locator(GRAD_ROW + " [data-graduate]").click()
        page.locator(BANNER).first.wait_for(state="visible", timeout=8000)
        self.assertIn("cannot reach", page.locator(BANNER).first.inner_text())
        self.assertTrue(page.locator(GRAD_ROW + " [data-graduate]").is_visible())
        self._no_dialogs()

    def test_banner_can_be_dismissed(self):
        page, ctx = self._open("done")
        ctx["proc"].terminate()
        ctx["proc"].wait(timeout=5)
        page.locator(GRAD_ROW + " [data-graduate]").click()
        page.locator(BANNER).first.wait_for(state="visible", timeout=8000)
        page.locator(BANNER + " button").first.click()
        self.assertEqual(page.locator(BANNER).count(), 0)

    def test_dismiss_and_reject_remove_their_rows(self):
        page, _ = self._open("done")
        page.locator(GRAD_ROW + " [data-dismiss]").click()
        page.locator(GRAD_ROW).wait_for(state="detached", timeout=8000)
        page.locator(PROP_ROW + " [data-reject-prop]").click()
        page.locator(PROP_ROW).wait_for(state="detached", timeout=8000)
        self.assertEqual(page.locator(BANNER).count(), 0)
        self._no_dialogs()


if __name__ == "__main__":
    unittest.main()
