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
    print("+", " ".join(cmd), flush=True)
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


def spanish_l10n(win_app):
    """Spanish default prefs from the Windows build, without //@line noise."""
    with open(os.path.join(win_app, "defaults", "pref", "celtx-l10n.js"),
              encoding="utf-8") as f:
        lines = [l.rstrip("\r\n") for l in f if not l.startswith("//@line")]
    return "\n".join(lines) + "\n"


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


def set_locale_es(app):
    pref = os.path.join(app, "defaults", "pref", "celtx.js")
    with open(pref, encoding="utf-8", errors="surrogateescape") as f:
        s = f.read()
    s = s.replace('pref("general.useragent.locale", "en-US");',
                  'pref("general.useragent.locale", "es-ES");')
    with open(pref, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(s)


# ---------------------------------------------------------------------------
def build_linux(args, work):
    win_app = extract_paf(args.win_paf, os.path.join(work, "paf"))
    with tarfile.open(args.linux_tar) as t:
        t.extractall(work)
    app = os.path.join(work, "celtx")

    copytree(os.path.join(ROOT, "overlay", "common"), app)
    copytree(os.path.join(ROOT, "overlay", "linux"), app)

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
    with open(os.path.join(app, "defaults", "pref", "celtx-l10n.js"), "w",
              encoding="utf-8") as f:
        f.write(spanish_l10n(win_app))
    set_locale_es(app)
    replace_icons(app)

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

    # English locale too, so the language can be switched
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
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    with tempfile.TemporaryDirectory() as work:
        (build_linux if args.platform == "linux" else build_windows)(args, work)


if __name__ == "__main__":
    main()
