#!/usr/bin/env python3
"""Unit tests for np_toggle.py's all_params() (stdlib unittest, direct import —
no bash parity needed since all_params has no bash-CLI equivalent to mirror)."""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "..", "..")


def _load_np_toggle():
    spec = importlib.util.spec_from_file_location("np_toggle", os.path.join(SETUP, "np_toggle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


np_toggle = _load_np_toggle()


class TestAllParams(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.tmp.name, "toggles.conf")
        self.local = os.path.join(self.tmp.name, "toggles.local")
        # newline="" avoids Python's universal-newline translation (\n -> \r\n on
        # native Windows text-mode writes), matching np_toggle.py's own convention
        # (set_local() writes the same way) since all_params() reads raw (newline="")
        # and only strips \n — a \r left in by a text-mode write would leak into
        # every parsed value.
        with open(self.conf, "w", newline="") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard_port=8787,implement_mode=pr\n")
            fh.write("memory|shared|runtime|on|cap_bytes=48000\n")
            fh.write("directive|shared|runtime|on|\n")
        self._prev_conf = os.environ.get("NP_TOGGLES_CONF")
        self._prev_local = os.environ.get("NP_TOGGLES_LOCAL")
        os.environ["NP_TOGGLES_CONF"] = self.conf
        os.environ["NP_TOGGLES_LOCAL"] = self.local

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in (("NP_TOGGLES_CONF", self._prev_conf), ("NP_TOGGLES_LOCAL", self._prev_local)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_returns_conf_values(self):
        self.assertEqual(np_toggle.all_params("evaluator"),
                          {"dashboard_port": "8787", "implement_mode": "pr"})

    def test_local_override_wins(self):
        with open(self.local, "w", newline="") as fh:
            fh.write("evaluator.implement_mode=direct\n")
        self.assertEqual(np_toggle.all_params("evaluator"),
                          {"dashboard_port": "8787", "implement_mode": "direct"})

    def test_unrelated_local_key_does_not_leak_in(self):
        with open(self.local, "w", newline="") as fh:
            fh.write("memory.cap_bytes=99999\n")
        self.assertEqual(np_toggle.all_params("evaluator"),
                          {"dashboard_port": "8787", "implement_mode": "pr"})

    def test_unknown_family_returns_empty(self):
        self.assertEqual(np_toggle.all_params("nonexistent"), {})

    def test_family_with_no_params_returns_empty(self):
        self.assertEqual(np_toggle.all_params("directive"), {})


if __name__ == "__main__":
    unittest.main()
