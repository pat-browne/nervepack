# np-test: credentials | registry merge across layers, ok/warn/expired/missing per source, rotation, no secret values
"""np_credentials tracks every credential a layer declares. Sources come from
the engine default registry plus each content layer. Only metadata is read:
dates, file existence and file mode, never the value."""
import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine"))
for _p in (SETUP, ENGINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_credentials as nc  # noqa: E402
import np_token_status  # noqa: E402

TODAY = datetime.date(2026, 11, 20)
SECRET = "fake-value-DO-NOT-PRINT-1234"


def _write(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, mode)


def _registry(root, entries):
    _write(os.path.join(root, "config", "credentials.json"),
           json.dumps({"schema": 1, "credentials": entries}), 0o644)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine_reg = os.path.join(self.tmp, "engine-credentials.json")
        _write(self.engine_reg, json.dumps({"schema": 1, "credentials": []}), 0o644)
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(self.overlay)
        self.env = mock.patch.dict(os.environ, {
            "NP_CREDENTIALS_ENGINE_FILE": self.engine_reg,
            "NP_CONTENT_DIR": self.overlay, "NP_TEAM_DIR": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def survey(self, **kw):
        return {r["name"]: r for r in nc.survey(today=TODAY, **kw)}


class TestStatus(Base):
    def test_literal_expiry_gives_ok_warn_expired(self):
        _registry(self.overlay, [
            {"name": "fresh", "store": {"kind": "vault", "backend": "bw", "item": "a"},
             "expires": "2027-06-01"},
            {"name": "soon", "store": {"kind": "vault", "item": "b"},
             "expires": "2026-12-01", "warn_days": 14},
            {"name": "gone", "store": {"kind": "vault", "item": "c"}, "expires": "2026-11-01"},
        ])
        rows = self.survey()
        self.assertEqual(rows["fresh"]["status"], "ok")
        self.assertEqual(rows["soon"]["status"], "warn")
        self.assertEqual(rows["soon"]["days_left"], 11)
        self.assertEqual(rows["gone"]["status"], "expired")
        self.assertEqual(rows["gone"]["days_left"], -19)

    def test_issued_plus_ttl(self):
        _registry(self.overlay, [{"name": "pat", "store": {"kind": "vault", "item": "x"},
                                  "issued": "2026-09-16", "ttl_days": 90, "warn_days": 14}])
        row = self.survey()["pat"]
        self.assertEqual(row["expires"], "2026-12-15")
        self.assertEqual((row["status"], row["days_left"]), ("ok", 25))

    def test_no_dates_is_unknown_and_warns(self):
        _registry(self.overlay, [{"name": "mystery", "store": {"kind": "vault", "item": "m"}}])
        row = self.survey()["mystery"]
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(row["days_left"])

    def test_never_expiring_source(self):
        _registry(self.overlay, [{"name": "aws", "store": {"kind": "vault", "item": "a"},
                                  "expires": "never"}])
        self.assertEqual(self.survey()["aws"]["status"], "ok")

    def test_file_store_missing_sidecar_and_mode(self):
        tok = os.path.join(self.tmp, "tok")
        _registry(self.overlay, [{"name": "f", "store": {"kind": "file", "path": tok},
                                  "ttl_days": 365}])
        self.assertEqual(self.survey()["f"]["status"], "missing")
        _write(tok, SECRET, 0o644)
        _write(tok + ".issued", "2026-11-01")
        row = self.survey()["f"]
        self.assertEqual(row["status"], "warn")
        self.assertIn("mode 644", " ".join(row["problems"]))
        os.chmod(tok, 0o600)
        row = self.survey()["f"]
        self.assertEqual((row["status"], row["days_left"]), ("ok", 346))

    def test_issued_from_file_mtime(self):
        cache = os.path.join(self.tmp, "msal_token_cache.json")
        _write(cache, "{}")
        ts = datetime.datetime(2026, 11, 10, 12).timestamp()
        os.utime(cache, (ts, ts))
        _registry(self.overlay, [{"name": "az", "store": {"kind": "file", "path": cache},
                                  "issued": "mtime", "ttl_days": 90, "warn_days": 14}])
        row = self.survey()["az"]
        self.assertEqual((row["expires"], row["status"]), ("2027-02-08", "ok"))

    def test_path_env_and_config_placeholder(self):
        tok = os.path.join(self.tmp, "envtok")
        _write(tok, SECRET)
        _registry(self.overlay, [{"name": "e", "store": {
            "kind": "file", "path": "{config}/nope", "path_env": "NP_TEST_TOK"}, "expires": "never"}])
        with mock.patch.dict(os.environ, {"NP_TEST_TOK": tok}):
            row = self.survey()["e"]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["location"], tok)

    def test_expires_cmd_output_is_parsed_not_shown(self):
        _registry(self.overlay, [{"name": "c", "store": {"kind": "vault", "item": "c"},
                                  "expires_cmd": "echo 2026-12-31"}])
        row = self.survey(run=lambda cmd: "2026-12-31\n")
        self.assertEqual((row := row["c"])["expires"], "2026-12-31")
        self.assertEqual(row["status"], "ok")

    def test_expires_cmd_failure_is_unknown(self):
        _registry(self.overlay, [{"name": "c", "store": {"kind": "vault", "item": "c"},
                                  "expires_cmd": "false"}])
        self.assertEqual(self.survey(run=lambda cmd: None)["c"]["status"], "unknown")

    def test_secret_value_never_appears(self):
        tok = os.path.join(self.tmp, "tok")
        _write(tok, SECRET)
        _write(tok + ".issued", "2026-11-01")
        _registry(self.overlay, [{"name": "f", "store": {"kind": "file", "path": tok},
                                  "ttl_days": 365, "rotate": {"mode": "manual", "command": "x"}}])
        rows = nc.survey(today=TODAY)
        self.assertNotIn(SECRET, json.dumps(rows))
        self.assertNotIn(SECRET, nc.report(today=TODAY))


class TestLayers(Base):
    def test_overlay_overrides_engine_by_name_and_adds(self):
        _write(self.engine_reg, json.dumps({"schema": 1, "credentials": [
            {"name": "shared", "store": {"kind": "vault", "item": "e"}, "expires": "2026-11-01"}]}))
        _registry(self.overlay, [
            {"name": "shared", "store": {"kind": "vault", "item": "o"}, "expires": "2027-11-01"},
            {"name": "mine", "store": {"kind": "vault", "item": "m"}, "expires": "never"}])
        rows = self.survey()
        self.assertEqual(rows["shared"]["status"], "ok")
        self.assertEqual(rows["shared"]["layer"], "personal")
        self.assertIn("mine", rows)

    def test_team_layer_wins(self):
        team = os.path.join(self.tmp, "team")
        os.makedirs(team)
        _registry(self.overlay, [{"name": "s", "store": {"kind": "vault", "item": "p"},
                                  "expires": "2026-11-01"}])
        _registry(team, [{"name": "s", "store": {"kind": "vault", "item": "t"},
                          "expires": "never"}])
        with mock.patch.dict(os.environ, {"NP_TEAM_DIR": team}):
            row = self.survey()["s"]
        self.assertEqual((row["layer"], row["status"]), ("team", "ok"))

    def test_team_layer_commands_never_run(self):
        team = os.path.join(self.tmp, "team")
        os.makedirs(team)
        _registry(team, [{"name": "t", "expires_cmd": "evil",
                          "rotate": {"mode": "auto", "command": "evil"}}])
        ran = []
        run = lambda c: ran.append(c) or 0  # noqa: E731
        with mock.patch.dict(os.environ, {"NP_TEAM_DIR": team}):
            row = {r["name"]: r for r in nc.survey(today=TODAY, run=run)}["t"]
            code, msg = nc.rotate("t", today=TODAY, run_cmd=run, run=run)
        self.assertEqual(ran, [])
        self.assertIn("not run", " ".join(row["problems"]))
        self.assertEqual(code, 2)
        self.assertIn("evil", msg)

    def test_bad_registry_is_reported_not_raised(self):
        _write(os.path.join(self.overlay, "config", "credentials.json"), "{not json")
        rows = nc.survey(today=TODAY)
        self.assertEqual(rows, [])
        self.assertIn("unreadable", nc.report(today=TODAY))

    def test_entry_without_name_is_skipped(self):
        _registry(self.overlay, [{"store": {"kind": "vault"}}, {"name": "ok", "expires": "never"}])
        self.assertEqual(list(self.survey()), ["ok"])


class TestEngineDefault(unittest.TestCase):
    """The scheduled-auth token is the first registered source, and its status
    must agree with np_token_status, which 62-install-scheduled-auth-token.sh uses."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tok = os.path.join(self.tmp, "claude-oauth-token")
        p = mock.patch.dict(os.environ, {"NP_CLAUDE_TOKEN_FILE": self.tok,
                                         "NP_CONTENT_DIR": self.tmp, "NP_TEAM_DIR": ""})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("NP_CREDENTIALS_ENGINE_FILE", None)

    def row(self):
        return {r["name"]: r for r in nc.survey(today=TODAY)}["claude-scheduled-auth-token"]

    def test_registered_and_manual_with_the_rotate_command(self):
        row = self.row()
        self.assertEqual(row["rotate_mode"], "manual")
        self.assertIn("62-install-scheduled-auth-token.sh --rotate", row["command"])
        self.assertEqual(row["status"], "missing")

    def test_parity_with_np_token_status(self):
        _write(self.tok, SECRET)
        for issued in ("2026-11-19", "2025-12-30", "2025-12-15"):
            _write(self.tok + ".issued", issued)
            legacy = np_token_status.status(self.tok, today=TODAY).split()
            row = self.row()
            self.assertEqual(row["days_left"], int(legacy[1]))
            self.assertEqual(row["status"] == "ok", legacy[0] == "ok")


class TestRotate(Base):
    def test_manual_prints_reminder_and_command(self):
        _registry(self.overlay, [{"name": "pat", "store": {"kind": "vault", "item": "x"},
                                  "expires": "2026-11-25",
                                  "rotate": {"mode": "manual", "command": "do-the-thing"}}])
        ran = []
        code, msg = nc.rotate("pat", today=TODAY, run_cmd=lambda c: ran.append(c) or 0)
        self.assertEqual(code, 0)
        self.assertEqual(ran, [])
        self.assertIn("do-the-thing", msg)
        self.assertIn("manual", msg)

    def test_auto_runs_command_and_stamps_sidecar(self):
        tok = os.path.join(self.tmp, "tok")
        _write(tok, SECRET)
        _registry(self.overlay, [{"name": "a", "store": {"kind": "file", "path": tok},
                                  "ttl_days": 30, "rotate": {"mode": "auto", "command": "refresh"}}])
        ran = []
        code, _ = nc.rotate("a", today=TODAY, run_cmd=lambda c: ran.append(c) or 0)
        self.assertEqual((code, ran), (0, ["refresh"]))
        with open(tok + ".issued") as fh:
            self.assertEqual(fh.read().strip(), "2026-11-20")
        self.assertEqual(os.stat(tok + ".issued").st_mode & 0o777, 0o600)

    def test_auto_failure_does_not_stamp(self):
        tok = os.path.join(self.tmp, "tok")
        _write(tok, SECRET)
        _registry(self.overlay, [{"name": "a", "store": {"kind": "file", "path": tok},
                                  "ttl_days": 30, "rotate": {"mode": "auto", "command": "x"}}])
        code, msg = nc.rotate("a", today=TODAY, run_cmd=lambda c: 3)
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(tok + ".issued"))
        self.assertIn("exit 3", msg)

    def test_unknown_name(self):
        code, msg = nc.rotate("nope", today=TODAY)
        self.assertEqual(code, 2)
        self.assertIn("nope", msg)

    def test_due_rotates_auto_and_lists_manual(self):
        _registry(self.overlay, [
            {"name": "auto-due", "expires": "2026-11-21", "rotate": {"mode": "auto", "command": "a"}},
            {"name": "auto-fresh", "expires": "2027-11-21", "rotate": {"mode": "auto", "command": "b"}},
            {"name": "man-due", "expires": "2026-11-01", "rotate": {"mode": "manual", "command": "m"}},
        ])
        ran = []
        code, msg = nc.rotate_due(today=TODAY, run_cmd=lambda c: ran.append(c) or 0)
        self.assertEqual((code, ran), (0, ["a"]))
        self.assertIn("man-due", msg)
        self.assertNotIn("auto-fresh", msg)


class TestReportAndCli(Base):
    def test_report_pass_and_warn(self):
        _registry(self.overlay, [{"name": "a", "expires": "never"}])
        self.assertTrue(nc.report(today=TODAY).startswith("PASS (1 credential"))
        _registry(self.overlay, [{"name": "a", "expires": "2026-11-01",
                                  "rotate": {"mode": "manual", "command": "fix-a"}}])
        line = nc.report(today=TODAY)
        self.assertTrue(line.startswith("WARN"))
        self.assertIn("a: expired", line)
        self.assertIn("fix-a", line)

    def test_report_disabled_by_toggle(self):
        with mock.patch.object(nc.np_toggle, "enabled", return_value=False):
            self.assertIn("disabled", nc.report(today=TODAY))

    def test_main_json_and_table(self):
        _registry(self.overlay, [{"name": "a", "expires": "never"}])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(nc.main(["--json"]), 0)
        self.assertIn('"name": "a"', buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(nc.main([]), 0)
        self.assertIn("credential", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
