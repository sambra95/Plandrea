#!/usr/bin/env bash
#
# Build the portable macOS bundle for Plandrea.
#
# Produces Plandrea.app carrying its own Python and every dependency, so the Mac
# it lands on needs no Python, uv or git - download, unzip, double-click. The
# app opens in your default browser and quits once the last tab closes.
#
# The bundle is built for the architecture of the machine running this script.
#
# Usage:
#   ./macos_install/make_dist.sh [--version 1.0.0] [--no-dmg] [--zip] [--xz]

set -euo pipefail

VERSION="1.0.0"
MAKE_DMG=1
MAKE_ZIP=0
MAKE_XZ=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="$2"; shift 2 ;;
        --version=*) VERSION="${1#*=}"; shift ;;
        --no-dmg) MAKE_DMG=0; shift ;;
        --zip) MAKE_ZIP=1; shift ;;
        --xz) MAKE_XZ=1; shift ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

PY_VERSION=3.12
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P_LIB=""   # set once the interpreter is in place
cd "$ROOT"

case "$(uname -m)" in
    arm64)  PY_ARCH="aarch64" ;;
    x86_64) PY_ARCH="x86_64" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

APP="$ROOT/dist/Plandrea.app"
RESOURCES="$APP/Contents/Resources"
BUILD="$ROOT/build"

