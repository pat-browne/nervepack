#!/usr/bin/env python3
"""Contract test for np-ledger-append.py (stdlib unittest, per language
policy). F5 in the AI-native compliance epic (#251)."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-ledger-append.py"))

_spec = importlib.util.spec_from_file_location("ledger_append", CHK)
ledger_append = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger_append)


class TestGatesFromVerdicts(unittest.TestCase):
    def test_trims_each_verdict_to_name_verdict_rules_sha(self):
        verdicts = [
            {"schema": "nervepack.gate-verdict/1", "gate": "syntax",
             "verdict": "PASSED", "reason": "clean", "evidence_ref": "http://x",
             "rules_sha": "abc123"},
        ]
        self.assertEqual(
            ledger_append.gates_from_verdicts(verdicts),
            [{"name": "syntax", "verdict": "PASSED", "rules_sha": "abc123"}],
        )

    def test_empty_list_stays_empty(self):
        self.assertEqual(ledger_append.gates_from_verdicts([]), [])


class TestBuildEntry(unittest.TestCase):
    def test_shape_matches_the_issues_example(self):
        entry = ledger_append.build_entry(
            change_id="feat-f5-thing",
            spec="change-specs/feat-f5-thing.md",
            tier="normal",
            diff_sha="head123",
            gates=[{"name": "regression", "verdict": "PASSED", "rules_sha": "abc"}],
            merge_sha="merge456",
            ts="2026-08-15T00:00:00+00:00",
        )
        self.assertEqual(entry["change_id"], "feat-f5-thing")
        self.assertEqual(entry["spec"], "change-specs/feat-f5-thing.md")
        self.assertEqual(entry["tier"], "normal")
        self.assertEqual(entry["diff_sha"], "head123")
        self.assertEqual(entry["gates"][0]["name"], "regression")
        self.assertEqual(entry["merge_sha"], "merge456")
        self.assertEqual(entry["ts"], "2026-08-15T00:00:00+00:00")


class TestAppendEntry(unittest.TestCase):
    def test_appends_one_json_line_creating_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dashboard", "data", "ledger.jsonl")
            ledger_append.append_entry(path, {"change_id": "a"})
            ledger_append.append_entry(path, {"change_id": "b"})
            with open(path) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertEqual([l["change_id"] for l in lines], ["a", "b"])

    def test_never_overwrites_prior_entries(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"change_id": "existing"}) + "\n")
            ledger_append.append_entry(path, {"change_id": "new"})
            with open(path) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertEqual([l["change_id"] for l in lines], ["existing", "new"])


class TestExtractVerdictsJsonMirror(unittest.TestCase):
    """A small, deliberate duplicate of np-gate-verdicts-comment.py's
    extract_verdicts_json - see that module's docstring for why this isn't
    a cross-script import."""

    def test_extracts_embedded_json(self):
        body = "some text\n<!-- nervepack:gate-verdicts-json\n[{\"gate\": \"syntax\"}]\n-->"
        self.assertEqual(
            ledger_append.extract_verdicts_json(body), [{"gate": "syntax"}])

    def test_none_when_absent(self):
        self.assertIsNone(ledger_append.extract_verdicts_json("no marker here"))

    def test_none_on_malformed(self):
        body = "<!-- nervepack:gate-verdicts-json\nnot json\n-->"
        self.assertIsNone(ledger_append.extract_verdicts_json(body))


class TestFetchPrMeta(unittest.TestCase):
    def test_extracts_head_sha_head_ref_and_merge_sha(self):
        def fake_fetch(url, token, method="GET", data=None):
            return {
                "head": {"sha": "headsha123", "ref": "feat/thing"},
                "merge_commit_sha": "mergesha456",
            }

        meta = ledger_append.fetch_pr_meta("owner/repo", "7", "tok", fetch=fake_fetch)
        self.assertEqual(meta["head_sha"], "headsha123")
        self.assertEqual(meta["head_ref"], "feat/thing")
        self.assertEqual(meta["merge_sha"], "mergesha456")


class TestFindGateVerdictsCommentBody(unittest.TestCase):
    def test_finds_comment_body_containing_the_json_marker(self):
        def fake_fetch(url, token, method="GET", data=None):
            return [
                {"id": 1, "body": "unrelated"},
                {"id": 2, "body": "<!-- nervepack:gate-verdicts -->\nstuff\n"
                                  "<!-- nervepack:gate-verdicts-json\n[]\n-->"},
            ]

        body = ledger_append.find_gate_verdicts_comment_body(
            "owner/repo", "7", "tok", fetch=fake_fetch)
        self.assertIn("gate-verdicts-json", body)

    def test_none_when_no_comment_has_the_marker(self):
        def fake_fetch(url, token, method="GET", data=None):
            return [{"id": 1, "body": "unrelated"}]

        self.assertIsNone(
            ledger_append.find_gate_verdicts_comment_body("owner/repo", "7", "tok", fetch=fake_fetch))


class TestMainFailureModes(unittest.TestCase):
    def test_missing_token_returns_one(self):
        env_backup = os.environ.pop("GITHUB_TOKEN", None)
        gh_backup = os.environ.pop("GH_TOKEN", None)
        try:
            rc = ledger_append.main(
                ["prog", "--repo", "owner/repo", "--pr", "1",
                 "--content-dir", "/tmp/does-not-matter"])
        finally:
            if env_backup is not None:
                os.environ["GITHUB_TOKEN"] = env_backup
            if gh_backup is not None:
                os.environ["GH_TOKEN"] = gh_backup
        self.assertEqual(rc, 1)

    def test_missing_content_dir_returns_one(self):
        os.environ["GITHUB_TOKEN"] = "tok"
        cd_backup = os.environ.pop("NP_CONTENT_DIR", None)
        try:
            rc = ledger_append.main(["prog", "--repo", "owner/repo", "--pr", "1"])
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            if cd_backup is not None:
                os.environ["NP_CONTENT_DIR"] = cd_backup
        self.assertEqual(rc, 1)

    def test_missing_spec_file_is_not_an_error_standard_tier_may_have_none(self):
        with tempfile.TemporaryDirectory() as repo_root, \
                tempfile.TemporaryDirectory() as content_dir:
            os.environ["GITHUB_TOKEN"] = "tok"

            def fake_fetch(url, token, method="GET", data=None):
                if "pulls" in url:
                    return {"head": {"sha": "h", "ref": "docs/no-spec-needed"},
                            "merge_commit_sha": "m"}
                return []

            try:
                rc = ledger_append.main(
                    ["prog", "--repo", "owner/repo", "--pr", "1",
                     "--repo-root", repo_root, "--content-dir", content_dir],
                    fetch=fake_fetch,
                )
            finally:
                os.environ.pop("GITHUB_TOKEN", None)
            self.assertEqual(rc, 0)
            ledger_path = os.path.join(content_dir, "dashboard", "data", "ledger.jsonl")
            self.assertFalse(os.path.isfile(ledger_path))




class TestExistingChangeIds(unittest.TestCase):
    """Backfill idempotence rests entirely on this. F9/#255."""

    def _ledger(self, d, lines):
        path = os.path.join(d, "ledger.jsonl")
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        return path

    def test_reads_every_change_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._ledger(d, [json.dumps({"change_id": "a"}),
                                    json.dumps({"change_id": "b"})])
            self.assertEqual(ledger_append.existing_change_ids(path), {"a", "b"})

    def test_a_missing_ledger_is_an_empty_set_not_an_error(self):
        self.assertEqual(
            ledger_append.existing_change_ids("/nonexistent/ledger.jsonl"), set())

    def test_an_unparseable_line_is_skipped_not_fatal(self):
        """The ledger is append-only and kept indefinitely. One bad line written
        years ago must not stop today from being recorded."""
        with tempfile.TemporaryDirectory() as d:
            path = self._ledger(d, ["{not json", json.dumps({"change_id": "b"})])
            self.assertEqual(ledger_append.existing_change_ids(path), {"b"})

    def test_blank_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._ledger(d, [json.dumps({"change_id": "a"}), "", "  "])
            self.assertEqual(ledger_append.existing_change_ids(path), {"a"})

    def test_an_entry_without_a_change_id_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._ledger(d, [json.dumps({"spec": "x"})])
            self.assertEqual(ledger_append.existing_change_ids(path), set())


