#!/usr/bin/env python3
# np-test: automerge | happy
"""Tests for np_automerge -- confidence-gated auto-merge (F9/#255).

The failure that matters here is one-directional. A decision that wrongly
declines costs a click. A decision that wrongly enables puts unreviewed code on
main under the repository's own authority. Every test below is written to catch
the second kind.
"""
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_automerge  # noqa: E402
import np_risk_tiers  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))
CI_YML = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")

POLICY = {"schema": 1, "enabled": True, "allowed_tiers": ["standard"],
          "trusted_authors": ["trusted-person"]}


def _tier_policy(**over):
    base = {
        "schema": "nervepack.tier-policy/1",
        "tier": "standard",
        "auto_merge_eligible": True,
        "problems": [],
        "gate_verdicts": {"syntax": "PASSED", "regression": "PASSED",
                          "diff-review": "PASSED"},
    }
    base.update(over)
    return base


class TestTheHappyPath(unittest.TestCase):
    def test_a_clean_standard_change_by_a_trusted_author_qualifies(self):
        d = np_automerge.decide(_tier_policy(), "trusted-person", POLICY)
        self.assertEqual(d["reasons"], [])
        self.assertTrue(d["eligible"])
        self.assertTrue(d["will_enable"])


class TestEachConditionBlocksOnItsOwn(unittest.TestCase):
    """Five conditions. Each one must be sufficient by itself, or a single
    mistake elsewhere silently becomes the only thing standing in the way."""

    def test_tier_gate_saying_no_blocks(self):
        d = np_automerge.decide(
            _tier_policy(auto_merge_eligible=False, problems=["regression is FAILED"]),
            "trusted-person", POLICY)
        self.assertFalse(d["will_enable"])
        self.assertTrue(any("regression is FAILED" in r for r in d["reasons"]))

    def test_a_tier_outside_the_policy_blocks(self):
        d = np_automerge.decide(_tier_policy(tier="normal"), "trusted-person", POLICY)
        self.assertFalse(d["will_enable"])
        self.assertTrue(any("allowed_tiers" in r for r in d["reasons"]))

    def test_an_untrusted_author_blocks(self):
        d = np_automerge.decide(_tier_policy(), "someone-else", POLICY)
        self.assertFalse(d["will_enable"])
        self.assertTrue(any("someone-else" in r for r in d["reasons"]))

    def test_a_missing_author_blocks(self):
        """An empty author must never read as 'no objection'."""
        for author in ("", None):
            d = np_automerge.decide(_tier_policy(), author, POLICY)
            self.assertFalse(d["will_enable"], repr(author))

    def test_a_skipped_adversarial_lens_blocks(self):
        tp = _tier_policy()
        tp["gate_verdicts"]["diff-review"] = "SKIPPED"
        d = np_automerge.decide(tp, "trusted-person", POLICY)
        self.assertFalse(d["will_enable"])
        self.assertTrue(any("adversarial lens" in r for r in d["reasons"]))

    def test_an_absent_adversarial_verdict_blocks(self):
        tp = _tier_policy()
        del tp["gate_verdicts"]["diff-review"]
        d = np_automerge.decide(tp, "trusted-person", POLICY)
        self.assertFalse(d["will_enable"])

    def test_the_kill_switch_overrides_everything(self):
        off = dict(POLICY, enabled=False)
        d = np_automerge.decide(_tier_policy(), "trusted-person", off)
        self.assertFalse(d["will_enable"])
        # Still records that it WOULD have qualified - that is what makes a
        # watch period worth running.
        self.assertTrue(d["eligible"])
        self.assertEqual(d["reasons"], [])

    def test_a_missing_tier_policy_blocks(self):
        for tp in (None, {}, "not a dict", []):
            d = np_automerge.decide(tp, "trusted-person", POLICY)
            self.assertFalse(d["will_enable"], repr(tp))


