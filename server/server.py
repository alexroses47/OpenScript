#!/usr/bin/env python3
"""Local replacement for the defunct render.celtx.com PDF service.

Celtx 2.9.7 POSTs the (XSLT-prefiltered) script HTML to:
  /as/pdf   -> expects a PDF back
  /as/html  -> expects an HTML preview with one <div class="page"> per page
This server typesets the script with WeasyPrint using standard screenplay
layout and renders preview pages as PNG images via pdftoppm.
"""
import base64
import hmac
import html
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import weasyprint

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exporters  # noqa: E402

HOST, PORT = "127.0.0.1", int(os.environ.get("CELTX_PDF_PORT", "47890"))
ALLOWED_HOSTS = {"127.0.0.1:%d" % PORT, "localhost:%d" % PORT}
# Secret shared with the engine by the launcher (see overlay/*/celtx and
# server/launcher.py). Requests without it are rejected.
TOKEN = os.environ.get("OPENSCRIPT_TOKEN", "")
MAX_BODY = 32 * 1024 * 1024  # a script document is far smaller than this

# Preview oversampling for HiDPI displays (Celtx scales CSS px by 2 at 192 dpi).
PREVIEW_SCALE = int(os.environ.get("CELTX_PDF_PREVIEW_SCALE", "2"))

PAGE_SIZES = {"A4": "A4", "USLetter": "letter"}

# Screenplay layout, measured from the page edge (US industry standard):
# left margin 1.5in, right 1in, top/bottom 1in; dialogue at 2.5in,
# parenthetical at 3.1in, character cue at 3.7in, transitions right-aligned.
SCREENPLAY_CSS = """
@page {
  size: %(size)s;
  margin: 1in 1in 0.8in 1.5in;
  @top-right { content: counter(page) "."; font: 12pt "Courier Prime", "Courier New", "Liberation Mono", Courier, monospace; }
}
@page :first { @top-right { content: none; } }
@page title { @top-right { content: none; } }
html { font: 12pt/1 "Courier Prime", "Courier New", "Liberation Mono", Courier, monospace; }
body { margin: 0; }
p { margin: 0 0 12pt 0; orphans: 2; widows: 2; white-space: pre-wrap; }
p:empty { min-height: 12pt; }
.sceneheading, .shot { text-transform: uppercase; break-after: avoid; }
.sceneheading { margin-top: 12pt; position: relative; }
.sceneheading[scenestr]::before { content: attr(scenestr); position: absolute; left: -0.75in; }
.sceneheading[scenestr]::after { content: attr(scenestr); position: absolute; right: -0.6in; }
.character { text-transform: uppercase; margin: 0 0 0 2.2in; break-after: avoid; }
.parenthetical { margin: 0 2.0in 0 1.6in; break-after: avoid; }
.dialog { margin: 0 1.5in 0 1.0in; }
.dialog + .parenthetical { break-before: avoid; }
.character + .dialog, .parenthetical + .dialog { break-before: avoid; }
.dialog + .dialog { margin-top: 0; }
p.dialog:not(:last-child) { margin-bottom: 0; }
.dialog + p:not(.parenthetical):not(.dialog) { margin-top: 12pt; }
.transition { text-transform: uppercase; text-align: right; }
.hardbreak { break-before: page; height: 0; }
.titlepage { page: title; height: 8.4in; position: relative; break-after: page; }
.titlepage .tp-title { text-align: center; padding-top: 3in; text-transform: uppercase; text-decoration: underline; }
.titlepage .tp-center { text-align: center; margin-top: 12pt; }
.titlepage .tp-contact { position: absolute; bottom: 0; left: 0; width: 3.5in; }
.titlepage .tp-rights { position: absolute; bottom: 0; right: 0; width: 2.5in; text-align: right; }
"""

