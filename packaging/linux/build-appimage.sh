#!/usr/bin/env bash
# dist/analyser/ -> a single-file AppImage. Run after `uv run pyinstaller analyser.spec`.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
# --group build on every uv call, so reading the version does not re-sync pyinstaller away.
version=$(uv run --no-dev --group build python -c 'from importlib.metadata import version; print(version("analyser"))')
arch=$(uname -m)

if [ ! -d dist/analyser ]; then
    echo "dist/analyser missing — run:" >&2
    echo "  uv run --no-dev --group build pyinstaller --noconfirm analyser.spec" >&2
    exit 1
fi

appdir=build/AppDir
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin"
cp -a dist/analyser/. "$appdir/usr/bin/"
install -m644 packaging/icon.png "$appdir/analyser.png"
install -m644 packaging/linux/analyser.desktop "$appdir/analyser.desktop"
install -m755 packaging/linux/AppRun "$appdir/AppRun"

# Fetched on demand rather than vendored: 10MB, changes rarely, and pinning it would mean
# tracking a binary in git.
tool=build/appimagetool
if [ ! -x "$tool" ]; then
    curl -fsSL -o "$tool" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$arch.AppImage"
    chmod +x "$tool"
fi

out="dist/goncanalyser-$version-$arch.AppImage"
# appimagetool is itself an AppImage, so it needs FUSE unless told to self-extract. CI
# runners and plenty of desktops lack libfuse2, and extracting costs a second.
ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" "$appdir" "$out"
echo "$out"