step() { echo ""; echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

command -v uv >/dev/null || die "uv not found: https://docs.astral.sh/uv/"

echo "Building Plandrea $VERSION for macOS ($(uname -m))"

step "[1/7] Skeleton"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RESOURCES/bin" "$BUILD"

step "[2/7] Bundling Python $PY_VERSION"
# A uv-managed (python-build-standalone) interpreter is relocatable. A `uv venv`
# would not do: it only symlinks back to the Python that made it.
uv python install "$PY_VERSION" >/dev/null 2>&1 || true
PATTERN="cpython-$PY_VERSION.*-macos-$PY_ARCH-none"
SRC="$(ls -d "$(uv python dir)"/$PATTERN 2>/dev/null | sort -V | tail -1)"
[[ -n "$SRC" && -d "$SRC" ]] \
    || die "no CPython $PY_VERSION for $PY_ARCH; run: uv python install $PY_VERSION"
echo "    $(basename "$SRC")"
cp -R "$SRC" "$RESOURCES/bin/python"
# Installing into the copy is the whole point of having made one.
find "$RESOURCES/bin/python" -name EXTERNALLY-MANAGED -delete
BUNDLED_PY="$RESOURCES/bin/python/bin/python3"
P_LIB="$RESOURCES/bin/python/lib/python$PY_VERSION"

step "[3/7] Installing dependencies"
uv export --no-dev --no-emit-project -o "$BUILD/requirements.txt" >/dev/null
uv pip install --python "$BUNDLED_PY" -r "$BUILD/requirements.txt" --quiet
echo "    $(grep -cE '^[a-zA-Z0-9_.-]+==' "$BUILD/requirements.txt") pinned packages"

step "[4/7] Copying the app"
# Every module at the root, so adding one needs no edit here.
cp ./*.py "$RESOURCES/"
cp -R app_pages "$RESOURCES/app_pages"
cp -R assets "$RESOURCES/assets"
# CFBundleIconFile names a file at the root of Resources, not inside a folder.
cp assets/Plandrea.icns "$RESOURCES/Plandrea.icns"
cp -R .streamlit "$RESOURCES/.streamlit"
cp README.md "$RESOURCES/README.md"
find "$RESOURCES" -name '__pycache__' -type d -prune -exec rm -rf {} +

step "[5/7] Trimming"
# What a packaged Streamlit app never touches. What is absent here is equally
# deliberate: pyarrow's other libraries are linked by pyarrow.lib itself, and
# pydeck/nbextension/__init__.py is imported by pydeck - only its static/ can go.
SITE="$P_LIB/site-packages"
before_trim=$(du -sm "$APP" | cut -f1)
rm -rf "$RESOURCES/bin/python/share/jupyter" "$SITE/pydeck/nbextension/static"
find "$SITE" -type d \( -name tests -o -name testing \) -prune \
     -exec rm -rf {} + 2>/dev/null || true
rm -rf "$SITE/pip" "$SITE"/pip-*.dist-info "$P_LIB/ensurepip" "$P_LIB/idlelib"
rm -rf "$P_LIB/tkinter" "$P_LIB"/lib-dynload/_tkinter*.so
rm -rf "$SITE/pyarrow/include" "$RESOURCES/bin/python/include"
rm -f "$SITE/pyarrow"/libarrow_flight.*.dylib "$SITE/pyarrow"/_flight*.so
# Debug symbols are a third of what is left in the binaries.
find "$RESOURCES/bin/python" \( -name "*.so" -o -name "*.dylib" \) \
     -exec strip -x -S {} + 2>/dev/null || true
echo "    $before_trim MB -> $(du -sm "$APP" | cut -f1) MB"

step "[6/7] Launcher and metadata"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Plandrea</string>
    <key>CFBundleDisplayName</key><string>Plandrea</string>
    <key>CFBundleIdentifier</key><string>local.plandrea</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Plandrea</string>
    <key>CFBundleIconFile</key><string>Plandrea</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Plandrea" <<'LAUNCH'
#!/bin/bash
# Everything is found relative to this script: a bundle can be anywhere, and
# double-clicked it starts in "/".
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
PYTHON="$RESOURCES/bin/python/bin/python3"

if [ ! -x "$PYTHON" ]; then
    # No console here, so a message has to be shown rather than printed. The
    # usual cause is running it from inside the zip without unpacking first.
    osascript -e 'display dialog "Plandrea is missing its Python. Unzip the app \
before opening it." with title "Plandrea" buttons {"OK"} with icon stop' \
        >/dev/null 2>&1
    exit 1
fi
exec "$PYTHON" "$RESOURCES/bootstrap.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/Plandrea"

# Signing comes last: stripping removes a signature, and arm64 macOS kills
# unsigned code on load. Each binary needs its own, not just the bundle.
find "$RESOURCES/bin/python" \( -name "*.so" -o -name "*.dylib" \) \
     -exec codesign --force --sign - {} + 2>/dev/null || true
codesign --force --sign - "$BUNDLED_PY" >/dev/null 2>&1 || true
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true

step "[7/7] Packaging"
SIZE="$(du -sh "$APP" | cut -f1)"
echo "    $APP ($SIZE)"
# No version in the archive names: that keeps the GitHub
# releases/latest/download/<name> link permanent. The version is in Info.plist.
if [[ $MAKE_DMG == 1 ]]; then
    # A disk image, so opening it offers the app beside an Applications alias to
    # drag it onto. A zip cannot do that: it just unpacks wherever it lands.
    DMG="$ROOT/dist/Plandrea-macos-$(uname -m).dmg"
    STAGE="$BUILD/dmg"
    RW="$BUILD/rw.dmg"
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    cp -R "$APP" "$STAGE/Plandrea.app"
    ln -s /Applications "$STAGE/Applications"
    rm -f "$DMG" "$RW"

    # Built writable first so Finder can lay the window out, then compressed.
    hdiutil create -volname "Plandrea" -srcfolder "$STAGE" -ov \
        -format UDRW -quiet "$RW"
    MOUNT="$(hdiutil attach "$RW" -nobrowse -readwrite -noverify \
             | awk '/\/Volumes\//{print $3; exit}')"

    # The arrangement Finder writes lands in the image's own .DS_Store, so the
    # window opens showing the app beside the Applications folder to drag it
    # onto. Best effort: a machine with no Finder session still gets a usable
    # image, just without the positions.
    osascript >/dev/null 2>&1 <<'LAYOUT' || echo "    (no Finder: window left unarranged)"
tell application "Finder"
    tell disk "Plandrea"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 800, 520}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to 128
        set position of item "Plandrea.app" of container window to {150, 200}
        set position of item "Applications" of container window to {450, 200}
        close
        open
        update without registering applications
        delay 2
    end tell
end tell
LAYOUT
    sync
    hdiutil detach "$MOUNT" -quiet

    # ULMO (LZMA) rather than the default UDZO (zlib), and converting a
    # read-write image compresses better than writing one compressed outright.
    hdiutil convert "$RW" -format ULMO -o "$DMG" -quiet
    rm -f "$RW"
    rm -rf "$STAGE"
    echo "    $DMG ($(du -sh "$DMG" | cut -f1))"
fi
if [[ $MAKE_ZIP == 1 ]]; then
    ZIP="$ROOT/dist/Plandrea-macos-$(uname -m).zip"
    rm -f "$ZIP"
    ( cd "$ROOT/dist" && ditto -c -k --keepParent "Plandrea.app" "$ZIP" )
    echo "    $ZIP ($(du -sh "$ZIP" | cut -f1))"
fi
if [[ $MAKE_XZ == 1 ]]; then
    # Roughly half the zip, at the cost of needing tar to open it.
    XZ="$ROOT/dist/Plandrea-macos-$(uname -m).tar.xz"
    rm -f "$XZ"
    ( cd "$ROOT/dist" && tar -cJf "$XZ" "Plandrea.app" )
    echo "    $XZ ($(du -sh "$XZ" | cut -f1))"
fi
echo ""
echo "Done."
