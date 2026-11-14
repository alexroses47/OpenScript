#!/bin/bash
# Build OpenScript-<version>-x86_64.AppImage.
#
#   packaging/appimage/build-appimage.sh LINUX_TAR WIN_PAF OUT_DIR [VERSION]
#
# Meant for Ubuntu 22.04 (the oldest base we support, for glibc
# compatibility). Needs: gcc make curl xz-utils p7zip-full file
# libgtk2.0-0 gnome-themes-extra libxt6 python3 + server requirements and
# pyinstaller (pip).
set -euo pipefail

LINUX_TAR=$(readlink -f "$1")
WIN_PAF=$(readlink -f "$2")
OUT=$(mkdir -p "$3" && readlink -f "$3")
VERSION=${4:-dev}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$ROOT/packaging/appimage"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
AD="$WORK/AppDir"
APP="$AD/usr/lib/openscript"
BUNDLED="$AD/usr/lib/bundled"
LIBDIR=/usr/lib/x86_64-linux-gnu

LIBPNG_URL=https://download.sourceforge.net/libpng/libpng-1.2.59.tar.xz
LIBPNG_SHA256=b4635f15b8adccc8ad0934eea485ef59cc4cae24d0f0300a9a941e51974ffcc7
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage

echo "==> App folder"
mkdir -p "$AD/usr/lib"
python3 "$ROOT/scripts/assemble.py" linux --linux-tar "$LINUX_TAR" \
  --win-paf "$WIN_PAF" --out "$WORK" --app-dir "$APP"
rm -rf "$APP/pdfserver"   # replaced by the frozen server below

echo "==> libpng 1.2 (required by the engine, gone from modern distros)"
curl -fsSL -o "$WORK/libpng.tar.xz" "$LIBPNG_URL"
echo "$LIBPNG_SHA256  $WORK/libpng.tar.xz" | sha256sum -c -
tar -C "$WORK" -xf "$WORK/libpng.tar.xz"
(cd "$WORK/libpng-1.2.59" && ./configure -q --prefix="$WORK/png" --disable-static \
  && make -s -j"$(nproc)" && make -s install)
mkdir -p "$BUNDLED"
cp -L "$WORK/png/lib/libpng12.so.0" "$BUNDLED/"

echo "==> GTK2, X libraries and the Adwaita GTK2 theme"
for lib in libgtk-x11-2.0.so.0 libgdk-x11-2.0.so.0 libXt.so.6 libSM.so.6 libICE.so.6; do
  cp -L "$LIBDIR/$lib" "$BUNDLED/"
done
mkdir -p "$AD/usr/lib/gtk-2.0/2.10.0"
for mod in engines printbackends; do
  [ -d "$LIBDIR/gtk-2.0/2.10.0/$mod" ] && cp -rL "$LIBDIR/gtk-2.0/2.10.0/$mod" "$AD/usr/lib/gtk-2.0/2.10.0/"
done
mkdir -p "$AD/usr/share/themes/Adwaita"
cp -r /usr/share/themes/Adwaita/gtk-2.0 "$AD/usr/share/themes/Adwaita/"
cp /usr/share/themes/Adwaita/index.theme "$AD/usr/share/themes/Adwaita/" 2>/dev/null || true

echo "==> Frozen PDF/export server"
# Bundle the whole Pango text stack: PyInstaller already ships GLib from the
# build system, and a newer system Pango would not work with that older GLib.
PANGO_LIBS=()
for lib in libpango-1.0.so.0 libpangoft2-1.0.so.0 libharfbuzz.so.0 \
           libharfbuzz-subset.so.0 libfontconfig.so.1 libfreetype.so.6 \
           libfribidi.so.0 libthai.so.0 libdatrie.so.1 libgraphite2.so.3 libpng16.so.16; do
  if [ -e "$LIBDIR/$lib" ]; then
    # copied under its SONAME, the name WeasyPrint dlopen()s
    PANGO_LIBS+=(--add-binary "$LIBDIR/$lib:.")
  fi
done
python3 -m PyInstaller "$ROOT/server/launcher.py" --name openscript-server --onedir \
  --paths "$ROOT/server" --hidden-import server --hidden-import exporters \
  "${PANGO_LIBS[@]}" --exclude-module apt_pkg --exclude-module dbus --exclude-module gi \
  --distpath "$WORK/pyi" --workpath "$WORK/pyi-build" --specpath "$WORK" --noconfirm --log-level WARN
mv "$WORK/pyi/openscript-server" "$APP/server"
rm -f "${TMPDIR:-/tmp}/openscript-server.log"
"$APP/server/openscript-server" --selftest || true
grep -q "SELFTEST OK" "${TMPDIR:-/tmp}/openscript-server.log" || {
  cat "${TMPDIR:-/tmp}/openscript-server.log"; echo "server selftest failed"; exit 1; }

echo "==> AppRun, desktop entry, icon, MIME type"
install -m 755 "$HERE/AppRun" "$AD/AppRun"
cp "$HERE/openscript.desktop" "$AD/openscript.desktop"
cp "$ROOT/assets/openscript-256.png" "$AD/openscript.png"
ln -sf openscript.png "$AD/.DirIcon"
mkdir -p "$AD/usr/share/mime/packages" "$AD/usr/share/metainfo"
cat > "$AD/usr/share/mime/packages/openscript.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-celtx">
    <comment>Proyecto de guion (.celtx)</comment>
    <glob pattern="*.celtx"/>
  </mime-type>
</mime-info>
EOF

echo "==> appimagetool"
curl -fsSL -o "$WORK/appimagetool" "$APPIMAGETOOL_URL"
chmod +x "$WORK/appimagetool"
OUTFILE="$OUT/OpenScript-$VERSION-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$WORK/appimagetool" --no-appstream "$AD" "$OUTFILE"
echo "built $OUTFILE"
