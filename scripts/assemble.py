#!/usr/bin/env python3
"""Assemble OpenScript packages from the original Celtx 2.9.7 binaries.

The repository only contains OpenScript's own changes (overlay/, server/,
packaging/). This script takes the untouched upstream builds and applies
those changes:

  linux   : Celtx-2.9.7-64.tar.bz2  (+ Spanish locale from the Windows build)
  windows : CeltxPortable_2.9.7_Spanish_Development_Test_1.paf.exe
            (the PyInstaller-built OpenScript.exe is added by the CI job)

Usage:
  scripts/assemble.py linux   --linux-tar T --win-paf P --out DIR [--wheels]
  scripts/assemble.py windows --linux-tar T --win-paf P --out DIR
  scripts/assemble.py linux   ... --app-dir DIR   (bare app, for the AppImage)
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
PY_VERSIONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)  # noqa: T201
    subprocess.run(cmd, check=True, **kw)


def copytree(src, dst):
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(base, f), os.path.join(dst, rel, f))


def extract_paf(paf, dest):
    """Extract the PortableApps NSIS installer (needs 7-Zip)."""
    seven = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz") \
        or r"C:\Program Files\7-Zip\7z.exe"
    run([seven, "x", "-y", "-o" + dest, paf], stdout=subprocess.DEVNULL)
    return os.path.join(dest, "App", "Celtx")


def build_celtx_es_jar(win_app, out_jar):
    """Extract locale/es-ES/celtx from the Windows celtx.jar into its own jar."""
    with zipfile.ZipFile(os.path.join(win_app, "chrome", "celtx.jar")) as src, \
            zipfile.ZipFile(out_jar, "w", zipfile.ZIP_STORED) as dst:
        for item in src.infolist():
            if item.filename.startswith("locale/es-ES/celtx/"):
                dst.writestr(item, src.read(item))


def replace_icons(app):
    """Replace Celtx window icons with the OpenScript icon (Linux layout)."""
    for path in glob.glob(os.path.join(app, "icons", "*.png")) + \
            glob.glob(os.path.join(app, "chrome", "icons", "default", "*.png")):
        name = os.path.basename(path)
        m = re.search(r"(\d+)", name)
        size = int(m.group(1)) if m else 128
        if size == 50:
            size = 48
        src = os.path.join(ASSETS, "openscript-%d.png" % size)
        if not os.path.exists(src):
            src = os.path.join(ASSETS, "openscript-128.png")
        shutil.copy2(src, path)
    shutil.copy2(os.path.join(ASSETS, "openscript-256.png"),
                 os.path.join(app, "icons", "openscript.png"))


def set_default_locale(app, locale="en-US"):
    """Fallback UI language (the OS language is used when available)."""
    pref = os.path.join(app, "defaults", "pref", "celtx.js")
    with open(pref, encoding="utf-8", errors="surrogateescape") as f:
        s = f.read()
    s = re.sub(r'pref\("general\.useragent\.locale", "[^"]*"\);',
               'pref("general.useragent.locale", "%s");' % locale, s)
    with open(pref, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(s)


# ---------------------------------------------------------------------------
# Code changes kept as patches against the original Celtx 2.9.7 files
# ---------------------------------------------------------------------------
PATCHES = os.path.join(ROOT, "patches")


def apply_patch(text, name):
    """Apply patches/<name>.patch to the original file content (LF endings)."""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, name)
        with open(target, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
            f.write(text.replace("\r\n", "\n"))
        # normalise the patch too (a Windows checkout may have turned it CRLF)
        with open(os.path.join(PATCHES, name + ".patch"), "rb") as f:
            patch = f.read().replace(b"\r\n", b"\n")
        patch_file = os.path.join(tmp, name + ".patch")
        with open(patch_file, "wb") as f:
            f.write(patch)
        run(["git", "apply", "-p1", "--whitespace=nowarn", patch_file], cwd=tmp)
        with open(target, encoding="utf-8", errors="surrogateescape") as f:
            return f.read()


def apply_code_patches(app):
    """Patched engine files: dead services off, local server, export menu."""
    service = os.path.join(app, "components", "nsCeltxService.js")
    with open(service, encoding="utf-8", errors="surrogateescape") as f:
        patched = apply_patch(f.read(), "nsCeltxService.js")
    with open(service, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(patched)

    with zipfile.ZipFile(os.path.join(app, "chrome", "celtx.jar")) as z:
        editor = z.read("content/celtx/editors/scripteditor.js").decode(
            "utf-8", errors="surrogateescape")
    dest = os.path.join(app, "chrome", "celtx-export", "scripteditor.js")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(apply_patch(editor, "scripteditor.js"))


# ---------------------------------------------------------------------------
# Rebranding of user-visible strings (Celtx -> OpenScript)
# ---------------------------------------------------------------------------
PROJECT_URL = "https://github.com/alexroses47/OpenScript"

# Keys whose value names the .celtx file format: kept as is.
KEEP_KEYS = {"Celtx095Project", "Celtx097Project", "CeltxProject", "CeltxTemplate"}

SPECIAL = {
    "en": {
        "celtxTagline.label": "Write your story: film, theatre, radio and comics.",
        "pdfWarningText": "OpenScript formats your script on your own computer to an "
                          "industry standard Screenplay, Stageplay, Audio Play or Dual "
                          "Column (AV). Nothing is sent over the internet.",
        "CeltxVersion": "OpenScript {version} · Celtx engine",
    },
    "es": {
        "celtxTagline.label": "Escribe tu historia: cine, teatro, radio y cómic.",
        "pdfWarningText": "OpenScript da formato a tu guion en tu propio equipo, según el "
                          "estándar de la industria: guion de cine, teatro, radio o doble "
                          "columna (AV). No se envía nada por internet.",
        "CeltxVersion": "OpenScript {version} · motor Celtx",
    },
}
SPECIAL["en"]["pdfErrorText2"] = SPECIAL["en"]["pdfWarningText"]
SPECIAL["es"]["pdfErrorText2"] = SPECIAL["es"]["pdfWarningText"]

DTD_RE = re.compile(r'(<!ENTITY\s+([\w.\-]+)\s+)(["\'])(.*?)\3', re.S)


def _rebrand_value(key, value, lang, version):
    special = SPECIAL.get(lang, {})
    if key in special:
        return special[key].format(version=version)
    if key in KEEP_KEYS:
        return value
    return value.replace("Celtx", "OpenScript")


def rebrand_text(name, text, lang, version):
    if name.endswith(".dtd"):
        def sub(m):
            value = _rebrand_value(m.group(2), m.group(4), lang, version)
            return m.group(1) + m.group(3) + value + m.group(3)
        return DTD_RE.sub(sub, text)
    out = []
    for line in text.splitlines(True):
        stripped = line.lstrip()
        if "=" in line and not stripped.startswith(("#", "!")):
            key, value = line.split("=", 1)
            end = "\n" if value.endswith("\n") else ""
            value = _rebrand_value(key.strip(), value.rstrip("\r\n"), lang, version)
            line = key + "=" + value + ("\r\n" if line.endswith("\r\n") else end)
        out.append(line)
    return "".join(out)


def rebrand_jar(jar, version):
    """Rewrite locale/<lang>/celtx/*.dtd|*.properties inside a jar in place."""
    tmp = jar + ".tmp"
    with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            parts = item.filename.split("/")
            if (len(parts) == 4 and parts[0] == "locale" and parts[2] == "celtx"
                    and parts[3].endswith((".dtd", ".properties"))):
                lang = parts[1].split("-")[0]
                text = data.decode("utf-8", errors="surrogateescape")
                data = rebrand_text(parts[3], text, lang, version).encode(
                    "utf-8", errors="surrogateescape")
            dst.writestr(item, data)
    os.replace(tmp, jar)


def write_branded_util(app):
    """Help menu links (support, bugs, guide) point to the OpenScript project."""
    with zipfile.ZipFile(os.path.join(app, "chrome", "celtx.jar")) as z:
        js = z.read("content/celtx/util.js").decode("utf-8", errors="surrogateescape")
    links = {
        "BUG_REPORT_URL": PROJECT_URL + "/issues",
        "SUPPORT_URL": PROJECT_URL + "#readme",
        "WALKTHRU_URL": PROJECT_URL + "#readme",
        "USER_GUIDE_URL": PROJECT_URL + "#readme",
        "FORUMS_URL": PROJECT_URL + "/issues",
        "PROJ_CENTRAL_URL": PROJECT_URL,
    }
    for key, url in links.items():
        js, n = re.subn(r"(get %s\s*\(\)\s*\{\s*return )'[^']*'" % key,
                        r"\1'%s'" % url, js)
        assert n == 1, key
    dest = os.path.join(app, "chrome", "openscript-branding", "util.js")
    with open(dest, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write("// OpenScript: Celtx util.js with help links to the OpenScript project.\n" + js)


CREDITS_BLOCK = """
    <p><b>OpenScript</b><br/>
       Revival by Ismael A. Rodr\u00edguez<br/>
       <a href="%s" target="_blank">%s</a>
    </p>
    <p></p>
    <p><b>Original program:</b></p>
    <p>Celtx 2.9.7 by the Celtx team (Greyfirst Corp.)</p>
    <p></p>""" % (PROJECT_URL, PROJECT_URL)


def write_branded_credits(app):
    """About dialog credits: OpenScript revival first, original credits kept."""
    with zipfile.ZipFile(os.path.join(app, "chrome", "celtx.jar")) as z:
        page = z.read("content/celtx/credits.xhtml").decode("utf-8")
    marker = '<div style="height: 300px;"/>'
    assert marker in page
    page = page.replace(marker, marker + CREDITS_BLOCK, 1)
    with open(os.path.join(app, "chrome", "openscript-branding", "credits.xhtml"),
              "w", encoding="utf-8", newline="") as f:
        f.write(page)


def rebrand(app, version):
    version = version.lstrip("v")
    for jar in ("celtx.jar", "celtx-es-ES.jar"):
        path = os.path.join(app, "chrome", jar)
        if os.path.exists(path):
            rebrand_jar(path, version)
    write_branded_util(app)
    write_branded_credits(app)


# ---------------------------------------------------------------------------
def build_linux(args, work):
    win_app = extract_paf(args.win_paf, os.path.join(work, "paf"))
    with tarfile.open(args.linux_tar) as t:
        t.extractall(work)
    app = os.path.join(work, "celtx")

    copytree(os.path.join(ROOT, "overlay", "common"), app)
    copytree(os.path.join(ROOT, "overlay", "linux"), app)
    apply_code_patches(app)

    # Spanish UI + dictionary (locale files are platform independent)
    for name in ("es-ES.jar", "es-ES.manifest", "calendar-es-ES.jar",
                 "calendar-es-ES.manifest"):
        shutil.copy2(os.path.join(win_app, "chrome", name), os.path.join(app, "chrome"))
    build_celtx_es_jar(win_app, os.path.join(app, "chrome", "celtx-es-ES.jar"))
    with open(os.path.join(app, "chrome", "celtx-es-ES.manifest"), "w") as f:
        f.write("locale  celtx es-ES       jar:celtx-es-ES.jar!/locale/es-ES/celtx/\n")
    for name in ("es_ES.aff", "es_ES.dic"):
        shutil.copy2(os.path.join(win_app, "dictionaries", name),
                     os.path.join(app, "dictionaries"))
    replace_icons(app)
    rebrand(app, args.version)

    # Light-theme shim (needs gcc; prebuilt .so is also shipped)
    run(["gcc", "-shared", "-fPIC", "-O2", "-o",
         os.path.join(app, "gtkfix", "libforcetheme.so"),
         os.path.join(app, "gtkfix", "force-theme.c"), "-ldl"])

    # Render/export server
    srv = os.path.join(app, "pdfserver")
    os.makedirs(srv, exist_ok=True)
    for name in ("server.py", "exporters.py", "requirements.txt"):
        shutil.copy2(os.path.join(ROOT, "server", name), srv)
    if args.wheels:
        wheels = os.path.join(srv, "wheels")
        for ver in PY_VERSIONS:
            run([sys.executable, "-m", "pip", "download", "-q", "-d", wheels,
                 "--only-binary=:all:", "--platform", "manylinux2014_x86_64",
                 "--platform", "manylinux_2_28_x86_64", "--platform", "any",
                 "--python-version", ver, "-r", os.path.join(srv, "requirements.txt")])

    # OpenScript entry point (keeps the original "celtx" launcher working)
    entry = os.path.join(app, "openscript")
    with open(entry, "w") as f:
        f.write('#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/celtx" "$@"\n')
    os.chmod(entry, 0o755)
    os.chmod(os.path.join(app, "celtx"), 0o755)
    touch(os.path.join(app, ".autoreg"))

    if args.app_dir:  # raw app folder (used to build the AppImage)
        if os.path.exists(args.app_dir):
            shutil.rmtree(args.app_dir)
        shutil.move(app, args.app_dir)
        print("app folder", args.app_dir)
        return

    pkg = os.path.join(work, "OpenScript")
    os.makedirs(pkg)
    shutil.move(app, os.path.join(pkg, "openscript"))
    for name in os.listdir(os.path.join(ROOT, "packaging", "linux")):
        shutil.copy2(os.path.join(ROOT, "packaging", "linux", name), pkg)
    for name in ("LICENSE", "NOTICE.md", "README.md"):
        if os.path.exists(os.path.join(ROOT, name)):
            shutil.copy2(os.path.join(ROOT, name), pkg)
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "OpenScript-%s-linux-x86_64.tar.gz" % args.version)
    with tarfile.open(out, "w:gz") as t:
        t.add(pkg, arcname="OpenScript")
    print("built", out)


def build_windows(args, work):
    win_app = extract_paf(args.win_paf, os.path.join(work, "paf"))
    pkg = os.path.join(args.out, "OpenScript")
    if os.path.exists(pkg):
        shutil.rmtree(pkg)
    app = os.path.join(pkg, "app")
    shutil.copytree(win_app, app)
    copytree(os.path.join(ROOT, "overlay", "common"), app)
    apply_code_patches(app)
    set_default_locale(app)
    rebrand(app, args.version)

    # English locale (the Spanish portable build ships only Spanish)
    with tarfile.open(args.linux_tar) as t:
        for member in ("celtx/chrome/en-US.jar", "celtx/chrome/en-US.manifest",
                       "celtx/chrome/calendar-en-US.jar",
                       "celtx/chrome/calendar-en-US.manifest",
                       "celtx/dictionaries/en-US.aff", "celtx/dictionaries/en-US.dic"):
            try:
                data = t.extractfile(member).read()
            except KeyError:
                continue
            dest = os.path.join(app, *member.split("/")[1:])
            with open(dest, "wb") as f:
                f.write(data)
    touch(os.path.join(app, ".autoreg"))
    for name in ("LICENSE", "NOTICE.md", "README.md"):
        if os.path.exists(os.path.join(ROOT, name)):
            shutil.copy2(os.path.join(ROOT, name), pkg)
    print("assembled", pkg)


def touch(path):
    open(path, "a").close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=["linux", "windows"])
    ap.add_argument("--linux-tar", required=True)
    ap.add_argument("--win-paf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="dev")
    ap.add_argument("--wheels", action="store_true",
                    help="bundle Python wheels for offline install (Linux)")
    ap.add_argument("--app-dir", help="linux: write the bare app folder here "
                    "instead of the tar.gz package")
    args = ap.parse_args()
    if args.app_dir:
        args.app_dir = os.path.abspath(args.app_dir)
    args.out = os.path.abspath(args.out)
    with tempfile.TemporaryDirectory() as work:
        (build_linux if args.platform == "linux" else build_windows)(args, work)


if __name__ == "__main__":
    main()
