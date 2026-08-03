# analyser

A Qt workspace for looking at what OpenCV sees. Load an image, a folder or a
video; stack preprocessing; switch on colour, texture, keypoint or structural
extractors; watch the result at playback speed; export the numbers.

```bash
uv run python main.py               # opens a file dialog
uv run python main.py clip.mp4      # a video
uv run python main.py frames/       # a folder of images
uv run python main.py shot.png      # one image
```

## Install

Installers for all three platforms are on the
[releases page](https://github.com/goncamateus/goncanalyser/releases) — no Python and no
checkout needed. Linux gets an AppImage (`chmod +x` and run it), Windows a `setup.exe`,
macOS a `.dmg`.

The builds are not code-signed, so the first launch needs a nudge: on macOS right-click
the app in Applications and choose *Open* rather than double-clicking it, and on Windows
choose *More info* then *Run anyway* when SmartScreen warns. The AppImage needs neither.

## Layout

```
main.py                    entry point: pick a source, then the window
core/
  settings.py              Settings — every knob as one frozen dataclass — and its cache
  pipeline.py              the frame chain. No Qt, importable on its own
  source.py                FrameSource: video / folder / single image, one interface
  worker.py                Worker QThread and ReportThread
features/                  no Qt in here either
  adjust.py                preprocessing, plus the shared kernel/colour helpers
  color.py                 RGB/HSV/LAB histograms, drawn with cv2.polylines
  texture.py               HOG and LBP (scikit-image)
  keypoints.py             SIFT and ORB
  structure.py             edges, Hough, corners, contours, blobs
  motion.py                heatmap, foreground, six motion algorithms — the one
                           feature that spans frames, so the one with state
  report.py                JSON / CSV / overlay / object-crop export
ui/
  main_window.py           viewer left, tabs right, menu bar, transport
  dialogs.py               File menu: open, export, preferences
  controls/
    base.py                Knob, Section, Preview, and the widget factories
    adjust.py globals.py local.py structures.py motion.py    one tab each
  viewer.py                the image label, plus the rubber-band region drag
```

## The window

Viewer on the **left**, controls on the **right** in five tabs. The menu bar's
`Image Adjustment | Global | Local | Structures | Motion` raise their tab rather than
opening a second window — there is exactly one definition of every control, it is
always one click away, and it never covers the image. `File` is the one menu
that does open dialogs, because opening and exporting are one-shot questions.

`View` under the image picks which stage is on screen: `Source`, `Grayscale`,
`Threshold`, `Edges`, `Contour mask`, `Motion mask`, `Motion heatmap`, `HOG`,
`LBP` or `Histogram`. Geometry
overlays — keypoints, corners, contours, Hough lines, blobs — draw *on top* of
whichever view you chose, so "Canny with SIFT keypoints over it" is just two
controls. A view whose feature is switched off falls back to `Source` instead of
blanking.

## The chain

    adjust -> motion -> structure -> keypoints -> texture -> colour

One frame runs through once, and that single run feeds the viewer, the status bar
and the export. Each feature writes into three collectors:

* **canvases** — whole-frame images it can offer as *the* view.
* **ops** — callables that paint geometry onto whichever canvas was picked.
* **metrics** / **rows** — the numbers. `metrics` are per-frame scalars for the
  status bar; `rows` are per-object (one per contour, keypoint, blob) for CSV.

Splitting `ops` from `canvases` is what lets any overlay compose with any view
without either feature knowing the other exists.

Adding a feature means one module with a `run(frame, settings, out, state=None)`
and one tab that declares its knobs. Nothing else changes — not the window, not
the worker.

## Region of interest

**Image Adjustment → Selection** limits every analysis to a rectangle. Drag it on
the image with the **Draw** button, or type it into the four spinboxes (arrows
step by 10; `0` for W or H means out to the edge). The two stay in sync.

The frame around the rectangle stays on screen as context and **never reaches the
numbers**. That guarantee is why the crop happens *first* in the chain rather
than last, which would have been easier to wire up: `Otsu` picks its level from
whatever histogram it is given, and a blur reads a kernel's worth of neighbours
across the border, so cropping afterwards would let the surround set the
threshold and bleed over the edge. The background you see is the raw decoded
frame, never processed, so it cannot leak by construction.

`core.pipeline`'s check pins this down — it analyses a region, blanks every pixel
outside it, re-analyses, and asserts the metrics are byte-identical, with Otsu
and a blur switched on because those are the two operators that leak.

Exported coordinates are translated back to full-frame pixels, so a CSV means the
same thing with a region as without one.

It is also the cheap way to make the expensive features usable: SIFT + HOG over a
full 640x512 frame is **202 ms**; over a 200x160 region, **21 ms**.

## Preprocessing is not cosmetic

The Image Adjustment tab runs *before* everything else, colour space included.
Edges, keypoints and texture all measure the frame it produces, so switching to
LAB genuinely changes what SIFT sees. That is the point.

Contours specifically read the **Threshold** image, not the edge map — contour
finding wants a binary image and thresholding is how you get one. Set the
threshold up first and use the `Threshold` view to see exactly what the contour
finder is being handed.

## Motion

The **Motion** tab is the only one that measures the time axis, which makes it
the only one with state behind it. Six algorithms, all reporting the same thing:

| | |
|---|---|
| `MOG2`, `KNN` | statistical background model; adapts, so a plume that never moves eventually *becomes* background — that is what History and Learning rate are for |
| `Farneback` | dense optical flow. The one to use when the shape of the moving thing matters |
| `Lucas-Kanade` | sparse flow at tracked corners, each vector splatted as a disc. Fast, but a disc is not a segmentation |
| `Frame difference` | the plain absolute difference |
| `Three-frame difference` | the minimum of two consecutive differences, which drops the ghost a plain difference leaves *behind* the object |

Whichever is selected, it produces a 0..255 motion image, and everything after
that is shared: one **Sensitivity** threshold, one noise-removal kernel, one set
of contours. So the knobs mean the same thing across all six and switching
algorithm is not re-learning the panel. Optical flow is scaled on the way in —
8 px/frame reads as full scale, `motion.FLOW_GAIN` if that needs calibrating.

`Motion mask` is the extracted foreground, `Motion heatmap` is an exponential
average of the motion over the last N frames, painted with `COLORMAP_JET` and
weighted per pixel by its own heat, so cold areas stay as the frame instead of
washing blue. Tick **Overlay** and it composites onto whichever view you are on,
like any other overlay. Both are also thumbnails on the tab, next to the knobs
that change them.

Boxes carry area and pixels-per-frame speed, matched by nearest centroid between
frames. That answers "how fast is something moving here", **not** "where did
object 7 go" — there is no track identity, so two blobs that cross swap speeds.

### The three state rules

`MotionState` is owned by whoever drives the frames — the worker has one, an
export has its own — and reset by three things, all of which happen in normal use:

1. **The same frame twice does not advance it.** Dragging a knob while paused
   re-analyses the frame on screen over and over; feeding a background model the
   same image fifty times teaches it that image *is* the background, so a still
   frame would fade to nothing while you tuned it. The thresholds stay live
   though — only the carried state is pinned.
2. **A seek or a backwards step resets it.** The previous frame is no longer the
   previous frame, and differencing across the jump lights up the whole image.
3. **A changed model resets it** — a different algorithm, or a resized region,
   leaves a model of the wrong kind or the wrong shape.

The region needs no special handling here: `adjust` crops before any feature
runs, so the frame this module sees *is* the region and the heatmap is confined
to it for free.

## What this OpenCV build can and cannot do

Section D of the original spec asked for SIFT, SURF and ORB. **SIFT and ORB are
shipped; SURF is not, and neither are the usual substitutes:**

* **SURF** is patented, lives behind `OPENCV_ENABLE_NONFREE`, and no published
  wheel sets it — not even `opencv-contrib-python`. It needs a source build.
* **AKAZE, BRISK and KAZE** are absent from the `opencv-python` 5.0 Python
  bindings entirely (`cv2.AKAZE` does not exist).
* **ALIKED and DISK**, which 5.0 adds in their place, require ONNX model files
  that are not bundled.

So the Local tab offers the two that work: SIFT (128-d float, slow, more
discriminative) and ORB (32-byte binary, fast enough for video). Their native
thresholds are on different scales, so the panel exposes one normalised
**Sensitivity** knob and `keypoints.SENSITIVITY` holds each detector's real
range — up always means more keypoints.

## Speed

HOG is the expensive thing: **150-300 ms a frame at 640x512**, slower than a
video frame arrives. It runs on the worker thread so the window never freezes,
but playback drops frames while it is on. It is off by default.

Dense optical flow (`Farneback`) is the next one down at **30-60 ms**; the other
five motion algorithms are ~8 ms a frame at 640x512, comfortably real-time, as is
everything else.

The worker skips the whole chain when paused on a frame nobody re-tuned, and only
converts a canvas to a QImage thumbnail when the tab showing it is actually
visible.

## Export

**File → Export analysis…** re-runs the chain over every frame and writes any of:

* `settings.json` — the full `Settings`, and no measurements. A metrics table
  without the parameters that produced it is not reproducible, so the parameters
  ship alongside it; the numbers themselves are the CSVs' job. Ticking this on
  its own reads no frames at all, so it is instant.
* `metrics.csv` — one row per frame; `contours.csv`, `keypoints.csv`,
  `blobs.csv`, `lines.csv`, `corners.csv`, `motion.csv`, `histogram.csv` — one
  row per object, each carrying the frame it came from.
* `overlays/frame_%06d.png` — the composited frames.
* `objects/frame_%06d_%02d.png` — every moving object, cut out of the **raw**
  frame rather than the composite, so what lands on disk is the object as the
  camera saw it and not a picture of a box drawn round it.

Rows are streamed, not accumulated: a 900-frame clip with SIFT on produces close
to half a million keypoint rows, which would cost more memory than the video.

## Settings cache

Written on quit, restored on the next launch, in the per-platform config
directory Qt nominates (`~/Library/Preferences/analyser/` on macOS,
`~/.config/analyser/` on Linux). A missing or corrupt file is ignored rather
than fatal, and a cache written before a knob existed still loads — the missing
field keeps its default. **File → Preferences** shows the path and resets
everything.

**File → Load settings…** goes the other way: point it at an exported
`settings.json` and the tuning that produced that export goes back into the
controls. Reproducing a run is the point of exporting the settings alongside the
metrics. The cache file works there too — the same flat dict, only not nested
under `settings` — and either way a field the file does not carry keeps its
current value, so an export from an older build still loads.

## Keys

`space` play/pause · `.` step forward · `,` step back · `Ctrl+O` open ·
`Ctrl+Shift+O` open folder · `Ctrl+L` load settings ·
`Ctrl+S` export · `Ctrl+R` reset all controls · `Ctrl+W` close (`⌘W` on macOS,
where Qt maps Ctrl onto Command — so these are `⌘S`, `⌘L`, `⌘R` there)

`Ctrl+R` does not ask for confirmation — a shortcut that stops to ask is not
worth having. It stashes the previous values instead, so pressing it again puts
them back, and it keeps toggling between defaults and your last tuning. That
doubles as an A/B compare.

## Check

Every module carries a runnable self-check:

```bash
uv run python -m core.settings      # (no check — data only)
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
```

## Packaging

`analyser.spec` is one PyInstaller recipe shared by all three platforms; each one then has
a short script that turns the bundle into an installer.

```bash
uv sync --no-dev --group build

# Linux and Windows: bundle first, then wrap it.
uv run --no-dev --group build pyinstaller --noconfirm analyser.spec
bash packaging/linux/build-appimage.sh   # -> dist/goncanalyser-VERSION-ARCH.AppImage

# macOS is one step, not two: the spec's BUNDLE needs the .icns, and this script is what
# generates it, so it calls PyInstaller itself.
bash packaging/macos/build-dmg.sh        # -> dist/goncanalyser-VERSION-arm64.dmg
```

Windows wrapping needs [Inno Setup](https://jrsoftware.org/isinfo.php):

```
iscc /DAppVersion=0.3.0 packaging\windows\analyser.iss
```

`--group build` belongs on every `uv run` in a build, including the ones that only read
the version — without it uv re-syncs and drops PyInstaller back out of the environment.

An installer can only be built on the platform it targets, so
`.github/workflows/release.yml` builds all three on tag push and attaches them to a
GitHub release. Only the Linux path can be iterated locally.

Two packaging constraints worth knowing before changing dependencies:

- The dependency is `opencv-python-headless`, not `opencv-python`. Nothing here calls
  `cv2.imshow` or `waitKey`, and the plain wheel ships a second copy of Qt that fights
  PyQt6's inside a bundle — the classic `Could not load the Qt platform plugin "xcb"`.
- macOS ships arm64 only. cv2 and scipy publish separate arm64 and x86_64 wheels with no
  `universal2`, so one dmg cannot cover both kinds of Mac.

`packaging/icon.png` is a placeholder. Replacing it wants a 1024×1024 PNG plus a
regenerated `icon.ico`; the macOS `.icns` is derived at build time by `build-dmg.sh`.
