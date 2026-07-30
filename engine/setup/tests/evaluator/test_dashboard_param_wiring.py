# np-test: dashboard-param-wiring | every knob the dashboard reads is actually
#          fed, declared, and documented — no silently-dead tuning parameters.
"""The second drift shape.

A dashboard knob only works if FOUR things agree:

    build.py reads env  <-  np_aggregate.py sets env  <-  toggles.conf declares
    the param                                         ->  toggle-schema.json types it

Break any link and the parameter silently does nothing. Nothing errors, no test
fails, and the default quietly rules forever — the same class of failure as the
seven-week dead dashboard: correct-looking parts, broken composition.

This is a structural test, not a behavioural one: it reads the sources and
asserts the four layers line up, so a future knob added to build.py but never
passed by the aggregator fails here instead of being discovered months later by
someone wondering why their toggle does nothing.

Deliberately source-scraping rather than importing: the point is to catch a
DECLARATION that was never wired, which an import-and-call test cannot see.
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
BUILD = os.path.join(ROOT, "dashboard", "build.py")
AGGREGATE = os.path.join(ROOT, "engine", "setup", "np_aggregate.py")
TOGGLES = os.path.join(ROOT, "engine", "setup", "toggles.conf")
SCHEMA = os.path.join(ROOT, "engine", "setup", "toggle-schema.json")


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _declared_evaluator_params():
    """The param names on the `evaluator|` row of toggles.conf."""
    for line in _read(TOGGLES).splitlines():
        if line.startswith("evaluator|"):
            fields = line.split("|")
            if len(fields) < 5 or not fields[4].strip():
                return set()
            return {"evaluator." + p.split("=", 1)[0].strip()
                    for p in fields[4].split(",") if p.strip()}
    raise AssertionError("no evaluator row in toggles.conf")


class DashboardParamWiringTest(unittest.TestCase):
    def test_every_dashboard_env_build_reads_is_set_by_the_aggregator(self):
        """build.py runs as a subprocess of np_aggregate.py. An env var it reads
        that the aggregator never sets can only ever take its hardcoded default."""
        reads = set(re.findall(r'os\.environ\.get\(\s*"(DASHBOARD_[A-Z_]+)"', _read(BUILD)))
        sets = set(re.findall(r'env\[\s*"(DASHBOARD_[A-Z_]+)"\s*\]', _read(AGGREGATE)))
        self.assertTrue(reads, "expected build.py to read some DASHBOARD_* env vars")
        unfed = sorted(reads - sets)
        self.assertEqual(unfed, [],
                         "build.py reads %s but np_aggregate.py never sets them — the "
                         "toggle param can never reach the dashboard" % unfed)

    def test_every_evaluator_param_the_aggregator_resolves_is_declared(self):
        """np_toggle.param() fails open to its inline default, so resolving an
        undeclared param works — and is invisible in `cli.py toggle` forever."""
        resolved = set(re.findall(r'np_toggle\.param\(\s*"(evaluator\.[a-z_]+)"',
                                  _read(AGGREGATE)))
        self.assertTrue(resolved, "expected np_aggregate.py to resolve evaluator params")
        undeclared = sorted(resolved - _declared_evaluator_params())
        self.assertEqual(undeclared, [],
                         "%s resolved but absent from toggles.conf — undiscoverable, "
                         "and `cli.py toggle` cannot show or set it" % undeclared)

    def test_every_declared_evaluator_param_is_typed_in_the_schema(self):
        """toggle-schema.json drives the dashboard's own Feature Toggles panel.
        A declared-but-unschema'd param cannot be edited from the UI."""
        schema = json.loads(_read(SCHEMA))
        missing = sorted(p for p in _declared_evaluator_params() if p not in schema)
        self.assertEqual(missing, [],
                         "%s declared in toggles.conf but missing from "
                         "toggle-schema.json — not editable from the toggle panel"
                         % missing)

    def test_aggregator_default_matches_the_manifest_default(self):
        """np_toggle.param(key, DEFAULT) repeats the default as a fallback. If it
        drifts from the toggles.conf value, behaviour silently depends on whether
        the manifest was readable — two different defaults for one knob."""
        conf_defaults = {}
        for line in _read(TOGGLES).splitlines():
            if line.startswith("evaluator|"):
                for p in line.split("|")[4].split(","):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        conf_defaults["evaluator." + k.strip()] = v.strip()
        mismatches = []
        for key, fallback in re.findall(
                r'np_toggle\.param\(\s*"(evaluator\.[a-z_]+)"\s*,\s*"([^"]*)"\s*\)',
                _read(AGGREGATE)):
            declared = conf_defaults.get(key)
            if declared is not None and declared != fallback:
                mismatches.append("%s: toggles.conf=%s but code fallback=%s"
                                  % (key, declared, fallback))
        self.assertEqual(mismatches, [], "; ".join(mismatches))


if __name__ == "__main__":
    unittest.main()