class TestMergedPullRequests(unittest.TestCase):
    def test_unmerged_closed_pull_requests_are_filtered_out(self):
        """state=closed covers both closed and merged, so merged_at is the only
        thing that distinguishes them."""
        def fake_fetch(url, token, **kw):
            return [
                {"number": 3, "head": {"ref": "feat/a"}, "merged_at": "2026-08-01T00:00:00Z"},
                {"number": 4, "head": {"ref": "feat/b"}, "merged_at": None},
            ]
        self.assertEqual(
            ledger_append.merged_pull_requests("o/r", "tok", 50, fetch=fake_fetch),
            [(3, "feat/a")])

    def test_the_page_size_is_capped_at_the_api_maximum(self):
        seen = {}
        def fake_fetch(url, token, **kw):
            seen["url"] = url
            return []
        ledger_append.merged_pull_requests("o/r", "tok", 500, fetch=fake_fetch)
        self.assertIn("per_page=100", seen["url"])


class TestBackfillSkipsWhatIsAlreadyRecorded(unittest.TestCase):
    def test_a_pull_request_already_in_the_ledger_is_not_fetched_again(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "dashboard", "data")
            os.makedirs(data)
            with open(os.path.join(data, "ledger.jsonl"), "w") as f:
                f.write(json.dumps({"change_id": "feat-a"}) + "\n")

            calls = []
            def fake_fetch(url, token, **kw):
                calls.append(url)
                if "/pulls?" in url:
                    return [{"number": 3, "head": {"ref": "feat/a"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                return []

            args = argparse.Namespace(
                repo="o/r", pr=None, backfill=True, limit=50, repo_root=d,
                content_dir=d, spec=None, tier=None, merge_sha=None)
            rc = ledger_append.backfill(args, "tok", fetch=fake_fetch)
            self.assertEqual(rc, 0)
            # Only the listing call. No per-PR fetch for an entry already held.
            self.assertEqual([c for c in calls if "/pulls/" in c], [])

    def test_a_missing_pull_request_is_appended(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "dashboard", "data")
            os.makedirs(data)
            os.makedirs(os.path.join(d, "change-specs"))
            with open(os.path.join(d, "change-specs", "feat-b.md"), "w") as f:
                f.write("---\ntier: normal\n---\nbody\n")

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 4, "head": {"ref": "feat/b"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                if "/pulls/4" in url:
                    return {"head": {"sha": "head4", "ref": "feat/b"},
                            "merge_commit_sha": "merge4"}
                return []

            args = argparse.Namespace(
                repo="o/r", pr=None, backfill=True, limit=50, repo_root=d,
                content_dir=d, spec=None, tier=None, merge_sha=None)
            self.assertEqual(ledger_append.backfill(args, "tok", fetch=fake_fetch), 0)
            with open(os.path.join(data, "ledger.jsonl")) as f:
                entries = [json.loads(x) for x in f if x.strip()]
            self.assertEqual([e["change_id"] for e in entries], ["feat-b"])
            self.assertEqual(entries[0]["merge_sha"], "merge4")

    def test_running_it_twice_appends_nothing_the_second_time(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "dashboard", "data")
            os.makedirs(data)
            os.makedirs(os.path.join(d, "change-specs"))
            with open(os.path.join(d, "change-specs", "feat-b.md"), "w") as f:
                f.write("---\ntier: normal\n---\nbody\n")

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 4, "head": {"ref": "feat/b"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                if "/pulls/4" in url:
                    return {"head": {"sha": "head4", "ref": "feat/b"},
                            "merge_commit_sha": "merge4"}
                return []

            args = argparse.Namespace(
                repo="o/r", pr=None, backfill=True, limit=50, repo_root=d,
                content_dir=d, spec=None, tier=None, merge_sha=None)
            ledger_append.backfill(args, "tok", fetch=fake_fetch)
            ledger_append.backfill(args, "tok", fetch=fake_fetch)
            with open(os.path.join(data, "ledger.jsonl")) as f:
                self.assertEqual(len([x for x in f if x.strip()]), 1)


class TestBackfillCountsHonestly(unittest.TestCase):
    """append_one returns 0 both when it wrote an entry and when it correctly
    wrote nothing (a standard-tier change with no spec). Counting every zero as
    an append reports work that never happened."""

    def _args(self, d):
        import argparse
        return argparse.Namespace(repo="o/r", pr=None, backfill=True, limit=50,
                                  repo_root=d, content_dir=d, spec=None,
                                  tier=None, merge_sha=None)

    def _setup(self, d):
        os.makedirs(os.path.join(d, "dashboard", "data"))
        os.makedirs(os.path.join(d, "change-specs"))

    def test_a_pull_request_with_no_spec_is_not_counted_as_appended(self):
        with tempfile.TemporaryDirectory() as d:
            self._setup(d)   # no spec file written

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 5, "head": {"ref": "docs/typo"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                if "/pulls/5" in url:
                    return {"head": {"sha": "h5", "ref": "docs/typo"},
                            "merge_commit_sha": "m5"}
                return []

            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch)
            self.assertEqual(rc, 0)
            self.assertIn("appended 0", buf.getvalue())
            self.assertIn("skipped 1 with no change spec", buf.getvalue())
            self.assertFalse(os.path.exists(
                os.path.join(d, "dashboard", "data", "ledger.jsonl")))

    def test_a_failure_is_counted_and_exits_nonzero(self):
        """A partial backfill leaves the durable record incomplete, and
        'appended N' alone reads as success."""
        import urllib.error
        with tempfile.TemporaryDirectory() as d:
            self._setup(d)

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 6, "head": {"ref": "feat/c"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                raise urllib.error.HTTPError(url, 502, "Bad Gateway", None, None)

            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch)
            self.assertEqual(rc, 1)
            self.assertIn("failed 1", buf.getvalue())

    def test_a_listing_error_exits_nonzero(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as d:
            self._setup(d)

            def fake_fetch(url, token, **kw):
                raise urllib.error.HTTPError(url, 500, "boom", None, None)

            self.assertEqual(
                ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch), 1)



class TestBackfillNamesSlugCollisions(unittest.TestCase):
    """`feat/foo` and `feat-foo` produce the same change_id, and so does the
    same branch merged twice. Backfill is the one place that turns into a SILENT
    omission, because the second pull request looks already recorded."""

    def _args(self, d):
        import argparse
        return argparse.Namespace(repo="o/r", pr=None, backfill=True, limit=50,
                                  repo_root=d, content_dir=d, spec=None,
                                  tier=None, merge_sha=None)

    def test_colliding_slugs_are_reported_on_stderr(self):
        import io, contextlib
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "dashboard", "data"))
            os.makedirs(os.path.join(d, "change-specs"))

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 7, "head": {"ref": "feat/foo"},
                             "merged_at": "2026-08-01T00:00:00Z"},
                            {"number": 8, "head": {"ref": "feat-foo"},
                             "merged_at": "2026-08-02T00:00:00Z"}]
                return {"head": {"sha": "h", "ref": "feat/foo"},
                        "merge_commit_sha": "m"}

            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(err):
                ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch)
            self.assertIn("#7", err.getvalue())
            self.assertIn("#8", err.getvalue())
            self.assertIn("feat-foo", err.getvalue())

    def test_an_entry_already_in_the_ledger_is_counted_not_dropped(self):
        import io, contextlib
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "dashboard", "data")
            os.makedirs(data)
            with open(os.path.join(data, "ledger.jsonl"), "w") as f:
                f.write(json.dumps({"change_id": "feat-a"}) + "\n")

            def fake_fetch(url, token, **kw):
                if "/pulls?" in url:
                    return [{"number": 3, "head": {"ref": "feat/a"},
                             "merged_at": "2026-08-01T00:00:00Z"}]
                return []

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch)
            self.assertIn("already recorded 1", buf.getvalue())



