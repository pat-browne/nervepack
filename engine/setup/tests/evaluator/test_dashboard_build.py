#!/usr/bin/env python3
"""Contract test for dashboard/build.py (stdlib unittest — no pytest, per the
harness language policy in CLAUDE.md). Black-box: runs the script as a subprocess
with explicit input/output paths and asserts on the generated metrics.js."""
import os
import re
import json
import subprocess
import tempfile
import shutil
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "..", "..", "..", "..", "dashboard", "build.py")


def run_build(jsonl_text, **env):
    """Write jsonl_text to a temp input, run build.py, return the metrics.js text.
    Extra kwargs are passed as environment variables (e.g. DASHBOARD_SESSIONS)."""
    with tempfile.TemporaryDirectory() as tmp:
        inp = os.path.join(tmp, "metrics.jsonl")
        out = os.path.join(tmp, "metrics.js")
        with open(inp, "w") as fh:
            fh.write(jsonl_text)
        e = dict(os.environ); e.update({k: str(v) for k, v in env.items()})
        subprocess.run(["python3", BUILD, inp, out], check=True,
                       capture_output=True, text=True, env=e)
        with open(out) as fh:
            return fh.read()


def _lesson(d, topic, provenance):
    """Write a minimal memory/lessons/<topic>.md carrying a provenance tag."""
    with open(os.path.join(d, topic + ".md"), "w") as fh:
        fh.write("---\nname: %s\nkind: lesson\nprovenance: %s\n---\nbody\n"
                 % (topic, provenance))


def _seven():
    """7 records, ts ascending s1..s7."""
    return "".join(
        '{"session_id":"s%d","ts":"2026-06-%02dT10:00:00Z"}\n' % (i, i)
        for i in range(1, 8)
    )


def parse_records(js_text):
    """Extract the window.METRICS array literal (followed by window.LEARNED)."""
    m = re.search(r"window\.METRICS = (.*?);\s*(?:\nwindow\.LEARNED|\Z)",
                  js_text, re.S)
    assert m, f"unexpected output shape: {js_text!r}"
    return json.loads(m.group(1))


