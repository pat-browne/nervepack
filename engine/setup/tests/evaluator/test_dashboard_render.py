#!/usr/bin/env python3
"""Unit tests for build.py's Markdown->HTML renderer (md_to_html). Imports the
module directly (pure function) — stdlib unittest, per the harness policy."""
import os
import sys
import subprocess
import tempfile
import importlib.util
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_PY = os.path.join(HERE, "..", "..", "..", "..", "dashboard", "build.py")


def _load_build():
    spec = importlib.util.spec_from_file_location("np_build", BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


class TestRenderer(unittest.TestCase):
    def test_heading_and_paragraph(self):
        out = build.md_to_html("# Title\n\nHello world.")
        self.assertIn("<h1>Title</h1>", out)
        self.assertIn("<p>Hello world.</p>", out)

    def test_list_and_code(self):
        out = build.md_to_html("- one\n- two\n\n`code`")
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>two</li>", out)
        self.assertIn("<code>code</code>", out)

    def test_fenced_code_is_escaped(self):
        out = build.md_to_html("```\n<script>x</script>\n```")
        self.assertIn("<pre><code>", out)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", out)
        self.assertNotIn("<script>x</script>", out)

    def test_inline_html_is_escaped_not_executed(self):
        out = build.md_to_html("a <script>alert(1)</script> b")
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_external_link_kept_internal_javascript_dropped(self):
        out = build.md_to_html("[ok](https://example.com) [bad](javascript:alert(1))")
        self.assertIn('href="https://example.com"', out)
        self.assertNotIn("javascript:", out)      # dropped entirely
        self.assertIn("bad", out)                  # text survives, no href
        # No anchor tag at all for the bad link — no empty-href anchor emitted
        self.assertNotIn('<a href=""', out)
        # The good link is the only external-URL anchor
        self.assertEqual(out.count('<a href="https://'), 1)

    def test_wikilink_resolved_and_dangling(self):
        lm = {"rust": "wiki/rust.html"}
        out = build.md_to_html("see [[rust]] and [[ghost]]", link_map=lm, here="wiki")
        self.assertIn('href="rust.html"', out)     # same dir -> bare filename
        self.assertIn(">rust</a>", out)
        self.assertNotIn("[[ghost]]", out)         # dangling -> plain text
        self.assertIn("ghost", out)

    def test_wikilink_relative_across_dirs(self):
        lm = {"wcag-2.2": "sources/design/wcag-2.2.html"}
        out = build.md_to_html("[[wcag-2.2]]", link_map=lm, here="wiki")
        self.assertIn('href="../sources/design/wcag-2.2.html"', out)

    def test_deterministic(self):
        md = "# H\n\ntext **bold**\n"
        self.assertEqual(build.md_to_html(md), build.md_to_html(md))

    def test_safe_href(self):
        self.assertEqual(build._safe_href("https://x.com"), "https://x.com")
        self.assertEqual(build._safe_href("/rel"), "/rel")
        self.assertEqual(build._safe_href("#frag"), "#frag")
        self.assertEqual(build._safe_href("javascript:x"), "")
        self.assertEqual(build._safe_href("data:text/html,x"), "")
        # protocol-relative //host must be rejected; single-slash root-relative must pass
        self.assertEqual(build._safe_href("//evil.com"), "")
        self.assertEqual(build._safe_href("/path/to/page"), "/path/to/page")

    def test_gfm_table(self):
        md = "| Field | Value |\n|---|---|\n| Source | AzureBlob |\n| Layer | landing |"
        out = build.md_to_html(md)
        self.assertIn("<table>", out)
        self.assertIn("<th>Field</th>", out)
        self.assertIn("<th>Value</th>", out)
        self.assertIn("<td>Source</td>", out)
        self.assertIn("<td>landing</td>", out)
        self.assertNotIn("| Field |", out)        # raw pipes gone

    def test_table_cells_render_inline(self):
        md = "| A | B |\n|---|---|\n| `code` | **bold** |"
        out = build.md_to_html(md)
        self.assertIn("<td><code>code</code></td>", out)
        self.assertIn("<strong>bold</strong>", out)

    def test_stray_pipe_in_prose_does_not_stall(self):
        # a lone '|' with no delimiter row must not be treated as a table or loop forever
        out = build.md_to_html("use a | b pipe here\n\nnext para")
        self.assertIn("<p>", out)
        self.assertIn("next para", out)
        self.assertNotIn("<table>", out)

    def test_mermaid_fence_renders_container_not_code(self):
        md = "```mermaid\nerDiagram\n  A ||--o{ B : x\n```"
        out = build.md_to_html(md)
        self.assertIn('<pre class="mermaid">', out)
        self.assertIn("erDiagram", out)
        self.assertNotIn("<code>erDiagram", out)   # not a plain code block

    def test_mermaid_script_injected_only_when_present_and_enabled(self):
        with_diagram = build.md_to_html("```mermaid\nerDiagram\n```", here="wiki/topics/x")
        self.assertIn("vendor/mermaid.min.js", with_diagram)
        self.assertIn("mermaid.initialize", with_diagram)
        # plain page: no mermaid script
        plain = build.md_to_html("# Title\n\ntext", here="wiki/topics/x")
        self.assertNotIn("mermaid.min.js", plain)

    def test_mermaid_gate_off(self):
        os.environ["WIKI_MERMAID"] = "off"
        try:
            out = build.md_to_html("```mermaid\nerDiagram\n```", here="wiki/topics/x")
            self.assertIn('<pre class="mermaid">', out)   # still emits the container
            self.assertNotIn("mermaid.min.js", out)       # but no script when gated off
        finally:
            del os.environ["WIKI_MERMAID"]


BUILD_PY = os.path.join(HERE, "..", "..", "..", "..", "dashboard", "build.py")


def _run_build_in_content(content_dir):
    """Run build.py with NP_CONTENT_DIR=content_dir; return (out_dir, js_text)."""
    tmp = tempfile.mkdtemp()
    inp = os.path.join(tmp, "metrics.jsonl")
    with open(inp, "w"):
        pass
    out = os.path.join(tmp, "metrics.js")
    ev = dict(os.environ)
    ev.pop("NP_LESSONS_DIR", None)
    ev["NP_CONTENT_DIR"] = content_dir
    subprocess.run(["python3", BUILD_PY, inp, out], check=True,
                   capture_output=True, text=True, env=ev)
    with open(out) as fh:
        return tmp, fh.read()


def _write_topic_source(content_dir, topic, name, version, body):
    """Write wiki/topics/<topic>/<name>.md with kind:reference and given version."""
    d = os.path.join(content_dir, "wiki", "topics", topic)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: %s\nkind: reference\nversion: %s\n---\n\n%s\n" % (name, version, body))


def _write_topic_synthesis(content_dir, topic, name):
    """Write wiki/topics/<topic>/<name>.md with kind:topic (synthesis page)."""
    d = os.path.join(content_dir, "wiki", "topics", topic)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: %s\nkind: topic\nlast_updated: 2026-06-01\nsources: []\n---\n\nSynthesis body.\n" % name)


class TestRenderPagesVersionStamp(unittest.TestCase):
    """render_pages() must carry the version field into meta so md_to_html renders
    the version stamp on source pages (kind:reference with a version but no last_updated)."""

    def test_source_page_version_stamp_appears_in_html(self):
        """A wiki/topics/<topic>/<src>.md source page with version: 1.2.3 and
        kind: reference must render an HTML file containing '1.2.3' in the header
        stamp (via meta['version'] -> md_to_html stamp logic)."""
        with tempfile.TemporaryDirectory() as cd:
            _write_topic_synthesis(cd, "aws", "aws")
            _write_topic_source(cd, "aws", "creds", "1.2.3",
                                 "Credentials reference content.")
            out_dir, _ = _run_build_in_content(cd)
        html_path = os.path.join(out_dir, "wiki", "topics", "aws", "creds.html")
        self.assertTrue(os.path.isfile(html_path),
                        "rendered source page not found at %s" % html_path)
        with open(html_path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("1.2.3", body,
                      "version stamp '1.2.3' missing from rendered source page")


class TestWikiStructureRenders(unittest.TestCase):
    """A topic holding reference pages that carry Mermaid fences + GFM tables must
    render end-to-end via render_pages: diagram containers, the vendored (local)
    mermaid script, and HTML tables — no raw pipes left behind."""

    def test_reference_page_with_mermaid_and_table_renders(self):
        with tempfile.TemporaryDirectory() as cd:
            _write_topic_synthesis(cd, "platform", "platform")
            body = ("| Domain | Diagram |\n|---|---|\n| Camper | x |\n\n"
                    "```mermaid\nerDiagram\n  A ||--o{ B : id\n```\n")
            _write_topic_source(cd, "platform", "erd-camper", "", body)
            out_dir, _ = _run_build_in_content(cd)
        html_path = os.path.join(out_dir, "wiki", "topics", "platform", "erd-camper.html")
        self.assertTrue(os.path.isfile(html_path),
                        "rendered reference page not found at %s" % html_path)
        with open(html_path, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('<pre class="mermaid">', page)   # diagram container
        self.assertIn("vendor/mermaid.min.js", page)   # vendored, local (not CDN)
        self.assertIn("<table>", page)                 # GFM table rendered
        self.assertNotIn("| Domain |", page)           # raw pipes gone


if __name__ == "__main__":
    unittest.main()
