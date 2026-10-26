"""Resources catalog, richer journal fields, and crawl-before-cleanup."""
import json
import os
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_np_journal import JournalBase  # noqa: E402  (also sets sys.path)
import np_resources  # noqa: E402
import np_journal  # noqa: E402

GHP_TOKEN = "gh" + "p_abcdefghijklmnopqrstuvwxyz0123"
AWS_KEY = "AK" + "IAABCDEFGHIJKLMNOP"
SK_TOKEN = "s" + "k-abcdefghijklmnopqrstuv"
JWT = "ey" + "JhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"
SECRET_TEXT = (
    "Server=tcp:sql-prod.database.windows.net,1433;Initial Catalog=Reporting;"
    "User Id=app;Password=Sup3rS3cretValue!;\n"
    "https://u:hunter2pass@evil.example.com/x "
    "https://blob.core.windows.net/c/f?sv=2024&sig=abcDEF123456 "
    "Authorization: Bearer abcdefghijklmnop1234 "
    + JWT + " "
    "token=abcdef123456 AccountKey=QWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo= "
    + GHP_TOKEN + " " + AWS_KEY + " "
    "https://myvault.vault.azure.net/secrets/db-pass/0123456789abcdef0123456789abcdef\n"
)


def ids(items):
    return {i["id"]: i["type"] for i in items}


class TestExtract(unittest.TestCase):
    def test_finds_each_identifier_type(self):
        text = (
            "/subscriptions/12345678-1234-1234-1234-123456789abc/resourceGroups/rg-data/"
            "providers/Microsoft.Sql/servers/s1\n"
            "arn:aws:s3:::my-bucket/key 198.51.100.4/16 203.0.113.5:5432 api.example.com "
            "SELECT * FROM dbo.Camper JOIN [DW].[mart].[Fact] x definitionId=42 "
            "https://dev.azure.com/org/proj/_git/data-base port 8080 setup.py package.json"
        )
        got = ids(np_resources.extract(text))
        self.assertEqual(got["arn:aws:s3:::my-bucket/key"], "arn")
        self.assertEqual(got["198.51.100.4/16"], "cidr")
        self.assertEqual(got["203.0.113.5:5432"], "endpoint")
        self.assertEqual(got["203.0.113.5"], "ip")
        self.assertEqual(got["api.example.com"], "hostname")
        self.assertEqual(got["dbo.Camper"], "db-object")
        self.assertEqual(got["DW.mart.Fact"], "db-object")
        self.assertEqual(got["definitionId=42"], "pipeline-id")
        self.assertEqual(got["dev.azure.com/org/proj/_git/data-base"], "repo")
        self.assertEqual(got["port 8080"], "port")
        self.assertTrue(any(t == "azure-resource-id" for t in got.values()))
        self.assertNotIn("setup.py", got)
        self.assertNotIn("package.json", got)

    def test_keyvault_secret_name_kept(self):
        got = ids(np_resources.extract(SECRET_TEXT))
        self.assertEqual(got["myvault/db-pass"], "keyvault-secret")

    def test_connection_string_yields_names_only(self):
        got = ids(np_resources.extract(SECRET_TEXT))
        self.assertEqual(got["Reporting"], "database")
        self.assertEqual(got["sql-prod.database.windows.net"], "hostname")

    def test_no_secret_value_survives(self):
        blob = json.dumps(np_resources.extract(SECRET_TEXT))
        for secret in ("Sup3rS3cretValue", "hunter2pass", "abcDEF123456", "abcdefghijklmnop1234",
                       "SflKxwRJSMeKKF2QT4", "abcdef123456", "QWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo",
                       GHP_TOKEN, AWS_KEY,
                       "0123456789abcdef0123456789abcdef", "evil.example.com"):
            self.assertNotIn(secret, blob)

    def test_url_query_stripped_and_userinfo_dropped(self):
        got = ids(np_resources.extract(SECRET_TEXT))
        self.assertIn("https://blob.core.windows.net/c/f", got)
        self.assertFalse([i for i in got if "@" in i])

    def test_credential_looking_candidate_is_dropped_at_stage(self):
        n = np_resources.stage([{"id": SK_TOKEN, "type": "url"}], "s", "r")
        self.assertEqual(n, 0)

    def test_extract_is_bounded(self):
        text = " ".join("h%d.example.com" % i for i in range(200))
        self.assertLessEqual(len(np_resources.extract(text)), np_resources.MAX_PER_SESSION)


