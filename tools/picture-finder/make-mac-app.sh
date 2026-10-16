#!/bin/sh
# Makes "Picture Finder.app" for your Mac (Apple silicon or Intel) from picture_finder.py.
# Run once in Terminal, in this folder:   sh make-mac-app.sh
# The app is created on your own Mac, so macOS does not block it. Double-click it to start.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$HOME/Applications/Picture Finder.app}"
[ -f "$HERE/picture_finder.py" ] || { echo "picture_finder.py must be next to this script."; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/picture_finder.py" "$APP/Contents/Resources/picture_finder.py"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Picture Finder</string>
  <key>CFBundleDisplayName</key><string>Picture Finder</string>
  <key>CFBundleIdentifier</key><string>local.winecellar.picturefinder</string>
  <key>CFBundleExecutable</key><string>PictureFinder</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/PictureFinder" <<'LAUNCH'
#!/bin/sh
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
PORT="${PF_PORT:-8765}"
URL="http://127.0.0.1:$PORT/"
KEYFILE="$HOME/.picture_finder_key"
PY="$(command -v python3 || echo /usr/bin/python3)"
if [ -z "$BRAVE_API_KEY" ] && [ ! -s "$KEYFILE" ]; then
  KEY="$(osascript -e 'text returned of (display dialog "Paste your Brave Search API key. It is stored only on this Mac." default answer "" with title "Picture Finder" buttons {"Cancel", "Save"} default button "Save")' 2>/dev/null)" || exit 0
  [ -n "$KEY" ] && { umask 077; printf '%s' "$KEY" > "$KEYFILE"; }
fi
# already running: just show the page again
if curl -s -m 1 -o /dev/null "$URL"; then open "$URL"; exit 0; fi
( sleep 1; open "$URL" ) &
exec "$PY" "$DIR/picture_finder.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/PictureFinder"

# icon: use the add-on's wine glass if the repository is next to this folder and the Mac tools are there
PNG="$HERE/../../wine_cellar/icon.png"
if [ -f "$PNG" ] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  S="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$S"
  for n in 16 32 128 256 512; do
    sips -z $n $n "$PNG" --out "$S/icon_${n}x${n}.png" >/dev/null 2>&1 || true
    sips -z $((n*2)) $((n*2)) "$PNG" --out "$S/icon_${n}x${n}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$S" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Created: $APP"
echo "Double-click it (or open it from Launchpad after dragging it to Applications)."
echo "The first time it asks for your Brave Search API key. Quit it from the Dock to stop."
echo "If a message offers to install the command line developer tools, accept: that provides Python 3."
