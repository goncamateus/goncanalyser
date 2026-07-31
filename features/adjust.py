"""Preprocessing: the frame every other feature reads.

Runs in a fixed order, and each stage is skipped when its knob sits at identity,
so an untouched panel costs nothing per frame. Nothing is written in place — the
caller's frame is reused whenever a paused frame is re-rendered, so it must stay
pristine.

    brightness/contrast -> saturation -> gamma -> colour space -> blur -> threshold

The colour space conversion is *not* cosmetic here: it lands before the blur and
the threshold, so everything downstream — edges, keypoints, texture — measures
the space you picked. Running SIFT on the LAB rendering is a thing you may
legitimately want, and this is a workspace for trying that.

This module also owns the small shared helpers (`odd_kernel`, `to_gray`,
`to_bgr`) because they are all about kernels and colour, and putting them here
means `features/*` never has to import from `core`, which would be a cycle.
"""

from dataclasses import replace
from functools import lru_cache

import cv2
import numpy as np

from core.settings import Settings

# Label -> OpenCV conversion code. `None` means "leave it as BGR".
# Order matters: the combo box is built from these keys.
COLOR_SPACES: dict[str, int | None] = {
    "BGR": None,
    "Grayscale": cv2.COLOR_BGR2GRAY,
    "HSV": cv2.COLOR_BGR2HSV,
    "LAB": cv2.COLOR_BGR2LAB,
    "HLS": cv2.COLOR_BGR2HLS,
}

BLURS = ("None", "Gaussian", "Median")

THRESHOLDS = (
    "None",
    "Binary",
    "Binary inverted",
    "Otsu",
    "Adaptive mean",
    "Adaptive Gaussian",
)


def odd_kernel(size: int) -> int:
    """Nearest valid kernel size: odd and at least 1.

    GaussianBlur and medianBlur both throw on even or zero kernels, and a slider
    can absolutely be dragged to either, so clamp here rather than trusting the
    widget's range.
    """
    size = max(1, int(size))
    return size if size % 2 else size + 1


def to_gray(img: np.ndarray) -> np.ndarray:
    """Single-channel view of anything. Already-grey input passes straight through."""
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def to_bgr(img: np.ndarray) -> np.ndarray:
    """Three-channel view of anything, so the rest of the chain never branches on ndim."""
    return img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


@lru_cache(maxsize=64)
def gamma_lut(gamma: float) -> np.ndarray:
    """256-entry gamma curve. Cached — rebuilding it per frame is pure waste."""
    return np.clip((np.arange(256) / 255.0) ** (1.0 / gamma) * 255, 0, 255).astype(np.uint8)


def to_color_space(bgr: np.ndarray, name: str) -> np.ndarray:
    """The chosen colour space, always 3-channel so a QLabel can show it.

    HSV, LAB and HLS come out as false colour — plotting H as blue is not
    meaningful, it is simply what the raw channels look like, which is the point
    of the view.
    """
    code = COLOR_SPACES.get(name)
    if code is None:
        return bgr
    return to_bgr(cv2.cvtColor(bgr, code))


def threshold(gray: np.ndarray, s: Settings) -> np.ndarray:
    """Single-channel binary image. Assumes `gray` is already single-channel."""
    value = int(s.threshold)
    if s.threshold_kind == "Binary":
        return cv2.threshold(gray, value, 255, cv2.THRESH_BINARY)[1]
    if s.threshold_kind == "Binary inverted":
        return cv2.threshold(gray, value, 255, cv2.THRESH_BINARY_INV)[1]
    if s.threshold_kind == "Otsu":
        # Otsu picks the level itself, so the slider is ignored on purpose — the
        # tab says so, and leaving the knob live would suggest it does something.
        return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    method = (
        cv2.ADAPTIVE_THRESH_MEAN_C
        if s.threshold_kind == "Adaptive mean"
        else cv2.ADAPTIVE_THRESH_GAUSSIAN_C
    )
    # OpenCV requires an odd block size of at least 3 and throws otherwise.
    block = max(3, odd_kernel(s.adaptive_block))
    return cv2.adaptiveThreshold(gray, 255, method, cv2.THRESH_BINARY, block, 2)


