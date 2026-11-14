"""Export Celtx 2.9.7 script HTML to open screenplay formats.

Input is the script editor document (HTML, one <p class="..."> per
element). Supported targets:
  fountain  - https://fountain.io (plain text, future-proof)
  fdx       - Final Draft XML (imported by most screenwriting apps)
  odt/docx  - via LibreOffice (headless) from a print-oriented HTML
Comic scripts (sceneheading = page, shot = panel) are mapped onto the
screenplay vocabulary of each format, since none of them has panels.
"""
import html
import os
import re
import shutil
import subprocess
import tempfile
from xml.sax.saxutils import escape as xml_escape

from bs4 import BeautifulSoup, NavigableString

# ---------------------------------------------------------------------------
# Output language (follows the operating system, like the user interface)
# ---------------------------------------------------------------------------
def system_language():
    """'es' or 'en'. OPENSCRIPT_LANG overrides the detection."""
    lang = os.environ.get("OPENSCRIPT_LANG", "")
    if not lang and os.name == "nt":
        try:
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            lang = "es" if (langid & 0x3FF) == 0x0A else "en"
        except Exception:
            lang = ""
    if not lang:
        for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(var, "")
            if value and value not in ("C", "POSIX", "C.UTF-8"):
                lang = value.split(":")[0]
                break
    return "es" if lang.lower().startswith("es") else "en"


LABELS = {
    "es": {"page": "PÁGINA", "panel": "PANEL", "caption": "RÓTULO",
           "page_short": "Pág.", "description": "Descripción",
           "dialog": "Diálogo", "caption_title": "Rótulo", "byline": "Escrito por"},
    "en": {"page": "PAGE", "panel": "PANEL", "caption": "CAPTION",
           "page_short": "Page", "description": "Description",
           "dialog": "Dialogue", "caption_title": "Caption", "byline": "Written by"},
}


def labels():
    return LABELS[system_language()]


SCENE_PREFIX = re.compile(r"^(INT|EXT|EST|INT\./EXT|INT/EXT|I/E)[ .]", re.I)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _meta(soup, name):
    tag = soup.find("meta", attrs={"name": name})
    return (tag.get("content") or "").strip() if tag else ""


def _runs(node, style=frozenset()):
    """Flatten inline content into [(text, {"b","i","u"})] runs."""
    out = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if text:
                out.append((text, style))
            continue
        name = child.name
        if name == "br":
            out.append(("\n", style))
            continue
        extra = set()
        if name in ("b", "strong"):
            extra.add("b")
        elif name in ("i", "em"):
            extra.add("i")
        elif name == "u":
            extra.add("u")
        elif name == "span":
            st = (child.get("style") or "").replace(" ", "").lower()
            if "font-weight:bold" in st:
                extra.add("b")
            if "font-style:italic" in st:
                extra.add("i")
            if "underline" in st:
                extra.add("u")
        out.extend(_runs(child, style | frozenset(extra)))
    # collapse whitespace like a browser, keep explicit line breaks
    cleaned = []
    for text, st in out:
        if text != "\n":
            text = re.sub(r"[ \t\r\n]+", " ", text)
        cleaned.append((text, st))
    # strip the editor's trailing <br> and outer whitespace
    while cleaned and cleaned[-1][0].strip() == "":
        cleaned.pop()
    while cleaned and cleaned[0][0].strip() == "" :
        cleaned.pop(0)
    if cleaned:
        cleaned[0] = (cleaned[0][0].lstrip(" "), cleaned[0][1])
        cleaned[-1] = (cleaned[-1][0].rstrip(" "), cleaned[-1][1])
    return cleaned


def plain(runs):
    return "".join(t for t, _ in runs)


