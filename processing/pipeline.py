"""Pure OpenCV image processing. No Qt, no threads, no widgets.

Keeping this module Qt-free is deliberate: every function here can be exercised
from a plain script or a test without spinning up a QApplication, and the GUI
layer stays a thin shell that only moves values around.

The GUI describes what it wants with a single frozen `Settings` bundle and calls
`Pipeline.process()`. Everything stateful (the background model) lives inside
`Pipeline`, so the caller never has to remember to reset anything.

Processing order for one frame:

    raw BGR frame
      -> basic adjustments (brightness / contrast / saturation / gamma / blur)
      -> background subtraction (optional; replaces the frame with the motion
         mask, or with the colour frame masked down to the moving pixels)
      -> edge detection (optional; run on whatever the previous stage produced,
         painted on top or shown on its own)
      -> colour space view (last, so it never changes what the detectors saw)
"""

from dataclasses import dataclass, replace
from functools import lru_cache

import cv2
import numpy as np

from .motion import CompensatedSGM, GlobalMotion

# Label -> OpenCV conversion code. `None` means "leave it as BGR".
# Order matters: the GUI combo box is built from these keys.
COLOR_SPACES: dict[str, int | None] = {
    "Default (BGR)": None,
    "Grayscale": cv2.COLOR_BGR2GRAY,
    "HSV": cv2.COLOR_BGR2HSV,
    "LAB": cv2.COLOR_BGR2LAB,
}

EDGE_COLOR = (0, 255, 255)  # BGR yellow — readable on both grey masks and colour frames

# Background subtraction models, in the order the GUI lists them. The first two
# assume the camera is bolted down; only the third survives a moving one.
BG_MODELS = ("MOG2", "KNN", "Compensated (moving camera)")
COMPENSATED = BG_MODELS[2]


@dataclass(frozen=True)
class Settings:
    """Every knob in the control panel, as one immutable bundle.

    Frozen on purpose. The GUI thread never mutates a `Settings` the worker is
    reading; it builds a whole new one and rebinds a single attribute, which is
    atomic in CPython. The worker therefore always sees a self-consistent set of
    values and neither side needs a lock.
    """

    # --- Section A: basic adjustments ---
    brightness: int = 0  # additive offset, -100..100
    contrast: float = 1.0  # multiplicative gain, 1.0 = identity
    saturation: float = 1.0  # HSV S channel gain, 1.0 = identity
    gamma: float = 1.0  # 1.0 = identity, <1 darkens, >1 brightens
    blur: int = 0  # Gaussian denoise kernel; 0 or 1 = off
    color_space: str = "Default (BGR)"  # key into COLOR_SPACES

    # --- Section B: edge detection ---
    edges_on: bool = False
    blur_kernel: int = 5  # Gaussian kernel; forced odd and >= 1 before use
    canny_lo: int = 50
    canny_hi: int = 150
    edges_only: bool = False  # True = show the raw edge map, False = overlay it

    # --- Section C: background subtraction ---
    bgsub_on: bool = False
    bg_model: str = "MOG2"  # key into BG_MODELS
    history: int = 500  # frames the model remembers (the SGM's age cap)
    var_threshold: float = 16.0  # MOG2 varThreshold / KNN dist2Threshold / SGM theta^2
    learning_rate: float = -1.0  # passed to .apply(); -1 = let the model decide
    mask_only: bool = True  # True = show the B/W motion mask, False = foreground
    # Compensated model only — ignored by MOG2 and KNN.
    gmc_method: str = "flow"  # how camera motion is estimated; see motion.GMC_METHODS
    gmc_homography: bool = False  # False = 4-dof similarity, True = full homography
    block: int = 4  # model resolution: one Gaussian per block x block pixels
    edge_tolerance: float = 1.5  # px of parallax slack, charged per unit of gradient
    min_age: int = 10  # frames a cell must be modelled before it may report


@lru_cache(maxsize=64)
def gamma_lut(gamma: float) -> np.ndarray:
    """256-entry gamma curve. Cached — rebuilding it per frame is pure waste."""
    return np.clip((np.arange(256) / 255.0) ** (1.0 / gamma) * 255, 0, 255).astype(np.uint8)


