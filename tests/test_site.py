import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402
import mdlite  # noqa: E402


class MarkdownTests(unittest.TestCase):
    def test_inline(self):
        self.assertEqual(mdlite.inline("a **b** `c<d>` [e](f.html) *g*"),
                         'a <strong>b</strong> <code>c&lt;d&gt;</code> <a href="f.html">e</a> <em>g</em>')

    def test_code_is_not_formatted(self):
        self.assertEqual(mdlite.inline("`**x**`"), "<code>**x**</code>")

    def test_heading_and_paragraph(self):
        out = mdlite.render("# Title\n\nOne\ntwo")
        self.assertIn('<h1 id="title">Title</h1>', out)
        self.assertIn("<p>One two</p>", out)

    def test_table(self):
        out = mdlite.render("| A | B |\n|---|---|\n| 1 | `2` |")
        self.assertIn("<th>A</th>", out)
        self.assertIn("<td><code>2</code></td>", out)

    def test_list_with_nested_code_block(self):
        out = mdlite.render("- one\n- two:\n\n  ```\n  x = 1\n  ```\n- three")
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<pre><code>x = 1\n</code></pre>", out)

    def test_ordered_list_with_continuation(self):
        out = mdlite.render("1. first\n   more\n2. second")
        self.assertIn("<ol>", out)
        self.assertIn("first more", out)


class SiteTests(unittest.TestCase):
    def test_build_produces_every_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_site.build(tmp + "/site")
            for slug, _ in build_site.GUIDES:
                page = (out / "guides" / (slug + ".html")).read_text(encoding="utf-8")
                self.assertIn("<h1", page)
                self.assertNotIn("{{", page)
                self.assertIsNone(re.search(r'href="(?!https?:)[^"]*\.md', page), slug)
            for name in ("index.html", "404.html", "sitemap.xml", "robots.txt", ".nojekyll", "style.css"):
                self.assertTrue((out / name).exists(), name)

    def test_every_doc_is_in_the_site_nav(self):
        slugs = {s for s, _ in build_site.GUIDES}
        docs = {p.stem for p in (ROOT / "docs").glob("*.md")}
        self.assertEqual(slugs, docs)

    def test_links_between_guides_and_out_of_docs(self):
        self.assertEqual(build_site.rewrite_links("[x](setup.md#a) [y](../CHANGELOG.md) [z](https://e.org)"),
                         "[x](setup.html#a) [y](" + build_site.REPO + "CHANGELOG.md) [z](https://e.org)")


if __name__ == "__main__":
    unittest.main()