# Generic layout for theatre / radio / AV / comic: keep it readable.
GENERIC_CSS = """
@page {
  size: %(size)s;
  margin: 1in;
  @top-right { content: counter(page) "."; font: 12pt "Courier New", "Liberation Mono", monospace; }
}
@page :first { @top-right { content: none; } }
@page title { @top-right { content: none; } }
html { font: 12pt/1.15 "Courier New", "Liberation Mono", Courier, monospace; }
p { margin: 0 0 12pt 0; white-space: pre-wrap; }
.sceneheading, .act, .scene, .shot { text-transform: uppercase; font-weight: bold; break-after: avoid; }
.character { text-transform: uppercase; margin-left: 2in; margin-bottom: 0; break-after: avoid; }
.parenthetical { margin-left: 1.5in; margin-bottom: 0; break-after: avoid; }
.dialog { margin-left: 1in; margin-right: 1in; }
.transition { text-align: right; text-transform: uppercase; }
.hardbreak { break-before: page; height: 0; }
table { width: 100%%; border-collapse: collapse; }
td, th { vertical-align: top; border: 1px solid #999; padding: 4pt; }
.titlepage { page: title; height: 8.4in; position: relative; break-after: page; }
.titlepage .tp-title { text-align: center; padding-top: 3in; text-transform: uppercase; }
.titlepage .tp-center { text-align: center; margin-top: 12pt; }
.titlepage .tp-contact { position: absolute; bottom: 0; left: 0; width: 3.5in; }
.titlepage .tp-rights { position: absolute; bottom: 0; right: 0; width: 2.5in; text-align: right; }
"""


