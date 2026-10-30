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

    def test_suggestion_argv_unchanged(self):
        import np_model
        argv = np_model.agent_argv("m", imp._AGENT_TOOLS)
        self.assertIn("bypassPermissions", argv)
        self.assertIn("Bash", argv)


if __name__ == "__main__":
    unittest.main()
