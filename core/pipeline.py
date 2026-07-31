"""The per-frame chain. Pure OpenCV — no Qt, no threads, no widgets.

Keeping this Qt-free is deliberate: every function here can be exercised from a
plain script or a test without spinning up a QApplication, and the GUI layer
stays a thin shell that only moves values around.

One frame runs through it once, and that single run feeds the viewer, the status
bar and the report export. Nothing is computed twice and nothing gets a second
code path.

    adjust -> structure -> keypoints -> texture -> colour

Each feature contributes to three collectors on a `Result`:

* **canvases** — whole-frame images it can offer as *the* view ("Edges", "HOG"…).
* **ops** — callables that paint geometry (keypoints, contours, lines) onto
  whichever canvas the user picked, so overlays compose with any view.
* **metrics** — plain numbers, which are what the status bar shows and the report
  summarises per frame.
* **rows** — per-object detail (one dict per contour, keypoint, blob). Kept apart
  from `metrics` because these are what the CSV export writes, and a status bar
  cannot show four hundred contours.

Splitting canvases from ops is what makes "Canny view with SIFT keypoints drawn
on top" work without either feature knowing the other exists.
"""

from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from features import adjust, color, keypoints, motion, structure, texture

from .settings import VIEWS, Settings

ROI_COLOR = (0, 255, 255)  # the outline drawn around an active region


@dataclass
class Result:
    """The three collectors every feature writes into."""

    canvases: dict[str, np.ndarray] = field(default_factory=dict)
    ops: list = field(default_factory=list)  # each is (canvas) -> None
    metrics: dict = field(default_factory=dict)
    rows: dict[str, list[dict]] = field(default_factory=dict)
    roi: tuple[int, int, int, int] | None = None  # (x, y, w, h) in frame pixels


# Fixed order. Adjust runs first and separately — it produces the frame the rest
# read. Motion is next so its overlay ends up *under* the detectors' — a heatmap
# painted last would bury every box drawn before it. Colour is last only because
# it is the one feature that reads the frame and draws nothing on it.
FEATURES = (motion, structure, keypoints, texture, color)


# Row keys that hold a coordinate, so a region's results can be reported in frame
# space. Everything else a feature emits — `bin`, `code`, `area`, `response` —
# is not a position and must be left alone.
X_KEYS = ("x", "x1", "x2")
Y_KEYS = ("y", "y1", "y2")


def analyse(bgr: np.ndarray, s: Settings, state=None) -> Result:
    """Run every enabled feature over one frame. No compositing, no drawing.

    `state` is a `motion.MotionState` belonging to whoever is driving the frames —
    the one thing in the chain that cannot be recomputed from this frame alone.
    Every feature takes it and only `motion` reads it, which keeps this loop a
    single line and keeps the special case out of the middle of it. `None` means
    "one frame, on its own", which is what every still-image caller means.
    """
    out = Result()
    frame = adjust.run(bgr, s, out)
    for module in FEATURES:
        module.run(frame, s, out, state)

    if out.roi is not None:
        # The features measured a cropped frame, so every coordinate they
        # produced is region-relative. Exports would be silently wrong otherwise
        # — a keypoint at (5, 5) of the region is not at (5, 5) of the frame, and
        # nothing in the CSV would say so. Done after the ops are built, so the
        # overlays, which draw on the region, are unaffected.
        x, y, _, _ = out.roi
        for rows in out.rows.values():
            for row in rows:
                for key in X_KEYS:
                    if key in row:
                        row[key] += x
                for key in Y_KEYS:
                    if key in row:
                        row[key] += y
    return out


def composite(out: Result, s: Settings) -> np.ndarray:
    """The chosen canvas with every overlay painted on it.

    Separate from `analyse` because the worker and the report exporter both need
    the metrics *and* the picture, and running the chain twice to get both would
    double the cost of the one expensive thing in the app.
    """
    # Fall back rather than fail: holding a view whose feature was just switched
    # off is normal, and blanking the viewer for it is worse than showing source.
    canvas = out.canvases.get(s.view, out.canvases["Source"]).copy()
    for op in out.ops:
        op(canvas)

    if out.roi is None:
        return canvas
    x, y, w, h = out.roi
    # The Histogram plot is 512x256 whatever the region is, so it is shown as
    # itself rather than squeezed into a rectangle it does not fit.
    if canvas.shape[:2] != (h, w):
        return canvas
    # Compositing the region first and pasting after is what avoids translating
    # every overlay: the ops already drew at region coordinates, and this moves
    # all of them at once.
    frame = out.canvases["Full"].copy()
    frame[y : y + h, x : x + w] = canvas
    cv2.rectangle(frame, (x, y), (x + w - 1, y + h - 1), ROI_COLOR, 1)
    return frame


def process(bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, dict]:
    """Run the chain and composite. Returns (frame to display, metrics)."""
    out = analyse(bgr, s)
    return composite(out, s), out.metrics


def summarise(metrics: dict) -> str:
    """One status-bar line. Empty when nothing is switched on."""
    return "  ".join(f"{k}={v}" for k, v in metrics.items())