def log(*args):
    print("[openscript-server]", *args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Security: a script document is untrusted input (a .celtx file can come from
# anyone). It must never make the renderer read local files or go online.
# ---------------------------------------------------------------------------
# WeasyPrint may only resolve data: URIs (no file://, http://, https://, ...).
NO_FETCH = weasyprint.urls.URLFetcher(allowed_protocols={"data"})

# Elements that load external resources or are not script text.
DROP_TAGS = ["script", "style", "link", "img", "image", "picture", "source",
             "object", "embed", "iframe", "frame", "frameset", "video", "audio",
             "track", "svg", "math", "canvas", "form", "input", "button",
             "select", "textarea", "base", "meta", "template", "noscript"]
# Attributes that can reference resources or carry styling.
DROP_ATTRS = {"style", "src", "srcset", "href", "background", "poster", "data",
              "action", "formaction", "xlink:href", "rel", "lowsrc", "dynsrc",
              "longdesc", "usemap", "cite", "codebase", "archive", "manifest"}


def sanitize(body):
    """Keep only text and harmless inline markup from the editor document."""
    for tag in body.find_all(DROP_TAGS):
        tag.decompose()
    for tag in body.find_all("a"):
        tag.unwrap()
    for tag in body.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower() in DROP_ATTRS or attr.lower().startswith("on"):
                del tag[attr]


def meta(soup, name, default=""):
    tag = soup.find("meta", attrs={"name": name})
    return tag.get("content", default) if tag else default


def nl2br(text):
    return "<br>".join(html.escape(line) for line in text.splitlines())


def build_document(raw):
    soup = BeautifulSoup(raw, "html.parser")
    fmt = meta(soup, "CX.script.format", "screenplay")
    size = PAGE_SIZES.get(meta(soup, "CX.page.size", "USLetter"), "letter")
    css = (SCREENPLAY_CSS if fmt == "screenplay" else GENERIC_CSS) % {"size": size}

    body = soup.body or soup
    sanitize(body)

    title = soup.title.get_text(strip=True) if soup.title else ""
    if fmt == "comic":
        return build_comic(soup, body, title, size)
    titlepage = ""
    if meta(soup, "CX.omitTitlePage").lower() != "true" and title:
        byline = meta(soup, "CX.byline", "by")
        author = meta(soup, "Author")
        source = meta(soup, "DC.source")
        contact = meta(soup, "CX.contact")
        rights = meta(soup, "DC.rights")
        parts = ['<div class="titlepage">',
                 '<p class="tp-title">%s</p>' % html.escape(title)]
        if author:
            parts.append('<p class="tp-center">%s</p>' % nl2br(byline))
            parts.append('<p class="tp-center">%s</p>' % nl2br(author))
        if source:
            parts.append('<p class="tp-center">%s</p>' % nl2br(source))
        if contact:
            parts.append('<p class="tp-contact">%s</p>' % nl2br(contact))
        if rights:
            parts.append('<p class="tp-rights">%s</p>' % nl2br(rights))
        parts.append("</div>")
        titlepage = "".join(parts)

    content = "".join(str(c) for c in body.contents)
    def wrap(inner):
        return ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>'
                + html.escape(title) + '</title><style>' + css
                + '</style></head><body>' + inner + '</body></html>')
    return (wrap(titlepage) if titlepage else None), wrap(content)


# ---------------------------------------------------------------------------
# Comic book format, reproducing the old render.celtx.com (LaTeX) output:
# one sheet per comic page, "Page N" header and a bordered three-column
# table (Panel | Description | Dialogue) that runs to the bottom of the sheet.
# Labels follow the operating system language (Spanish or English).
# Measurements taken from a PDF produced by the original service (A4).
# ---------------------------------------------------------------------------
def comic_labels():
    """PDF labels in the operating system language (see exporters)."""
    lb = exporters.labels()
    return {"page": lb["page_short"], "panel": "Panel",
            "description": lb["description"], "dialog": lb["dialog"],
            "caption": lb["caption_title"]}

COMIC_CSS = """
@page { size: %(size)s; margin: %(mt).2fin %(mr).2fin %(mb).2fin %(ml).2fin; }
html { font: 12pt/1.0 "Liberation Mono", "Courier New", Courier, monospace; }
body { margin: 0; }
.titlepage .tp-title { text-align: center; padding-top: 2.95in; margin: 0; }
.titlepage .tp-center { text-align: center; margin: 12pt 0 0 0; }
.sheet { break-before: page; }
.sheet:first-child { break-before: auto; }
.pagelabel { margin: 0 0 0 0.1in; height: %(label_h).2fin; }
table { width: 100%%; border-collapse: collapse; table-layout: fixed; }
th { font-weight: normal; text-align: center; border: 0.6pt solid #000;
     padding: 0.5pt 0 1.5pt 0; height: 12pt; }
td { vertical-align: top; border: 0.6pt solid #000;
     padding: 0.17in 0.1in 0.2in 0.1in; overflow-wrap: break-word; }
col.c-panel { width: 9.6%%; }
col.c-desc { width: 43.8%%; }
col.c-dialog { width: 46.6%%; }
.desc p, .dialog p { margin: 0; }
.dialog .block + .block { margin-top: 12pt; }
"""

# Page geometry shared by the comic CSS and the sheet layout (inches),
# measured from a PDF produced by the original render.celtx.com service.
PAGE_HEIGHTS_IN = {"A4": 11.69, "letter": 11.0}
COMIC_MARGIN_TOP, COMIC_MARGIN_RIGHT = 0.82, 0.47
COMIC_MARGIN_BOTTOM, COMIC_MARGIN_LEFT = 0.55, 0.50
COMIC_LABEL_H = 0.6   # the "Page N" line above the table


def inner_html(tag):
    """Inner HTML of an editor paragraph without the trailing <br>."""
    brs = tag.find_all("br")
    if brs and not "".join(str(s) for s in brs[-1].next_siblings).strip():
        brs[-1].decompose()
    for t in tag.find_all(True):
        if t.name not in ("b", "i", "u", "em", "strong", "br", "span"):
            t.unwrap()
    for t in tag.find_all(True):
        t.attrs = {}
    return tag.decode_contents().strip()


PAGE_WIDTHS_IN = {"A4": 8.27, "letter": 8.5}


def _plain_lines(fragment, width):
    """Number of lines an HTML fragment wraps to in a monospace column."""
    text = BeautifulSoup(fragment.replace("<br/>", "\n").replace("<br>", "\n"),
                         "html.parser").get_text()
    total = 0
    for line in text.split("\n"):
        words = line.split()
        if not words:
            total += 1
            continue
        n, cur = 1, 0
        for w in words:
            while len(w) > width:          # overlong word is hard-broken
                if cur:
                    n += 1
                n += 1
                w, cur = w[width:], 0
            need = len(w) if cur == 0 else cur + 1 + len(w)
            if need <= width:
                cur = need
            else:
                n += 1
                cur = len(w)
        total += n
    return total


def layout_comic_sheets(pages, size):
    """Split comic pages into sheets the way the old LaTeX service did.

    Courier is monospaced (0.1in per character at 12pt), so row heights can
    be computed exactly. Returns (page_no, is_first_sheet, rows, fill_in)
    where fill_in is the height the last row is stretched to.
    """
    line = 12 / 72.0
    pad = 0.17 + 0.2 + 0.6 / 72          # cell padding + rule
    width = PAGE_WIDTHS_IN.get(size, 8.5) - COMIC_MARGIN_LEFT - COMIC_MARGIN_RIGHT
    desc_chars = int((width * 0.438 - 0.2) / 0.1) - 1
    dialog_chars = int((width * 0.466 - 0.2) / 0.1) - 1
    content_h = PAGE_HEIGHTS_IN.get(size, 11.0) - COMIC_MARGIN_TOP - COMIC_MARGIN_BOTTOM
    header_h = 14 / 72.0 + 1.2 / 72      # table header row
    safety = 0.12

    def row_height(panel):
        desc = sum(_plain_lines(d, desc_chars) for d in panel["desc"])
        dialog = sum(sum(_plain_lines(x, dialog_chars) for x in blk)
                     for blk in panel["dialog"])
        dialog += max(0, len(panel["dialog"]) - 1)   # blank line between blocks
        return max(desc, dialog, 1) * line + pad

    sheets = []
    for n, panels in enumerate(pages, 1):
        # the first sheet of a comic page also carries the "Page N" label
        avail = content_h - COMIC_LABEL_H - header_h - safety
        rows, used, first = [], 0.0, True
        for m, panel in enumerate(panels, 1):
            h = row_height(panel)
            if rows and used + h > avail:
                sheets.append((n, first, rows, avail - used))
                rows, used, first = [], 0.0, False
                avail = content_h - header_h - safety
            rows.append((m, panel, h))
            used += h
        sheets.append((n, first, rows, avail - used))

    out = []
    for n, first, rows, slack in sheets:
        # the last row is stretched by the slack left on the sheet
        fill = (rows[-1][2] if rows else 0.0) + slack
        out.append((n, first, [(m, panel) for m, panel, _h in rows], max(fill, 0)))
    return out


def build_comic(soup, body, title, size):
    css = COMIC_CSS % {
        "size": size,
        "mt": COMIC_MARGIN_TOP, "mr": COMIC_MARGIN_RIGHT,
        "mb": COMIC_MARGIN_BOTTOM, "ml": COMIC_MARGIN_LEFT,
        "label_h": COMIC_LABEL_H,
    }
    L = comic_labels()

    # Walk the editor paragraphs: sceneheading = comic page, shot = panel,
    # character/parenthetical/dialog/caption = dialogue column of the panel.
    pages = []
    for p in body.find_all("p"):
        cls = (p.get("class") or [""])[0]
        if cls == "sceneheading" or not pages:
            pages.append([])
            if cls == "sceneheading":
                continue
        panels = pages[-1]
        if cls == "shot" or not panels:
            panels.append({"desc": [], "dialog": []})
            if cls == "shot":
                text = inner_html(p)
                if text:
                    panels[-1]["desc"].append(text)
                continue
        panel = panels[-1]
        text = inner_html(p)
        if not text:
            continue
        dlg = panel["dialog"]
        if cls == "character":
            dlg.append([text.upper()])
        elif cls == "parenthetical":
            if not dlg:
                dlg.append([])
            dlg[-1].append(text if text.startswith("(") else "(%s)" % text)
        elif cls == "dialog":
            if not dlg:
                dlg.append([])
            dlg[-1].append(text)
        elif cls == "caption":
            dlg.append(["%s: %s" % (html.escape(L["caption"]), text)])
        elif cls in ("note",):
            continue  # editor notes are not printed
        else:
            panel["desc"].append(text)

    sheets = layout_comic_sheets(pages, size)
    out = []
    for n, panel_no, rows, fill in sheets:
        html_rows = []
        for i, (m, panel) in enumerate(rows):
            desc = "".join("<p>%s</p>" % d for d in panel["desc"])
            dialog = "".join(
                '<div class="block">%s</div>' % "".join("<p>%s</p>" % l for l in blk)
                for blk in panel["dialog"])
            style = ""
            if i == len(rows) - 1 and fill > 0:
                # stretch the last panel so the table reaches the page bottom
                style = ' style="height:%.3fin"' % fill
            html_rows.append('<tr%s><td>%d.%d</td><td class="desc">%s</td>'
                             '<td class="dialog">%s</td></tr>'
                             % (style, n, m, desc, dialog))
        if not html_rows:
            html_rows.append('<tr style="height:%.3fin"><td></td><td></td><td></td></tr>' % fill)
        label = ('<p class="pagelabel">%s %d</p>' % (html.escape(L["page"]), n)
                 if panel_no else "")
        out.append(
            '<div class="sheet">%s<table><colgroup><col class="c-panel">'
            '<col class="c-desc"><col class="c-dialog"></colgroup>'
            '<thead><tr><th>%s</th><th>%s</th><th>%s</th></tr></thead>'
            '<tbody>%s</tbody></table></div>'
            % (label, html.escape(L["panel"]), html.escape(L["description"]),
               html.escape(L["dialog"]), "".join(html_rows)))

    titlepage = None
    if meta(soup, "CX.omitTitlePage").lower() != "true" and title:
        author = meta(soup, "Author")
        parts = ['<div class="titlepage"><p class="tp-title">%s</p>' % nl2br(title)]
        if author:
            parts.append('<p class="tp-center">%s</p>' % nl2br(meta(soup, "CX.byline", "")))
            parts.append('<p class="tp-center">%s</p>' % nl2br(author))
        for extra in ("DC.source", "CX.contact", "DC.rights"):
            if meta(soup, extra):
                parts.append('<p class="tp-center">%s</p>' % nl2br(meta(soup, extra)))
        parts.append("</div>")
        titlepage = "".join(parts)

    def wrap(inner):
        return ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>'
                + html.escape(title) + '</title><style>' + css
                + '</style></head><body>' + inner + '</body></html>')
    return (wrap(titlepage) if titlepage else None), wrap("".join(out))


