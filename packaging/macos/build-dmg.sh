#!/usr/bin/env bash
# Analyser.app -> a .dmg, with the .icns built on the way in. Runs the whole macOS build,
# because the spec's BUNDLE needs the .icns to exist before PyInstaller starts.
#
# hdiutil and iconutil are both stock macOS — no create-dmg, no Homebrew step.
#
# Ships one arch: cv2 and scipy publish separate arm64 and x86_64 wheels with no
# universal2, so a universal binary is not available. The dmg is named for the arch it
# was built on.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
# --group build on every uv call, so reading the version does not re-sync pyinstaller away.
version=$(uv run --no-dev --group build python -c 'from importlib.metadata import version; print(version("analyser"))')
arch=$(uname -m)

# iconutil wants an .iconset directory with exactly these names.
iconset=build/icon.iconset
rm -rf "$iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" packaging/icon.png --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" packaging/icon.png --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o build/icon.icns

uv run --no-dev --group build pyinstaller --noconfirm analyser.spec

staging=build/dmg
rm -rf "$staging"
mkdir -p "$staging"
cp -R dist/Analyser.app "$staging/"
ln -s /Applications "$staging/Applications"

out="dist/goncanalyser-$version-$arch.dmg"
rm -f "$out"
hdiutil create -volname "Analyser $version" -srcfolder "$staging" -ov -format UDZO "$out"
echo "$out"
