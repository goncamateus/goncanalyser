# Installation

Three ways in, in order of effort: download a prebuilt app, run it from source with `uv`, or
build your own installer.

## Prerequisites

| | |
|---|---|
| **Python** | 3.10 or newer, below 3.14 (`requires-python = ">=3.10,<3.14"`) |
| **Package manager** | [`uv`](https://docs.astral.sh/uv/) — it resolves, installs and runs, so there is no `venv` step |
| **Disk** | ~700 MB for the environment; PyQt6, OpenCV and scikit-image are large wheels |
| **Display** | A real desktop session. This is a GUI application and there is no headless mode |

Runtime dependencies are four, and they are installed for you: `numpy`, `opencv-python-headless`,
`pyqt6` and `scikit-image`.

!!! note "Why `opencv-python-headless` and not `opencv-python`"

    Nothing in this application calls `cv2.imshow` or `cv2.waitKey` — Qt does all the
    displaying. The plain `opencv-python` wheel ships its own copy of the Qt libraries, and
    two copies of Qt in one process is the classic
    `Could not load the Qt platform plugin "xcb"` failure. If you swap the dependency by
    hand, that is the error you will get.

### Operating systems

=== "Linux"

    Fully supported, from source and as an AppImage. On a minimal or container install you
    may need the X libraries Qt links against:

    ```bash
    sudo apt install libgl1 libegl1 libxkbcommon-x11-0 libdbus-1-3 \
                     libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
                     libxcb-randr0 libxcb-render-util0 libxcb-shape0
    ```

    The AppImage is built on Ubuntu 22.04 on purpose: an AppImage links against the glibc it
    was built on, so building on a newer distribution would produce one that refuses to
    start on older ones.

=== "macOS"

    Fully supported from source. The dmg is **arm64 only** — `cv2` and `scipy` publish
    separate `arm64` and `x86_64` wheels and no `universal2` wheel, so one dmg cannot cover
    both kinds of Mac. On an Intel Mac, run from source, or add a `macos-13` entry to the
    release workflow's matrix and build your own.

    Qt maps ++ctrl++ in a shortcut onto ++cmd++ here, so every ++ctrl+s++ in this
    documentation is ++cmd+s++ on macOS.

=== "Windows"

    Supported **from source**. There is no prebuilt installer: the Inno Setup recipe is in
    the repository but has never been executed, and the release workflow deliberately does
    not include Windows in its matrix. Treat
    [Building an installer](#building-an-installer) as a starting point rather than a
    supported path.

## Quick start with `uv`

```bash
git clone https://github.com/goncamateus/goncanalyser.git
cd goncanalyser
uv sync
uv run python main.py
```

`uv sync` creates `.venv` and installs everything pinned in `uv.lock`. No activation step is
needed — `uv run` uses that environment.

The window opens empty, with `Open video, image, or dataset to begin` where the frame goes.
Give it a path to skip that:

```bash
uv run python main.py clip.mp4     # a video
uv run python main.py frames/      # a folder of images, one per frame
uv run python main.py shot.png     # a single image
```

Supported extensions are `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.ppm`
for images and `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, `.webm`, `.mpg`, `.mpeg` for video.

### Optional dependency groups

The application runs on the four core dependencies. Three features ship their dependencies
separately, because none of them is needed to open an image and all of them are large:

| Group | Command | Enables |
|---|---|---|
| `dataset` | `uv sync --group dataset` | **Dataset → Analyse** (matplotlib) and **Dataset → Optimise** (optuna) |
| `rosbag` | `uv sync --group rosbag` | **Rosbag → Extract from ROS bag…** (rosbags, rosbags-image) |
| `build` | `uv sync --no-dev --group build` | PyInstaller, for building an installer |
| `dev` | installed by default | pytest |

If you open one of those menus without its package, the application tells you which single
package is missing and the exact command to install it — it names the package rather than
the group, because surveying needs matplotlib, tuning needs optuna, and extracting needs
rosbags, and none of the three needs another's.

## Prebuilt applications

Linux and macOS builds are attached to every tagged release on the
[releases page](https://github.com/goncamateus/goncanalyser/releases). Neither needs Python
or a checkout.

=== "Linux (AppImage)"

    ```bash
    chmod +x goncanalyser-0.3.0-x86_64.AppImage
    ./goncanalyser-0.3.0-x86_64.AppImage
    ```

    There is nothing to install and nothing to uninstall — delete the file when you are done
    with it.

=== "macOS (dmg)"

    Open the dmg, drag **Analyser** to Applications, then — for the first launch only —
    **right-click the app in Applications and choose *Open***, and confirm.

    The build is not notarised, so double-clicking it the first time gets you Gatekeeper's
    "cannot be opened because the developer cannot be verified" refusal. Right-click → Open
    is the documented way past that; after the first time it launches normally.

The packaged application ships **without** the optional groups, which is deliberate: the
`dataset` package is excluded from the bundle, so the desktop build still opens images and
video and tells you what to install if you reach for a dataset job.

## Building an installer

One PyInstaller recipe, `analyser.spec`, is shared by all three platforms; each then has a
short script that wraps the bundle. An installer can only be built on the platform it
targets — which is why the release workflow exists at all.

```bash
uv sync --no-dev --group build
```

!!! warning "`--group build` belongs on *every* `uv run` in a build"

    Including the ones that only read the version number. Without it, `uv` re-syncs the
    environment and drops PyInstaller straight back out of it, and the next step fails
    with `No module named PyInstaller`.

=== "Linux"

    ```bash
    uv run --no-dev --group build pyinstaller --noconfirm analyser.spec
    bash packaging/linux/build-appimage.sh
    # -> dist/goncanalyser-0.3.0-x86_64.AppImage
    ```

    Two steps: PyInstaller produces `dist/analyser/`, and the script turns it into an
    AppImage. The script downloads `appimagetool` on first run (~10 MB, cached in `build/`)
    and runs it with `APPIMAGE_EXTRACT_AND_RUN=1`, so no FUSE is required.

=== "macOS"

    ```bash
    bash packaging/macos/build-dmg.sh
    # -> dist/goncanalyser-0.3.0-arm64.dmg
    ```

    One step, not two. The spec's `BUNDLE` needs `build/icon.icns` to exist before the build
    starts, and this script is what generates it — from `packaging/icon.png` via `sips` and
    `iconutil`, both stock macOS. It then calls PyInstaller itself and wraps the result with
    `hdiutil`. No Homebrew, no `create-dmg`.

=== "Windows"

    ```powershell
    uv run --no-dev --group build pyinstaller --noconfirm analyser.spec
    iscc /DAppVersion=0.3.0 packaging\windows\analyser.iss
    # -> dist\goncanalyser-0.3.0-setup.exe
    ```

    Needs [Inno Setup](https://jrsoftware.org/isinfo.php). The version is passed on the
    command line so `pyproject.toml` stays the single source of truth. The installer is
    per-user (`PrivilegesRequired=lowest`, no UAC prompt) and x64 only, because the bundle
    carries 64-bit binary wheels.

    **This path has never been executed.** No release has ever carried a `setup.exe`.

### What the recipe does and does not do

`analyser.spec` is `onedir`, not `onefile`: `onefile` would unpack ~400 MB of `cv2` and
`scipy` into a temporary directory on every launch, costing ten seconds of cold start and
buying nothing once an installer wraps the output anyway.

`hiddenimports` is empty and `excludes` is short, both deliberately.
`pyinstaller-hooks-contrib` already knows how to collect PyQt6 and scikit-image, and the
PyQt6 hook prunes Qt down to the modules actually imported — which is the only reason the
260 MB PyQt6 tree does not land in the bundle. `tkinter`, `matplotlib`, `optuna` and
`dataset` are excluded so that a build machine which happens to have the optional group
synced does not quietly fold fifty megabytes of it into the app.

UPX and `strip` are both off: UPX mangles Qt's shared libraries often enough that the size
saving is not worth the class of bug it introduces.

`packaging/icon.png` is a placeholder. Replacing it wants a 1024×1024 PNG plus a regenerated
`icon.ico`; the macOS `.icns` is derived at build time.

## Troubleshooting

??? failure "`Could not load the Qt platform plugin "xcb"`"

    Almost always two copies of Qt in one process. Check that the installed OpenCV is
    `opencv-python-headless` and not `opencv-python`:

    ```bash
    uv run python -c "import cv2; print(cv2.__file__)"
    uv pip list | grep -i opencv
    ```

    If the plain wheel is present, remove it. If it is not, you are missing the X libraries
    listed under [Linux](#operating-systems) above. `QT_DEBUG_PLUGINS=1` will name the exact
    missing `.so`.

??? failure "`No module named PyInstaller` halfway through a build"

    A `uv run` without `--group build` re-synced the environment and evicted it. Put
    `--no-dev --group build` on every `uv run` in the build, including the one that just
    prints the version.

??? failure "`FT_Render_Glyph … failed with error 0x62: raster overflow`"

    matplotlib's `ft2font` and PyQt6 each ship their own FreeType, and whichever loads first
    wins the symbols for the whole process. `main.py` imports `matplotlib.ft2font` at the
    very top, before PyQt6, precisely to claim FreeType first — Qt takes it when it builds
    its first widget, so importing matplotlib after `MainWindow` exists is already too late,
    including from a worker thread.

    If you see this, something has moved or removed that import. It looks unused. It is not.

??? failure "A dataset menu says a package is missing"

    That is the intended message, not a bug — the optional groups are not installed by
    `uv sync`. Run the command it names: `uv sync --group dataset` for Analyse and
    Optimise, `uv sync --group rosbag` for bag extraction.

??? failure "The AppImage will not start on an older distribution"

    An AppImage carries no glibc; it links against the one it was built on. Build it on the
    oldest distribution you intend to support — the release workflow pins `ubuntu-22.04` for
    exactly this reason.

??? failure "macOS: \"the developer cannot be verified\""

    The build is unsigned and unnotarised. Right-click the app in Applications, choose
    *Open*, and confirm. Only the first launch needs it.

??? failure "The window opens but playback stutters or drops frames"

    Not a fault. HOG costs 150–300 ms a frame at 640×512 and dense optical flow 30–60 ms,
    both slower than a video frame arrives. They run off the GUI thread so nothing freezes,
    but playback will skip. Switch HOG off, or draw a region — a 200×160 region runs the
    same chain in a tenth of the time.

## Verifying an install

Every module carries a runnable self-check. They take seconds, need no fixtures, and are the
fastest way to confirm the environment is sound:

```bash
uv run python -m core.source        # video, folder and single image all read frame 0
uv run python -m core.pipeline      # the chain survives every view and every toggle
uv run python -m features.adjust    # identity is byte-exact; every threshold is binary
uv run python -m features.color     # known images have known histograms
uv run python -m features.texture   # HOG length matches the geometry; noise beats flat
uv run python -m features.keypoints # SIFT is 128-d, ORB is 32-byte, sensitivity monotonic
uv run python -m features.structure # a synthetic square: 1 contour, 4 corners, 4 lines
uv run python -m features.motion    # all six see a moving square and none see a still one
uv run python -m features.report    # JSON and CSV round-trip, driven like ReportThread
uv run python -m ui.viewer          # widget->image mapping, both letterbox orientations
uv run python -m ui.controls.base   # groups are siblings; every Settings field has a knob
uv run python -m ui.progress        # the pie sweeps; hiding the job window keeps it
```

The `dataset` package builds its own COCO fixture and needs its group:

```bash
uv run --group dataset python -m dataset.coco      # polygons and column-major RLE decode
uv run --group dataset python -m dataset.stats     # mask reads brighter than background
uv run --group dataset python -m dataset.optimise  # f(θ) corners exact; a study beats defaults
```