class TestReasonsAreComplete(unittest.TestCase):
    def test_every_blocker_is_listed_not_just_the_first(self):
        """A record that names one blocker sends the reader round the loop for
        the next one."""
        tp = _tier_policy(tier="high", auto_merge_eligible=False)
        tp["gate_verdicts"]["diff-review"] = "SKIPPED"
        d = np_automerge.decide(tp, "someone-else", POLICY)
        self.assertGreaterEqual(len(d["reasons"]), 4)


class TestTheAuthorIsTheAuthor(unittest.TestCase):
    """github.actor is the last identity to ACT on a pull request, not its
    author. An attacker who can cause any bot activity on a pull request they
    control flips that context and inherits the privileged path. This is the
    documented Dependabot pwn-request."""

    def test_the_author_is_a_parameter_not_read_from_the_environment(self):
        """decide() takes the author as an argument, so a test can prove which
        identity the caller passed. If the module ever reads it itself, that
        proof disappears."""
        with open(os.path.join(_ENGINE_SETUP, "np_automerge.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("GITHUB_ACTOR", source)
        self.assertNotIn("os.environ", source)

    def test_the_workflow_passes_the_pull_request_author(self):
        with open(CI_YML, encoding="utf-8") as fh:
            ci = fh.read()
        self.assertIn("github.event.pull_request.user.login", ci)

    def test_the_workflow_never_gates_on_github_actor(self):
        with open(CI_YML, encoding="utf-8") as fh:
            ci = fh.read()
        offenders = [line for line in ci.splitlines()
                     if "github.actor" in line and not line.strip().startswith("#")]
        self.assertEqual(offenders, [], offenders)


class TestWorkflowHardening(unittest.TestCase):
    def test_no_third_party_actions(self):
        """There are none today. The rule matters the day one arrives, and
        nobody will remember it then."""
        with open(CI_YML, encoding="utf-8") as fh:
            uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", fh.read(), re.MULTILINE)
        self.assertTrue(uses, "no uses: steps found - has ci.yml moved?")
        for ref in uses:
            self.assertTrue(ref.startswith("actions/"),
                            "third-party action %r must be pinned to a full commit "
                            "SHA, and this test updated to allow it" % ref)

    def test_the_workflow_declares_permissions_at_the_top(self):
        with open(CI_YML, encoding="utf-8") as fh:
            head = fh.read().split("jobs:", 1)[0]
        self.assertIn("permissions:", head)
        self.assertIn("contents: read", head)

    def test_pull_request_target_is_never_used(self):
        """Comment lines are excluded: the workflow explains WHY it does not use
        this trigger, and a test that cannot tell the explanation from the thing
        it warns about would push the explanation out of the file."""
        with open(CI_YML, encoding="utf-8") as fh:
            offenders = [line for line in fh.read().splitlines()
                         if "pull_request_target" in line
                         and not line.strip().startswith("#")]
        self.assertEqual(offenders, [], offenders)


class TestThePolicyFile(unittest.TestCase):
    def test_the_committed_policy_loads(self):
        policy = np_automerge.load()
        self.assertEqual(policy["allowed_tiers"], ["standard"])

    def test_it_ships_disabled(self):
        """Promotion is a one-line audited change, not the default state."""
        self.assertFalse(np_automerge.load()["enabled"])

    def test_the_policy_files_classify_themselves_high(self):
        registry = np_risk_tiers.load()
        for path in ("engine/setup/automerge.json",
                     "engine/setup/np_automerge.py",
                     "engine/setup/np-automerge-gate.py"):
            self.assertEqual(np_risk_tiers.tier_for(path, registry), "high", path)

    def test_a_broken_policy_raises_rather_than_defaulting(self):
        for bad in ("", "{not json", '{"schema": 99}',
                    '{"schema": 1, "enabled": "yes", "allowed_tiers": [], "trusted_authors": []}',
                    '{"schema": 1, "enabled": true, "allowed_tiers": "standard", "trusted_authors": []}'):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "automerge.json")
                with open(path, "w") as f:
                    f.write(bad)
                with self.assertRaises(np_automerge.PolicyError, msg=bad):
                    np_automerge.load(path)

    def test_a_missing_policy_raises(self):
        with self.assertRaises(np_automerge.PolicyError):
            np_automerge.load("/nonexistent/automerge.json")



class TestTheGateCliFailsClosed(unittest.TestCase):
    """np-automerge-gate.py writes the record BEFORE it emits the signal that
    acts on it. Enabling an unattended merge with no record of why is the exact
    state the decision artifact exists to prevent."""

    GATE = os.path.abspath(os.path.join(_ENGINE_SETUP, "np-automerge-gate.py"))

    def _run(self, d, tier_policy, out=None, github_output=None, author="trusted"):
        import subprocess
        tp = os.path.join(d, "tier-policy.json")
        with open(tp, "w") as f:
            json.dump(tier_policy, f)
        policy = os.path.join(d, "automerge.json")
        with open(policy, "w") as f:
            json.dump({"schema": 1, "enabled": True, "allowed_tiers": ["standard"],
                       "trusted_authors": ["trusted"]}, f)
        argv = [sys.executable, self.GATE, "--tier-policy", tp,
                "--policy", policy, "--author", author]
        if out:
            argv += ["--out", out]
        env = dict(os.environ)
        env.pop("GITHUB_OUTPUT", None)
        if github_output:
            env["GITHUB_OUTPUT"] = github_output
        return subprocess.run(argv, capture_output=True, text=True, env=env)

    def _eligible(self):
        return {"tier": "standard", "auto_merge_eligible": True, "problems": [],
                "gate_verdicts": {"diff-review": "PASSED"}}

    def test_an_unwritable_record_refuses_to_signal(self):
        with tempfile.TemporaryDirectory() as d:
            gh_out = os.path.join(d, "gh-output")
            rc = self._run(d, self._eligible(),
                           out=os.path.join(d, "no", "such", "dir", "decision.json"),
                           github_output=gh_out)
            self.assertEqual(rc.returncode, 1, rc.stdout + rc.stderr)
            self.assertIn("Refusing to signal", rc.stderr)
            self.assertFalse(os.path.exists(gh_out),
                             "will_enable was signalled with no decision record")

    def test_the_happy_path_signals_true(self):
        with tempfile.TemporaryDirectory() as d:
            gh_out = os.path.join(d, "gh-output")
            out = os.path.join(d, "decision.json")
            rc = self._run(d, self._eligible(), out=out, github_output=gh_out)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            with open(gh_out) as f:
                self.assertIn("will_enable=true", f.read())

    def test_an_untrusted_author_signals_false(self):
        with tempfile.TemporaryDirectory() as d:
            gh_out = os.path.join(d, "gh-output")
            rc = self._run(d, self._eligible(), out=os.path.join(d, "decision.json"),
                           github_output=gh_out, author="stranger")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            with open(gh_out) as f:
                self.assertIn("will_enable=false", f.read())

    def test_a_missing_tier_policy_signals_false(self):
        """A decision is still made and recorded - it is just a no."""
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            gh_out = os.path.join(d, "gh-output")
            policy = os.path.join(d, "automerge.json")
            with open(policy, "w") as f:
                json.dump({"schema": 1, "enabled": True, "allowed_tiers": ["standard"],
                           "trusted_authors": ["trusted"]}, f)
            env = dict(os.environ, GITHUB_OUTPUT=gh_out)
            rc = subprocess.run(
                [sys.executable, self.GATE, "--tier-policy",
                 os.path.join(d, "absent.json"), "--policy", policy,
                 "--author", "trusted"], capture_output=True, text=True, env=env)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            with open(gh_out) as f:
                self.assertIn("will_enable=false", f.read())

    def test_a_broken_policy_exits_one(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            policy = os.path.join(d, "automerge.json")
            with open(policy, "w") as f:
                f.write("{not json")
            rc = subprocess.run(
                [sys.executable, self.GATE, "--policy", policy, "--author", "x"],
                capture_output=True, text=True)
            self.assertEqual(rc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
