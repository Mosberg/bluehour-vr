"""A small Markdown renderer for the subset used by the docs: headings, paragraphs, bullet and numbered lists
(with nested code blocks and paragraphs), fenced code, tables, block quotes, rules, and inline code, bold, italic
and links. No dependencies."""
import html
import re

ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def inline(text):
    spans = []

    def keep(m):
        spans.append("<code>%s</code>" % html.escape(m.group(1), quote=False))
        return "\x00%d\x00" % (len(spans) - 1)

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: '<a href="%s">%s</a>' % (m.group(2).replace('"', "%22"), m.group(1)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _starts_block(line, nxt):
    return bool(HEADING.match(line) or FENCE.match(line) or ITEM.match(line) or line.startswith(">")
                or (line.lstrip().startswith("|") and nxt is not None and TABLE_SEP.match(nxt)))


def blocks(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = FENCE.match(line)
        if m:
            i += 1
            code = []
            while i < n and not FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            cls = ' class="language-%s"' % m.group(1) if m.group(1) else ""
            out.append("<pre><code%s>%s\n</code></pre>" % (cls, html.escape("\n".join(code), quote=False)))
            continue
        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", inline(m.group(2))).lower()).strip("-")
            out.append('<h%d id="%s">%s</h%d>' % (level, slug, inline(m.group(2)), level))
            i += 1
            continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            out.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            quote = []
            while i < n and lines[i].startswith(">"):
                quote.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>" % "\n".join(blocks(quote)))
            continue
        if line.lstrip().startswith("|") and i + 1 < n and TABLE_SEP.match(lines[i + 1]):
            head = _cells(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            t = "<div class=\"tablewrap\"><table><thead><tr>%s</tr></thead><tbody>\n" % "".join(
                "<th>%s</th>" % inline(c) for c in head)
            for r in rows:
                t += "<tr>%s</tr>\n" % "".join("<td>%s</td>" % inline(c) for c in r)
            out.append(t + "</tbody></table></div>")
            continue
        m = ITEM.match(line)
        if m:
            i, html_list = _list(lines, i)
            out.append(html_list)
            continue
        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i], lines[i + 1] if i + 1 < n else None):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(para)))
    return out


def _list(lines, i):
    n = len(lines)
    ordered = bool(re.match(r"^\s*\d+\.", lines[i]))
    items = []
    while i < n:
        m = ITEM.match(lines[i])
        if not m or m.group(1) or bool(re.match(r"\d+\.", m.group(2))) != ordered:
            break
        width = len(m.group(2)) + 1
        body = [m.group(3)]
        i += 1
        while i < n:
            ln = lines[i]
            if not ln.strip():
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                nxt = ITEM.match(lines[j]) if j < n else None
                if j < n and (lines[j].startswith(" " * width) or (nxt and not nxt.group(1))):
                    body.append("")
                    i += 1
                    continue
                break
            if ln.startswith(" " * width):
                body.append(ln[width:])
            elif ITEM.match(ln) or _starts_block(ln, None):
                break
            else:
                body.append(ln.strip())          # lazy continuation of the paragraph
            i += 1
        while body and not body[-1].strip():
            body.pop()
        inner = blocks(body)
        if len(inner) == 1 and inner[0].startswith("<p>"):
            inner = [inner[0][3:-4]]          # tight item: no paragraph wrapper
        items.append("<li>%s</li>" % "\n".join(inner))
        while i + 1 < n and not lines[i].strip():            # blank lines between items of the same list
            nxt = ITEM.match(lines[i + 1])
            if not (nxt and not nxt.group(1)):
                break
            i += 1
    tag = "ol" if ordered else "ul"
    return i, "<%s>\n%s\n</%s>" % (tag, "\n".join(items), tag)


def render(text):
    return "\n".join(blocks(text.replace("\r\n", "\n").split("\n")))
