# np-test: implement-kinds | compact-apply and graduate jobs reuse the implement queue
"""np_implement_suggestion job kinds.

The dashboard's compact-proposal Apply and graduation Graduate buttons reuse the
suggestion Implement machinery. A `kind` picks the agent prompt, runs in the
content overlay only, and skips the suggestion ledger.
"""
import os
import subprocess
import sys
import tempfile
import unittest

# Never read or write the real per-machine applied marker.
os.environ["NP_COMPACT_APPLIED"] = os.path.join(tempfile.mkdtemp(), "applied.json")

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


class TestKinds(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.status = os.path.join(d, "status")
        self.prompt = os.path.join(d, "prompt.md")
        with open(self.prompt, "w") as fh:
            fh.write("SUGGESTION TEMPLATE\n")
        os.environ["NP_RESOLVED_SUGGESTIONS"] = os.path.join(d, "resolved.txt")
        self.engine = _mkrepo(os.path.join(d, "engine"), "engine-marker.txt")
        self.content = _mkrepo(os.path.join(d, "content"), "content-marker.txt")
        # The jobs refuse a target origin lacks, so seed the entries the tests name.
        os.makedirs(os.path.join(self.content, "compact-proposals"))
        os.makedirs(os.path.join(self.content, "memory", "lessons"))
        with open(os.path.join(self.content, "compact-proposals", "2026-09-30.md"), "w") as fh:
            fh.write("### a vs b\n**Recommendation:** merge a into b\n")
        for name in ("s1", "security-review"):
            with open(os.path.join(self.content, "memory", "lessons", name + ".md"), "w") as fh:
                fh.write("---\nstatus: active\n---\nbody\n")
        _git(self.content, "add", "-A")
        _git(self.content, "commit", "-qm", "seed")
        os.environ["NP_CONTENT_DIR"] = self.content
        self.calls, self.resolved = [], []

    def tearDown(self):
        os.environ.pop("NP_RESOLVED_SUGGESTIONS", None)
        os.environ.pop("NP_CONTENT_DIR", None)
        self._tmp.cleanup()

    def _run(self, text, kind):
        def record(prompt, tools, cwd, timeout):
            which = "content" if os.path.exists(os.path.join(cwd, "content-marker.txt")) else "engine"
            self.calls.append((which, prompt))
            return (0, "NOT_IMPLEMENTABLE: test", "")

        return imp.implement(
            text, None, repo=self.engine, kind=kind,
            log_path=os.path.join(self._tmp.name, "log"),
            lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": self.resolved.append(t), agent_fn=record)

    def test_compact_kind_uses_its_prompt_and_overlay_first(self):
        self._run("compact-proposals/2026-09-30.md :: a vs b", "compact")
        self.assertEqual(self.calls[0][0], "content")
        self.assertIn("compact proposal", self.calls[0][1].lower())
        self.assertNotIn("SUGGESTION TEMPLATE", self.calls[0][1])

    def test_graduate_kind_uses_its_prompt(self):
        self._run("strategy:security-review", "graduate")
        self.assertIn("graduate one lesson into a skill", self.calls[0][1])
        self.assertEqual([c[0] for c in self.calls], ["content"])

    def test_unknown_kind_falls_back_to_suggestion(self):
        self._run("Do a thing", "../../etc")
        self.assertIn("SUGGESTION TEMPLATE", self.calls[0][1])

    def test_kind_survives_the_queue(self):
        qdir = imp.queue_dir(self.status)
        self.assertTrue(imp.enqueue(qdir, self.status, "x", kind="compact"))
        self.assertEqual(imp.queue_entries(qdir)[0][1]["kind"], "compact")

    def test_kind_job_never_gets_bash_and_lands_on_the_overlay(self):
        tools_seen = []
        # Force pr mode: overlay kind jobs must still land direct.
        orig = imp.np_toggle.param
        imp.np_toggle.param = lambda name, default=None: "pr" if name == "evaluator.implement_mode" else orig(name, default)
        self.addCleanup(setattr, imp.np_toggle, "param", orig)
        base_before = _git(self.content, "rev-parse", "main").stdout.strip()

        def agent(prompt, tools, cwd, timeout):
            tools_seen.append(tools)
            with open(os.path.join(cwd, "edit-%d.md" % len(tools_seen)), "w") as fh:
                fh.write("edited\n")
            return (0, "done", "")

        for kind, text in (("compact", "2026-09-30.md :: a vs b"), ("graduate", "strategy:s1")):
            imp.implement(
                text, None, repo=self.engine, kind=kind,
                log_path=os.path.join(self._tmp.name, "log"),
                lock_path=os.path.join(self._tmp.name, "lock"),
                status_dir=self.status, prompt_file=self.prompt,
                resolve_fn=lambda t, note="": None, agent_fn=agent,
                gh_pr_create_fn=lambda *a: "")
        self.assertEqual(len(tools_seen), 2)
        for t in tools_seen:
            self.assertNotIn("Bash", t.split())
        # The harness committed and landed direct on the overlay base.
        # The overlay has no PR gate. The engine never moved.
        self.assertNotEqual(_git(self.content, "rev-parse", "main").stdout.strip(), base_before)
        log = _git(self.content, "log", "--format=%s", "main").stdout
        self.assertIn("compact:", log)
        self.assertIn("graduate:", log)

    def _troubleshoot(self, agent, mode):
        orig = imp.np_toggle.param
        imp.np_toggle.param = lambda name, default=None: mode if name == "evaluator.implement_mode" else orig(name, default)
        self.addCleanup(setattr, imp.np_toggle, "param", orig)
        return imp.implement(
            "job:compact", None, repo=self.engine, kind="troubleshoot",
            log_path=os.path.join(self._tmp.name, "log"),
            lock_path=os.path.join(self._tmp.name, "lock"),
            status_dir=self.status, prompt_file=self.prompt,
            resolve_fn=lambda t, note="": self.resolved.append(t), agent_fn=agent,
            gh_pr_create_fn=lambda *a: "")

    def test_troubleshoot_engine_fix_follows_implement_mode(self):
        tools_seen = []

        def agent(prompt, tools, cwd, timeout):
            tools_seen.append(tools)
            if not os.path.exists(os.path.join(cwd, "engine-marker.txt")):
                return (0, "NOT_IMPLEMENTABLE: wrong repo", "")
            with open(os.path.join(cwd, "fix.txt"), "w") as fh:
                fh.write("fixed\n")
            return (0, "done", "")

        engine_main = _git(self.engine, "rev-parse", "main").stdout.strip()
        content_main = _git(self.content, "rev-parse", "main").stdout.strip()
        self._troubleshoot(agent, "pr")
        self.assertEqual(len(tools_seen), 1, "engine fix must stop the repo walk")
        self.assertIn("Bash", tools_seen[0].split())
        self.assertEqual(_git(self.engine, "rev-parse", "main").stdout.strip(), engine_main,
                         "pr mode keeps the engine fix off main")
        self.assertEqual(_git(self.content, "rev-parse", "main").stdout.strip(), content_main)
        branch = _git(self.engine, "log", "--format=%s", "np-suggest/job-compact").stdout
        self.assertIn("troubleshoot:", branch)

    def test_troubleshoot_diagnosis_only_reports_on_the_row(self):
        self._troubleshoot(lambda p, t, c, to: (0, "NOT_IMPLEMENTABLE: launchd plist missing, run installer", ""), "pr")
        import json
        files = [f for f in os.listdir(self.status) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.status, files[0])) as fh:
            st = json.load(fh)
        self.assertEqual(st["state"], "not_implementable")
        self.assertIn("launchd plist missing", st["ref"])
        self.assertEqual(self.resolved, [], "troubleshoot never touches the suggestion ledger")

    def test_suggestion_job_keeps_bash(self):
        seen = []
        imp.implement("Do a thing", None, repo=self.engine,
                      log_path=os.path.join(self._tmp.name, "log"),
                      lock_path=os.path.join(self._tmp.name, "lock"),
                      status_dir=self.status, prompt_file=self.prompt,
                      resolve_fn=lambda t, note="": None,
                      agent_fn=lambda p, tools, c, t: (seen.append(tools), (0, "NOT_IMPLEMENTABLE: x", ""))[1])
        self.assertIn("Bash", seen[0].split())


class TestRestrictedArgv(unittest.TestCase):
    def test_kind_job_argv_has_no_bash_and_no_bypass(self):
        import np_model
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        orig = imp.np_bashlib.run_killtree
        np_model.np_bashlib.run_killtree = fake_run
        self.addCleanup(setattr, np_model.np_bashlib, "run_killtree", orig)
        os.environ.pop("IMPLEMENT_LLM", None)
        os.environ["NP_LLM_BACKEND"] = "claude"
        self.addCleanup(os.environ.pop, "NP_LLM_BACKEND", None)
        imp._default_agent_fn("p", imp._KIND_TOOLS, None, 5)
        argv = captured["argv"]
        joined = " ".join(argv)
        self.assertNotIn("bypassPermissions", joined)
        self.assertIn("acceptEdits", argv)
        tools = argv[argv.index("--tools") + 1]
        self.assertNotIn("Bash", tools)
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "Bash")
        allowed = argv[argv.index("--allowedTools") + 1]
        self.assertNotIn("Bash", allowed)

    def test_troubleshoot_kind_is_known_with_its_own_prompt(self):
        self.assertEqual(imp._normalize_kind("TroubleShoot"), "troubleshoot")
        prompt = os.path.join(imp._NP, "agents", imp._KIND_PROMPTS["troubleshoot"])
        self.assertTrue(os.path.isfile(prompt), prompt)

    def test_troubleshoot_has_no_lesson_precheck(self):
        # Any non-compact kind used to fall through to the lesson check.
        self.assertIsNone(imp._kind_precheck_fn("troubleshoot", "job:compact"))
        self.assertIsNotNone(imp._kind_precheck_fn("graduate", "failure:x"))

    def test_troubleshoot_keeps_bash_and_overlay_kinds_do_not(self):
        self.assertIn("Bash", imp._tools_for("troubleshoot").split())
        for kind in ("compact", "graduate"):
            self.assertNotIn("Bash", imp._tools_for(kind).split())
        self.assertEqual(imp._tools_for(""), imp._AGENT_TOOLS)

    def test_suggestion_argv_unchanged(self):
        import np_model
        argv = np_model.agent_argv("m", imp._AGENT_TOOLS)
        self.assertIn("bypassPermissions", argv)
        self.assertIn("Bash", argv)


if __name__ == "__main__":
    unittest.main()
