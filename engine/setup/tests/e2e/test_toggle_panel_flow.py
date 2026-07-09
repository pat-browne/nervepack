# np-test: dashboard | happy
"""E2e tests: dashboard Feature Toggles panel (Playwright, quarantined)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright

import harness as harness_mod

FIXTURE_CONF = os.path.join(os.path.dirname(__file__), "fixtures", "toggles.conf")


class TestTogglePanelFlow(unittest.TestCase):

    def _open_page(self):
        base_url, stop_fn = harness_mod.start(stub_state="done", toggles_conf=FIXTURE_CONF)
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(base_url, wait_until="networkidle")
        return page, browser, pw, stop_fn

    def _cleanup(self, browser, pw, stop_fn):
        browser.close()
        pw.stop()
        stop_fn()

    def test_local_param_flip_persists_no_confirm(self):
        """Flipping evaluator.implement_mode isn't offered here (it's an enum
        select, not a checkbox); exercise a bool param instead — evaluator.implement
        is a dotted, non-lockout bool param, so it flips with no confirm dialog.

        The switch's real <input> is visually hidden (opacity:0, 0x0 box) behind a
        styled .swtrack sibling inside a <label class="swtoggle"> — the standard
        "hidden checkbox + custom switch" CSS pattern. Playwright's default
        actionability checks (visible, non-empty bounding box) apply to clicks and
        to wait_for()'s default state, so we target the wrapping <label> — which
        has real size and forwards clicks to its nested checkbox per the HTML
        label spec — for waiting/clicking, and use the <input> locator only for
        state assertions (is_checked() doesn't require visibility)."""
        page, browser, pw, stop_fn = self._open_page()
        try:
            label = page.locator('label.swtoggle:has(input[data-key="evaluator.implement"])')
            label.wait_for(timeout=5000)
            checkbox = page.locator('input[data-key="evaluator.implement"]')
            self.assertTrue(checkbox.is_checked())
            label.click()
            page.wait_for_timeout(500)  # allow the POST to land
            self.assertFalse(checkbox.is_checked())
        finally:
            self._cleanup(browser, pw, stop_fn)

    def test_self_lockout_param_is_read_only(self):
        """dashboard_serve is a self-lockout param — no input control, just a
        read-only 'locked' label; the server would refuse to write it anyway."""
        page, browser, pw, stop_fn = self._open_page()
        try:
            page.locator(".togfam").first.wait_for(timeout=5000)
            self.assertEqual(page.locator('input[data-key="evaluator.dashboard_serve"]').count(), 0)
            page.get_by_text("locked").first.wait_for(timeout=5000)
        finally:
            self._cleanup(browser, pw, stop_fn)

    def test_shared_feature_flip_requires_confirm(self):
        """Flipping a shared bare feature (memory) triggers window.confirm(); if the
        user dismisses it, the switch reverts and stays checked.

        See test_local_param_flip_persists_no_confirm for why we wait/click on the
        wrapping <label class="swtoggle"> rather than the visually-hidden <input>."""
        page, browser, pw, stop_fn = self._open_page()
        try:
            label = page.locator('label.swtoggle:has(input[data-key="memory"])')
            label.wait_for(timeout=5000)
            page.on("dialog", lambda d: d.dismiss())
            checkbox = page.locator('input[data-key="memory"]')
            self.assertTrue(checkbox.is_checked())
            label.click()
            page.wait_for_timeout(300)
            self.assertTrue(checkbox.is_checked())  # reverted — dialog was dismissed
        finally:
            self._cleanup(browser, pw, stop_fn)


if __name__ == "__main__":
    unittest.main()
