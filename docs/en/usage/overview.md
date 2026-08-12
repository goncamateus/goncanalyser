# Overview

How the window is laid out, what runs in what order, and what each view is showing you.

## The window

![Viewer on the left, five control tabs on the right, transport underneath](../assets/images/window_overview.png)

Viewer on the **left**, controls on the **right** in five tabs, transport bar underneath the
image, status bar along the bottom.

The menu bar's `Image Adjustment | Global | Local | Structures | Motion` entries **raise
their tab** rather than opening a second window. There is exactly one definition of every
control, it is always one click away, and it never covers the image. `File`, `Dataset` and
`Rosbag` are the menus that do open dialogs, because opening, exporting and running a job
are one-shot questions — you answer once and the answer is acted on.

The panel is a fixed 400 px wide and each tab scrolls independently.

| Region | What lives there |
|---|---|
| Menu bar | `File`, the five tab-raising entries, `Dataset`, `Rosbag` |
| Viewer | The composited frame, scaled to fit. Also where a region is dragged |
| Transport bar | `View` picker, ◀ step back, Play/Pause, ▶ step forward, seek slider, frame number |
| Control tabs | Adjust, Global, Local, Structures, Motion |
| Status bar | Source, frame index, frame size, live metrics, playback state — plus the job pie on the right while a dataset job runs |

## The chain

One frame runs through the chain once. That single run feeds the viewer, the status bar and
the export, so nothing is computed twice and nothing gets a second code path.

```
adjust ──▶ motion ──▶ structure ──▶ keypoints ──▶ texture ──▶ colour
```

`adjust` runs first and separately, because it produces the frame every other feature reads.
`motion` is next so its overlay ends up *under* the detectors' — a heatmap painted last would
bury every box drawn before it. `colour` is last only because it is the one feature that
reads the frame and draws nothing on it.

Each feature writes into three collectors:

| Collector | What it holds | Where it surfaces |
|---|---|---|
| **canvases** | Whole-frame images the feature can offer as *the* view | The `View` picker |
| **ops** | Callables that paint geometry onto whichever canvas was picked | Overlays |
| **metrics** | Per-frame scalars | The status bar, and `metrics.csv` |
| **rows** | Per-object records — one per contour, keypoint, blob, line, corner | The per-object CSVs |

Splitting `ops` from `canvases` is what lets **any overlay compose with any view** without
either feature knowing the other exists. "Canny with SIFT keypoints over it" is two controls,
not a special case.

!!! tip "Adding a feature"

    One module with `run(frame, settings, out, state=None)` and one tab that declares its
    knobs. Nothing else changes — not the window, not the worker.

## The ten views

`View`, under the image, decides which stage is on screen. Geometry overlays draw *on top* of
whichever one you picked.

| View | Produced by | Notes |
|---|---|---|
| `Source` | Image Adjustment | The preprocessed frame. **If a threshold mode is selected, this is binary** — thresholding is part of preprocessing |
| `Grayscale` | Image Adjustment | Single channel of the preprocessed frame, as BGR |
| `Threshold` | Image Adjustment | What the contour finder reads. Derived at Binary/`Level` even when the threshold combo says `None` |
| `Edges` | Structures | Canny, Sobel or Laplacian |
| `Contour mask` | Structures | Filled contours — the mask the optimiser scores |
| `Motion mask` | Motion | The extracted foreground |
| `Motion heatmap` | Motion | Exponential average of motion, `COLORMAP_JET`, weighted per pixel by its own heat |
| `HOG` | Global | The gradient-orientation visualisation |
| `LBP` | Global | The local-binary-pattern code image |
| `Histogram` | Global | A 512×256 plot, not a frame — the one view a region cannot be drawn on |

A view whose feature is switched off is never produced, and the viewer **falls back to
`Source`** rather than going blank. Holding a view whose feature you just turned off is
normal, and blanking the image for it would be worse than showing the source.

## Preprocessing is not cosmetic

The Image Adjustment tab runs *before* everything else, colour space included. Edges,
keypoints and texture all measure the frame it produces, so switching to LAB genuinely
changes what SIFT sees. That is the point, not a side effect.

Two consequences worth having in mind from the start:

- **Contours read the `Threshold` image, not the edge map.** Contour finding wants a binary
  image, and thresholding is how you get one. Set the threshold up first and use the
  `Threshold` view to see exactly what the finder is being handed.