class TestCheckpointFields(JournalBase):
    def _complete(self, prompt, *_a, **_k):
        self.prompt = prompt
        return json.dumps({
            "goal": "G", "hypotheses": "H", "struggles": "S", "progress": "P", "skills": "k",
            "wins": "W", "decisions": "use X (because Y)", "open_questions": "Q?",
            "next_step": "ship it", "files_touched": "a.py, b.py",
            "resources": {"api.example.com": "public api",
                          "invented.example.com": "model made this up"}})

    def test_new_fields_written(self):
        self._write_transcript("call api.example.com on port 8080")
        np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        body = self._read()
        for line in ("**Wins:** W", "**Decisions:** use X (because Y)", "**Open questions:** Q?",
                     "**Next step:** ship it", "**Files touched:** a.py, b.py"):
            self.assertIn(line, body)
        self.assertIn("- api.example.com | hostname | public api", body)
        self.assertIn("RESOURCES SEEN", self.prompt)

    def test_extraction_failure_does_not_lose_the_checkpoint(self):
        self._write_transcript("call api.example.com")
        with mock.patch.object(np_journal.np_resources, "extract", side_effect=RuntimeError("boom")):
            np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        self.assertIn("**Wins:** W", self._read())
        self.assertNotIn("**Resources:**", self._read())

    def test_model_cannot_add_identifiers(self):
        self._write_transcript("call api.example.com")
        np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        self.assertNotIn("invented.example.com", self._read())

    def test_secrets_never_reach_journal_or_prompt(self):
        self._write_transcript(SECRET_TEXT)
        np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        for secret in ("Sup3rS3cretValue", "hunter2pass", "abcDEF123456"):
            self.assertNotIn(secret, self._read())
        self.assertNotIn("Sup3rS3cretValue", self.prompt.split("RESOURCES SEEN")[-1])

    def test_empty_new_fields_are_omitted(self):
        np_journal.append_block("sid-1", "PreCompact", {"goal": "G", "wins": "none"})
        body = self._read()
        self.assertNotIn("Wins", body)
        self.assertIn("**Hypotheses:** TBD", body)

    def test_fields_are_bounded(self):
        np_journal.append_block("sid-1", "PreCompact", {"goal": "G", "decisions": "x " * 5000})
        line = [ln for ln in self._read().splitlines() if ln.startswith("**Decisions:**")][0]
        self.assertLess(len(line), 500)

    def test_resources_capped(self):
        items = [{"id": "h%d.example.com" % i, "type": "hostname", "purpose": ""} for i in range(60)]
        np_journal.append_block("sid-1", "PreCompact", {"goal": "G"},
                                extra_lines=np_journal._block_resources(items))
        self.assertEqual(self._read().count("| hostname |"), np_journal._RES_LINES)


class TestRestoreBounded(JournalBase):
    def test_restore_keeps_seed_and_newest_blocks(self):
        for i in range(10):
            np_journal.append_block("sid-1", "PreCompact", {"goal": "goal-%d" % i})
        out = np_journal.recall_sessionstart(self._payload(source="compact"))
        self.assertIn("goal-0", out)
        self.assertIn("goal-9", out)
        self.assertNotIn("goal-4", out)
        self.assertIn("6 older checkpoint(s) omitted", out)


