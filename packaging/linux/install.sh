#!/bin/sh
# OpenScript installer for Linux x86_64 (per user, no root needed except for
# missing system packages).
#
#   ./install.sh                 install to ~/.local/opt/openscript
#   ./install.sh /otra/ruta      install somewhere else
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-"$HOME/.local/opt/openscript"}
APPS="$HOME/.local/share/applications"
MIME="$HOME/.local/share/mime"

# Messages in Spanish or English, following the system language
case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-$LANG}}}" in
  es*) t() { printf '%s\n' "$1"; } ;;
  *)   t() { printf '%s\n' "$2"; } ;;
esac
say() { printf '\n==> '; t "$1" "$2"; }

say "Comprobando dependencias del sistema" "Checking system dependencies"
missing=""
# Ask the dynamic loader which libraries the engine cannot find.
notfound=$(cd "$HERE/openscript" && LD_LIBRARY_PATH=. ldd ./celtx-bin 2>/dev/null | awk '/not found/ {print $1}' | sort -u)
for lib in $notfound; do
  case "$lib" in
    libpng12.so.0)        missing="$missing libpng12-0" ;;
    libgtk-x11-2.0.so.0|libgdk-x11-2.0.so.0) missing="$missing libgtk-2_0-0" ;;
    libdbus-glib-1.so.2)  missing="$missing libdbus-glib-1-2" ;;
    libXt.so.6)           missing="$missing libXt6" ;;
    *)                    missing="$missing $lib" ;;
  esac
done
command -v python3 >/dev/null || missing="$missing python3"
command -v curl >/dev/null || missing="$missing curl"
python3 -c 'import venv' 2>/dev/null || missing="$missing python3"
[ -f /usr/share/themes/Adwaita/gtk-2.0/gtkrc ] || missing="$missing gtk2-metatheme-adwaita gtk2-theming-engine-adwaita"
if [ -n "$(echo $missing)" ]; then
  t "Faltan paquetes. Instálalos y vuelve a ejecutar este script." \
    "Some packages are missing. Install them and run this script again."
  echo
  echo "  openSUSE:      sudo zypper in $(echo $missing)"
  t "  Otras distros: instala los paquetes equivalentes." \
    "  Other distributions: install the equivalent packages."
  echo
  exit 1
fi
command -v soffice >/dev/null || t "Aviso: sin LibreOffice no se podrá exportar a ODT/DOCX." \
  "Note: without LibreOffice, ODT/DOCX export is not available."
echo "OK"

say "Copiando OpenScript a $DEST" "Copying OpenScript to $DEST"
if [ -e "$DEST" ]; then
  t "Ya existe una instalación; se reemplaza (tus proyectos y tu perfil no se tocan)." \
    "Replacing the existing installation (your projects and profile are not touched)."
  rm -rf "$DEST"
fi
mkdir -p "$(dirname "$DEST")"
cp -a "$HERE/openscript" "$DEST"
touch "$DEST/.autoreg"

say "Creando el entorno del servidor de PDF y exportación" "Setting up the PDF/export server"
python3 -m venv "$DEST/pdfserver/venv"
if ! "$DEST/pdfserver/venv/bin/pip" install -q --no-index \
      --find-links "$DEST/pdfserver/wheels" -r "$DEST/pdfserver/requirements.txt" 2>/dev/null; then
  t "Descargando librerías de Python de internet..." "Downloading Python libraries..."
  "$DEST/pdfserver/venv/bin/pip" install -q -r "$DEST/pdfserver/requirements.txt"
fi
"$DEST/pdfserver/venv/bin/python" -c 'import weasyprint, bs4, pypdfium2' && echo "OK"

if command -v gcc >/dev/null; then
  gcc -shared -fPIC -O2 -o "$DEST/gtkfix/libforcetheme.so" "$DEST/gtkfix/force-theme.c" -ldl 2>/dev/null || true
fi

say "Aplicando estilos a los perfiles existentes" "Applying styles to existing profiles"
for prof in "$HOME"/.greyfirst/celtx/*/; do
  [ -d "$prof" ] || continue
  mkdir -p "$prof/chrome"
  cp "$DEST/defaults/profile/chrome/userChrome.css" "$prof/chrome/userChrome.css"
  rm -f "$prof/XUL.mfl" "$prof/XUL.mfasl"
  echo "  $prof"
done

say "Creando acceso directo" "Creating the application shortcut"
mkdir -p "$APPS" "$MIME/packages"
cat > "$APPS/openscript.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OpenScript
GenericName=Screenwriting software
GenericName[es]=Editor de guiones
Comment=Write scripts for film, theatre, radio and comics
Comment[es]=Escribe guiones de cine, teatro, radio y cómic
Exec="$DEST/openscript" %f
Path=$DEST
Icon=$DEST/icons/openscript.png
Terminal=false
Categories=Office;WordProcessor;
MimeType=application/x-celtx;
StartupWMClass=Celtx
EOF
chmod +x "$APPS/openscript.desktop"
cat > "$MIME/packages/openscript.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-celtx">
    <comment>Script project (.celtx)</comment>
    <comment xml:lang="es">Proyecto de guion (.celtx)</comment>
    <glob pattern="*.celtx"/>
  </mime-type>
</mime-info>
EOF
update-mime-database "$MIME" >/dev/null 2>&1 || true
update-desktop-database "$APPS" >/dev/null 2>&1 || true

DESK=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
if [ -d "$DESK" ]; then
  cp "$APPS/openscript.desktop" "$DESK/openscript.desktop"
  chmod +x "$DESK/openscript.desktop"
  gio set "$DESK/openscript.desktop" metadata::trusted true 2>/dev/null || true
fi

say "Listo. Abre OpenScript desde el menú de aplicaciones o con:" "Done. Open OpenScript from the applications menu or with:"
echo "  \"$DEST/openscript\""