# A region smaller than this is not analysable: SIFT and ORB build a scale
# pyramid and cv2.resize refuses a zero dimension, so a stray 1-px drag would
# take the worker down. Sized in pixels, and small enough never to get in the way.
MIN_ROI = 16


def roi_rect(shape, s: Settings) -> tuple[int, int, int, int] | None:
    """The selected rectangle, fitted to this frame. None when there is not one.

    Fitted rather than trusted, in three ways, because all three happen in normal
    use: a rectangle left over from a 1920x1080 clip has to mean something on a
    640x512 one; a spinbox mid-edit holds a half-typed number; and a stray click
    is a rectangle a few pixels wide.

    So the size is clamped into `MIN_ROI..frame`, and then the origin is pulled
    back far enough for it to fit. Sliding the rectangle in beats shrinking it to
    a sliver, which is what a drag near the edge means anyway. When the frame
    itself is under `MIN_ROI` the whole frame is the region.
    """
    if not s.roi_on:
        return None
    h, w = shape[:2]
    cw = min(w, max(MIN_ROI, w if s.roi_w <= 0 else int(s.roi_w)))
    ch = min(h, max(MIN_ROI, h if s.roi_h <= 0 else int(s.roi_h)))
    x = min(max(0, int(s.roi_x)), w - cw)
    y = min(max(0, int(s.roi_y)), h - ch)
    return (x, y, cw, ch)