class TestBounds(JournalBase):
    def test_seed_survives_the_restore_cap(self):
        np_journal.append_block("sid-1", "SessionStart", {"goal": "SEED-GOAL"})
        for i in range(4):
            np_journal.append_block("sid-1", "PreCompact", {"goal": "g%d" % i, "decisions": "d " * 200})
        big = np_journal._RESTORE_CAP
        with mock.patch.object(np_journal, "_RESTORE_CAP", 1500):
            out = np_journal._restore_view(self._read())
        self.assertIn("SEED-GOAL", out)
        self.assertLessEqual(len(out), 1500)
        self.assertGreater(big, 1500)

    def test_single_block_keeps_its_start(self):
        np_journal.append_block("sid-1", "SessionStart", {"goal": "START-" + "x" * 500})
        with mock.patch.object(np_journal, "_RESTORE_CAP", 100):
            out = np_journal._restore_view(self._read())
        self.assertTrue(out.startswith("## "))
        self.assertEqual(len(out), 100)

    def test_text_never_exceeds_cap(self):
        self.assertEqual(len(np_journal._text("x" * 1000)), np_journal._FIELD_CAP)
        self.assertEqual(np_journal._text("x" * 400), "x" * 400)


class TestCrawl(JournalBase):
    def _seed_journal(self):
        np_journal.append_block("sid-1", "SessionStart", {"goal": "fix sync"},
                                extra_lines=["**Repo:** data-base @ main (abc, clean) [checkout: /x]"])
        np_journal.append_block(
            "sid-1", "PreCompact",
            {"goal": "fix sync", "struggles": "retry loop on 429", "wins": "backoff fixed it",
             "decisions": "use jitter (because thundering herd)", "next_step": "deploy"},
            extra_lines=np_journal._block_resources(
                [{"id": "api.example.com", "type": "hostname", "purpose": "sync target"}]))

    def _inbox(self, name):
        d = os.environ[name]
        out = []
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                out += [json.loads(x) for x in fh if x.strip()]
        return out

    def test_crawl_feeds_episodic_and_resources_inboxes(self):
        self._seed_journal()
        self.assertTrue(np_journal.crawl("sid-1", "/work/data-base"))
        epi = self._inbox("EPISODIC_INBOX")
        self.assertEqual(len(epi), 1)
        self.assertEqual(epi[0]["project"], "data-base")
        self.assertEqual(epi[0]["struggles"][0]["symptom"], "retry loop on 429")
        self.assertEqual(epi[0]["strategies"][0]["content"], "backoff fixed it")
        self.assertIn("use jitter (because thundering herd)", epi[0]["body"])
        res = self._inbox("NP_RESOURCES_INBOX")
        self.assertEqual(res[0]["id"], "api.example.com")
        self.assertEqual(res[0]["purpose"], "sync target")
        self.assertEqual(res[0]["repo"], "data-base")

    def test_cleanup_only_after_crawl_and_crawl_runs_once(self):
        self._seed_journal()
        np_journal.crawl_and_cleanup("sid-1", "/w/data-base")
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))
        self.assertEqual(len(self._inbox("EPISODIC_INBOX")), 1)

    def test_crawl_twice_does_not_duplicate(self):
        self._seed_journal()
        np_journal.crawl("sid-1")
        np_journal.crawl("sid-1")
        self.assertEqual(len(self._inbox("EPISODIC_INBOX")), 1)

    def test_failed_crawl_keeps_journal(self):
        self._seed_journal()
        with mock.patch.object(np_journal.np_capture, "append_note", return_value=False):
            np_journal.crawl_and_cleanup("sid-1")
        self.assertTrue(os.path.exists(np_journal.journal_path("sid-1")))

    def test_ttl_crawls_before_delete(self):
        self._seed_journal()
        path = np_journal.journal_path("sid-1")
        past = time.time() - 40 * 86400
        os.utime(path, (past, past))
        np_journal.ttl_sweep()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(len(self._inbox("EPISODIC_INBOX")), 1)
        self.assertEqual(len(self._inbox("NP_RESOURCES_INBOX")), 1)

    def test_ttl_keeps_journal_when_crawl_fails_until_double_ttl(self):
        self._seed_journal()
        path = np_journal.journal_path("sid-1")
        past = time.time() - 40 * 86400
        os.utime(path, (past, past))
        with mock.patch.object(np_journal, "crawl", return_value=False):
            np_journal.ttl_sweep()
            self.assertTrue(os.path.exists(path))
            past = time.time() - 65 * 86400
            os.utime(path, (past, past))
            np_journal.ttl_sweep()
        self.assertFalse(os.path.exists(path))

    def test_resources_stage_failure_keeps_journal(self):
        self._seed_journal()
        with mock.patch.object(np_journal.np_resources, "stage", return_value=-1):
            np_journal.crawl_and_cleanup("sid-1")
        self.assertTrue(os.path.exists(np_journal.journal_path("sid-1")))
        self.assertEqual(self._inbox("EPISODIC_INBOX"), [])

    def test_stage_oserror_returns_minus_one(self):
        with mock.patch.dict(os.environ, {"NP_RESOURCES_INBOX": os.path.join(self.tmp, "epi-inbox-file")}):
            open(os.environ["NP_RESOURCES_INBOX"], "w").close()
            n = np_resources.stage([{"id": "api.example.com", "type": "hostname"}], "s", "r")
        self.assertEqual(n, -1)

    def test_crawl_param_off_skips_analysis_but_cleanup_still_runs(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("journal|shared|runtime|on|ttl_days=30,crawl=off\n")
        self._seed_journal()
        np_journal.crawl_and_cleanup("sid-1")
        self.assertEqual(self._inbox("EPISODIC_INBOX"), [])
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))

    def test_crawl_with_no_signal_writes_nothing(self):
        np_journal.append_block("sid-1", "SessionStart", {"goal": "G"})
        self.assertTrue(np_journal.crawl("sid-1"))
        self.assertEqual(self._inbox("EPISODIC_INBOX"), [])