def adjust(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """Brightness, contrast, saturation, gamma and a denoise blur.

    Each stage is skipped when its knob sits at identity, so an untouched panel
    costs nothing per frame. Nothing is written in place — the caller's frame may
    be reused (e.g. re-rendered while paused), so it must stay pristine.

    The blur is last and it is not cosmetic: everything downstream reads this
    frame, so it is the one knob here that quiets sensor noise for the detectors
    rather than only for your eyes. It is a different kernel from the edge
    section's, which blurs again just before edge detection.
    """
    out = bgr
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
    k = odd_kernel(s.blur)
    if k > 1:
        out = cv2.GaussianBlur(out, (k, k), 0)
    return out


def to_color_space(bgr: np.ndarray, name: str) -> np.ndarray:
    """The chosen colour space, always as a 3-channel image a QLabel can show.

    HSV and LAB come out as false colour — plotting H as blue is not meaningful,
    it is simply what the raw channels look like, which is the point of the view.
    """
    code = COLOR_SPACES.get(name)
    if code is None:
        return bgr
    converted = cv2.cvtColor(bgr, code)
    if converted.ndim == 2:  # grayscale: widen back to 3 channels for display
        return cv2.cvtColor(converted, cv2.COLOR_GRAY2BGR)
    return converted


def odd_kernel(size: int) -> int:
    """Nearest valid Gaussian kernel size: odd and at least 1.

    cv2.GaussianBlur throws on even or zero kernels, and a slider can absolutely
    be dragged to either, so clamp here rather than trusting the widget's range.
    """
    size = max(1, int(size))
    return size if size % 2 else size + 1


def find_edges(img: np.ndarray, s: Settings) -> np.ndarray:
    """Blur, then Canny. Returns the edge map (uint8, 0 or 255).

    The blur is what makes the thresholds mean anything: Canny differentiates,
    and differentiating raw sensor noise produces edges everywhere. Kernel and
    both thresholds are the section's three knobs.

    Works on a colour frame or on a single-channel mask. On a mask the result is
    each blob's rim, which is the useful thing to look at when the previous stage
    was background subtraction.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    k = odd_kernel(s.blur_kernel)
    if k > 1:
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    return cv2.Canny(gray, s.canny_lo, s.canny_hi)


def draw_edges(bgr: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Edges painted onto a copy — never into a frame someone else may reuse.

    Boolean indexing rather than `drawContours`: there are no contours here, just
    a pixel map, and painting it directly keeps every single-pixel edge Canny
    found instead of only the ones that close into a loop.
    """
    out = bgr.copy()
    out[edges > 0] = EDGE_COLOR
    return out


class BackgroundModel:
    """Whichever subtractor the settings ask for, rebuilt when its knobs change.

    Every model here takes `history` and `var_threshold` at construction time
    only, so this tracks the values it was built with and transparently
    re-creates the model when the GUI moves a slider. That resets the learned
    background, which is the honest behaviour: the old model was trained under
    settings the user just rejected.

    MOG2 and KNN model a fixed pixel grid. The compensated model estimates the
    camera motion and warps its own model to follow it — see `motion.py` for why
    that is the only one of the three that works on drone footage.
    """

    def __init__(self) -> None:
        self._sub = None
        self._gmc: GlobalMotion | None = None
        self._prev_gray: np.ndarray | None = None
        self._built_with: tuple | None = None

    def reset(self) -> None:
        """Forget the learned background; it re-seeds from the next frame on."""
        self._sub = None
        self._gmc = None
        self._prev_gray = None
        self._built_with = None

    def _ensure(self, s: Settings) -> None:
        signature = (
            s.bg_model,
            int(s.history),
            float(s.var_threshold),
            # The rest only exist on the compensated model; including them
            # unconditionally is harmless and keeps the tuple flat.
            s.gmc_method,
            s.gmc_homography,
            int(s.block),
            float(s.edge_tolerance),
            int(s.min_age),
            float(s.learning_rate),
        )
        if self._sub is not None and self._built_with == signature:
            return
        self._built_with = signature
        self._prev_gray = None

        if s.bg_model == COMPENSATED:
            self._gmc = GlobalMotion(method=s.gmc_method, homography=s.gmc_homography)
            self._sub = CompensatedSGM(
                block=s.block,
                history=s.history,
                var_threshold=s.var_threshold,
                learning_rate=s.learning_rate,
                edge_tolerance=s.edge_tolerance,
                min_age=s.min_age,
            )
        elif s.bg_model == "KNN":
            # KNN calls the same knob dist2Threshold — the distance at which a
            # pixel counts as "not background". Same role, different name.
            self._sub = cv2.createBackgroundSubtractorKNN(
                history=int(s.history), dist2Threshold=float(s.var_threshold)
            )
        else:
            self._sub = cv2.createBackgroundSubtractorMOG2(
                history=int(s.history), varThreshold=float(s.var_threshold)
            )

    def _mask(self, bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, str]:
        """The raw foreground mask, plus a note for the status bar."""
        if s.bg_model != COMPENSATED:
            return self._sub.apply(bgr, learningRate=s.learning_rate), ""

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        warp, inliers = (
            self._gmc.estimate(self._prev_gray, gray)
            if self._prev_gray is not None
            else (np.eye(3, dtype=np.float32), 0)
        )
        self._prev_gray = gray
        # A failed estimate silently becomes an identity warp, which looks exactly
        # like a broken model on screen. Say so instead.
        note = f" gmc={inliers}in" if inliers else " gmc=NONE"
        return self._sub.apply(gray, warp), note

    def apply(self, bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, np.ndarray, str]:
        """(what to display, the raw mask, a note).

        The mask comes back alongside the rendering because the edge stage
        wants the blobs themselves, not whatever the view mode chose to paint.
        """
        self._ensure(s)
        mask, note = self._mask(bgr, s)
        if s.mask_only:
            return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), mask, note
        # MOG2 marks shadows as 127 and they survive `bitwise_and`, which is what
        # you want: a shadowed part of a moving object is still the moving object.
        return cv2.bitwise_and(bgr, bgr, mask=mask), mask, note