def parse(raw, mode=None):
    """Return (info, elements). elements = [(cls, runs, attrs)]."""
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    info = {
        "title": title,
        "byline": _meta(soup, "CX.byline"),
        "author": _meta(soup, "Author"),
        "source": _meta(soup, "DC.source"),
        "contact": _meta(soup, "CX.contact"),
        "rights": _meta(soup, "DC.rights"),
        "mode": mode or _meta(soup, "CX.script.format") or "film",
    }
    if info["mode"] == "screenplay":
        info["mode"] = "film"
    body = soup.body or soup
    elements = []
    for node in body.find_all(["p", "div"]):
        cls = (node.get("class") or [""])[0]
        if node.name == "div":
            if cls == "hardbreak":
                elements.append(("pagebreak", [], {}))
            continue
        runs = _runs(node)
        elements.append((cls or "action", runs, dict(node.attrs)))
    return info, elements


def comic_structure(elements):
    """Group comic elements into pages -> panels (like the PDF layout)."""
    pages = []
    for cls, runs, attrs in elements:
        if cls == "sceneheading" or not pages:
            pages.append({"heading": runs if cls == "sceneheading" else [],
                          "panels": []})
            if cls == "sceneheading":
                continue
        panels = pages[-1]["panels"]
        if cls == "shot" or not panels:
            panels.append({"desc": [], "items": []})
            if cls == "shot":
                if plain(runs).strip():
                    panels[-1]["desc"].append(runs)
                continue
        if not plain(runs).strip() or cls == "note":
            continue
        if cls in ("character", "dialog", "parenthetical", "caption"):
            panels[-1]["items"].append((cls, runs))
        else:
            panels[-1]["desc"].append(runs)
    return pages


# ---------------------------------------------------------------------------
# Fountain
# ---------------------------------------------------------------------------
def _fountain_inline(runs):
    out = []
    for text, st in runs:
        if text == "\n" or not text.strip():
            out.append(text)
            continue
        # escape characters that Fountain treats as markup
        text = text.replace("*", r"\*").replace("_", r"\_")
        lead = len(text) - len(text.lstrip())
        trail = len(text) - len(text.rstrip())
        core = text.strip()
        if "u" in st:
            core = "_%s_" % core
        if "b" in st and "i" in st:
            core = "***%s***" % core
        elif "b" in st:
            core = "**%s**" % core
        elif "i" in st:
            core = "*%s*" % core
        out.append(text[:lead] + core + (text[len(text) - trail:] if trail else ""))
    return "".join(out)


def _fountain_title_page(info):
    lines = []

    def field(key, value):
        value = value.strip()
        if not value:
            return
        parts = value.splitlines()
        if len(parts) == 1:
            lines.append("%s: %s" % (key, parts[0]))
        else:
            lines.append("%s:" % key)
            lines.extend("    " + p for p in parts)

    field("Title", info["title"])
    if info["author"]:
        field("Credit", info["byline"] or labels()["byline"])
        field("Author", info["author"])
    field("Source", info["source"])
    field("Contact", info["contact"])
    field("Copyright", info["rights"])
    return "\n".join(lines)


def _fountain_character(text):
    name = text.strip().upper()
    # Fountain requires at least one letter and no lowercase; force with @
    if not re.search(r"[A-ZÁÉÍÓÚÑÜ]", name) or name != name.upper():
        return "@" + name
    return name


