#!/usr/bin/env python3
"""Every key in the dashboard's TOGGLE_LABELS map must exist in toggles.conf,
as a feature or a feature.param, so labels cannot drift. stdlib unittest."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(SETUP, "..", ".."))
CONF = os.path.join(SETUP, "toggles.conf")
INDEX = os.path.join(ROOT, "dashboard", "index.html")


def conf_keys():
    keys = set()
    with open(CONF, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cols = line.split("|")
            keys.add(cols[0])
            if len(cols) > 4 and cols[4]:
                for kv in cols[4].split(","):
                    keys.add(cols[0] + "." + kv.split("=", 1)[0])
    return keys


def label_keys():
    with open(INDEX, encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r"const TOGGLE_LABELS = \{(.*?)\n\s*\};", html, re.S)
    if not m:
        raise AssertionError("TOGGLE_LABELS map not found in dashboard/index.html")
    return re.findall(r'^\s*"([^"]+)"\s*:', m.group(1), re.M)


class TestDisplayLabels(unittest.TestCase):
    def test_map_is_not_empty(self):
        self.assertGreater(len(label_keys()), 0)

    def test_every_label_key_exists_in_toggles_conf(self):
        missing = sorted(set(label_keys()) - conf_keys())
        self.assertEqual(missing, [], "label keys absent from toggles.conf")

    def test_no_duplicate_label_keys(self):
        keys = label_keys()
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
