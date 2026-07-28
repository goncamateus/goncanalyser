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
    basic.py                A: brightness / contrast / saturation / gamma / colour space
    contours.py             B: blur, Canny thresholds, min area
    background.py           C: MOG2 or KNN, history, varThreshold, learning rate
processing/
  video_thread.py           QThread: decode, process, emit QImages
  pipeline.py               the OpenCV chain -- no Qt, importable on its own
```

## Frame chain

    raw frame -> adjustments -> background subtraction -> contours -> colour space

Detection runs on the adjusted frame, and the colour space conversion happens
last, so switching to HSV changes what you see and never what was measured.

## Threading

`VideoThread` owns the capture and the pipeline. The GUI sends it settings by
rebinding one frozen dataclass (atomic, no lock) and gets finished QImages back
through signals, so decoding never blocks the widgets.

## Keys

`space` play/pause . `.` step forward . `,` step back

## Check

```bash
uv run python -m processing.pipeline   # asserts the chain over every toggle
```