class TestDrain(JournalBase):
    def _stage(self, ident, typ="hostname", purpose="", session="s1"):
        np_resources.stage([{"id": ident, "type": typ, "purpose": purpose}], session, "repo-a")

    def _catalog(self):
        cdir = np_resources.catalog_dir()
        out = []
        for f in sorted(os.listdir(cdir)):
            if f.endswith(".jsonl"):
                with open(os.path.join(cdir, f), encoding="utf-8") as fh:
                    for x in fh:
                        try:
                            r = json.loads(x)
                        except ValueError:
                            continue
                        if isinstance(r, dict) and isinstance(r.get("id"), str):
                            out.append(r)
        return out

    def test_drain_writes_month_file_and_index(self):
        self._stage("api.example.com", purpose="public api")
        self._stage("198.51.100.4", "ip")
        self.assertEqual(np_resources.drain(), 2)
        month = time.strftime("%Y-%m", time.gmtime())
        self.assertTrue(os.path.isfile(os.path.join(np_resources.catalog_dir(), month + ".jsonl")))
        with open(os.path.join(np_resources.catalog_dir(), "INDEX.md"), encoding="utf-8") as fh:
            idx = fh.read()
        self.assertIn("## hostname", idx)
        self.assertIn("## ip", idx)
        self.assertIn("| api.example.com | public api | repo-a", idx)
        self.assertEqual(os.listdir(os.environ["NP_RESOURCES_INBOX"]), [])

    def test_dedup_updates_last_seen_and_keeps_first(self):
        self._stage("api.example.com", session="s1")
        np_resources.drain()
        time.sleep(1.1)
        self._stage("api.example.com", purpose="late purpose", session="s2")
        np_resources.drain()
        rows = self._catalog()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["session"], "s1")
        self.assertEqual(r["seen"], 2)
        self.assertEqual(r["purpose"], "late purpose")
        self.assertGreater(r["last_seen"], r["first_seen"])

    def test_dedup_across_month_files(self):
        cdir = np_resources.catalog_dir()
        os.makedirs(cdir)
        with open(os.path.join(cdir, "2020-01.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "api.example.com", "type": "hostname", "purpose": "",
                                 "first_seen": "2020-01-01T00:00:00Z",
                                 "last_seen": "2020-01-01T00:00:00Z", "session": "old",
                                 "repo": "r", "seen": 1}) + "\n")
        self._stage("api.example.com")
        np_resources.drain()
        rows = self._catalog()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seen"], 2)
        self.assertEqual(rows[0]["first_seen"], "2020-01-01T00:00:00Z")

    def test_drain_drops_credential_shaped_inbox_records(self):
        os.makedirs(os.environ["NP_RESOURCES_INBOX"])
        with open(os.path.join(os.environ["NP_RESOURCES_INBOX"], "x.jsonl"), "w") as fh:
            fh.write(json.dumps({"id": GHP_TOKEN, "type": "url"}) + "\n")
        np_resources.drain()
        self.assertEqual(self._catalog(), [])

    def test_malformed_catalog_rows_are_skipped_not_fatal(self):
        cdir = np_resources.catalog_dir()
        os.makedirs(cdir)
        good = {"id": "keep.example.com", "type": "hostname", "purpose": "", "first_seen": "2020-01-01T00:00:00Z",
                "last_seen": "2020-01-01T00:00:00Z", "session": "o", "repo": "r", "seen": 1}
        bad = [
            "not json at all",
            json.dumps({"id": "no-first-seen.example.com", "type": "hostname", "seen": "x"}),
            json.dumps({"id": GHP_TOKEN, "type": "url"}),
            json.dumps([1, 2]),
            json.dumps({"id": 5}),
        ]
        with open(os.path.join(cdir, "2020-01.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(bad + [json.dumps(good)]) + "\n")
        self._stage("new.example.com")
        with mock.patch.dict(os.environ, {"NP_RESOURCES_LOG": os.path.join(self.tmp, "r.log")}):
            self.assertEqual(np_resources.drain(), 1)
        got = set(np_resources._load_catalog(np_resources.catalog_dir()))
        self.assertEqual(got, {"keep.example.com", "new.example.com"})
        with open(os.path.join(self.tmp, "r.log"), encoding="utf-8") as fh:
            self.assertIn("skipped 5 malformed", fh.read())

    def test_row_missing_first_seen_does_not_abort_merge(self):
        cdir = np_resources.catalog_dir()
        os.makedirs(cdir)
        with open(os.path.join(cdir, "2020-01.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "old.example.com", "type": "hostname"}) + "\n")
        self._stage("new.example.com")
        self.assertEqual(np_resources.drain(), 1)
        self.assertEqual(len(self._catalog()), 2)

    def test_index_escapes_pipes_backticks_and_markdown(self):
        self._stage("api.example.com", purpose="a|b `code` *bold* [x](y) <b>\nline2")
        np_resources.drain()
        with open(os.path.join(np_resources.catalog_dir(), "INDEX.md"), encoding="utf-8") as fh:
            idx = fh.read()
        row = [ln for ln in idx.splitlines() if ln.startswith("| api.example.com")][0]
        self.assertIn("a\\|b \\`code\\`", row)
        self.assertNotIn("`code`", row.replace("\\`", ""))
        self.assertIn("\\*bold\\*", row)
        self.assertIn("\\<b\\>", row)
        self.assertEqual(len(row.split(" | ")), 4)

    def test_drain_with_empty_inbox_is_noop(self):
        self.assertEqual(np_resources.drain(), 0)
        self.assertFalse(os.path.exists(np_resources.catalog_dir()))

    def test_drain_without_content_dir_keeps_inbox(self):
        self._stage("api.example.com")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": os.path.join(self.tmp, "missing")}):
            self.assertEqual(np_resources.drain(), 0)
        self.assertEqual(len(os.listdir(os.environ["NP_RESOURCES_INBOX"])), 1)


if __name__ == "__main__":
    unittest.main()
