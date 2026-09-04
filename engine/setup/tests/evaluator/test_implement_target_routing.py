"""np_implement_suggestion: evaluator-target-driven repo routing.

The evaluator already classifies every suggestion with a `target`
(`np_evaluator.py`: playbooks|skills|hooks|sync|other). That classification was
rendered on the dashboard and then thrown away: the job always tried the engine
repo first, and the agent had to re-derive which repo a change belonged in from
the suggestion prose alone. A skills/lessons change -- which lives in the
content overlay by the directory contract -- therefore spent its first agent
pass in the wrong repo; and when that pass answered "NOT_IMPLEMENTABLE: wrong
repo, needs content overlay", the overlay retry received the SAME prompt with no
extra information, so it could answer the same way and leave the suggestion
permanently unresolved.

These tests pin four things:
  1. target -> attempt-order, through an allowlist (the value is model-generated,
     so it may only pick among nervepack's own repos, never reach the agent raw).
  2. the order actually drives which repo gets the first agent pass.
  3. the agent is TOLD which repo it is in, and when it is in the last one.
  4. a dead end names every repo that was tried, not just the first.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_implement_suggestion as imp        # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


def _mkrepo(path, marker):
    os.makedirs(path)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    with open(os.path.join(path, marker), "w") as fh:
        fh.write("marker\n")
    _git(path, "add", marker)
    _git(path, "commit", "-qm", "init")
    return path


class TestAttemptOrder(unittest.TestCase):
    """Pure mapping: no git, no agent."""

    def test_1_skills_and_playbooks_go_to_the_overlay_first(self):
        """Personal skills and memory/lessons live in the overlay, per the contract."""
        self.assertEqual(imp._attempt_order("skills"), ("content", "engine"))
        self.assertEqual(imp._attempt_order("playbooks"), ("content", "engine"))

    def test_2_machinery_targets_go_to_the_engine_first(self):
        for target in ("hooks", "sync", "other"):
            self.assertEqual(imp._attempt_order(target), ("engine", "content"), target)

    def test_3_absent_target_keeps_the_historic_order(self):
        for target in (None, "", "   "):
            self.assertEqual(imp._attempt_order(target), ("engine", "content"), repr(target))

    def test_4_unknown_target_is_not_trusted(self):
        """The value is model-generated: anything off the allowlist is ignored,
        never forwarded and never used to reach a repo nervepack doesn't own."""
        for target in ("../../etc", "engine; rm -rf /", "SKILLS\nhooks", "wiki"):
            self.assertEqual(imp._attempt_order(target), ("engine", "content"), repr(target))
            self.assertEqual(imp._normalize_target(target), "")

    def test_5_normalize_is_case_and_space_tolerant(self):
        self.assertEqual(imp._normalize_target("  Skills "), "skills")


