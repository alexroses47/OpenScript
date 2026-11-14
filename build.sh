#!/bin/bash
# Build OpenScript from source with a single command.
#
#   ./build.sh            AppImage (default)  -> dist/OpenScript-dev-x86_64.AppImage
#   ./build.sh tarball    tar.gz with installer -> dist/OpenScript-dev-linux-x86_64.tar.gz
#
# The original Celtx 2.9.7 binaries are downloaded from this project's
# "upstream-2.9.7" release and verified against packaging/upstream.sha256.
# The AppImage is built inside an Ubuntu 22.04 container (podman or docker)
# unless the host already is Ubuntu 22.04 with the build dependencies.
# The Windows package is built by GitHub Actions (.github/workflows/build.yml).
set -euo pipefail
cd "$(dirname "$0")"

REPO=${OPENSCRIPT_REPO:-alexroses47/OpenScript}
VERSION=${VERSION:-dev}
LINUX_TAR=upstream/Celtx-2.9.7-64.tar.bz2
WIN_PAF=upstream/CeltxPortable_2.9.7_Spanish_Development_Test_1.paf.exe

fetch_upstream() {
  mkdir -p upstream
  for f in "$LINUX_TAR" "$WIN_PAF"; do
    if [ ! -f "$f" ]; then
      echo "Descargando $(basename "$f")..."
      curl -fL -o "$f" "https://github.com/$REPO/releases/download/upstream-2.9.7/$(basename "$f")"
    fi
  done
  (cd upstream && sha256sum -c ../packaging/upstream.sha256)
}

native_appimage_ok() {
  [ -f /etc/os-release ] && . /etc/os-release && [ "${ID:-}" = ubuntu ] &&
    [ -f /usr/lib/x86_64-linux-gnu/libgtk-x11-2.0.so.0 ] &&
    python3 -c 'import PyInstaller, weasyprint' 2>/dev/null
}

case "${1:-appimage}" in
  appimage)
    fetch_upstream
    if native_appimage_ok; then
      packaging/appimage/build-appimage.sh "$LINUX_TAR" "$WIN_PAF" dist "$VERSION"
    else
      engine=$(command -v podman || command -v docker || true)
      if [ -z "$engine" ]; then
        echo "Necesitas podman o docker (o compilar en Ubuntu 22.04)." >&2
        exit 1
      fi
      "$engine" build -t openscript-build -f packaging/appimage/Containerfile .
      "$engine" run --rm -v "$PWD:/src:Z" -e VERSION="$VERSION" openscript-build \
        packaging/appimage/build-appimage.sh "$LINUX_TAR" "$WIN_PAF" dist "$VERSION"
    fi
    ;;
  tarball)
    fetch_upstream
    python3 scripts/assemble.py linux --linux-tar "$LINUX_TAR" --win-paf "$WIN_PAF" \
      --out dist --version "$VERSION" --wheels
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
