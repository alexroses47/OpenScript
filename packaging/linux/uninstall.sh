#!/bin/sh
# Removes OpenScript and its shortcuts.
# Your projects (.celtx files) and your profile (~/.greyfirst) are kept.
DEST=${1:-"$HOME/.local/opt/openscript"}
rm -rf "$DEST"
rm -f "$HOME/.local/share/applications/openscript.desktop" \
      "$HOME/.local/share/mime/packages/openscript.xml"
DESK=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
rm -f "$DESK/openscript.desktop"
update-mime-database "$HOME/.local/share/mime" >/dev/null 2>&1 || true
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
echo "OpenScript desinstalado. Tu perfil (~/.greyfirst) y tus proyectos se conservan."
