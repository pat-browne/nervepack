"""Direct unit tests for np_doctor.py -- the full-parity Python doctor (phase 15,
np-doctor.sh retired). Ports test_doctor.sh's scenarios (llm-cli via a stubbed
np_model.complete, git-sync, toggles, content, adapter MISSING/UNSUPPORTED/
wired-PASS/wired-FAIL, hook-scripts, scheduled-auth-token) and drives
np_doctor.report() in-process in a hermetic env.

Hermetic: every test seeds temp dirs + os.environ (NP_DIR / NP_CAPABILITIES /
NP_ADAPTER / CLAUDE_SETTINGS / NP_CONTENT_DIR / NP_TEAM_DIR / NP_TOGGLES_* /
NP_CLAUDE_TOKEN_FILE / HOME) and restores it after -- never the dev box's real
git/settings/token/adapter files. The llm-cli check is stubbed (no real model
call) and adapter `verify` fixtures are SHELL-AGNOSTIC (`python3 -c
"import sys;sys.exit(N)"`) so they run identically under sh (Linux/macOS) and
cmd.exe (the Git-bash Windows lane) via subprocess shell=True. stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_doctor  # noqa: E402
import np_model  # noqa: E402

_CAPS = os.path.join(_ENGINE_SETUP, "..", "onboard", "capabilities.json")

# A verify command that exits 0 / 1 in BOTH sh and cmd.exe (shell=True) -- never a
# bash-only pipe/grep, which would fail under cmd.exe on the Windows lane.
_VERIFY_PASS = 'python3 -c "import sys;sys.exit(0)"'
_VERIFY_FAIL = 'python3 -c "import sys;sys.exit(1)"'
# On some hosts `python3` is only `python`; probe once so the fixtures are portable.
if subprocess.run(_VERIFY_PASS, shell=True,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    _VERIFY_PASS = 'python -c "import sys;sys.exit(0)"'
    _VERIFY_FAIL = 'python -c "import sys;sys.exit(1)"'


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self._saved_env = dict(os.environ)
        self._saved_complete = np_model.complete
        # Point everything the doctor reads at hermetic temp locations.
        os.environ["HOME"] = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.tmp, "home", ".config", "nervepack"))
        os.environ["NP_CAPABILITIES"] = os.path.abspath(_CAPS)
        os.environ["NP_ADAPTER"] = os.path.join(self.tmp, "adapter.json")
        os.environ["NP_DIR"] = self._git_repo()
        os.environ["NP_CONTENT_DIR"] = self._mkdir("content")
        os.environ["CLAUDE_SETTINGS"] = os.path.join(self.tmp, "no-settings.json")
        os.environ["NP_CLAUDE_TOKEN_FILE"] = os.path.join(self.tmp, "token")
        os.environ.pop("NP_TEAM_DIR", None)
        os.environ["NP_TOGGLES_CONF"] = os.path.join(_ENGINE_SETUP, "toggles.conf")
        os.environ["NP_TOGGLES_LOCAL"] = os.path.join(self.tmp, "toggles.local")
        # Default: llm-cli returns text (PASS). Individual tests override.
        np_model.complete = lambda prompt, *a, **k: "ok"

    def tearDown(self):
        np_model.complete = self._saved_complete
        os.environ.clear()
        os.environ.update(self._saved_env)
        self._tmp.cleanup()

    # --- helpers -----------------------------------------------------------
    def _mkdir(self, name):
        p = os.path.join(self.tmp, name)
        os.makedirs(p, exist_ok=True)
        return p

    def _git_repo(self):
        repo = self._mkdir("repo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                        "https://example.com/x.git"], check=True)
        return repo

    def _write_adapter(self, caps):
        with open(os.environ["NP_ADAPTER"], "w", encoding="utf-8") as f:
            json.dump({"host": "test", "capabilities": caps}, f)

    def _all_wired(self, verify=None):
        v = verify if verify is not None else _VERIFY_PASS
        return {c: {"status": "wired", "verify": v}
                for c in ("knowledge", "session-start", "session-end-capture",
                          "session-end-flush", "scheduled-maint")}

    def _line(self, text, cap_id):
        for ln in text.splitlines():
            if (" " + cap_id + " ") in ln or ln.rstrip().endswith(" " + cap_id):
                if cap_id in ln.split():
                    return ln
        for ln in text.splitlines():
            if cap_id in ln.split():
                return ln
        return ""

    # --- clean install / exit codes ---------------------------------------
    def test_clean_install_all_must_pass_exit0(self):
        self._write_adapter(self._all_wired())
        text, code = np_doctor.report()
        self.assertEqual(code, 0, text)
        self.assertIn("MUST tier OK", text)
        self.assertIn("nervepack doctor — contract:", text)
        # No capability is N/A'd anymore; all 16 caps are reported.
        self.assertNotIn("N/A", text)
        for cap in ("llm-cli", "git-sync", "toggles", "content", "knowledge"):
            self.assertRegex(self._line(text, cap), r"\bPASS\b", cap)

    def test_broken_must_knowledge_missing_exit1(self):
        # adapter present but missing the knowledge (MUST) entry -> MISSING -> exit 1.
        self._write_adapter({"session-start": {"status": "wired", "verify": _VERIFY_PASS}})
        text, code = np_doctor.report()
        self.assertEqual(code, 1, text)
        self.assertIn("MUST tier FAILED", text)
        self.assertRegex(self._line(text, "knowledge"), r"MISSING")

    def test_caps_unreadable_exit2(self):
        os.environ["NP_CAPABILITIES"] = os.path.join(self.tmp, "nope.json")
        text, code = np_doctor.report()
        self.assertEqual(code, 2, text)
        self.assertIn("capabilities.json not readable", text)

    # --- llm-cli (MUST core, stubbed) -------------------------------------
    def test_llm_cli_pass(self):
        self._write_adapter(self._all_wired())
        np_model.complete = lambda prompt, *a, **k: "pong\n"
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "llm-cli"), r"\bPASS\b")
        self.assertEqual(code, 0)

    def test_llm_cli_fail_empty_output(self):
        self._write_adapter(self._all_wired())
        np_model.complete = lambda prompt, *a, **k: "\n"   # only newlines -> empty
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "llm-cli"), r"\bFAIL\b")
        self.assertEqual(code, 1)   # llm-cli is MUST

    def test_llm_cli_fail_exception(self):
        self._write_adapter(self._all_wired())
        def boom(*a, **k):
            raise RuntimeError("backend down")
        np_model.complete = boom
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "llm-cli"), r"\bFAIL\b")
        self.assertEqual(code, 1)

    # --- adapter checks ----------------------------------------------------
    def test_adapter_missing_file(self):
        # No adapter.json at all -> every adapter cap MISSING (knowledge MUST -> exit 1).
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "knowledge"), r"MISSING")
        self.assertRegex(self._line(text, "session-start"), r"MISSING")
        self.assertIn("adapter: (none at", text)
        self.assertEqual(code, 1)

    def test_adapter_unsupported_should_still_exit0(self):
        caps = {"knowledge": {"status": "wired", "verify": _VERIFY_PASS}}
        for c in ("session-start", "session-end-capture", "session-end-flush",
                  "scheduled-maint"):
            caps[c] = {"status": "unsupported", "verify": ""}
        self._write_adapter(caps)
        text, code = np_doctor.report()
        self.assertEqual(code, 0, text)
        self.assertRegex(self._line(text, "session-start"), r"UNSUPPORTED")

    def test_adapter_wired_pass_and_fail(self):
        caps = self._all_wired()
        caps["session-start"] = {"status": "wired", "verify": _VERIFY_FAIL}
        self._write_adapter(caps)
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "knowledge"), r"\bPASS\b")
        self.assertRegex(self._line(text, "session-start"), r"\bFAIL\b")
        # session-start is SHOULD, knowledge (the only wired MUST) passed -> exit 0.
        self.assertEqual(code, 0, text)

    def test_adapter_wired_but_empty_verify_is_fail(self):
        caps = self._all_wired()
        caps["knowledge"] = {"status": "wired", "verify": ""}   # wired, no verify
        self._write_adapter(caps)
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "knowledge"), r"\bFAIL\b")
        self.assertEqual(code, 1)   # knowledge MUST

    # --- hook-scripts (SHOULD core) ---------------------------------------
    def test_hook_scripts_absent_settings_pass(self):
        self._write_adapter(self._all_wired())
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "hook-scripts"), r"PASS \(no settings.json")

    def test_hook_scripts_all_present_pass(self):
        self._write_adapter(self._all_wired())
        guard = os.path.join(self.tmp, "real-guard.sh")
        open(guard, "w").close()
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": guard}]}]}}, f)
        os.environ["CLAUDE_SETTINGS"] = settings
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "hook-scripts"), r"\bPASS\b")

    def test_hook_scripts_missing_named_fail_still_exit0(self):
        self._write_adapter(self._all_wired())
        # Forward-slash paths: real hook commands are registered forward-slash
        # (~/Code/...) even on Windows, and the hook-scripts check treats a token
        # with no "/" as a bare command name. os.path.join would give backslashes
        # on the Windows lane -> wrongly skipped as a bare name (would spuriously PASS).
        gone1 = os.path.join(self.tmp, "missing-guard.sh").replace(os.sep, "/")
        gone2 = os.path.join(self.tmp, "another-gone.sh").replace(os.sep, "/")
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": gone1}]}],
                "SessionStart": [{"matcher": "", "hooks": [
                    {"type": "command", "command": "np-toggle"},  # bare name -> skipped
                    {"type": "command", "command": gone2 + " --flag"}]}]}}, f)
        os.environ["CLAUDE_SETTINGS"] = settings
        text, code = np_doctor.report()
        line = self._line(text, "hook-scripts")
        self.assertRegex(line, r"\bFAIL\b")
        self.assertIn("missing-guard.sh", line)
        self.assertIn("another-gone.sh", line)
        self.assertEqual(code, 0)   # hook-scripts is SHOULD

    def test_hook_scripts_tilde_expands(self):
        self._write_adapter(self._all_wired())
        # A hook command that starts with ~/ must be expanded against HOME.
        script_rel = os.path.join(os.environ["HOME"], "hooks", "h.sh")
        os.makedirs(os.path.dirname(script_rel))
        open(script_rel, "w").close()
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"hooks": {"SessionStart": [{"matcher": "", "hooks": [
                {"type": "command", "command": "~/hooks/h.sh"}]}]}}, f)
        os.environ["CLAUDE_SETTINGS"] = settings
        text, _ = np_doctor.report()
        self.assertRegex(self._line(text, "hook-scripts"), r"\bPASS\b")

    # --- pii_filter_full (SHOULD core) ------------------------------------
    def test_pii_filter_present_and_absent(self):
        np = os.environ["NP_DIR"]
        saved = sys.modules.get("presidio_analyzer")
        try:
            sys.modules["presidio_analyzer"] = types.ModuleType("presidio_analyzer")
            self.assertEqual(np_doctor._core_check("pii_filter_full", np), "PASS")
            sys.modules["presidio_analyzer"] = None   # forces ImportError
            self.assertEqual(
                np_doctor._core_check("pii_filter_full", np),
                "FAIL (run: python3 engine/nervepack_engine/cli.py setup install-pii-deps)")
        finally:
            if saved is None:
                sys.modules.pop("presidio_analyzer", None)
            else:
                sys.modules["presidio_analyzer"] = saved

    # --- scheduled-auth-token (SHOULD core) -------------------------------
    def test_scheduled_auth_token_missing_warn(self):
        self._write_adapter(self._all_wired())
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "scheduled-auth-token"),
                         r"WARN \(no scheduled-auth token")
        self.assertEqual(code, 0)   # SHOULD

    def test_scheduled_auth_token_ok_pass(self):
        self._write_adapter(self._all_wired())
        tok = os.environ["NP_CLAUDE_TOKEN_FILE"]
        with open(tok, "w") as f:
            f.write("secret")
        with open(tok + ".issued", "w") as f:
            f.write(date.today().strftime("%Y-%m-%d"))
        text, _ = np_doctor.report()
        self.assertRegex(self._line(text, "scheduled-auth-token"), r"PASS \(ok ")

    def test_scheduled_auth_token_warn_window(self):
        self._write_adapter(self._all_wired())
        tok = os.environ["NP_CLAUDE_TOKEN_FILE"]
        with open(tok, "w") as f:
            f.write("secret")
        old = (date.today() - timedelta(days=350)).strftime("%Y-%m-%d")
        with open(tok + ".issued", "w") as f:
            f.write(old)
        text, _ = np_doctor.report()
        self.assertRegex(self._line(text, "scheduled-auth-token"),
                         r"WARN \(rotation window")

    # --- team (SHOULD core) -----------------------------------------------
    def test_team_none_configured_pass(self):
        self._write_adapter(self._all_wired())
        text, _ = np_doctor.report()
        self.assertRegex(self._line(text, "team"), r"PASS \(no team layer configured\)")

    def test_team_configured_shows_dir(self):
        self._write_adapter(self._all_wired())
        team = self._mkdir("team")
        os.environ["NP_TEAM_DIR"] = team
        text, _ = np_doctor.report()
        line = self._line(text, "team")
        self.assertRegex(line, r"\bPASS\b")
        self.assertIn(team, line)

    def test_team_merge_mode_reported(self):
        self._write_adapter(self._all_wired())
        team = self._mkdir("team")
        os.environ["NP_TEAM_DIR"] = team
        with open(os.environ["NP_TOGGLES_LOCAL"], "w") as f:
            f.write("team=on\nteam.merge=concatenate\n")
        text, _ = np_doctor.report()
        self.assertIn("concatenate", self._line(text, "team"))

    # --- review-gap regression guards (phase-15 review) --------------------
    def test_team_over_cap_warns(self):
        # >4 team dirs -> np_content.team_dirs() rejects (over-cap) -> [] while
        # team_origin is "env" (not "none") -> the invalid/over-cap WARN branch.
        self._write_adapter(self._all_wired())
        os.environ["NP_TEAM_DIR"] = ",".join(self._mkdir("t%d" % i) for i in range(5))
        text, _ = np_doctor.report()
        line = self._line(text, "team")
        self.assertIn("WARN", line)
        self.assertIn("invalid", line)

    def test_dashboard_data_split_missing_warns_then_single_repo_passes(self):
        self._write_adapter(self._all_wired())
        # setUp is a SPLIT layout (NP_CONTENT_DIR != NP_DIR) with no bridge ->
        # dashboard/data missing -> WARN.
        text, _ = np_doctor.report()
        self.assertIn("WARN", self._line(text, "dashboard-data"))
        # Single-repo (content dir == NP): the real dashboard/data dir must exist -> PASS.
        os.environ["NP_CONTENT_DIR"] = os.environ["NP_DIR"]
        os.makedirs(os.path.join(os.environ["NP_DIR"], "dashboard", "data"))
        text, _ = np_doctor.report()
        self.assertRegex(self._line(text, "dashboard-data"), r"\bPASS\b")

    @unittest.skipIf(os.name == "nt", "POSIX pipefail-off / SIGPIPE pipe semantics")
    def test_adapter_verify_pipe_form_passes(self):
        # np-doctor.sh ran verify with pipefail DISABLED so the idiomatic
        # `producer | grep -q PAT` (grep closes the pipe, SIGPIPEs the producer with
        # 141) reports PASS, not FAIL. shell=True uses /bin/sh (no pipefail) so the
        # behavior is preserved -- guard it (POSIX only; cmd.exe has no seq/grep).
        self._write_adapter(self._all_wired(verify="seq 100000 | grep -q 1"))
        text, code = np_doctor.report()
        self.assertRegex(self._line(text, "knowledge"), r"\bPASS\b")


class TestLayerLayoutCheck(unittest.TestCase):
    """nervepack#234: the doctor reports whether each content layer has RECORDED
    where its content lives. Inferred routes still work, so that is an advisory
    PASS; only a corrupt manifest is a FAIL, because that one silently misplaces
    durable writes if left alone."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="npdoc-layout-")
        self.home = tempfile.mkdtemp(prefix="npdoc-home-")
        self._saved = {k: os.environ.get(k)
                       for k in ("NP_CONTENT_DIR", "NP_TEAM_DIR", "HOME")}
        os.environ["NP_CONTENT_DIR"] = self.root
        os.environ["HOME"] = self.home
        os.environ.pop("NP_TEAM_DIR", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _write_skill(self):
        d = os.path.join(self.root, "skills", "s")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as fh:
            fh.write("---\nname: s\n---\n")

    def test_recorded_manifest_passes_clean(self):
        import np_layout
        self._write_skill()
        np_layout.record(self.root, {
            "schema": 1,
            "routes": {"skill": {"path": "skills/{name}/SKILL.md"},
                       "knowledge": {"path": "notes/{name}.md"},
                       "roadmap": {"path": "ROADMAP.md"}}})
        self.assertEqual(np_doctor._core_check("layer-layout", ""), "PASS")

    def test_inferred_layer_passes_with_an_advisory(self):
        self._write_skill()
        st = np_doctor._core_check("layer-layout", "")
        self.assertTrue(st.startswith("PASS"), st)
        self.assertIn("inferred", st)

    def test_corrupt_manifest_fails(self):
        p = os.path.join(self.root, ".nervepack", "layout.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write("{not json")
        self.assertTrue(
            np_doctor._core_check("layer-layout", "").startswith("FAIL"))

    def test_layer_layout_is_a_should_capability(self):
        with open(os.path.normpath(_CAPS), encoding="utf-8") as fh:
            caps = json.load(fh)["capabilities"]
        row = [c for c in caps if c.get("id") == "layer-layout"]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["tier"], "SHOULD")
        self.assertEqual(row[0]["check"], "core")

if __name__ == "__main__":
    unittest.main()
