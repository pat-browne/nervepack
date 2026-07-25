"""In-process coverage for np_toggle.enabled() / param() — the full resolver
matrix that the retired bash test tests/toggles/test_lib.sh held (phase 18).

Ports every assertion of test_lib.sh 1:1, driving np_toggle in-process against a
hermetic NP_TOGGLES_CONF / NP_TOGGLES_LOCAL (native tempfile paths, so
host-agnostic — no bash mktemp / MSYS). The enabled() inheritance matrix
(family-inherit on/off, explicit sub-override, unknown fail-open) and the
param conf/local/default precedence are the coverage that used to reach Python
only through the now-deleted A/B parity test.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import np_toggle  # noqa: E402

CONF = """\
memory|shared|runtime|on|
playbooks|shared|runtime|off|
sync|shared|runtime|on|interval=86400
allowlist|local|managed|on|
"""


class TestToggleResolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self.local = os.path.join(self.tmp, "local")
        # Force LF: the committed toggles.conf is always LF, but a text-mode write
        # on the Windows lane would emit CRLF, leaving a trailing \r on the last
        # column's value (interval=86400\r != 86400). Match the real file's form.
        with open(self.conf, "w", newline="\n") as fh:
            fh.write(CONF)
        # A clean env so no ambient toggle file leaks in; HOME points nowhere real.
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.tmp,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
        }, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_local(self, text):
        with open(self.local, "w") as fh:
            fh.write(text)

    # --- np_enabled, conf only (test_lib.sh lines 14-17) --------------------
    def test_family_on(self):
        self.assertTrue(np_toggle.enabled("memory"))          # memory should be on

    def test_family_off(self):
        self.assertFalse(np_toggle.enabled("playbooks"))      # playbooks should be off

    def test_sub_inherits_family_on(self):
        self.assertTrue(np_toggle.enabled("memory.capture"))  # sub inherits family on

    def test_unknown_fails_open_on(self):
        self.assertTrue(np_toggle.enabled("missingfeature"))  # unknown -> fail-open on

    # --- np_enabled, local overrides (test_lib.sh lines 19-23) --------------
    def test_local_override_off(self):
        self._write_local("memory=off\n")
        self.assertFalse(np_toggle.enabled("memory"))         # local override off honored

    def test_sub_inherits_local_family_off(self):
        self._write_local("memory=off\n")
        self.assertFalse(np_toggle.enabled("memory.recall"))  # sub inherits local family off

    def test_explicit_sub_override_on(self):
        self._write_local("memory=off\nmemory.recall=on\n")
        self.assertTrue(np_toggle.enabled("memory.recall"))   # explicit sub override on wins

    # --- np_param conf / local / default (test_lib.sh lines 25-28) ----------
    def test_param_from_conf(self):
        self.assertEqual(np_toggle.param("sync.interval", "999"), "86400")

    def test_param_local_override(self):
        self._write_local("sync.interval=3600\n")
        self.assertEqual(np_toggle.param("sync.interval", "999"), "3600")

    def test_param_default_fallback(self):
        self.assertEqual(np_toggle.param("no.such", "42"), "42")

    # --- parser footguns the deleted A/B parity test pinned (phase-18 review
    #     backfill): the resolver still implements these; guard them in-process. ---
    def test_local_read_tolerates_crlf(self):
        # A local file written with CRLF line endings must still resolve (the value
        # must not carry a trailing \r). Write bytes so newline translation can't hide it.
        with open(self.local, "wb") as fh:
            fh.write(b"sync.interval=3600\r\nmemory=off\r\n")
        self.assertEqual(np_toggle.param("sync.interval", "999"), "3600")
        self.assertFalse(np_toggle.enabled("memory"))         # local override off honored

    def test_param_value_with_embedded_equals_and_spaces(self):
        # A value containing '=' / spaces must survive intact (split on the FIRST '=').
        self._write_local("expr=a=b=c\ngreeting=hello world\n")
        self.assertEqual(np_toggle.param("expr", "x"), "a=b=c")
        self.assertEqual(np_toggle.param("greeting", "x"), "hello world")

    def test_local_duplicate_key_last_wins_on_read(self):
        # Two lines for the same key: the LAST wins on read (matches the write path).
        self._write_local("foo=first\nfoo=second\n")
        self.assertEqual(np_toggle.param("foo", "x"), "second")


if __name__ == "__main__":
    unittest.main()
