#!/usr/bin/env python3
"""Build the GitHub Pages site into _site/ from site/ (templates, CSS) and docs/*.md (guides).

No third-party packages needed.
"""
import html
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mdlite  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://mosberg.github.io/bluehour-vr/"
REPO = "https://github.com/Mosberg/bluehour-vr/blob/main/"
GUIDES = [
    ("setup", "Set up"),
    ("usage", "Use"),
    ("troubleshooting", "Troubleshooting and limits"),
    ("position-tracking", "Leaning and moving"),
    ("wii-remote", "Wii Remote"),
    ("gamepads", "USB gamepads"),
    ("architecture", "Architecture"),
    ("hardware-testing", "Hardware test checklist"),
]
ASSETS = ["favicon.svg", "favicon.ico", "icon.svg", "icon-192.png", "icon-512.png", "logo.svg", "logo-dark.svg",
          "social-preview.png"]


def rewrite_links(text):
    """Turn links between guides into .html links and links out of docs/ into GitHub links."""
    def fix(m):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        path, _, frag = target.partition("#")
        if path.startswith("../"):
            return "[%s](%s%s)" % (label, REPO, path[3:])
        if path.endswith(".md"):
            path = path[:-3] + ".html"
        return "[%s](%s%s)" % (label, path, "#" + frag if frag else "")
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", fix, text)


def render(md_text):
    return mdlite.render(rewrite_links(md_text))


def first_paragraph(md_text):
    for block in md_text.split("\n\n"):
        block = block.strip()
        if block and not block.startswith(("#", "```", "|", "-", "*")):
            flat = " ".join(block.split())
            return re.sub(r"[`*_]|\[([^\]]+)\]\([^)]*\)", lambda m: m.group(1) or "", flat)[:155]
    return "Bluehour documentation"


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "guides").mkdir(parents=True)
    (out / "assets").mkdir()
    for name in ASSETS:
        shutil.copy(ROOT / "assets" / "brand" / name, out / "assets" / name)
    shutil.copy(ROOT / "site" / "style.css", out / "style.css")
    shutil.copy(ROOT / "site" / "index.html", out / "index.html")
    (out / ".nojekyll").write_text("")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n" % BASE)

    template = (ROOT / "site" / "guide.html").read_text(encoding="utf-8")
    urls = [BASE]
    for slug, title in GUIDES:
        src = (ROOT / "docs" / (slug + ".md")).read_text(encoding="utf-8")
        nav = "\n".join(
            '      <li><a href="%s.html"%s>%s</a></li>'
            % (s, ' aria-current="page"' if s == slug else "", html.escape(t))
            for s, t in GUIDES)
        page = (template.replace("{{title}}", html.escape(title)).replace("{{slug}}", slug)
                .replace("{{description}}", html.escape(first_paragraph(src.split("\n", 1)[1])))
                .replace("{{nav}}", nav).replace("{{content}}", render(src)))
        (out / "guides" / (slug + ".html")).write_text(page, encoding="utf-8")
        urls.append("%sguides/%s.html" % (BASE, slug))

    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join("  <url><loc>%s</loc></url>\n" % u for u in urls) + "</urlset>\n")
    (out / "404.html").write_text(
        template.replace("{{title}}", "Page not found").replace("{{slug}}", "404")
        .replace("{{description}}", "This page does not exist.")
        .replace("../", BASE).replace("{{nav}}", "")
        .replace("{{content}}", '<h1>Page not found</h1><p>That page does not exist. Start from the '
                 '<a href="%s">home page</a> or the <a href="%sguides/setup.html">setup guide</a>.</p>' % (BASE, BASE)),
        encoding="utf-8")
    return out


if __name__ == "__main__":
    target = build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site")
    print("Site built in", target)
