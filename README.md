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
  report.py                JSON / CSV / overlay export
ui/
  main_window.py           viewer left, tabs right, menu bar, transport
  dialogs.py               File menu: open, export, preferences
  controls/
    base.py                Knob, Section, Preview, and the widget factories
    adjust.py globals.py local.py structures.py    one tab each
  viewer.py                the image label, plus the rubber-band region drag
```

## The window

Viewer on the **left**, controls on the **right** in four tabs. The menu bar's
`Image Adjustment | Global | Local | Structures` raise their tab rather than
opening a second window — there is exactly one definition of every control, it is
always one click away, and it never covers the image. `File` is the one menu
that does open dialogs, because opening and exporting are one-shot questions.

`View` under the image picks which stage is on screen: `Source`, `Grayscale`,
`Threshold`, `Edges`, `Contour mask`, `HOG`, `LBP` or `Histogram`. Geometry
overlays — keypoints, corners, contours, Hough lines, blobs — draw *on top* of
whichever view you chose, so "Canny with SIFT keypoints over it" is just two
controls. A view whose feature is switched off falls back to `Source` instead of
blanking.

## The chain

    adjust -> structure -> keypoints -> texture -> colour

One frame runs through once, and that single run feeds the viewer, the status bar
and the export. Each feature writes into three collectors:

* **canvases** — whole-frame images it can offer as *the* view.
* **ops** — callables that paint geometry onto whichever canvas was picked.
* **metrics** / **rows** — the numbers. `metrics` are per-frame scalars for the
  status bar; `rows` are per-object (one per contour, keypoint, blob) for CSV.

Splitting `ops` from `canvases` is what lets any overlay compose with any view
without either feature knowing the other exists.

Adding a feature means one module with a `run(frame, settings, out)` and one tab
that declares its knobs. Nothing else changes — not the window, not the worker.

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
but playback drops frames while it is on. It is off by default. Everything else
is comfortably real-time.

The worker skips the whole chain when paused on a frame nobody re-tuned, and only
converts a canvas to a QImage thumbnail when the tab showing it is actually
visible.

## Export

**File → Export analysis…** re-runs the chain over every frame and writes any of:

* `report.json` — the full `Settings` plus per-frame metrics. The settings are in
  the file because a metrics table without the parameters that produced it is not
  reproducible.
* `metrics.csv` — one row per frame; `contours.csv`, `keypoints.csv`,
  `blobs.csv`, `lines.csv`, `corners.csv`, `histogram.csv` — one row per object,
  each carrying the frame it came from.
* `overlays/frame_%06d.png` — the composited frames.

Rows are streamed, not accumulated: a 900-frame clip with SIFT on produces close
to half a million keypoint rows, which would cost more memory than the video.

## Settings cache

Written on quit, restored on the next launch, in the per-platform config
directory Qt nominates (`~/Library/Preferences/analyser/` on macOS,
`~/.config/analyser/` on Linux). A missing or corrupt file is ignored rather
than fatal, and a cache written before a knob existed still loads — the missing
field keeps its default. **File → Preferences** shows the path and resets
everything.

## Keys

`space` play/pause · `.` step forward · `,` step back · `Ctrl+O` open ·
`Ctrl+Shift+O` open folder · `Ctrl+E` export · `Ctrl+R` reset all controls ·
`Ctrl+W` close (`⌘W` on macOS, where Qt maps Ctrl onto Command)

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
uv run python -m features.report    # JSON and CSV round-trip, driven like ReportThread
uv run python -m ui.viewer          # widget->image mapping, both letterbox orientations
uv run python -m ui.controls.base   # groups are siblings; every Settings field has a knob
```