class TestBuild(unittest.TestCase):
    def test_valid_records_sorted_by_ts(self):
        text = (
            '{"session_id":"b","ts":"2026-06-02T10:00:00Z","contribution_score":50}\n'
            '{"session_id":"a","ts":"2026-06-01T10:00:00Z","contribution_score":70}\n'
        )
        recs = parse_records(run_build(text))
        self.assertEqual([r["session_id"] for r in recs], ["a", "b"])

    def test_blank_and_malformed_lines_skipped(self):
        text = (
            '{"session_id":"a","ts":"2026-06-01T10:00:00Z"}\n'
            '\n'
            'not json at all\n'
            '{"session_id":"b","ts":"2026-06-02T10:00:00Z"}\n'
        )
        recs = parse_records(run_build(text))
        self.assertEqual([r["session_id"] for r in recs], ["a", "b"])

    def test_empty_input_yields_empty_array(self):
        self.assertIn("window.METRICS = [];", run_build(""))

    def test_deterministic(self):
        text = '{"session_id":"a","ts":"2026-06-01T10:00:00Z"}\n'
        self.assertEqual(run_build(text), run_build(text))

    def test_default_window_is_last_5(self):
        recs = parse_records(run_build(_seven()))  # no env -> default 5
        self.assertEqual([r["session_id"] for r in recs],
                         ["s3", "s4", "s5", "s6", "s7"])

    def test_window_is_tunable(self):
        recs = parse_records(run_build(_seven(), DASHBOARD_SESSIONS=3))
        self.assertEqual([r["session_id"] for r in recs], ["s5", "s6", "s7"])

    def test_window_zero_means_all(self):
        recs = parse_records(run_build(_seven(), DASHBOARD_SESSIONS=0))
        self.assertEqual(len(recs), 7)

    def test_window_larger_than_data_yields_all(self):
        recs = parse_records(run_build(_seven(), DASHBOARD_SESSIONS=100))
        self.assertEqual(len(recs), 7)

    def test_agent_sessions_excluded_from_window(self):
        """agent-* subagent sessions are internal machinery — they record asset
        presence but never mark usefulness (used=False) and carry low/zero scores,
        so they skew every dashboard panel. They must be excluded from the window
        even when they are the most recent records. metrics.jsonl stays full."""
        text = (
            '{"session_id":"r1","ts":"2026-06-01T10:00:00Z","project":"myproj"}\n'
            '{"session_id":"r2","ts":"2026-06-02T10:00:00Z","project":"myproj"}\n'
            '{"session_id":"a1","ts":"2026-06-03T10:00:00Z","project":"agent-abc123"}\n'
            '{"session_id":"a2","ts":"2026-06-04T10:00:00Z","project":"agent-abc123"}\n'
        )
        recs = parse_records(run_build(text, DASHBOARD_SESSIONS=5))
        self.assertEqual([r["session_id"] for r in recs], ["r1", "r2"])
        self.assertFalse(
            any(str(r.get("project", "")).startswith("agent-") for r in recs))

    def test_resolved_suggestions_are_filtered_out(self):
        """A suggestion whose (normalized) text is in the resolved ledger is dropped
        from the rendered record, so the dashboard never resurfaces it; others stay."""
        rec = (
            '{"session_id":"a","ts":"2026-06-01T10:00:00Z","suggestions":['
            '{"text":"Promote auto-push rule","confidence":0.8},'
            '{"text":"Strengthen the directive","confidence":0.6}]}\n'
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as rf:
            rf.write("# acted on\npromote auto-push rule\n")  # lowercase -> normalized match
            resolved = rf.name
        try:
            recs = parse_records(run_build(
                rec, NP_RESOLVED_SUGGESTIONS=resolved, DASHBOARD_SESSIONS=0))
        finally:
            os.unlink(resolved)
        texts = [s["text"] for s in recs[0].get("suggestions", [])]
        self.assertEqual(texts, ["Strengthen the directive"])

    def test_no_resolved_file_keeps_all_suggestions(self):
        rec = ('{"session_id":"a","ts":"2026-06-01T10:00:00Z","suggestions":'
               '[{"text":"Keep me","confidence":0.5}]}\n')
        recs = parse_records(run_build(
            rec, NP_RESOLVED_SUGGESTIONS="/nonexistent/resolved.txt", DASHBOARD_SESSIONS=0))
        self.assertEqual([s["text"] for s in recs[0]["suggestions"]], ["Keep me"])

    def test_learned_counts_playbooks_and_strategies(self):
        """build.py emits window.LEARNED = {playbooks, strategies} splitting the
        memory/lessons topics by provenance (failure -> playbooks, success ->
        strategies), INDEX.md/README.md excluded, so the dashboard shows growth."""
        with tempfile.TemporaryDirectory() as d:
            le = os.path.join(d, "lessons"); os.makedirs(le)
            _lesson(le, "a", "failure"); _lesson(le, "b", "failure")
            _lesson(le, "x", "success")
            for f in ("INDEX.md", "README.md"):
                with open(os.path.join(le, f), "w"):
                    pass
            js = run_build("", NP_LESSONS_DIR=le)
        m = re.search(r"window\.LEARNED = (\{.*?\});", js, re.S)
        self.assertTrue(m, f"no window.LEARNED in output: {js!r}")
        learned = json.loads(m.group(1))
        self.assertEqual(learned, {"playbooks": 2, "strategies": 1,
                                   "strategy_names": ["x"]})

    def test_learned_strategy_names_sorted_excluding_index_readme(self):
        """strategy_names lists success-provenance <topic> names, sorted, with
        INDEX.md / README.md and non-.md files excluded."""
        with tempfile.TemporaryDirectory() as d:
            le = os.path.join(d, "lessons"); os.makedirs(le)
            _lesson(le, "b", "success"); _lesson(le, "a", "success")
            for f in ("INDEX.md", "README.md"):
                with open(os.path.join(le, f), "w"):
                    pass
            with open(os.path.join(le, "notmd.txt"), "w"):
                pass
            js = run_build("", NP_LESSONS_DIR=le)
        m = re.search(r"window\.LEARNED = (\{.*?\});", js, re.S)
        learned = json.loads(m.group(1))
        self.assertEqual(learned["strategy_names"], ["a", "b"])
        self.assertEqual(learned["strategies"], 2)

    def test_learned_counts_resolve_content_dir_when_no_explicit_dirs(self):
        """After the engine/content-overlay split, lessons live in the content
        overlay under memory/lessons, not the engine repo. With no explicit
        NP_LESSONS_DIR, learned_counts must resolve it under <content>/memory/lessons
        (NP_CONTENT_DIR, mirroring np_content_dir) — otherwise a bare `build.py`
        (manual open-dashboard, MCP summary) reports 0/0 and the Wins & learnings
        panel looks empty. Explicit dir still overrides."""
        with tempfile.TemporaryDirectory() as content:
            le = os.path.join(content, "memory", "lessons"); os.makedirs(le)
            _lesson(le, "p1", "failure"); _lesson(le, "p2", "failure")
            _lesson(le, "s1", "success")
            for f in ("INDEX.md", "README.md"):
                with open(os.path.join(le, f), "w"):
                    pass
            # NP_CONTENT_DIR set, but NOT NP_LESSONS_DIR.
            e = dict(os.environ)
            e.pop("NP_LESSONS_DIR", None)
            with tempfile.TemporaryDirectory() as tmp:
                inp = os.path.join(tmp, "metrics.jsonl")
                with open(inp, "w"):
                    pass
                out = os.path.join(tmp, "metrics.js")
                e["NP_CONTENT_DIR"] = content
                subprocess.run(["python3", BUILD, inp, out], check=True,
                               capture_output=True, text=True, env=e)
                with open(out) as fh:
                    js = fh.read()
        m = re.search(r"window\.LEARNED = (\{.*?\});", js, re.S)
        learned = json.loads(m.group(1))
        self.assertEqual(learned, {"playbooks": 2, "strategies": 1,
                                   "strategy_names": ["s1"]})


    def test_tokens_saved_lower_bound_math(self):
        """build.py emits window.TOKENS_SAVED = {total, per_session} as a
        deterministic lower bound: sum of max(0, cache_read - directive_tokens)
        per session. directive_tokens defaults to 0 when absent (fail-open).

        Synthetic record shape:
          session A: cache_read=10000, directive_tokens=500  -> saved=9500
          session B: cache_read=3000,  directive_tokens=0    -> saved=3000
          session C: cache_read=200,   directive_tokens=500  -> saved=0 (clamp)
        Expected: total=12500, per_session avg=12500//3=4166 (floor division)
        """
        rec = "\n".join([
            json.dumps({"session_id": "a", "ts": "2026-06-01T10:00:00Z",
                        "signals": {"tokens": {"cache_read": 10000}, "directive_tokens": 500}}),
            json.dumps({"session_id": "b", "ts": "2026-06-02T10:00:00Z",
                        "signals": {"tokens": {"cache_read": 3000}}}),   # no directive_tokens
            json.dumps({"session_id": "c", "ts": "2026-06-03T10:00:00Z",
                        "signals": {"tokens": {"cache_read": 200}, "directive_tokens": 500}}),
        ]) + "\n"
        js = run_build(rec, DASHBOARD_SESSIONS=0)
        m = re.search(r"window\.TOKENS_SAVED = (\{.*?\});", js, re.S)
        self.assertTrue(m, f"window.TOKENS_SAVED missing from output:\n{js}")
        saved = json.loads(m.group(1))
        self.assertEqual(saved["total"], 12500,
                         f"expected total=12500, got {saved['total']}")
        self.assertEqual(saved["per_session"], 4166,
                         f"expected per_session=4166, got {saved['per_session']}")

    def test_tokens_saved_zero_when_no_cache_read(self):
        """Sessions with no cache_read (or cache_read < directive_tokens) clamp to 0."""
        rec = json.dumps({"session_id": "x", "ts": "2026-06-01T10:00:00Z",
                          "signals": {"directive_tokens": 500}}) + "\n"
        js = run_build(rec, DASHBOARD_SESSIONS=0)
        m = re.search(r"window\.TOKENS_SAVED = (\{.*?\});", js, re.S)
        self.assertTrue(m, "window.TOKENS_SAVED missing")
        saved = json.loads(m.group(1))
        self.assertEqual(saved["total"], 0)
        self.assertEqual(saved["per_session"], 0)

    def test_tokens_saved_empty_input(self):
        """With no records, TOKENS_SAVED total and per_session are both 0."""
        js = run_build("")
        m = re.search(r"window\.TOKENS_SAVED = (\{.*?\});", js, re.S)
        self.assertTrue(m, "window.TOKENS_SAVED missing")
        saved = json.loads(m.group(1))
        self.assertEqual(saved["total"], 0)
        self.assertEqual(saved["per_session"], 0)

    def test_graduation_emitted_from_fixture(self):
        """build.py emits window.GRADUATION from a committed graduation-candidates.json
        (written by np_skill_maintain.py, content-routed) so the dashboard can surface
        strategies/playbooks overdue to graduate into a skill. The candidate list and
        thresholds pass through verbatim."""
        fixture = {
            "candidates": [
                {"kind": "strategy", "name": "security-review", "seen": 14,
                 "bytes": 7300, "reasons": ["seen", "bytes"]},
                {"kind": "playbook", "name": "bash-nested-substitution", "seen": 11,
                 "bytes": 1200, "reasons": ["seen"]},
            ],
            "thresholds": {"graduate_seen": 10, "graduate_kb": 6},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as gf:
            json.dump(fixture, gf)
            grad = gf.name
        try:
            js = run_build("", NP_GRADUATION_CANDIDATES=grad)
        finally:
            os.unlink(grad)
        m = re.search(r"window\.GRADUATION = (\{.*?\});", js, re.S)
        self.assertTrue(m, f"window.GRADUATION missing from output:\n{js}")
        grad_out = json.loads(m.group(1))
        self.assertEqual(grad_out, fixture)

    def test_graduation_missing_file_is_empty_fail_open(self):
        """No committed graduation-candidates.json (e.g. cloud/CI, or no candidates) ->
        an empty candidate list, never a crash. The panel renders its empty state."""
        js = run_build("", NP_GRADUATION_CANDIDATES="/nonexistent/graduation.json")
        m = re.search(r"window\.GRADUATION = (\{.*?\});", js, re.S)
        self.assertTrue(m, "window.GRADUATION missing")
        grad_out = json.loads(m.group(1))
        self.assertEqual(grad_out["candidates"], [])

    def test_graduation_malformed_json_is_empty_fail_open(self):
        """A malformed/partial graduation-candidates.json must not break the build —
        it degrades to an empty candidate list (fail-open)."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as gf:
            gf.write("{not valid json")
            grad = gf.name
        try:
            js = run_build("", NP_GRADUATION_CANDIDATES=grad)
        finally:
            os.unlink(grad)
        m = re.search(r"window\.GRADUATION = (\{.*?\});", js, re.S)
        self.assertTrue(m, "window.GRADUATION missing")
        grad_out = json.loads(m.group(1))
        self.assertEqual(grad_out["candidates"], [])


def _parse_wiki(js_text):
    """Extract the window.WIKI = {...} object literal from build.py output."""
    m = re.search(r"window\.WIKI = (\{.*?\});\s*\n", js_text, re.S)
    assert m, f"no window.WIKI object in output: {js_text!r}"
    return json.loads(m.group(1))


def _write_wiki(content_dir, kind, name, frontmatter, body):
    """Write a fixture wiki page under <content>/wiki/<entities|concepts>/<name>.md."""
    sub = "entities" if kind == "entity" else "concepts"
    d = os.path.join(content_dir, "wiki", sub)
    os.makedirs(d, exist_ok=True)
    fm = "".join("%s: %s\n" % (k, v) for k, v in frontmatter.items())
    with open(os.path.join(d, name + ".md"), "w") as fh:
        fh.write("---\n" + fm + "---\n\n" + body)


def _write_source(content_dir, topic, name, frontmatter, body):
    """Write a fixture under <content>/sources/<topic>/<name>.md."""
    d = os.path.join(content_dir, "sources", topic)
    os.makedirs(d, exist_ok=True)
    fm = "".join("%s: %s\n" % (k, v) for k, v in frontmatter.items())
    with open(os.path.join(d, name + ".md"), "w") as fh:
        fh.write("---\n" + fm + "---\n\n" + body)


def run_build_wiki(content_dir, **env):
    """Run build.py with NP_CONTENT_DIR=content_dir (so it resolves wiki/ there)
    and empty metrics input; return the generated metrics.js text."""
    e = {"NP_CONTENT_DIR": content_dir}
    e.update(env)
    with tempfile.TemporaryDirectory() as tmp:
        inp = os.path.join(tmp, "metrics.jsonl")
        with open(inp, "w"):
            pass
        out = os.path.join(tmp, "metrics.js")
        ev = dict(os.environ)
        ev.pop("NP_PLAYBOOKS_DIR", None); ev.pop("NP_STRATEGIES_DIR", None)
        ev.update({k: str(v) for k, v in e.items()})
        subprocess.run(["python3", BUILD, inp, out], check=True,
                       capture_output=True, text=True, env=ev)
        with open(out) as fh:
            return fh.read()


def _write_topic(content_dir, topic, name, frontmatter, body):
    """Write a fixture wiki page under <content>/wiki/topics/<topic>/<name>.md."""
    d = os.path.join(content_dir, "wiki", "topics", topic)
    os.makedirs(d, exist_ok=True)
    fm = "".join("%s: %s\n" % (k, v) for k, v in frontmatter.items())
    with open(os.path.join(d, name + ".md"), "w") as fh:
        fh.write("---\n" + fm + "---\n\n" + body)


def _write_concept(content_dir, name, frontmatter, body):
    """Write a fixture concept synthesis page under
    <content>/wiki/concepts/<name>/<name>.md (concepts are folders, like topics)."""
    d = os.path.join(content_dir, "wiki", "concepts", name)
    os.makedirs(d, exist_ok=True)
    fm = "".join("%s: %s\n" % (k, v) for k, v in frontmatter.items())
    with open(os.path.join(d, name + ".md"), "w") as fh:
        fh.write("---\n" + fm + "---\n\n" + body)


class TestWikiIndex(unittest.TestCase):
    """window.WIKI is {topics:[{topic,synthesis,sources[]}], concepts:[]}.
    New layout only: wiki/topics/<topic>/ (synthesis + co-located sources) and
    wiki/concepts/<name>/. Legacy wiki/entities/ and top-level sources/ are ignored."""

    def test_groups_topics_concepts_and_sources(self):
        """New-layout topic + concept + co-located source are gathered into new shape."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": '["ownership"]'},
                         "# Rust\n\nSystems language.")
            _write_concept(cd, "borrow-checker",
                           {"name": "borrow-checker", "kind": "concept",
                            "last_updated": "2026-05-10", "sources": "[]"},
                           "# Borrow checker\n\nOwnership.")
            _write_topic(cd, "design", "wcag-2.2",
                         {"name": "wcag-2.2", "kind": "reference", "topic": "design",
                          "version": "2.2", "captured_date": "2026-06-01"},
                         "# WCAG 2.2\n\nContrast rules.")
            wiki = _parse_wiki(run_build_wiki(cd))
        topic_names = [t["topic"] for t in wiki["topics"]]
        self.assertIn("rust", topic_names)
        self.assertIn("design", topic_names)
        self.assertEqual([c["name"] for c in wiki["concepts"]], ["borrow-checker"])
        design_topic = next(t for t in wiki["topics"] if t["topic"] == "design")
        self.assertEqual(design_topic["sources"][0]["name"], "wcag-2.2")

    def test_html_paths_are_relative_under_data(self):
        """New-layout topic synthesis html maps to wiki/topics/<topic>/<name>.html;
        co-located source html maps to wiki/topics/<topic>/<name>.html."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "# Rust\n\nx.")
            _write_topic(cd, "aws", "creds",
                         {"name": "creds", "kind": "reference", "topic": "aws", "version": "1"},
                         "# Creds\n\ny.")
            wiki = _parse_wiki(run_build_wiki(cd))
        rust_topic = next(t for t in wiki["topics"] if t["topic"] == "rust")
        self.assertEqual(rust_topic["synthesis"]["html"], "data/wiki/topics/rust/rust.html")
        aws_topic = next(t for t in wiki["topics"] if t["topic"] == "aws")
        self.assertEqual(aws_topic["sources"][0]["html"], "data/wiki/topics/aws/creds.html")

    def test_excerpt_skips_heading(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "python", "python",
                         {"name": "python", "kind": "topic",
                          "last_updated": "2026-06-07", "sources": "[]"},
                         "# Python\n\nWhat nervepack knows.\n\nMore.")
            wiki = _parse_wiki(run_build_wiki(cd))
        python_topic = next(t for t in wiki["topics"] if t["topic"] == "python")
        self.assertEqual(python_topic["synthesis"]["excerpt"], "What nervepack knows.")

    def test_missing_dirs_yield_empty_groups(self):
        with tempfile.TemporaryDirectory() as cd:
            wiki = _parse_wiki(run_build_wiki(cd))
        self.assertEqual(wiki, {"topics": [], "concepts": []})

    def test_index_md_and_readme_excluded(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "aws", "aws",
                         {"name": "aws", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "# AWS\n\nx.")
            td = os.path.join(cd, "wiki", "topics", "aws")
            with open(os.path.join(td, "INDEX.md"), "w"):
                pass
            with open(os.path.join(td, "README.md"), "w"):
                pass
            wiki = _parse_wiki(run_build_wiki(cd))
        topic_names = [t["topic"] for t in wiki["topics"]]
        self.assertEqual(topic_names, ["aws"])

    def test_wiki_nav_off_yields_empty_groups(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "# Rust\n\nx.")
            wiki = _parse_wiki(run_build_wiki(cd, WIKI_NAV="off"))
        self.assertEqual(wiki, {"topics": [], "concepts": []})


class TestRenderPages(unittest.TestCase):
    """build.py renders each wiki/source .md to a styled .html next to metrics.js,
    under wiki/topics/<topic>/ and wiki/concepts/. Cross-links resolve; escaping holds."""

    def _run(self, cd, **env):
        """Run build.py with explicit out in a temp dir; return (out_dir, js)."""
        e = {"NP_CONTENT_DIR": cd}
        e.update({k: str(v) for k, v in env.items()})
        tmp = tempfile.mkdtemp()
        inp = os.path.join(tmp, "metrics.jsonl")
        with open(inp, "w"):
            pass
        out = os.path.join(tmp, "metrics.js")
        ev = dict(os.environ)
        ev.pop("NP_PLAYBOOKS_DIR", None); ev.pop("NP_STRATEGIES_DIR", None)
        ev.update(e)
        subprocess.run(["python3", BUILD, inp, out], check=True,
                       capture_output=True, text=True, env=ev)
        with open(out) as fh:
            return tmp, fh.read()

    def test_renders_wiki_and_source_html_files(self):
        """New-layout topic renders to wiki/topics/<topic>/<name>.html;
        co-located source renders to wiki/topics/<topic>/<name>.html."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"},
                         "# Rust\n\nSystems language.")
            _write_topic(cd, "design", "wcag-2.2",
                         {"name": "wcag-2.2", "kind": "reference", "topic": "design",
                          "version": "2.2"},
                         "# WCAG\n\nContrast.")
            out_dir, _ = self._run(cd)
        wiki_html = os.path.join(out_dir, "wiki", "topics", "rust", "rust.html")
        src_html = os.path.join(out_dir, "wiki", "topics", "design", "wcag-2.2.html")
        self.assertTrue(os.path.isfile(wiki_html))
        self.assertTrue(os.path.isfile(src_html))
        with open(wiki_html) as fh:
            body = fh.read()
        self.assertIn("<h1>Rust</h1>", body)

    def test_rendered_html_escapes_content(self):
        """Concepts render to wiki/concepts/<concept>/<name>.html (concepts are folders)."""
        with tempfile.TemporaryDirectory() as cd:
            _write_concept(cd, "x",
                           {"name": "x", "kind": "concept",
                            "last_updated": "2026-06-01", "sources": "[]"},
                           "# X\n\n<script>alert(1)</script>")
            out_dir, _ = self._run(cd)
        with open(os.path.join(out_dir, "wiki", "concepts", "x", "x.html")) as fh:
            body = fh.read()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_cross_link_resolves_between_pages(self):
        """New-layout: topic at wiki/topics/rust/, concept at wiki/concepts/<concept>/.
        Link from topic to concept is ../../concepts/<concept>/<name>.html."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"},
                         "# Rust\n\nSee [[borrow-checker]].")
            _write_concept(cd, "borrow-checker",
                           {"name": "borrow-checker", "kind": "concept",
                            "last_updated": "2026-06-01", "sources": "[]"},
                           "# BC\n\nx.")
            out_dir, _ = self._run(cd)
        with open(os.path.join(out_dir, "wiki", "topics", "rust", "rust.html")) as fh:
            body = fh.read()
        self.assertIn('href="../../concepts/borrow-checker/borrow-checker.html"', body)

    def test_dangling_cross_link_is_plain_text(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"},
                         "# Rust\n\nSee [[ghost]].")
            out_dir, _ = self._run(cd)
        with open(os.path.join(out_dir, "wiki", "topics", "rust", "rust.html")) as fh:
            body = fh.read()
        self.assertNotIn("[[ghost]]", body)
        self.assertIn("ghost", body)

    def test_idempotent_rerun(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "# Rust\n\nx.")
            out_dir, _ = self._run(cd)
            with open(os.path.join(out_dir, "wiki", "topics", "rust", "rust.html")) as fh:
                first = fh.read()
            # second build into the SAME content dir, fresh out dir
            out_dir2, _ = self._run(cd)
            with open(os.path.join(out_dir2, "wiki", "topics", "rust", "rust.html")) as fh:
                second = fh.read()
        self.assertEqual(first, second)

    def test_wiki_nav_off_renders_nothing(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "# Rust\n\nx.")
            out_dir, _ = self._run(cd, WIKI_NAV="off")
        self.assertFalse(os.path.exists(os.path.join(out_dir, "wiki")))

    def test_wiki_back_link_depth(self):
        """New-layout topic pages live at <out>/wiki/topics/<topic>/<name>.html (4 dirs
        below the index.html). The back-link must be ../../../../index.html."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "rust", "rust",
                         {"name": "rust", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"},
                         "# Rust\n\nSystems language.")
            out_dir, _ = self._run(cd)
        with open(os.path.join(out_dir, "wiki", "topics", "rust", "rust.html")) as fh:
            body = fh.read()
        self.assertIn('href="../../../../index.html"', body)

    def test_source_back_link_depth(self):
        """Co-located source pages live at <out>/wiki/topics/<topic>/<name>.html
        (4 dirs below the index.html). The back-link must be ../../../../index.html."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "design", "wcag-2.2",
                         {"name": "wcag-2.2", "kind": "reference", "topic": "design",
                          "version": "2.2"},
                         "# WCAG\n\nContrast.")
            out_dir, _ = self._run(cd)
        with open(os.path.join(out_dir, "wiki", "topics", "design", "wcag-2.2.html")) as fh:
            body = fh.read()
        self.assertIn('href="../../../../index.html"', body)


import sys as _sys
import importlib.util as _ilu

def _load_build_direct():
    """Load dashboard/build.py as a module (direct import, not subprocess)."""
    _spec = _ilu.spec_from_file_location("build", BUILD)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod


def _mk(root, rel, kind, name, sources=None, extra=""):
    d = os.path.join(root, os.path.dirname(rel))
    os.makedirs(d, exist_ok=True)
    fm = "---\nname: %s\nkind: %s\n" % (name, kind)
    if sources is not None:
        fm += "sources: %s\n" % json.dumps(sources)
    fm += "---\n\nFirst paragraph excerpt.\n"
    with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
        fh.write(fm + extra)


class TestWikiIndexNewLayout(unittest.TestCase):
    """Tests for wiki_index() reading the wiki/topics/ layout."""

    def test_wiki_index_new_topics_layout(self):
        bp = _load_build_direct()
        with tempfile.TemporaryDirectory() as cd:
            _mk(cd, "wiki/topics/aws/aws.md", "topic", "aws", sources=["creds"])
            _mk(cd, "wiki/topics/aws/creds.md", "reference", "creds")
            _mk(cd, "wiki/concepts/prompt-caching/prompt-caching.md", "concept", "prompt-caching", sources=[])
            os.environ["NP_CONTENT_DIR"] = cd
            idx = bp.wiki_index()
            os.environ.pop("NP_CONTENT_DIR", None)
        names = [t["topic"] for t in idx["topics"]]
        self.assertEqual(names, ["aws"], names)
        aws = idx["topics"][0]
        self.assertEqual(aws["synthesis"]["name"], "aws")
        self.assertEqual(aws["synthesis"]["html"], "data/wiki/topics/aws/aws.html")
        self.assertEqual([s["name"] for s in aws["sources"]], ["creds"])
        self.assertEqual([c["name"] for c in idx["concepts"]], ["prompt-caching"])

    def test_wiki_index_ignores_legacy_dirs(self):
        bp = _load_build_direct()
        with tempfile.TemporaryDirectory() as cd:
            _mk(cd, "wiki/entities/python.md", "entity", "python", sources=[])
            _mk(cd, "sources/python/typing.md", "reference", "typing")
            os.environ["NP_CONTENT_DIR"] = cd
            idx = bp.wiki_index()
            os.environ.pop("NP_CONTENT_DIR", None)
        assert idx["topics"] == [] and idx["concepts"] == []


class TestWikiIndexLayers(unittest.TestCase):
    """wiki_index merges a team overlay over personal per team.merge."""

    def tearDown(self):
        for d in (getattr(self, "_p", None), getattr(self, "_t", None), getattr(self, "_h", None)):
            if d:
                shutil.rmtree(d, ignore_errors=True)

    def _two_layers(self, mode):
        self._p = tempfile.mkdtemp(); self._t = tempfile.mkdtemp(); self._h = tempfile.mkdtemp()
        # same topic name 'rust' in both layers; a personal-only 'go'; a team-only 'zig'
        _write_topic(self._p, "rust", "rust", {"name": "rust", "kind": "topic",
                     "last_updated": "2026-06-01", "sources": "[]"}, "PERSONAL rust")
        _write_topic(self._t, "rust", "rust", {"name": "rust", "kind": "topic",
                     "last_updated": "2026-06-02", "sources": "[]"}, "TEAM rust")
        _write_topic(self._p, "go", "go", {"name": "go", "kind": "topic",
                     "last_updated": "2026-06-01", "sources": "[]"}, "PERSONAL go")
        _write_topic(self._t, "zig", "zig", {"name": "zig", "kind": "topic",
                     "last_updated": "2026-06-01", "sources": "[]"}, "TEAM zig")
        toggles_local = os.path.join(self._h, "local")
        with open(toggles_local, "w") as fh:
            fh.write("team.merge=%s\n" % mode)
        # toggles.conf lives at engine/setup/toggles.conf; this test file is at
        # engine/setup/tests/evaluator/ → two levels up.
        conf = os.path.join(os.path.dirname(__file__), "..", "..", "toggles.conf")
        return _parse_wiki(run_build_wiki(self._p, NP_TEAM_DIR=self._t,
                                          NP_TOGGLES_CONF=conf, NP_TOGGLES_LOCAL=toggles_local))

    def test_override_team_wins_union(self):
        w = self._two_layers("override")
        names = [t["topic"] for t in w["topics"]]
        self.assertEqual(sorted(set(names)), ["go", "rust", "zig"])  # union
        self.assertEqual(names.count("rust"), 1)                      # deduped
        rust = next(t for t in w["topics"] if t["topic"] == "rust")
        self.assertIn("TEAM rust", rust["synthesis"]["excerpt"])      # team won

    def test_team_only(self):
        w = self._two_layers("team-only")
        self.assertEqual(sorted(t["topic"] for t in w["topics"]), ["rust", "zig"])  # team set only

    def test_concatenate_merges_same_named_topic(self):
        # concatenate unions topics across layers, but a same-named topic is ONE
        # node, not a duplicate ("effectively the same" — issue #44).
        w = self._two_layers("concatenate")
        names = [t["topic"] for t in w["topics"]]
        self.assertEqual(sorted(names), ["go", "rust", "zig"])        # union of topics
        self.assertEqual(names.count("rust"), 1)                      # merged, not duplicated
        rust = next(t for t in w["topics"] if t["topic"] == "rust")
        self.assertIn("TEAM rust", rust["synthesis"]["excerpt"])      # higher layer's synthesis wins


class TestWikiNesting(unittest.TestCase):
    """A topic may nest reference pages in subdirectories (the content dir tree).
    wiki_index carries each page's `dir` (nesting path) and a subdir-qualified
    html path; a flat topic (no subdirs) still indexes as before (dir == '')."""

    def test_flat_and_nested_indexing(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic(cd, "plat", "plat",
                         {"name": "plat", "kind": "topic",
                          "last_updated": "2026-06-01", "sources": "[]"}, "hub")
            _write_topic(cd, "plat", "flatpage",
                         {"name": "flatpage", "kind": "reference"}, "flat ref")
            sub = os.path.join(cd, "wiki", "topics", "plat", "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "nestedpage.md"), "w") as fh:
                fh.write("---\nname: nestedpage\nkind: reference\n---\n\nnested ref")
            w = _parse_wiki(run_build_wiki(cd))
        plat = next(t for t in w["topics"] if t["topic"] == "plat")
        srcs = {s["name"]: s for s in plat["sources"]}
        # flat page: no subdir
        self.assertEqual(srcs["flatpage"]["dir"], "")
        self.assertEqual(srcs["flatpage"]["html"], "data/wiki/topics/plat/flatpage.html")
        # nested page: dir carries the subdir, html path is subdir-qualified
        self.assertEqual(srcs["nestedpage"]["dir"], "sub")
        self.assertEqual(srcs["nestedpage"]["html"], "data/wiki/topics/plat/sub/nestedpage.html")


class TestLearnedLayers(unittest.TestCase):
    """learned_counts unions memory/lessons across team>personal, split by
    provenance (counts dedup)."""

    def setUp(self):
        self._p = tempfile.mkdtemp(); self._t = tempfile.mkdtemp(); self._h = tempfile.mkdtemp()

    def tearDown(self):
        for d in (self._p, self._t, self._h):
            shutil.rmtree(d, ignore_errors=True)

    def _mk(self, root, provenance, names):
        d = os.path.join(root, "memory", "lessons"); os.makedirs(d, exist_ok=True)
        for n in names:
            with open(os.path.join(d, n + ".md"), "w") as fh:
                fh.write("---\nname: %s\nprovenance: %s\n---\nbody\n" % (n, provenance))

    def _run(self, mode):
        with open(os.path.join(self._h, "local"), "w") as fh:
            fh.write("team.merge=%s\n" % mode)
        conf = os.path.join(os.path.dirname(__file__), "..", "..", "toggles.conf")
        js = run_build("", NP_CONTENT_DIR=self._p, NP_TEAM_DIR=self._t,
                       NP_LESSONS_DIR="",
                       NP_TOGGLES_CONF=conf, NP_TOGGLES_LOCAL=os.path.join(self._h, "local"))
        m = re.search(r"window\.LEARNED = (\{.*?\});", js, re.S)
        self.assertTrue(m, "no window.LEARNED in: %r" % js)
        return json.loads(m.group(1))

    def test_override_unions_and_dedups(self):
        self._mk(self._p, "success", ["a", "b"]); self._mk(self._t, "success", ["b", "c"])
        self._mk(self._p, "failure", ["p1"]); self._mk(self._t, "failure", ["p1", "p2"])
        learned = self._run("override")
        self.assertEqual(learned["strategy_names"], ["a", "b", "c"])  # union, deduped
        self.assertEqual(learned["strategies"], 3)
        self.assertEqual(learned["playbooks"], 2)                     # p1 deduped

    def test_team_only(self):
        self._mk(self._p, "success", ["a", "b"]); self._mk(self._t, "success", ["c"])
        learned = self._run("team-only")
        self.assertEqual(learned["strategy_names"], ["c"])            # team set only


class TestConceptFolders(unittest.TestCase):
    """Concepts are folders (wiki/concepts/<concept>/) like topics: a kind:concept
    synthesis page + co-located kind:reference sources. learned_counts reads memory/."""

    def test_concept_folder_synthesis_sources_and_memory_counts(self):
        bp = _load_build_direct()
        with tempfile.TemporaryDirectory() as cd:
            _mk(cd, "wiki/concepts/widgets/widgets.md", "concept", "widgets", sources=[])
            _mk(cd, "wiki/concepts/widgets/spec.md", "reference", "spec")
            os.makedirs(os.path.join(cd, "memory", "lessons"), exist_ok=True)
            with open(os.path.join(cd, "memory", "lessons", "foo.md"), "w") as fh:
                fh.write("---\nname: foo\nprovenance: failure\n---\nbody\n")
            with open(os.path.join(cd, "memory", "lessons", "bar.md"), "w") as fh:
                fh.write("---\nname: bar\nprovenance: success\n---\nbody\n")
            saved = {k: os.environ.get(k)
                     for k in ("NP_CONTENT_DIR", "NP_LESSONS_DIR")}
            os.environ["NP_CONTENT_DIR"] = cd
            os.environ.pop("NP_LESSONS_DIR", None)
            try:
                idx = bp.wiki_index()
                lc = bp.learned_counts()
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        c = {x["name"]: x for x in idx["concepts"]}["widgets"]
        self.assertIsNotNone(c["synthesis"], "concept synthesis page not indexed")
        self.assertTrue(any(s["name"] == "spec" for s in c["sources"]),
                        "co-located concept source not indexed")
        self.assertEqual(lc["playbooks"], 1, "learned counts not reading memory/playbooks")
        self.assertEqual(lc["strategies"], 1, "learned counts not reading memory/strategies")


class TestBacklogMetrics(unittest.TestCase):
    """window.BACKLOG: the back-capture sweep's pending/oldest-age/drain-rate
    snapshot, read from the same local-cache dirs np-backcapture-sweep.sh uses
    (BACKCAPTURE_QUEUE_DIR/BACKCAPTURE_SEEN_DIR — same env var names as the sweep
    script's own overrides, so tests sandbox exactly what production reads)."""

    def _queue_entry(self, qdir, sid, mtime):
        with open(os.path.join(qdir, sid), "w") as fh:
            json.dump({"sid": sid, "mtime": mtime, "transcript_path": "/x", "cwd": "/x"}, fh)

    def _mark_seen(self, sdir, sid):
        open(os.path.join(sdir, sid), "w").close()

    def _parse(self, js):
        m = re.search(r"window\.BACKLOG = (\{.*?\});", js, re.S)
        self.assertTrue(m, f"window.BACKLOG missing from output:\n{js}")
        return json.loads(m.group(1))

    def test_pending_excludes_seen_and_oldest_wins(self):
        """pending = queued minus seen; oldest_pending_days reflects the OLDEST
        still-pending entry's recorded mtime, not the newest or an already-seen one."""
        now = time.time()
        with tempfile.TemporaryDirectory() as qdir, tempfile.TemporaryDirectory() as sdir:
            self._queue_entry(qdir, "a-older", now - 5 * 86400)   # 5 days old, pending
            self._queue_entry(qdir, "b-newer", now - 1 * 86400)   # 1 day old, pending
            self._queue_entry(qdir, "c-done", now - 9 * 86400)    # oldest of all, but already seen
            self._mark_seen(sdir, "c-done")
            js = run_build("", BACKCAPTURE_QUEUE_DIR=qdir, BACKCAPTURE_SEEN_DIR=sdir)
        b = self._parse(js)
        self.assertEqual(b["pending"], 2, "seen entry must not count as pending")
        # oldest_pending_days is computed against build.py's own time.time() call,
        # a few ms after `now` above — assert it's much closer to 5 days than 1.
        self.assertGreater(b["oldest_pending_days"], 3)

    def test_missing_dirs_is_empty_fail_open(self):
        """No queue/seen dirs yet (fresh box, or backcapture never ran) -> zeroed
        stats, never a crash — the panel renders its quiet empty state."""
        js = run_build("", BACKCAPTURE_QUEUE_DIR="/nonexistent/queue",
                       BACKCAPTURE_SEEN_DIR="/nonexistent/seen")
        b = self._parse(js)
        self.assertEqual(b["pending"], 0)
        self.assertIsNone(b["oldest_pending_days"])
        self.assertEqual(b["resolved_last_24h"], 0)

    def test_malformed_queue_entry_still_counts_as_pending_but_not_aged(self):
        """A corrupt/unreadable queue file must not break the build or vanish from
        the pending count — it just can't contribute to the oldest-age figure."""
        with tempfile.TemporaryDirectory() as qdir, tempfile.TemporaryDirectory() as sdir:
            with open(os.path.join(qdir, "corrupt"), "w") as fh:
                fh.write("{not valid json")
            self._queue_entry(qdir, "valid", time.time() - 86400)
            js = run_build("", BACKCAPTURE_QUEUE_DIR=qdir, BACKCAPTURE_SEEN_DIR=sdir)
        b = self._parse(js)
        self.assertEqual(b["pending"], 2, "corrupt entry should still count toward the backlog")
        self.assertIsNotNone(b["oldest_pending_days"], "the one valid entry should still yield an age")

    def test_ceiling_days_reads_backcapture_days_toggle(self):
        """ceiling_days mirrors memory.backcapture_days (the discovery ceiling), not
        a hardcoded constant — so the dashboard stays truthful if the toggle changes."""
        with tempfile.TemporaryDirectory() as h:
            local = os.path.join(h, "local")
            with open(local, "w") as fh:
                fh.write("memory.backcapture_days=3\n")
            conf = os.path.join(os.path.dirname(__file__), "..", "..", "toggles.conf")
            js = run_build("", NP_TOGGLES_CONF=conf, NP_TOGGLES_LOCAL=local,
                           BACKCAPTURE_QUEUE_DIR="/nonexistent/queue",
                           BACKCAPTURE_SEEN_DIR="/nonexistent/seen")
        b = self._parse(js)
        self.assertEqual(b["ceiling_days"], 3.0)

    def test_resolved_last_24h_counts_recently_seen_markers(self):
        """resolved_last_24h reflects how many seen-markers were touched recently —
        the drain-rate half of the panel."""
        with tempfile.TemporaryDirectory() as qdir, tempfile.TemporaryDirectory() as sdir:
            self._mark_seen(sdir, "just-resolved-1")
            self._mark_seen(sdir, "just-resolved-2")
            old_marker = os.path.join(sdir, "long-ago")
            open(old_marker, "w").close()
            old_ts = time.time() - 2 * 86400
            os.utime(old_marker, (old_ts, old_ts))
            js = run_build("", BACKCAPTURE_QUEUE_DIR=qdir, BACKCAPTURE_SEEN_DIR=sdir)
        b = self._parse(js)
        self.assertEqual(b["resolved_last_24h"], 2, "a 2-day-old seen marker must not count as last-24h")


if __name__ == "__main__":
    unittest.main()
