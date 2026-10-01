"""np_model per-feature model selection, the availability probe, and the
implement job's model-rejected handling."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
for _p in (_SETUP, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_model  # noqa: E402

REJECT = ("There's an issue with the selected model (claude-bad-1). It may not exist "
          "or you may not have access to it.")

# Stub CLI: rejects `--model claude-bad-1`, answers ok otherwise.
STUB = """#!/usr/bin/env bash
cat >/dev/null
for a in "$@"; do [ "$prev" = "--model" ] && model="$a"; prev="$a"; done
if [ "$model" = "claude-bad-1" ]; then echo "%s"; exit 1; fi
echo ok
""" % REJECT


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.conf = os.path.join(d, "toggles.conf")
        self.local = os.path.join(d, "toggles.local")
        self.cache = os.path.join(d, "model-probe.json")
        stub = os.path.join(d, "claude")
        with open(stub, "w") as fh:
            fh.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        self.write_conf("")
        self.env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.conf, "NP_TOGGLES_LOCAL": self.local,
            "NP_MODEL_PROBE_CACHE": self.cache, "CLAUDE_BIN": stub,
            "NP_OWN_SESSIONS_DIR": os.path.join(d, "own"), "NP_LLM_BACKEND": "claude"})
        self.env.start()
        for v in ("NP_LLM_MODEL_CHEAP", "NP_LLM_MODEL_AGENT"):
            os.environ.pop(v, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write_conf(self, params):
        with open(self.conf, "w") as fh:
            fh.write("models|shared|runtime|on|%s\n" % params)

    def write_local(self, text):
        with open(self.local, "w") as fh:
            fh.write(text)


class TestResolution(Base):
    def test_default_when_nothing_is_set(self):
        self.assertEqual(np_model.resolve_model("cheap"), np_model.DEFAULT_CHEAP)
        self.assertEqual(np_model.resolve_model("agent", "implement"), np_model.DEFAULT_AGENT)

    def test_no_default_is_opus(self):
        for m in (np_model.DEFAULT_CHEAP, np_model.DEFAULT_AGENT):
            self.assertNotIn("opus", m)

    def test_tier_param_beats_default(self):
        self.write_conf("agent=tier-agent,implement=")
        self.assertEqual(np_model.resolve_model("agent", "implement"), "tier-agent")

    def test_feature_param_beats_tier_param(self):
        self.write_conf("agent=tier-agent,episodic_maintain=feat-m")
        self.assertEqual(np_model.resolve_model("agent", "episodic-maintain"), "feat-m")
        self.assertEqual(np_model.resolve_model("agent", "memory-promote"), "tier-agent")

    def test_local_override_beats_conf(self):
        self.write_conf("cheap=conf-cheap,evaluator=conf-eval")
        self.write_local("models.evaluator=local-eval\n")
        self.assertEqual(np_model.resolve_model("cheap", "evaluator"), "local-eval")

    def test_empty_local_override_inherits(self):
        self.write_conf("cheap=conf-cheap")
        self.write_local("models.capture=\n")
        self.assertEqual(np_model.resolve_model("cheap", "capture"), "conf-cheap")

    def test_env_beats_everything(self):
        self.write_conf("agent=tier-agent,implement=feat-m")
        with mock.patch.dict(os.environ, {"NP_LLM_MODEL_AGENT": "env-m"}):
            self.assertEqual(np_model.resolve_model("agent", "implement"), "env-m")

    def test_argv_carries_the_feature_model(self):
        self.write_conf("cheap=c,review=r")
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return mock.Mock(stdout="ok", stderr="", returncode=0)
        with mock.patch.object(np_model.np_bashlib, "run_killtree", fake_run):
            np_model.complete("p", feature="review")
        self.assertEqual(seen["argv"][seen["argv"].index("--model") + 1], "r")


class TestProbe(Base):
    def test_model_error_line(self):
        self.assertIn("issue with the selected model", np_model.model_error_line("x\n" + REJECT))
        self.assertEqual(np_model.model_error_line("all fine"), "")

    def test_classify(self):
        self.assertEqual(np_model.classify_probe(0, "ok", ""), ("available", ""))
        self.assertEqual(np_model.classify_probe(1, REJECT, "")[0], "missing")
        self.assertEqual(np_model.classify_probe(0, "", REJECT)[0], "missing")
        self.assertEqual(np_model.classify_probe(0, "Not logged in", "")[0], "error")
        self.assertEqual(np_model.classify_probe(2, "", "boom")[0], "error")

    def test_probe_caches_available_and_missing(self):
        self.assertEqual(np_model.probe("claude-good-1")["status"], "available")
        bad = np_model.probe("claude-bad-1")
        self.assertEqual(bad["status"], "missing")
        with open(self.cache) as fh:
            data = json.load(fh)
        self.assertEqual(data["claude-good-1"]["status"], "available")
        self.assertEqual(data["claude-bad-1"]["status"], "missing")
        self.assertIn("ts", data["claude-bad-1"])

    def test_complete_records_a_rejected_model(self):
        self.write_conf("cheap=claude-bad-1")
        np_model.complete("p", feature="capture")
        self.assertEqual(np_model.load_probe_cache()["claude-bad-1"]["status"], "missing")

    def test_inventory_lists_the_current_ids(self):
        ids = {m["id"] for m in np_model.inventory()}
        for m in ("claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5",
                  "claude-fable-5-1", "claude-sonnet-4-6"):
            self.assertIn(m, ids)
        self.assertIn(np_model.DEFAULT_AGENT, ids)


class TestImplementModelError(Base):
    def setUp(self):
        super().setUp()
        import np_implement_suggestion
        self.imp = np_implement_suggestion
        self.write_conf("agent=claude-bad-1")

    def test_agent_call_raises_and_marks_model_missing(self):
        def agent_fn(prompt, tools, cwd, timeout):
            return 1, "", REJECT
        with self.assertRaises(self.imp.ModelRejected) as cm:
            self.imp._agent_call("p", self.tmp.name, agent_fn, os.path.join(self.tmp.name, "log"))
        self.assertEqual(cm.exception.model, "claude-bad-1")
        self.assertEqual(np_model.load_probe_cache()["claude-bad-1"]["status"], "missing")

    def test_status_carries_model_error_flag(self):
        status = os.path.join(self.tmp.name, "status")
        ctx = {"repo": self.tmp.name, "log_path": os.path.join(self.tmp.name, "log"),
               "status_dir": status, "prompt_file": "", "agent_fn": None,
               "resolve_fn": None, "gh_pr_create_fn": None}

        def boom(*a, **k):
            raise self.imp.ModelRejected("claude-bad-1", REJECT)
        with mock.patch.object(self.imp, "_attempt_repo", boom), \
                mock.patch.object(self.imp, "_resolve_content_repo", lambda r: None), \
                mock.patch.object(self.imp.np_suggestion_resolve, "is_resolved", lambda t: False):
            self.imp._run_one("do x", None, None, ctx)
        with open(os.path.join(status, self.imp._status_key("do x") + ".json")) as fh:
            st = json.load(fh)
        self.assertEqual(st["state"], "failed")
        self.assertTrue(st["model_error"])
        self.assertEqual(st["model"], "claude-bad-1")


if __name__ == "__main__":
    unittest.main()