def render_pdf(raw):
    # Title page and script are laid out separately so the script's page
    # numbering starts at 1 (unnumbered first page) as in the old service.
    title_html, script_html = build_document(raw)
    script = weasyprint.HTML(string=script_html, url_fetcher=NO_FETCH).render()
    if not title_html:
        return script.write_pdf()
    title = weasyprint.HTML(string=title_html, url_fetcher=NO_FETCH).render()
    return script.copy(title.pages + script.pages).write_pdf()


def render_preview(raw):
    """Rasterize the PDF pages (pypdfium2, works on Linux and Windows)."""
    import io
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(render_pdf(raw))
    divs = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            # Rendered at PREVIEW_SCALE x 96 dpi and shown at 96 dpi CSS size,
            # so HiDPI screens get sharp text instead of an upscaled bitmap.
            image = page.render(scale=96 * PREVIEW_SCALE / 72.0).to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            divs.append('<div class="page"><img width="%d" height="%d" '
                        'src="data:image/png;base64,%s"></div>'
                        % (image.width // PREVIEW_SCALE,
                           image.height // PREVIEW_SCALE, b64))
            page.close()
    finally:
        pdf.close()
    return ('<html><head><meta charset="utf-8"><style>'
            'body{background:#808080;margin:0;padding:12px 0;}'
            '.page{margin:0 auto 12px auto;width:-moz-fit-content;background:#fff;'
            'box-shadow:0 2px 6px rgba(0,0,0,.5);}'
            '.page img{display:block;}'
            '</style></head><body>%s</body></html>' % "".join(divs)).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # never log query strings: they carry the session token
        log(self.address_string(), re.sub(r"\?\S*", "", fmt % args))

    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self, url):
        """Only the local engine may use the server.

        - Host must be the loopback address (blocks DNS rebinding).
        - No Origin header: requests made by web pages always carry one.
        - The per-session token shared by the launcher must match.
        """
        host = (self.headers.get("Host") or "").lower()
        if host not in ALLOWED_HOSTS:
            self._send(403, "text/plain", b"forbidden host\n")
            return False
        if self.headers.get("Origin") is not None:
            self._send(403, "text/plain", b"forbidden origin\n")
            return False
        if TOKEN:
            given = (parse_qs(url.query).get("token") or [""])[0]
            if not hmac.compare_digest(given.encode(), TOKEN.encode()):
                self._send(403, "text/plain", b"bad token\n")
                return False
        return True

    def do_GET(self):
        if self._allowed(urlsplit(self.path)):
            self._send(200, "text/plain", b"openscript server ok\n")

    def do_POST(self):
        url = urlsplit(self.path)
        if not self._allowed(url):
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._send(413, "text/plain", b"request too large\n")
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        query = parse_qs(url.query)
        mode = (query.get("mode") or [None])[0]
        size = (query.get("size") or ["USLetter"])[0]
        try:
            if url.path == "/as/pdf":
                self._send(200, "application/pdf", render_pdf(with_format(raw, mode, size)))
            elif url.path == "/as/html":
                self._send(200, "text/html; charset=UTF-8", render_preview(raw))
            elif url.path == "/export/fountain":
                self._send(200, "text/plain; charset=UTF-8", exporters.to_fountain(raw, mode))
            elif url.path == "/export/fdx":
                self._send(200, "application/xml", exporters.to_fdx(raw, mode))
            elif url.path in ("/export/odt", "/export/docx"):
                fmt = url.path.rsplit("/", 1)[1]
                self._send(200, "application/octet-stream",
                           exporters.to_office(raw, fmt, mode, size))
            elif url.path == "/export/pdf":
                self._send(200, "application/pdf", render_pdf(with_format(raw, mode, size)))
            else:
                self._send(404, "text/plain", b"not found")
        except Exception as ex:  # report to Celtx as a failed request
            log("render error:", repr(ex))
            self._send(500, "text/plain", repr(ex).encode())


# Celtx editor modes -> format names used by the PDF prefilter metadata.
MODE_TO_FORMAT = {"film": "screenplay", "comic": "comic", "theatre": "theatre",
                  "radio": "radioplay", "av": "av"}


def with_format(raw, mode, size):
    """Add the prefilter's format/size metadata to a raw editor document."""
    if not mode or 'name="CX.script.format"' in raw:
        return raw
    metas = ('<meta name="CX.script.format" content="%s">'
             '<meta name="CX.page.size" content="%s">'
             % (MODE_TO_FORMAT.get(mode, mode), html.escape(size)))
    return re.sub(r"<head[^>]*>", lambda m: m.group(0) + metas, raw, count=1) \
        if re.search(r"<head[^>]*>", raw) else metas + raw


def serve():
    """Run the server forever (blocking)."""
    log("listening on http://%s:%d" % (HOST, PORT))
    if not TOKEN:
        log("WARNING: OPENSCRIPT_TOKEN is not set; any local program can use this server")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    serve()
