# np-test: layout | happy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLI = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine",
                                     "cli.py"))


class TestLayoutCLI(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nplayout-")
        self.home = tempfile.mkdtemp(prefix="nphome-")
        os.makedirs(os.path.join(self.root, "skills", "s"))
        with open(os.path.join(self.root, "skills", "s", "SKILL.md"), "w") as fh:
            fh.write("---\nname: s\n---\n")
        self.env = dict(os.environ, NP_CONTENT_DIR=self.root, HOME=self.home)
        self.env.pop("NP_TEAM_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def run_cli(self, *args, **kw):
        return subprocess.run([sys.executable, _CLI, "layout"] + list(args),
                              capture_output=True, text=True,
                              env=kw.get("env", self.env),
                              input=kw.get("input"))

    def test_show_emits_json_with_source(self):
        r = self.run_cli("show")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["source"], "inferred")
        self.assertEqual(got["layout"]["routes"]["skill"]["path"],
                         "skills/{name}/SKILL.md")

    def test_infer_emits_a_layout(self):
        r = self.run_cli("infer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["schema"], 1)

    def test_questions_emits_a_json_list(self):
        r = self.run_cli("questions")
        self.assertEqual(r.returncode, 0, r.stderr)
        ids = [q["id"] for q in json.loads(r.stdout)]
        self.assertIn("missing-kind:knowledge", ids)

    def test_record_reads_stdin_and_writes_the_manifest(self):
        layout = json.dumps({"schema": 1,
                             "routes": {"skill": {"path": "skills/{name}/SKILL.md"}}})
        r = self.run_cli("record", input=layout)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(
            os.path.join(self.root, ".nervepack", "layout.json")))

    def test_show_reports_manifest_after_record(self):
        self.run_cli("record", input=json.dumps(
            {"schema": 1, "routes": {"skill": {"path": "skills/{name}/SKILL.md"}}}))
        self.assertEqual(json.loads(self.run_cli("show").stdout)["source"], "manifest")

    def test_record_rejects_an_invalid_layout_with_exit_1(self):
        r = self.run_cli("record", input=json.dumps({"schema": 99, "routes": {}}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("schema", r.stderr)

    def test_record_rejects_bad_json_with_exit_1(self):
        r = self.run_cli("record", input="{not json")
        self.assertEqual(r.returncode, 1)

    def test_route_prints_a_path(self):
        r = self.run_cli("route", "--kind", "skill", "--value", "name=np-kb-x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "skills/np-kb-x/SKILL.md")

    def test_route_refuses_a_traversal_value(self):
        r = self.run_cli("route", "--kind", "skill", "--value", "name=../etc")
        self.assertEqual(r.returncode, 1)
        self.assertIn("segment", r.stderr)

    def test_route_for_unrouted_kind_exits_1(self):
        r = self.run_cli("route", "--kind", "knowledge", "--value", "name=x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no route", r.stderr.lower())

    def test_unknown_verb_exits_2(self):
        self.assertEqual(self.run_cli("bogus").returncode, 2)

    def test_no_verb_exits_2(self):
        self.assertEqual(self.run_cli().returncode, 2)

    def test_team_layer_without_config_exits_1(self):
        r = self.run_cli("show", "--layer", "team")
        self.assertEqual(r.returncode, 1)
        self.assertIn("team", r.stderr.lower())

    def test_engine_layer_resolves(self):
        r = self.run_cli("show", "--layer", "engine")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("routes", json.loads(r.stdout)["layout"])


if __name__ == "__main__":
    unittest.main()