def crop(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """The selected rectangle as its own array. A copy, never a view.

    A view would let an overlay drawn on the region write straight through into
    the full frame kept behind it as the display background.
    """
    rect = roi_rect(bgr.shape, s)
    if rect is None:
        return bgr
    x, y, w, h = rect
    return bgr[y : y + h, x : x + w].copy()


def apply(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """The whole preprocessing chain. Always returns a 3-channel BGR-shaped array.

    The crop is **first**, and that ordering is the feature, not an optimisation.
    Cropping last would be cheaper to wire up — the full adjusted frame would
    then be free to use as the display background — but it leaks the surround
    into the numbers two ways: Otsu picks its level from the histogram it is
    given, and the blurs read a kernel's worth of neighbours across the border.
    Both would make the result depend on pixels outside the rectangle.
    """
    out = crop(bgr, s)
    if s.contrast != 1.0 or s.brightness:
        out = cv2.convertScaleAbs(out, alpha=s.contrast, beta=s.brightness)
    if s.saturation != 1.0:
        # split/merge rather than an in-place slice: hsv[:, :, 1] is a
        # non-contiguous view and OpenCV refuses those.
        h, sat, v = cv2.split(cv2.cvtColor(out, cv2.COLOR_BGR2HSV))
        out = cv2.cvtColor(
            cv2.merge((h, cv2.convertScaleAbs(sat, alpha=s.saturation), v)),
            cv2.COLOR_HSV2BGR,
        )
    if s.gamma != 1.0:
        out = cv2.LUT(out, gamma_lut(s.gamma))

    out = to_color_space(out, s.color_space)

    k = odd_kernel(s.blur)
    if k > 1 and s.blur_kind == "Gaussian":
        out = cv2.GaussianBlur(out, (k, k), 0)
    elif k > 1 and s.blur_kind == "Median":
        out = cv2.medianBlur(out, k)

    if s.threshold_kind != "None":
        out = to_bgr(threshold(to_gray(out), s))
    return out


def run(bgr: np.ndarray, s: Settings, out) -> np.ndarray:
    """Fill the preprocessing canvases and hand the chain its working frame.

    "Grayscale" and "Threshold" are offered as views whether or not the combos
    select them, because looking at what the threshold is *about* to do is how
    you set it — that is exactly the frame the contour finder will see.
    """
    frame = apply(bgr, s)
    out.roi = roi_rect(bgr.shape, s)
    if out.roi is not None:
        # The *raw* frame, deliberately unprocessed. It is the background the
        # finished region gets pasted back into, and keeping it out of the
        # analysis path entirely is what makes the isolation guarantee structural
        # rather than something to remember.
        out.canvases["Full"] = bgr
    out.canvases["Source"] = frame
    gray = to_gray(frame)
    out.canvases["Grayscale"] = to_bgr(gray)
    if s.threshold_kind != "None":
        out.canvases["Threshold"] = frame  # the chain already thresholded it
    else:
        out.canvases["Threshold"] = to_bgr(
            threshold(gray, replace(s, threshold_kind="Binary"))
        )
    return frame


def _demo() -> None:
    """Smallest runnable check: identity is a passthrough, every option survives."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    base = Settings()

    # Identity must not touch a single pixel — the worker's paused-frame cache
    # assumes an unchanged Settings redraws to an identical image.
    assert (apply(frame, base) == frame).all(), "defaults must be a passthrough"

    # Blur off means *off*, not a 1x1 kernel copy.
    assert (apply(frame, replace(base, blur_kind="Gaussian", blur=1)) == frame).all()
    for kind in ("Gaussian", "Median"):
        smoothed = apply(frame, replace(base, blur_kind=kind, blur=5))
        assert smoothed.shape == frame.shape and not (smoothed == frame).all(), kind

    # A zero kernel used to crash GaussianBlur; the clamp is what stops it.
    assert odd_kernel(0) == 1 and odd_kernel(4) == 5 and odd_kernel(-3) == 1

    for name in COLOR_SPACES:
        out = apply(frame, replace(base, color_space=name))
        assert out.ndim == 3 and out.shape[2] == 3, f"{name} must stay displayable"

    for kind in THRESHOLDS[1:]:
        out = apply(frame, replace(base, threshold_kind=kind))
        assert out.shape == frame.shape, kind
        assert set(np.unique(out)) <= {0, 255}, f"{kind} must be binary"

    tuned = replace(base, brightness=20, contrast=1.5, saturation=1.2, gamma=0.8)
    assert apply(frame, tuned).shape == frame.shape

    # --- region of interest ---
    assert roi_rect(frame.shape, base) is None, "off means off"
    # frame is 64 tall, 96 wide
    roi = replace(base, roi_on=True, roi_x=10, roi_y=8, roi_w=40, roi_h=30)
    assert roi_rect(frame.shape, roi) == (10, 8, 40, 30)
    out = apply(frame, roi)
    assert out.shape == (30, 40, 3), out.shape
    assert (out == frame[8:38, 10:50]).all(), "the crop is not the rectangle asked for"

    # 0 means out to the edge, so 0/0 is the whole frame.
    assert roi_rect(frame.shape, replace(roi, roi_x=0, roi_y=0, roi_w=0, roi_h=0)) == (
        0, 0, 96, 64,
    )
    assert (apply(frame, replace(roi, roi_x=0, roi_y=0, roi_w=0, roi_h=0)) == frame).all()

    # A copy, not a view: an overlay drawn on the region must not reach through
    # into the full frame kept behind it.
    crop(frame, roi)[:] = 0
    assert frame.any(), "crop returned a view into the caller's frame"

    # Oversized, undersized and off-frame all resolve to something analysable.
    assert roi_rect(frame.shape, replace(roi, roi_w=9000, roi_h=9000)) == (0, 0, 96, 64)
    assert roi_rect(frame.shape, replace(roi, roi_x=95, roi_y=63, roi_w=1, roi_h=1)) == (
        96 - MIN_ROI, 64 - MIN_ROI, MIN_ROI, MIN_ROI,
    )
    tiny = np.zeros((8, 8, 3), np.uint8)  # frame smaller than MIN_ROI
    assert roi_rect(tiny.shape, roi) == (0, 0, 8, 8)

    print("adjust ok")


if __name__ == "__main__":
    _demo()
