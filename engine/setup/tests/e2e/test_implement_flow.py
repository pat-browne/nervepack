# np-test: dashboard | happy
"""E2e tests: dashboard implement / reject flow (Playwright, quarantined)."""
import os
import sys
import unittest

# harness.py lives in the same directory as this test
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright

import harness as harness_mod

SUGGESTION_TEXT = "Add a regression test for the foo path"


class TestImplementFlow(unittest.TestCase):

    def _open_page(self, stub_state: str):
        """Start server + browser, return (page, browser, pw, stop_fn)."""
        base_url, stop_fn = harness_mod.start(stub_state=stub_state)
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(base_url, wait_until="networkidle")
        return page, browser, pw, stop_fn

    def _cleanup(self, browser, pw, stop_fn):
        browser.close()
        pw.stop()
        stop_fn()

    def test_implement_removes_the_row(self):
        """Clicking implement on a suggestion → .note.ok appears, .sug row is removed."""
        page, browser, pw, stop_fn = self._open_page(stub_state="done")
        try:
            # Wait for the implement button to be present
            page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').first.wait_for(timeout=5000)

            # Click implement
            page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').click()

            # Wait for .note.ok to appear (JS polls every ~3s, give 15s)
            page.locator(".note.ok").first.wait_for(state="visible", timeout=15000)

            # Assert the sug row is gone (implement button detached)
            remaining = page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').count()
            self.assertEqual(remaining, 0, "Suggestion row should be removed after implement")
        finally:
            self._cleanup(browser, pw, stop_fn)

    def test_not_implementable_keeps_the_row(self):
        """not_implementable → pill shows 'Not a code change', row stays."""
        page, browser, pw, stop_fn = self._open_page(stub_state="not_implementable")
        try:
            page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').first.wait_for(timeout=5000)
            page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').click()

            # Wait for the not-implementable pill text (15s)
            page.get_by_text("Not a code change").first.wait_for(state="visible", timeout=15000)

            # Row should still be present — buttons are restored
            row_count = page.locator(f'[data-implement="{SUGGESTION_TEXT}"]').count()
            self.assertGreater(row_count, 0, "Suggestion row should remain for not_implementable")
        finally:
            self._cleanup(browser, pw, stop_fn)

    def test_reject_removes_the_row(self):
        """Reject → POST /api/resolve → row removed client-side."""
        page, browser, pw, stop_fn = self._open_page(stub_state="done")
        try:
            page.locator(f'[data-reject="{SUGGESTION_TEXT}"]').first.wait_for(timeout=5000)
            page.locator(f'[data-reject="{SUGGESTION_TEXT}"]').click()

            # Row should be removed after reject (client-side, fast)
            page.locator(f'[data-reject="{SUGGESTION_TEXT}"]').wait_for(state="detached", timeout=10000)
            remaining = page.locator(f'[data-reject="{SUGGESTION_TEXT}"]').count()
            self.assertEqual(remaining, 0, "Suggestion row should be removed after reject")
        finally:
            self._cleanup(browser, pw, stop_fn)


if __name__ == "__main__":
    unittest.main()
