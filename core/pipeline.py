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

import numpy as np

from features import adjust, color, keypoints, structure, texture

from .settings import VIEWS, Settings


@dataclass
class Result:
    """The three collectors every feature writes into."""

    canvases: dict[str, np.ndarray] = field(default_factory=dict)
    ops: list = field(default_factory=list)  # each is (canvas) -> None
    metrics: dict = field(default_factory=dict)
    rows: dict[str, list[dict]] = field(default_factory=dict)


# Fixed order. Adjust runs first and separately — it produces the frame the rest
# read. Colour is last only because it is the one feature that reads the frame
# and draws nothing on it.
FEATURES = (structure, keypoints, texture, color)


def analyse(bgr: np.ndarray, s: Settings) -> Result:
    """Run every enabled feature over one frame. No compositing, no drawing."""
    out = Result()
    frame = adjust.run(bgr, s, out)
    for module in FEATURES:
        module.run(frame, s, out)
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
    return canvas


def process(bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, dict]:
    """Run the chain and composite. Returns (frame to display, metrics)."""
    out = analyse(bgr, s)
    return composite(out, s), out.metrics


def summarise(metrics: dict) -> str:
    """One status-bar line. Empty when nothing is switched on."""
    return "  ".join(f"{k}={v}" for k, v in metrics.items())


def _demo() -> None:
    """The chain survives every view and every feature toggle on a fake frame."""
    import cv2

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

    print("pipeline ok")


if __name__ == "__main__":
    _demo()