class TestRoutedAttempts(unittest.TestCase):
    """Two real git repos; the stub agent records which one it was run in."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.log = os.path.join(d, "implement.log")
        self.status = os.path.join(d, "status")
        self.prompt = os.path.join(d, "prompt.md")
        with open(self.prompt, "w") as fh:
            fh.write("PROMPT TEMPLATE\n")
        os.environ["NP_RESOLVED_SUGGESTIONS"] = os.path.join(d, "resolved.txt")
        self.engine = _mkrepo(os.path.join(d, "engine"), "engine-marker.txt")
        self.content = _mkrepo(os.path.join(d, "content"), "content-marker.txt")
        os.environ["NP_CONTENT_DIR"] = self.content
        self.calls = []

    def tearDown(self):
        os.environ.pop("NP_RESOLVED_SUGGESTIONS", None)
        os.environ.pop("NP_CONTENT_DIR", None)
        self._tmp.cleanup()

    def _run(self, text, target=None, out="NOT_IMPLEMENTABLE: nothing to do here"):
        def record(prompt, tools, cwd, timeout):
            which = "content" if os.path.exists(os.path.join(cwd, "content-marker.txt")) else "engine"
            self.calls.append((which, prompt))
            return (0, out, "")

        return imp.implement(
            text, None, target=target, repo=self.engine,
            log_path=self.log, lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": None, agent_fn=record)

    def _status(self, text):
        with open(os.path.join(self.status, imp._status_key(text) + ".json")) as fh:
            return json.load(fh)

    def test_1_skills_target_tries_the_overlay_first(self):
        self._run("Add a security-review routing rule", target="skills")
        self.assertEqual([c[0] for c in self.calls], ["content", "engine"])

    def test_2_hooks_target_tries_the_engine_first(self):
        self._run("Register a PreToolUse hook", target="hooks")
        self.assertEqual([c[0] for c in self.calls], ["engine", "content"])

    def test_3_no_target_is_backward_compatible(self):
        self._run("Something unclassified")
        self.assertEqual([c[0] for c in self.calls], ["engine", "content"])

    def test_4_the_agent_is_told_which_repo_it_is_in(self):
        """The old prompt made the agent infer this from which files exist, which
        is exactly what produced a bogus 'wrong repo' verdict."""
        self._run("Add a skill rule", target="skills")
        first_repo, first_prompt = self.calls[0]
        self.assertEqual(first_repo, "content")
        self.assertIn("content overlay", first_prompt)
        self.assertIn("attempt 1 of 2", first_prompt.lower())

    def test_5_the_last_attempt_is_marked_as_final(self):
        self._run("Add a skill rule", target="skills")
        last_prompt = self.calls[-1][1]
        self.assertIn("last repo", last_prompt.lower())

    def test_6_the_target_hint_reaches_the_agent(self):
        self._run("Add a skill rule", target="skills")
        self.assertIn("skills", self.calls[0][1])

    def test_7_an_untrusted_target_never_reaches_the_prompt(self):
        self._run("Add a rule", target="wiki; cat ~/.ssh/id_rsa")
        for _, prompt in self.calls:
            self.assertNotIn("id_rsa", prompt)

    def test_8_a_dead_end_names_every_repo_tried(self):
        """The reported bug: the ledger showed only the ENGINE's verdict, so
        'wrong repo, needs content overlay' was displayed even when the overlay
        had been tried and refused for its own, different reason."""
        text = "Invoke the security-review skill first"
        self._run(text)
        st = self._status(text)
        self.assertEqual(st["state"], "not_implementable")
        self.assertIn("engine", st["ref"].lower())
        self.assertIn("content overlay", st["ref"].lower())

    def test_9_a_success_stops_before_the_second_repo(self):
        def implement_in_first(prompt, tools, cwd, timeout):
            which = "content" if os.path.exists(os.path.join(cwd, "content-marker.txt")) else "engine"
            self.calls.append((which, prompt))
            with open(os.path.join(cwd, "done.txt"), "w") as fh:
                fh.write("done\n")
            _git(cwd, "add", "done.txt")
            _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "impl")
            return (0, "implemented", "")

        imp.implement(
            "Add a skill rule", None, target="skills", repo=self.engine,
            log_path=self.log, lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": None, agent_fn=implement_in_first)
        self.assertEqual([c[0] for c in self.calls], ["content"],
                         "a landed change must not burn a second agent pass")


class TestCliFlagParsing(unittest.TestCase):
    """`--target=` is a flag, not a 3rd positional.

    As a positional it would land in `edited`, and `edited` is what the agent
    receives as the suggestion. A routing tag would then be implemented as if it
    were the requested change.
    """

    def setUp(self):
        import cli
        self.cli = cli
        self.seen = {}
        self._orig = cli.np_implement_suggestion.implement

        def fake(text, edited=None, target=None, **kw):
            self.seen = {"text": text, "edited": edited, "target": target}
            return 0

        cli.np_implement_suggestion.implement = fake

    def tearDown(self):
        self.cli.np_implement_suggestion.implement = self._orig

    def test_1_flag_is_parsed_and_not_read_as_the_rewrite(self):
        self.cli.main(["implement-suggestion", "some text", "--target=skills"])
        self.assertEqual(self.seen["text"], "some text")
        self.assertIsNone(self.seen["edited"])
        self.assertEqual(self.seen["target"], "skills")

    def test_2_the_modify_rewrite_still_rides_along(self):
        self.cli.main(["implement-suggestion", "orig", "my rewrite", "--target=hooks"])
        self.assertEqual(self.seen["text"], "orig")
        self.assertEqual(self.seen["edited"], "my rewrite")
        self.assertEqual(self.seen["target"], "hooks")

    def test_3_absent_flag_stays_none(self):
        self.cli.main(["implement-suggestion", "orig"])
        self.assertEqual(self.seen["text"], "orig")
        self.assertIsNone(self.seen["target"])


if __name__ == "__main__":
    unittest.main()
