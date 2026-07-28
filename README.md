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
    contours.py             B: blur, Canny thresholds, min area
    background.py           C: model choice, history, varThreshold, learning rate
processing/
  video_thread.py           QThread: decode, process, emit QImages
  pipeline.py               the OpenCV chain -- no Qt, importable on its own
  motion.py                 moving-camera background subtraction
```

## Frame chain

    raw frame -> adjustments -> background subtraction -> contours -> colour space

Contours run *after* background subtraction and are traced on the motion mask
itself, so the two view modes report the same regions and the Min area filter
measures the moving blob. With subtraction off they fall back to Canny edges of
the adjusted frame. The colour space conversion happens last, so switching to
HSV changes what you see and never what was measured.

## Settings cache

The panel's state is written on quit and restored on the next launch, to the
per-platform config directory Qt nominates (`~/Library/Preferences/video-tuner/`
on macOS, `~/.config/video-tuner/` on Linux). Delete `settings.json` there to get
the defaults back. A missing or corrupt file is ignored rather than fatal, and a
cache written before a knob existed still loads — the missing field keeps its
default.

## Background subtraction on a moving camera

MOG2 and KNN model *this pixel* over time, so they only work when the pixel grid
is nailed to the world. Under a drone every pixel changes and they charge the
camera's own motion to the foreground -- on `voo_1.mp4` they call 15 % and 61 %
of the frame moving, which is the whole plant outlined in white.

The third model, **Compensated (moving camera)**, estimates the frame-to-frame
camera warp (sparse Lucas-Kanade, ORB or ECC) and warps its background model to
follow it before comparing. Same clip: 1.4 % foreground, and it is the plume.
It is a numpy port of the dual-mode SGM with age from Yi et al., CVPRW 2013,
["Detection of Moving Objects with Non-Stationary Cameras in 5.8ms"](https://www.cv-foundation.org/openaccess/content_cvpr_workshops_2013/W03/papers/Yi_Detection_of_Moving_2013_CVPR_paper.pdf)
([reference C++](https://github.com/kmyid/fastMCD)) -- an apparent and a
candidate Gaussian per block, so something lingering over one spot keeps
resetting the candidate instead of being learned as background. ~5 ms/frame at
960x540.

Two things to know when tuning it:

* **Keep History short.** Once camera motion is cancelled, a plume venting from
  a fixed spot is *stationary*, and a long history will learn it. What still
  gives it away is that it churns.
* **The anchored stem is invisible to it.** The base of the jet is clipped white
  in every frame, so its temporal residual is zero. This finds the churning
  head, not the column.

## Threading

`VideoThread` owns the capture and the pipeline. The GUI sends it settings by
rebinding one frozen dataclass (atomic, no lock) and gets finished QImages back
through signals, so decoding never blocks the widgets.

## Keys

`space` play/pause . `.` step forward . `,` step back

## Check

```bash
uv run python -m processing.pipeline   # asserts the chain over every toggle
uv run python -m processing.motion     # asserts detection under a synthetic pan
```
