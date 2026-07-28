# video-tuner

A Qt front end for tuning OpenCV operations against a video file, live. Pick a
clip, drag sliders, watch the result at playback speed.

```bash
uv run python main.py            # opens a file dialog
uv run python main.py clip.mp4   # skips the dialog
```

## Layout

```
main.py                     entry point: file dialog, then the window
gui/
  main_window.py            layout, transport, panel <-> worker wiring
  controls/
    base.py                 Knob (slider + readout) and the Section base class
    basic.py                A: brightness / contrast / saturation / gamma / blur / colour space
    plume.py                B: source finding, then the plume grown out of it
    labelling.py            C: label counts, key legend, export button
processing/
  video_thread.py           QThread: decode, process, emit QImages; plus ExportThread
  pipeline.py               the OpenCV chain -- no Qt, importable on its own
  plume.py                  single-frame steam plume segmentation
  tracking.py               Kalman + association, to stop the detections flickering
  labels.py                 which detection is the real plume, per frame
  coco.py                   one-class COCO segmentation export
```

## Frame chain

    raw frame -> adjustments -> plume detection -> colour space

Section A is not cosmetic: the detector reads the frame it produces, and every
threshold in Section B is a *percentile of that frame's histogram*. Brightness,
contrast and gamma move the histogram, so settle Section A first, then calibrate
Section B, then leave A alone. The colour space conversion happens last and is
the one genuinely cosmetic stage.

## Tracking

The raw detector is per-frame and unstable: measured over 60 consecutive frames of
`voo_1.mp4`, it changed how many sources it found on **36 of 59** transitions,
swinging between 2 and 5 as the hot equipment blinked in and out. A Kalman filter
alone does not fix that -- a filter smooths a signal it is given, and the problem
is the signal disappearing. So `tracking.py` is the usual three parts:

* **associate** each frame's detections to existing tracks by distance
* **coast** an unmatched track for `max_age` frames before dropping it, which
  bridges a 1-2 frame dropout; its last mask is redrawn, shifted by the filter's
  predicted motion so it keeps up with the drone
* **confirm** a new track only after `min_hits` detections, so a one-frame speck
  never reaches the screen

The filter is constant-velocity over `[cx, cy, w, h]`. Velocity is what makes
coasting worth anything -- a plume drifts and the drone moves, so a coasted track
has to keep moving or the next association fails anyway.

Result on the same 60 frames: count changes **36 -> 12**, at 23 -> 26 ms/frame.
The status bar shows `plumes=4(3)` when the two disagree, so a held-through
dropout is visible rather than silent.

This is the only stateful thing in the chain, which costs two guarantees worth
knowing about. Track state belongs to a *contiguous* run of frames, so any seek
throws it away. And re-rendering a frame must not step the filter -- dragging a
slider re-runs the chain many times a second on the same frame -- so the state
from before the current frame is kept and restored on a repeat. A paused frame
therefore renders identically however many times it is redrawn.

## Labelling and export

The detector cannot separate a plume from hot dithered equipment (see the known
limit below), so the last step is a human. Step through the clip and press the
digit matching the `#N` drawn on the plume; `N` marks a frame as having no plume
at all, `U` undoes. The pick is acknowledged on screen -- the chosen outline goes
yellow and its label gains `OK`.

A pick is stored as **a point in the image**, not as the number you pressed.
Indices belong to the current parameters: nudge a percentile, a source appears,
and every index after it shifts. An anchor belongs to the scene, so re-tuning
re-binds each label to whichever detection is now nearest instead of silently
relabelling the wrong blob. A pick whose plume no longer exists is reported
*lost* rather than guessed at, and is left out of the export.

Labels live beside the settings cache, one file per video, written on every
keystroke rather than at quit.

Export warms the tracker up by decoding the frames before each labelled one, so
the exported mask is the one that was on screen when the pick was made -- including
on a frame where the plume was being coasted through a dropout.

**Export COCO dataset…** writes `images/frame_%06d.png` plus
`annotations/instances.json`. One category, `plume`, covering halo and core as a
single outline -- there is no separate core or source class. One annotation per
image, whose `segmentation` is a list of polygons when the mask is in several
pieces. Rejected frames export as an image with no annotation, which is a genuine
negative sample. The image written is the **raw** decoded frame: Section A's
adjustments are tuning aids for the detector, not part of the data.

## Settings cache

The panel's state is written on quit and restored on the next launch, to the
per-platform config directory Qt nominates (`~/Library/Preferences/video-tuner/`
on macOS, `~/.config/video-tuner/` on Linux). Delete `settings.json` there to get
the defaults back. A missing or corrupt file is ignored rather than fatal, and a
cache written before a knob existed still loads — the missing field keeps its
default.

## Plume detection

Ported from this repo's earlier `steamdet/plume.py` (`git show 9fdd3dd^:steamdet/plume.py`)
with the temporal half removed. The original ANDed three cues -- hot, textured
and *moving* -- and got the motion term by aligning neighbouring frames. Camera
motion compensation never earned its cost on drone footage, so this keeps the two
cues that need only the frame in front of you:

* **Temperature.** The clip is not radiometric -- the camera baked a colormap in
  -- but HLS lightness rises monotonically along that palette, so `L` is a
  temperature proxy (r = 0.96 against a full inverse-LUT reconstruction). Every
  threshold is a percentile, never a grey level, because the camera runs AGC.
  Which channel gets measured is Section A's colour space: each one hands the
  detector its lightness-like channel (HLS/LAB `L`, HSV `V`, or grey), and
  `Default (BGR)` leaves the picture alone while measuring HLS lightness.
* **Texture.** Above the top of the palette the sensor dithers, so the hottest
  things come out speckled rather than flat. High local sigma is the signature.
* **Geometry.** Plumes rise, so each source's search region runs from its own
  base upward. That one line keeps hot ground and vehicles out of the mask.

Detection is two stages, and the panel is grouped the same way: find the vents
(hot **and** dithered), then grow a plume out of each one by hysteresis -- keep
the blobs containing a core pixel, then walk outward through saturated pixels and
finally a few steps into the cooler halo. Masks carry `0 = background, 1 = halo,
2 = core`, so one array holds both extents. ~30-60 ms/frame at 640x512.

**Known limit.** Texture does not separate the plume from hot dithered equipment
on `voo_1.mp4` -- measured at the native 640x512, plume sigma averages 24.2 and
the hot equipment 25.1. Both sit at the top of the palette and both dither. The
motion cue is what used to reject static hot metal; without it, expect the plant's
hot surfaces among the detections and use `p_src`, `Source min area` and the
search margin to cut them down.## Threading

`VideoThread` owns the capture and the pipeline. The GUI sends it settings by
rebinding one frozen dataclass (atomic, no lock) and gets finished QImages back
through signals, so decoding never blocks the widgets.

## Keys

`space` play/pause . `.` step forward . `,` step back

## Check

```bash
uv run python -m processing.pipeline   # asserts the chain over every toggle
uv run python -m processing.plume      # asserts a synthetic vent is found and
                                       # a smooth hot slab is not
uv run python -m processing.labels     # asserts picks survive re-tuning
uv run python -m processing.coco       # asserts the COCO schema by hand
uv run python -m processing.tracking   # asserts a dropout is bridged and a
                                       # jittering centre is smoothed
```