def _roi_demo() -> None:
    """The region must be analysed in isolation, and reported in frame space."""
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (60, 40), (100, 80), (255, 255, 255), -1)
    rect = (40, 20, 80, 70)  # x, y, w, h — contains the white square
    x, y, w, h = rect

    # Otsu and a blur are exactly the two operators that leak: Otsu takes its
    # level from whatever histogram it is handed, and a blur reads neighbours
    # across the border. Anything analysed on the full frame and cropped after
    # would fail this.
    roi_on = Settings(
        roi_on=True, roi_x=x, roi_y=y, roi_w=w, roi_h=h,
        threshold_kind="Otsu", blur_kind="Gaussian", blur=5,
        edge_kind="Canny", contours_on=True, detector="ORB", corner_kind="Harris",
    )

    scribbled = np.zeros_like(frame)  # obliterate everything…
    scribbled[y : y + h, x : x + w] = frame[y : y + h, x : x + w]  # …but the region
    assert analyse(frame, roi_on).metrics == analyse(scribbled, roi_on).metrics, (
        "pixels outside the region changed the numbers"
    )

    # The negative, or the assert above would also pass for a chain that ignores
    # its input entirely.
    roi_off = replace(roi_on, roi_on=False)
    assert analyse(frame, roi_off).metrics != analyse(scribbled, roi_off).metrics

    # A region covering the whole frame must be the same as no region at all.
    # Catches an off-by-one in the crop, the paste or the row translation.
    whole = replace(roi_on, roi_x=0, roi_y=0, roi_w=0, roi_h=0)
    assert analyse(frame, whole).metrics == analyse(frame, roi_off).metrics
    assert analyse(frame, whole).rows == analyse(frame, roi_off).rows

    # Compositing puts the region back where it came from, at full frame size.
    out, _ = process(frame, roi_on)
    assert out.shape == frame.shape, out.shape
    # Outside the rectangle the raw frame shows through untouched, apart from the
    # one-pixel outline drawn on its border.
    assert (out[: y - 1, :] == frame[: y - 1, :]).all(), "the surround was processed"

    # The rows come back in frame coordinates, so they land inside the rectangle.
    for row in analyse(frame, roi_on).rows["keypoints"]:
        assert x <= row["x"] < x + w and y <= row["y"] < y + h, row

    # Every view stays displayable with a region active, including the one canvas
    # that is not frame-shaped.
    for view in VIEWS:
        got, _ = process(frame, replace(roi_on, view=view))
        assert got.ndim == 3 and got.shape[2] == 3, view
    assert process(frame, replace(roi_on, view="Histogram"))[0].shape[:2] == (256, 512)

    # A rectangle from a bigger source is fitted, not fatal: it degrades to the
    # whole frame rather than the 1x1 sliver a naive clamp would leave.
    huge = replace(roi_on, roi_x=5000, roi_y=5000, roi_w=9000, roi_h=9000)
    assert process(frame, huge)[0].shape == frame.shape
    assert analyse(frame, huge).roi == (0, 0, 160, 120)

    # A stray one-pixel drag is widened to something the detectors can work on,
    # and slid back inside the frame rather than left hanging off the edge.
    speck = replace(roi_on, roi_x=158, roi_y=118, roi_w=1, roi_h=1)
    rx, ry, rw, rh = analyse(frame, speck).roi
    assert (rw, rh) == (16, 16) and rx + rw <= 160 and ry + rh <= 120, (rx, ry, rw, rh)
    assert process(frame, speck)[0].shape == frame.shape

    print("  roi ok")


def _demo() -> None:
    """The chain survives every view and every feature toggle on a fake frame."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (60, 50), (255, 255, 255), -1)  # something to find
    base = Settings()

    out, metrics = process(frame, base)
    assert (out == frame).all(), "identity settings must not touch the pixels"
    assert not analyse(frame, base).ops, "nothing switched on must draw nothing"
    # Colour statistics are the exception to "off by default" — they are always
    # measured, because three calcHist calls are cheaper than the checkbox.
    assert set(metrics) == {f"{c}_{k}" for c in "BGR" for k in ("mean", "sd")}, metrics

    # Every view must render, whether or not its feature is on — the fallback is
    # what makes toggling a feature off while looking at its view survivable.
    for view in VIEWS:
        out, _ = process(frame, replace(base, view=view))
        assert out.ndim == 3 and out.shape[2] == 3, f"{view} is not displayable"

    # Everything on at once: the collectors must not collide.
    everything = replace(
        base,
        view="Edges",
        edge_kind="Canny",
        hough_kind="Lines",
        corner_kind="Harris",
        contours_on=True,
        blobs_on=True,
        detector="ORB",
        hog_on=True,
        lbp_on=True,
    )
    out, metrics = process(frame, everything)
    assert out.shape == frame.shape, "an overlay resized the frame"
    assert metrics, "everything on must measure something"
    assert summarise(metrics)

    # Overlays compose with any canvas, which is the whole point of splitting
    # `ops` from `canvases`.
    for view in VIEWS:
        assert process(frame, replace(everything, view=view))[0].ndim == 3, view

    _roi_demo()
    print("pipeline ok")


if __name__ == "__main__":
    _demo()
