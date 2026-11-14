#!/bin/bash
# OpenScript for macOS: runs the Windows build of the engine with the bundled
# Wine, and the PDF/export server natively. Called by Contents/MacOS/OpenScript
# with the files to open.
RES="$(cd "$(dirname "$0")" && pwd)"            # Contents/Resources
SUPPORT="$HOME/Library/Application Support/OpenScript"
LOG="$SUPPORT/openscript.log"
WINE="$RES/wine/bin/wine"
WINESERVER="$RES/wine/bin/wineserver"
SERVER="$RES/server/openscript-server"
APP_EXE="$RES/app/celtx.exe"

export WINEPREFIX="$SUPPORT/prefix"
export WINEDEBUG=-all
# no desktop integration, no .NET / Internet Explorer install prompts
export WINEDLLOVERRIDES="winemenubuilder.exe=d;mscoree=d;mshtml=d"
export MVK_CONFIG_LOG_LEVEL=0   # MoltenVK (Vulkan) is not used; keep the log short

mkdir -p "$SUPPORT"
exec >>"$LOG" 2>&1
echo "== $(date) OpenScript start: $*"

# Messages in Spanish or English, following the system language
lang="${LANG:-$(defaults read -g AppleLocale 2>/dev/null)}"
case "$lang" in
  es*) t() { printf '%s' "$1"; } ;;
  *)   t() { printf '%s' "$2"; } ;;
esac
alert() {
  /usr/bin/osascript -e "display alert \"OpenScript\" message \"$1\" as critical" >/dev/null 2>&1
}

# Apple Silicon: Wine and the server are Intel programs and need Rosetta 2.
if [ "$(uname -m)" = "arm64" ] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
  alert "$(t "OpenScript necesita Rosetta 2. Instálalo abriendo Terminal y ejecutando:  softwareupdate --install-rosetta" \
             "OpenScript needs Rosetta 2. Install it by opening Terminal and running:  softwareupdate --install-rosetta")"
  exit 1
fi

# 1. Wine prefix (created on first run)
if [ ! -f "$WINEPREFIX/.openscript-ready" ]; then
  echo "creating Wine prefix in $WINEPREFIX"
  "$WINE" wineboot --init
  "$WINESERVER" -w
  touch "$WINEPREFIX/.openscript-ready"
fi

# 2. Display scale (from the native launcher: NSScreen backingScaleFactor).
#    Retina (2x): Wine renders at full resolution (RetinaMode) and the
#    engine, which follows the Windows DPI, draws its interface at 192 dpi.
#    Standard (1x): no RetinaMode and 96 dpi. Both must change together, or
#    the interface comes out at half or double size. Checked on every start,
#    since the Mac may now be using a different monitor.
scale="${OPENSCRIPT_SCALE:-2}"
if [ "$scale" -ge 2 ] 2>/dev/null; then retina=y; dpi=192; else retina=n; dpi=96; fi
if [ "$(cat "$SUPPORT/display" 2>/dev/null)" != "$retina $dpi" ]; then
  "$WINE" reg add 'HKCU\Software\Wine\Mac Driver' /v RetinaMode /t REG_SZ /d $retina /f
  "$WINE" reg add 'HKCU\Control Panel\Desktop' /v LogPixels /t REG_DWORD /d $dpi /f
  "$WINESERVER" -w
  echo "$retina $dpi" > "$SUPPORT/display"
fi

# Per-user secret shared by the engine and the local server
TOKEN_FILE="$SUPPORT/token"
if [ ! -s "$TOKEN_FILE" ]; then
  (umask 077; od -An -N24 -tx1 /dev/urandom | tr -d ' \n' > "$TOKEN_FILE")
fi
export OPENSCRIPT_TOKEN="$(cat "$TOKEN_FILE")"

# 3. Native PDF/export server (exits by itself if the port is already in use).
#    Its fontconfig uses our configuration (macOS font folders).
FONTCONFIG_FILE="$RES/server/fonts.conf" "$SERVER" --server &
server_pid=$!

# 4. Files to open: macOS paths -> Wine paths
args=()
for arg in "$@"; do
  if [ -e "$arg" ]; then
    args+=("$("$WINE" winepath -w "$arg" 2>/dev/null)")
  else
    args+=("$arg")
  fi
done

# File dialogs start in the user's home folder
cd "$HOME" || cd /
"$WINE" "$APP_EXE" "${args[@]}"

# 5. The engine may restart itself (first run) or still be running if this
#    was a second launch: wait for the whole Wine session, then stop the
#    server we started.
"$WINESERVER" -w
kill "$server_pid" 2>/dev/null
echo "== $(date) OpenScript end"
