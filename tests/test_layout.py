#!/usr/bin/env python3
"""Layout regression tests: render each fixture and compare it with a
reference (page count, and position and text of every line).

    python tests/test_layout.py           # compare with tests/golden/
    python tests/test_layout.py --update  # rewrite the references

Font metrics decide the layout, so the test restricts fontconfig to the
Liberation fonts (Liberation Mono has the same metrics as Courier). They must
be installed (Debian/Ubuntu: fonts-liberation; Fedora: liberation-mono-fonts;
openSUSE: liberation-fonts).
"""
import glob
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
GOLDEN = os.path.join(HERE, "golden")
TOLERANCE_PT = 2.0

# (fixture, Celtx editor mode, page size)
CASES = [
    ("film", "film", "USLetter"),
    ("comic", "comic", "A4"),
    ("theatre", "theatre", "USLetter"),
]


def restrict_fonts():
    """Point fontconfig at a folder that only contains the Liberation fonts."""
    found = []
    for pattern in ("/usr/share/fonts/**/Liberation*.ttf",
                    "/usr/local/share/fonts/**/Liberation*.ttf"):
        found += glob.glob(pattern, recursive=True)
    if not any("Mono" in os.path.basename(f) for f in found):
        sys.exit("Liberation Mono is not installed (see the docstring)")
    folder = tempfile.mkdtemp(prefix="openscript-fonts-")
    for path in found:
        os.symlink(path, os.path.join(folder, os.path.basename(path)))
    conf = os.path.join(folder, "fonts.conf")
    with open(conf, "w") as f:
        f.write('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
                "<fontconfig><dir>%s</dir><cachedir>%s/cache</cachedir></fontconfig>"
                % (folder, folder))
    os.environ["FONTCONFIG_FILE"] = conf
    os.environ["OPENSCRIPT_LANG"] = "en"


def lines_of(pdf_bytes):
    """[[page, x, y, text], ...] with positions in points, top-left origin."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    out = []
    for index in range(len(pdf)):
        page = pdf[index]
        height = page.get_height()
        text = page.get_textpage()
        rows = {}
        for i in range(text.count_chars()):
            ch = text.get_text_range(i, 1)
            if ch in ("\r", "\n", ""):
                continue
            # loose box: font ascent/descent, the same for every glyph of a line
            left, bottom, _right, _top = text.get_charbox(i, loose=True)
            key = round(height - bottom)
            rows.setdefault(key, []).append((left, i, ch))
        for y in sorted(rows):
            chars = sorted(rows[y])
            line = "".join(c for _x, _i, c in chars).strip()
            if line:
                first = next(x for x, _i, c in chars if c.strip())
                out.append([index + 1, round(first, 1), y, line])
        text.close()
        page.close()
    pages = len(pdf)
    pdf.close()
    return pages, out


def render(name, mode, size):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
    import server
    with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
        raw = f.read()
    return server.render_pdf(server.with_format(raw, mode, size))


def compare(name, got, want):
    errors = []
    if got["pages"] != want["pages"]:
        errors.append("pages: %d, expected %d" % (got["pages"], want["pages"]))
    if len(got["lines"]) != len(want["lines"]):
        errors.append("lines: %d, expected %d" % (len(got["lines"]), len(want["lines"])))
    for g, w in zip(got["lines"], want["lines"]):
        if (g[0] != w[0] or g[3] != w[3] or abs(g[1] - w[1]) > TOLERANCE_PT
                or abs(g[2] - w[2]) > TOLERANCE_PT):
            errors.append("expected %r\n          got %r" % (w, g))
            if len(errors) > 5:
                break
    for e in errors:
        print("  %s: %s" % (name, e))
    return not errors


def main():
    update = "--update" in sys.argv
    restrict_fonts()
    os.makedirs(GOLDEN, exist_ok=True)
    ok = True
    for name, mode, size in CASES:
        pages, lines = lines_of(render(name, mode, size))
        got = {"pages": pages, "lines": lines}
        path = os.path.join(GOLDEN, name + ".json")
        if update:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False, indent=0)
            print("updated", path, "(%d pages, %d lines)" % (pages, len(lines)))
            continue
        with open(path, encoding="utf-8") as f:
            want = json.load(f)
        passed = compare(name, got, want)
        print("%s %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