class TestANoSpecResultCannotShadowALaterPullRequest(unittest.TestCase):
    """`already` is updated only when an entry actually lands, never on a
    no-spec result. The sequence that would supposedly need is unreachable: two
    pull requests sharing a slug also share the change spec path, because
    append_one derives it from that same slug. So one cannot find a spec while
    the other does not.

    Marking the slug seen on a no-spec result would therefore buy nothing and
    could only suppress a legitimate entry - data loss dressed as
    de-duplication."""

    def _args(self, d):
        import argparse
        return argparse.Namespace(repo="o/r", pr=None, backfill=True, limit=50,
                                  repo_root=d, content_dir=d, spec=None,
                                  tier=None, merge_sha=None)

    def _two_colliding(self, d, with_spec):
        data = os.path.join(d, "dashboard", "data")
        os.makedirs(data)
        os.makedirs(os.path.join(d, "change-specs"))
        if with_spec:
            with open(os.path.join(d, "change-specs", "feat-foo.md"), "w") as f:
                f.write("---\ntier: normal\n---\nbody\n")

        def fake_fetch(url, token, **kw):
            if "/pulls?" in url:
                return [{"number": 7, "head": {"ref": "feat/foo"},
                         "merged_at": "2026-08-01T00:00:00Z"},
                        {"number": 8, "head": {"ref": "feat-foo"},
                         "merged_at": "2026-08-02T00:00:00Z"}]
            if "/comments" in url:
                return []
            if "/pulls/7" in url:
                return {"head": {"sha": "h7", "ref": "feat/foo"},
                        "merge_commit_sha": "m7"}
            return {"head": {"sha": "h8", "ref": "feat-foo"},
                    "merge_commit_sha": "m8"}
        return data, fake_fetch

    def _run(self, d, fake_fetch):
        import io, contextlib
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ledger_append.backfill(self._args(d), "tok", fetch=fake_fetch)
        return out.getvalue(), err.getvalue()

    def test_colliding_pull_requests_append_exactly_once(self):
        with tempfile.TemporaryDirectory() as d:
            data, fetch = self._two_colliding(d, with_spec=True)
            out, err = self._run(d, fetch)
            with open(os.path.join(data, "ledger.jsonl")) as f:
                entries = [json.loads(x) for x in f if x.strip()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["merge_sha"], "m7")
            self.assertIn("already recorded 1", out)
            # And the one that could not be recorded is NAMED, not dropped.
            self.assertIn("#7", err)
            self.assertIn("#8", err)

    def test_when_neither_has_a_spec_nothing_is_written_and_nothing_claims_it_was(self):
        with tempfile.TemporaryDirectory() as d:
            data, fetch = self._two_colliding(d, with_spec=False)
            out, _ = self._run(d, fetch)
            self.assertFalse(os.path.exists(os.path.join(data, "ledger.jsonl")))
            self.assertIn("appended 0", out)
            self.assertIn("skipped 2 with no change spec", out)


if __name__ == "__main__":
    unittest.main()