class Pipeline:
    """The whole per-frame chain, plus the one piece of state it needs.

    One instance lives on the worker thread. `process()` is the only entry point.
    """

    def __init__(self) -> None:
        self.background = BackgroundModel()

    def reset_background(self) -> None:
        self.background.reset()

    def process(self, bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, str]:
        """Run the chain. Returns the displayable frame and a note for the status bar.

        The note is a string rather than a count because the stages have
        different things worth reporting — and a camera-motion estimate that
        failed has to be visible, since it looks identical to a working one.
        """
        frame = adjust(bgr, s)

        note, mask = "", None
        if s.bgsub_on:
            frame, mask, note = self.background.apply(frame, s)

        if s.edges_on:
            # Read the mask, not the rendering. In the Foreground view the frame
            # is a colour cut-out, so Canny on it would find the cut-out's border
            # and every bit of texture inside it rather than the moving regions.
            edges = find_edges(mask if mask is not None else frame, s)
            frame = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR) if s.edges_only else draw_edges(
                frame, edges
            )
            note += f" edges={(edges > 0).mean():.1%}"

        # Last, so the colour space view is purely cosmetic and never feeds back
        # into what the detectors above measured.
        return to_color_space(frame, s.color_space), note


def _demo() -> None:
    """Smallest runnable check: the chain survives every toggle on a fake frame."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (60, 50), (255, 255, 255), -1)  # something to find

    pipe = Pipeline()
    base = Settings()

    out, note = pipe.process(frame, base)
    assert out.shape == frame.shape and note == "", "defaults must be a passthrough"
    assert (out == frame).all(), "identity settings must not touch the pixels"

    tuned = replace(base, brightness=20, contrast=1.5, saturation=1.2, gamma=0.8)
    assert pipe.process(frame, tuned)[0].shape == frame.shape

    # Blur off means *off*, not a 1x1 kernel copy — the identity check above is
    # what the paused-frame cache relies on.
    assert (pipe.process(frame, replace(base, blur=1))[0] == frame).all()
    smoothed = pipe.process(frame, replace(base, blur=5))[0]
    assert smoothed.shape == frame.shape and not (smoothed == frame).all()

    for name in COLOR_SPACES:
        out, _ = pipe.process(frame, replace(base, color_space=name))
        assert out.ndim == 3 and out.shape[2] == 3, f"{name} must stay displayable"

    # A zero kernel used to crash GaussianBlur; the clamp is what stops it.
    assert odd_kernel(0) == 1 and odd_kernel(4) == 5
    edged, note = pipe.process(frame, replace(base, edges_on=True, blur_kernel=0))
    assert "edges=" in note and "edges=0.0%" not in note, note
    assert (edged == EDGE_COLOR).all(axis=2).any(), "the overlay must paint something"

    # Edges-only replaces the picture rather than painting over it.
    only, _ = pipe.process(frame, replace(base, edges_on=True, edges_only=True))
    assert set(np.unique(only)) <= {0, 255}, "the edge map view must stay binary"

    # A mask arrives single-channel: Canny must trace the blob's rim, not crash.
    blob = np.zeros((64, 96), np.uint8)
    blob[10:50, 20:70] = 255
    rim = find_edges(blob, replace(base, blur_kernel=0))
    assert rim[10, 20:70].any(), "the blob's top edge should be found"
    assert not rim[30, 45], "the blob's interior is flat, so it is not an edge"

    # Background subtraction needs a few frames before it reports anything sane;
    # what matters here is that every model builds and both view modes come back.
    for name in BG_MODELS:
        s = replace(base, bgsub_on=True, bg_model=name, learning_rate=0.5)
        for _ in range(3):
            assert pipe.process(frame, s)[0].shape == frame.shape
        assert pipe.process(frame, replace(s, mask_only=False))[0].shape == frame.shape
    # Only the compensated model reports a camera-motion estimate.
    assert "gmc=" in pipe.process(frame, replace(base, bgsub_on=True, bg_model=COMPENSATED))[1]

    print("pipeline ok")


if __name__ == "__main__":
    _demo()
