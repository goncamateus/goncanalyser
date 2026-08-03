# -*- mode: python ; coding: utf-8 -*-
"""One build recipe for all three platforms.

onedir rather than onefile: onefile would unpack ~400MB of cv2 and scipy into a temp
directory on every launch, which costs ten seconds of cold start and buys nothing once
an installer is wrapping the output anyway.

`hiddenimports` is deliberately empty and `excludes` deliberately short.
pyinstaller-hooks-contrib already knows how to collect PyQt6 and scikit-image — whose
`lazy_loader` stubs are data files rather than imports — and the PyQt6 hook prunes Qt
down to the modules actually imported, which is the whole reason the 260MB PyQt6 tree
does not land in the bundle. Entries added here without a failing smoke test to point at
are cargo cult.
"""

import sys
from importlib.metadata import version

# The build env has the package installed, so the version has one source: pyproject.toml.
VERSION = version("analyser")

# PyInstaller only consumes an icon here on Windows; macOS takes it from BUNDLE below and
# Linux takes it from the .desktop file.
ICON = "packaging/icon.ico" if sys.platform == "win32" else None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="analyser",
    debug=False,
    bootloader_ignore_signals=False,
    # UPX mangles Qt's shared libraries often enough that the size win is not worth the
    # class of bug it introduces, and stripping breaks some binary wheels the same way.
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="analyser",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Analyser.app",
        # Built by packaging/macos/build-dmg.sh, which is also what invokes this spec.
        icon="build/icon.icns",
        bundle_identifier="io.github.goncamateus.analyser",
        version=VERSION,
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": VERSION,
            # The app takes a path argument, so let Finder hand it files directly.
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Image or video",
                    "CFBundleTypeRole": "Viewer",
                    "LSItemContentTypes": ["public.image", "public.movie"],
                }
            ],
        },
    )
