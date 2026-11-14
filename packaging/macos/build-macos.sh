#!/bin/bash
# Build OpenScript.app (and a .dmg) for macOS, Apple Silicon and Intel.
#
#   packaging/macos/build-macos.sh WIN_DIR WINE_TARBALL SERVER_DIR OUT_DIR [VERSION]
#
#   WIN_DIR       assembled Windows folder (scripts/assemble.py windows): has app/
#   WINE_TARBALL  Gcenx macOS Wine build (verified against packaging/tools.sha256)
#   SERVER_DIR    PyInstaller onedir of server/launcher.py ("openscript-server")
#
# The engine is the Windows build of Celtx 2.9.7 (32-bit) running in Wine's
# WoW64 mode; Wine and the server are x86_64 and use Rosetta 2 on Apple Silicon.
# Runs on macOS (needs swiftc, lipo, sips, iconutil, codesign, hdiutil).
set -euo pipefail

WIN_DIR=$(cd "$1" && pwd)
WINE_TARBALL=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
SERVER_DIR=$(cd "$3" && pwd)
OUT=$(mkdir -p "$4" && cd "$4" && pwd)
VERSION=${5:-dev}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$ROOT/packaging/macos"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

APP="$OUT/OpenScript.app"
C="$APP/Contents"
rm -rf "$APP"
mkdir -p "$C/MacOS" "$C/Resources"

echo "==> Wine: verify and unpack"
(cd "$(dirname "$WINE_TARBALL")" && grep " $(basename "$WINE_TARBALL")\$" "$ROOT/packaging/tools.sha256" | shasum -a 256 -c -)
tar -C "$WORK" -xf "$WINE_TARBALL"
WINE_BUNDLE=$(dirname "$(dirname "$(dirname "$(find "$WORK" -path '*/Contents/Resources/wine/bin/wine' -print -quit)")")")
[ -x "$WINE_BUNDLE/Resources/wine/bin/wine" ] || { echo "wine binary not found in tarball"; exit 1; }
# Same relative layout as the original Wine.app (lib -> ../../Frameworks)
cp -R "$WINE_BUNDLE/Resources/wine" "$C/Resources/wine"
[ -d "$WINE_BUNDLE/Frameworks" ] && cp -R "$WINE_BUNDLE/Frameworks" "$C/Frameworks"
# Not needed by the engine (.NET and Internet Explorer runtimes are disabled)
rm -rf "$C/Resources/wine/share/wine/mono" "$C/Resources/wine/share/wine/gecko"
du -sh "$C/Resources/wine" "$C/Frameworks" 2>/dev/null || true

echo "==> Engine (Windows build) and readable menu bar under Wine"
cp -R "$WIN_DIR/app" "$C/Resources/app"
cp -R "$ROOT/overlay/linux/chrome/openscript-linux" "$ROOT/overlay/linux/chrome/openscript-linux.manifest" \
  "$C/Resources/app/chrome/"
touch "$C/Resources/app/.autoreg"

echo "==> Native PDF/export server"
cp -R "$SERVER_DIR" "$C/Resources/server"
cp "$HERE/fonts.conf" "$C/Resources/server/fonts.conf"
[ -x "$C/Resources/server/openscript-server" ]

echo "==> Launcher (universal) and start script"
swiftc -O -target arm64-apple-macos11 "$HERE/launcher/main.swift" -o "$WORK/OpenScript-arm64"
swiftc -O -target x86_64-apple-macos11 "$HERE/launcher/main.swift" -o "$WORK/OpenScript-x86_64"
lipo -create "$WORK/OpenScript-arm64" "$WORK/OpenScript-x86_64" -output "$C/MacOS/OpenScript"
install -m 755 "$HERE/openscript.sh" "$C/Resources/openscript.sh"

echo "==> Icon and Info.plist"
ICONSET="$WORK/openscript.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$ROOT/assets/openscript-1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) "$ROOT/assets/openscript-1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$C/Resources/openscript.icns"
sed "s/@VERSION@/${VERSION#v}/g" "$HERE/Info.plist" > "$C/Info.plist"
plutil -lint "$C/Info.plist"

echo "==> Ad hoc signature (the app is not notarized)"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> Disk image"
STAGE="$WORK/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "OpenScript" -srcfolder "$STAGE" -ov -format UDZO \
  "$OUT/OpenScript-$VERSION-macos.dmg"
du -sh "$APP" "$OUT/OpenScript-$VERSION-macos.dmg"
echo "built $OUT/OpenScript-$VERSION-macos.dmg"