def to_fountain(raw, mode=None):
    lb = labels()
    LABEL_PAGE, LABEL_PANEL, LABEL_CAPTION = lb["page"], lb["panel"], lb["caption"]
    info, elements = parse(raw, mode)
    blocks = []
    tp = _fountain_title_page(info)
    if tp:
        blocks.append(tp)

    def add(text):
        blocks.append(text)

    if info["mode"] == "comic":
        for pn, page in enumerate(comic_structure(elements), 1):
            heading = plain(page["heading"]).strip()
            add(".%s %d%s" % (LABEL_PAGE, pn, (" - " + heading.upper()) if heading else ""))
            for mn, panel in enumerate(page["panels"], 1):
                add("!%s %d.%d" % (LABEL_PANEL, pn, mn))
                for d in panel["desc"]:
                    add(_fountain_inline(d))
                cur = None
                for cls, runs in panel["items"]:
                    txt = _fountain_inline(runs)
                    if cls == "character":
                        cur = [_fountain_character(plain(runs))]
                        add_block = cur
                        blocks.append(add_block)
                    elif cls == "caption":
                        blocks.append([LABEL_CAPTION, txt])
                        cur = None
                    elif cls == "parenthetical":
                        p = txt.strip()
                        p = p if p.startswith("(") else "(%s)" % p
                        if cur is None:
                            cur = [LABEL_CAPTION]
                            blocks.append(cur)
                        cur.append(p)
                    else:  # dialog
                        if cur is None:
                            cur = [LABEL_CAPTION]
                            blocks.append(cur)
                        cur.append(txt)
            add("===")
        if blocks and blocks[-1] == "===":
            blocks.pop()
    else:
        cur = None  # current dialogue block (list of lines)
        for cls, runs, attrs in elements:
            txt = _fountain_inline(runs)
            p = plain(runs).strip()
            if cls == "pagebreak":
                add("===")
                cur = None
                continue
            if not p and cls not in ("action",):
                continue
            if cls in ("sceneheading",):
                line = p.upper()
                if not SCENE_PREFIX.match(line):
                    line = "." + line
                num = attrs.get("scenestr")
                if num:
                    line += " #%s#" % num
                add(line)
                cur = None
            elif cls == "act":
                add("# " + p)
                cur = None
            elif cls == "character":
                cur = [_fountain_character(p)]
                blocks.append(cur)
            elif cls == "parenthetical":
                q = txt.strip()
                q = q if q.startswith("(") else "(%s)" % q
                if cur is None:
                    add(q)
                else:
                    cur.append(q)
            elif cls in ("dialog", "voice"):
                if cur is None:
                    add(txt)
                else:
                    cur.append(txt)
            elif cls == "transition":
                line = p.upper()
                add(line if line.endswith("TO:") else ">" + line)
                cur = None
            elif cls == "shot":
                add("!" + p.upper())
                cur = None
            elif cls in ("sound", "music"):
                add("!" + p.upper())
                cur = None
            elif cls == "note":
                add("[[%s]]" % p)
            else:  # action and anything unknown
                if not p:
                    continue
                # an all-caps action line would be read as a character cue
                if p == p.upper() and re.search(r"[A-Z]", p) and "\n" not in txt:
                    txt = "!" + txt
                add(txt)
                cur = None

    out = []
    for b in blocks:
        out.append("\n".join(b) if isinstance(b, list) else b)
    return ("\n\n".join(out).strip() + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Final Draft (FDX)
# ---------------------------------------------------------------------------
def _fdx_text(runs, upper=False):
    parts = []
    for text, st in runs:
        if not text:
            continue
        if upper:
            text = text.upper()
        style = "+".join(n for k, n in (("b", "Bold"), ("i", "Italic"),
                                        ("u", "Underline")) if k in st)
        attr = ' Style="%s"' % style if style else ""
        parts.append("<Text%s>%s</Text>" % (attr, xml_escape(text)))
    return "".join(parts) or "<Text></Text>"


def _fdx_para(ptype, runs, upper=False, number=None):
    num = ' Number="%s"' % xml_escape(number) if number else ""
    return '    <Paragraph Type="%s"%s>%s</Paragraph>' % (ptype, num, _fdx_text(runs, upper))


FDX_TYPES = {
    "sceneheading": "Scene Heading", "action": "Action", "character": "Character",
    "parenthetical": "Parenthetical", "dialog": "Dialogue", "transition": "Transition",
    "shot": "Shot", "act": "New Act", "voice": "Dialogue", "sound": "Action",
    "music": "Action", "caption": "Action",
}


def to_fdx(raw, mode=None):
    lb = labels()
    LABEL_PAGE, LABEL_PANEL, LABEL_CAPTION = lb["page"], lb["panel"], lb["caption"]
    info, elements = parse(raw, mode)
    paras = []
    if info["mode"] == "comic":
        for pn, page in enumerate(comic_structure(elements), 1):
            heading = plain(page["heading"]).strip()
            paras.append(_fdx_para("Scene Heading", [("%s %d%s" % (
                LABEL_PAGE, pn, (" - " + heading) if heading else ""), set())], True))
            for mn, panel in enumerate(page["panels"], 1):
                paras.append(_fdx_para("Shot", [("%s %d.%d" % (LABEL_PANEL, pn, mn), set())], True))
                for d in panel["desc"]:
                    paras.append(_fdx_para("Action", d))
                for cls, runs in panel["items"]:
                    if cls == "caption":
                        paras.append(_fdx_para("Character", [(LABEL_CAPTION, set())], True))
                        paras.append(_fdx_para("Dialogue", runs))
                    elif cls == "character":
                        paras.append(_fdx_para("Character", runs, True))
                    elif cls == "parenthetical":
                        t = plain(runs).strip()
                        r = runs if t.startswith("(") else [("(%s)" % t, set())]
                        paras.append(_fdx_para("Parenthetical", r))
                    else:
                        paras.append(_fdx_para("Dialogue", runs))
    else:
        for cls, runs, attrs in elements:
            if cls == "pagebreak" or cls == "note":
                continue
            ptype = FDX_TYPES.get(cls, "General")
            upper = cls in ("sceneheading", "character", "transition", "shot")
            if cls == "parenthetical":
                t = plain(runs).strip()
                if t and not t.startswith("("):
                    runs = [("(%s)" % t, set())]
            paras.append(_fdx_para(ptype, runs, upper, attrs.get("scenestr")))

    tp = []

    def tp_line(text, align="Center"):
        tp.append('    <Paragraph Alignment="%s" Type="General"><Text>%s</Text></Paragraph>'
                  % (align, xml_escape(text)))

    if info["title"]:
        for _ in range(16):
            tp_line("")
        for line in info["title"].splitlines():
            tp_line(line)
        if info["author"]:
            tp_line("")
            tp_line(info["byline"] or labels()["byline"])
            tp_line("")
            for line in info["author"].splitlines():
                tp_line(line)
        for key in ("source", "contact", "rights"):
            if info[key]:
                tp_line("")
                for line in info[key].splitlines():
                    tp_line(line, "Left" if key == "contact" else "Center")

    doc = ['<?xml version="1.0" encoding="UTF-8" standalone="no" ?>',
           '<FinalDraft DocumentType="Script" Template="No" Version="5">',
           "  <Content>"] + paras + ["  </Content>"]
    if tp:
        doc += ["  <TitlePage>", "   <Content>"] + tp + ["   </Content>", "  </TitlePage>"]
    doc.append("</FinalDraft>")
    return ("\n".join(doc) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# ODT / DOCX via LibreOffice
# ---------------------------------------------------------------------------
def _html_inline(runs):
    out = []
    for text, st in runs:
        if text == "\n":
            out.append("<br>")
            continue
        t = html.escape(text)
        if "u" in st:
            t = "<u>%s</u>" % t
        if "i" in st:
            t = "<i>%s</i>" % t
        if "b" in st:
            t = "<b>%s</b>" % t
        out.append(t)
    return "".join(out)


def office_html(raw, mode=None, page_size="USLetter"):
    """Simple, office-friendly HTML (LibreOffice honours these styles)."""
    lb = labels()
    info, elements = parse(raw, mode)
    font = "font-family: 'Courier New', 'Liberation Mono', monospace; font-size: 12pt;"
    parts = ['<html><head><meta charset="utf-8"><title>%s</title><style>'
             "body { %s } p { margin: 0 0 12pt 0; %s }"
             "td, th { %s vertical-align: top; border: 1px solid #000; padding: 4pt; }"
             "table { border-collapse: collapse; width: 100%%; }"
             "</style></head><body>" % (html.escape(info["title"]), font, font, font)]
    if info["title"]:
        parts.append('<p style="margin-top: 3in; text-align: center">%s</p>'
                     % "<br>".join(html.escape(l) for l in info["title"].splitlines()))
        if info["author"]:
            parts.append('<p style="text-align: center">%s</p>' % html.escape(info["byline"] or ""))
            parts.append('<p style="text-align: center">%s</p>' % html.escape(info["author"]))
        for key in ("source", "contact", "rights"):
            if info[key]:
                parts.append('<p style="text-align: center">%s</p>' % html.escape(info[key]))
    first_break = ' style="page-break-before: always"' if info["title"] else ""

    if info["mode"] == "comic":
        for pn, page in enumerate(comic_structure(elements), 1):
            brk = first_break if pn == 1 else ' style="page-break-before: always"'
            parts.append("<p%s>%s %d</p>" % (brk, html.escape(lb["page_short"]), pn))
            # LibreOffice's HTML import ignores table CSS: use attributes
            parts.append('<table width="100%" border="1" cellpadding="6" cellspacing="0">'
                         '<col width="10%"><col width="44%"><col width="46%">'
                         '<tr><th align="center">Panel</th><th align="center">%s</th>'
                         '<th align="center">%s</th></tr>'
                         % (html.escape(lb["description"]), html.escape(lb["dialog"])))
            for mn, panel in enumerate(page["panels"], 1):
                desc = "".join('<p style="margin:0">%s</p>' % _html_inline(d) for d in panel["desc"])
                items, block = [], []
                for cls, runs in panel["items"]:
                    if cls in ("character", "caption") and block:
                        items.append(block)
                        block = []
                    if cls == "caption":
                        block.append(html.escape(lb["caption_title"]) + ": " + _html_inline(runs))
                    elif cls == "character":
                        block.append(html.escape(plain(runs).upper()))
                    else:
                        block.append(_html_inline(runs))
                if block:
                    items.append(block)
                dialog = "".join('<p style="margin:0 0 12pt 0">%s</p>' % "<br>".join(b) for b in items)
                parts.append('<tr valign="top"><td valign="top">%d.%d</td><td valign="top">%s</td>'
                             '<td valign="top">%s</td></tr>' % (pn, mn, desc, dialog))
            parts.append("</table>")
    else:
        indent = {"character": "2.2in", "parenthetical": "1.6in", "dialog": "1.0in"}
        right = {"parenthetical": "2.0in", "dialog": "1.5in"}
        first = True
        for cls, runs, attrs in elements:
            if cls == "pagebreak":
                parts.append('<p style="page-break-before: always"></p>')
                continue
            if not plain(runs).strip() or cls == "note":
                continue
            style = []
            if first and first_break:
                style.append("page-break-before: always")
                first = False
            if cls in indent:
                style.append("margin-left: %s" % indent[cls])
            if cls in right:
                style.append("margin-right: %s" % right[cls])
            if cls in ("character", "parenthetical"):
                style.append("margin-bottom: 0")
            if cls == "transition":
                style.append("text-align: right")
            text = _html_inline(runs)
            if cls in ("sceneheading", "character", "transition", "shot"):
                text = text.upper()
            if cls == "sceneheading":
                text = "<b>%s</b>" % text
            parts.append('<p style="%s">%s</p>' % ("; ".join(style), text))
    parts.append("</body></html>")
    return "".join(parts)


def clean_env():
    """Environment for external programs without our bundled libraries.

    PyInstaller and the AppImage prepend their own library folders to
    LD_LIBRARY_PATH; LibreOffice must use the system libraries instead.
    """
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "GTK_PATH", "GTK_DATA_PREFIX", "GTK2_RC_FILES"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            env[var] = orig
        elif var != "LD_LIBRARY_PATH" or getattr(__import__("sys"), "frozen", False) \
                or os.environ.get("APPIMAGE"):
            env.pop(var, None)
    return env


def find_soffice():
    """Locate LibreOffice on Linux, Windows or macOS."""
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    candidates = [
        os.path.join(os.environ.get(v, ""), "LibreOffice", "program", "soffice.exe")
        for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
    ] + ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def to_office(raw, fmt, mode=None, page_size="USLetter"):
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice no está instalado (necesario para ODT/DOCX)")
    filt = {"odt": "odt:writer8", "docx": "docx:MS Word 2007 XML"}[fmt]
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "script.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(office_html(raw, mode, page_size))
        from pathlib import Path
        profile = Path(tmp, "lo-profile").as_uri()
        subprocess.run([soffice, "-env:UserInstallation=" + profile, "--headless",
                        "--infilter=HTML (StarWriter)", "--convert-to", filt,
                        "--outdir", tmp, src],
                       check=True, timeout=180, env=clean_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(tmp, "script." + fmt), "rb") as f:
            return f.read()