- **Selecting a threshold mode binarises the working frame itself**, so the `Source` view
  goes black and white too, and every downstream feature measures a binary image. Leave the
  combo on `None` and the `Threshold` canvas is still derived for the contour finder — which
  is how you get contour boxes drawn over a colour frame.

## Region of interest

**Image Adjustment → Selection** limits every analysis to a rectangle.

![Region on: inside is Otsu-thresholded, outside is the raw decoded frame](../assets/images/window_region.png)

The frame around the rectangle stays on screen as context and **never reaches the numbers**.
That guarantee is why the crop happens *first* in the chain rather than last, which would
have been easier to wire up: `Otsu` picks its level from whatever histogram it is given, and
a blur reads a kernel's worth of neighbours across the border, so cropping afterwards would
let the surround set the threshold and bleed over the edge. The background you see is the raw
decoded frame, never processed, so it cannot leak by construction.

`core.pipeline`'s own self-check pins this down: it analyses a region, blanks every pixel
outside it, re-analyses, and asserts the metrics are byte-identical — with Otsu and a blur
switched on, because those are the two operators that leak.

Exported coordinates are translated back to full-frame pixels, so a CSV means the same thing
with a region as without one.

It is also the cheap way to make the expensive features usable: SIFT + HOG over a full
640×512 frame is **202 ms**; over a 200×160 region, **21 ms**.

See [Controls → Region of interest](controls.md#region-of-interest) for how to draw one.

## Threading and responsiveness

| Thread | What it does |
|---|---|
| GUI | Widgets, and building a `Settings` when a knob moves |
| `Worker` | Decodes frames and runs the chain. One per open source |
| `ReportThread` | An export. Re-runs the chain over every frame |
| `DatasetThread` | One dataset job — a survey, a search, or a bag extraction |

`Settings` is a frozen dataclass. The GUI thread never mutates the one the worker is reading:
it builds a whole new one and rebinds a single attribute, which is atomic in CPython. The
worker therefore always sees a self-consistent set of values, and neither side needs a lock.

Two things keep the frame rate up:

- The worker **skips the whole chain** when paused on a frame nobody re-tuned.
- A canvas is **only converted to a QImage thumbnail when the tab showing it is visible** —
  the panel previews on the Global and Motion tabs cost nothing while you are on another tab.

### Measured cost per frame at 640×512

| Feature | Cost | Consequence |
|---|---|---|
| HOG | 150–300 ms | Slower than a video frame arrives. Off by default; playback drops frames while it is on |
| Farneback dense flow | 30–60 ms | Noticeable but usable |
| The other five motion algorithms | ~8 ms | Comfortably real-time |
| Everything else | ~8 ms or less | Comfortably real-time |

## Settings, saved and restored

**Written on quit, restored on the next launch**, in the per-platform config directory Qt
nominates:

| Platform | Path |
|---|---|
| Linux | `~/.config/analyser/settings.json` |
| macOS | `~/Library/Preferences/analyser/settings.json` |

A missing or corrupt file is ignored rather than fatal, and a cache written before a knob
existed still loads — the missing field keeps its default. **File → Preferences** shows the
path and offers a reset.

**File → Load settings…** (++ctrl+l++) goes the other way: point it at an exported
`settings.json` and the tuning that produced that export goes back into the controls.
Reproducing a run is the whole point of exporting the settings alongside the metrics. The
cache file works there too — the same flat dict, only not nested under `settings` — and
either way a field the file does not carry keeps its current value, so an export from an
older build still loads.

**File → Reset all controls** (++ctrl+r++) does not ask for confirmation — a shortcut that
stops to ask is not worth having. It stashes the previous values instead, so pressing it
again puts them back, and it keeps toggling between defaults and your last tuning. That
doubles as an A/B compare.

## Export in one paragraph

**File → Export analysis…** (++ctrl+s++) re-runs the chain over every frame and writes any of
`settings.json`, seven CSVs, composited overlay PNGs, and every moving object cropped out of
the *raw* frame. Rows are streamed rather than accumulated — a 900-frame clip with SIFT on
produces close to half a million keypoint rows, which would cost more memory than the video.
The full breakdown is in [Features → Export](features.md#export).

## Where the numbers come from

The status bar carries the source, the frame index, the frame size, and every per-frame
metric the enabled features produced — `B_mean`, `R_sd`, `contours`, `keypoints`,
`motion_objects`, `motion_speed`, `lbp_entropy` and so on. It is the same `metrics` dict that
becomes a row of `metrics.csv`, so what you read while tuning is exactly what an export
records.
