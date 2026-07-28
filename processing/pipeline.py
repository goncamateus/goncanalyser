"""Pure OpenCV image processing. No Qt, no threads, no widgets.

Keeping this module Qt-free is deliberate: every function here can be exercised
from a plain script or a test without spinning up a QApplication, and the GUI
layer stays a thin shell that only moves values around.

The GUI describes what it wants with a single frozen `Settings` bundle and calls
`Pipeline.process()`. Everything stateful (the background model) lives inside
`Pipeline`, so the caller never has to remember to reset anything.

Processing order for one frame:

    raw BGR frame
      -> basic adjustments (brightness / contrast / saturation / gamma)
      -> background subtraction (optional; replaces the frame with the motion
         mask, or with the colour frame masked down to the moving pixels)
      -> contour finding (optional; detected on whatever the previous stage
         produced, drawn on top so the outlines survive)
      -> colour space view (last, so it never changes what the detectors saw)
"""

from dataclasses import dataclass, replace
from functools import lru_cache

import cv2
import numpy as np

# Label -> OpenCV conversion code. `None` means "leave it as BGR".
# Order matters: the GUI combo box is built from these keys.
COLOR_SPACES: dict[str, int | None] = {
    "Default (BGR)": None,
    "Grayscale": cv2.COLOR_BGR2GRAY,
    "HSV": cv2.COLOR_BGR2HSV,
    "LAB": cv2.COLOR_BGR2LAB,
}

CONTOUR_COLOR = (0, 255, 255)  # BGR yellow — readable on both grey masks and colour frames


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
    color_space: str = "Default (BGR)"  # key into COLOR_SPACES

    # --- Section B: contour finding ---
    contours_on: bool = False
    blur_kernel: int = 5  # Gaussian kernel; forced odd and >= 1 before use
    canny_lo: int = 50
    canny_hi: int = 150
    min_area: int = 200  # contours smaller than this are dropped

    # --- Section C: background subtraction ---
    bgsub_on: bool = False
    bgsub_knn: bool = False  # False = MOG2, True = KNN
    history: int = 500  # frames the model remembers
    var_threshold: float = 16.0  # MOG2 varThreshold / KNN dist2Threshold
    learning_rate: float = -1.0  # passed to .apply(); -1 = let OpenCV decide
    mask_only: bool = True  # True = show the B/W motion mask, False = foreground


@lru_cache(maxsize=64)
def gamma_lut(gamma: float) -> np.ndarray:
    """256-entry gamma curve. Cached — rebuilding it per frame is pure waste."""
    return np.clip((np.arange(256) / 255.0) ** (1.0 / gamma) * 255, 0, 255).astype(np.uint8)


def adjust(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """Brightness, contrast, saturation and gamma.

    Each stage is skipped when its knob sits at identity, so an untouched panel
    costs nothing per frame. Nothing is written in place — the caller's frame may
    be reused (e.g. re-rendered while paused), so it must stay pristine.
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


def find_contours(bgr: np.ndarray, s: Settings) -> list[np.ndarray]:
    """Blur -> Canny -> external contours -> drop the ones under `min_area`.

    Only the outermost contours are kept: a region with a hole in it is still one
    region, and the hole is rarely what you are counting.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    k = odd_kernel(s.blur_kernel)
    if k > 1:
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    edges = cv2.Canny(gray, s.canny_lo, s.canny_hi)
    found, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [c for c in found if cv2.contourArea(c) >= s.min_area]


def draw_contours(bgr: np.ndarray, contours: list[np.ndarray]) -> np.ndarray:
    """Outlines drawn onto a copy — never into a frame someone else may reuse."""
    if not contours:
        return bgr
    out = bgr.copy()
    cv2.drawContours(out, contours, -1, CONTOUR_COLOR, 2)
    return out


class BackgroundModel:
    """MOG2/KNN wrapper that rebuilds itself when a constructor knob changes.

    `history` and `varThreshold` can only be set when the subtractor is created,
    so this tracks the values it was built with and transparently re-creates the
    model when the GUI moves either slider. That resets the learned background,
    which is the honest behaviour: the old model was trained under settings the
    user just rejected.
    """

    def __init__(self) -> None:
        self._sub = None
        self._built_with: tuple | None = None

    def reset(self) -> None:
        """Forget the learned background; it re-seeds from the next frame on."""
        self._sub = None
        self._built_with = None

    def _ensure(self, s: Settings) -> None:
        signature = (s.bgsub_knn, int(s.history), float(s.var_threshold))
        if self._sub is not None and self._built_with == signature:
            return
        knn, history, var = signature
        self._sub = (
            # KNN calls the same knob dist2Threshold — the distance at which a
            # pixel counts as "not background". Same role, different name.
            cv2.createBackgroundSubtractorKNN(history=history, dist2Threshold=var)
            if knn
            else cv2.createBackgroundSubtractorMOG2(history=history, varThreshold=var)
        )
        self._built_with = signature

    def apply(self, bgr: np.ndarray, s: Settings) -> np.ndarray:
        """Motion mask (B/W) or the foreground (mask applied to the colour frame)."""
        self._ensure(s)
        mask = self._sub.apply(bgr, learningRate=s.learning_rate)
        if s.mask_only:
            return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        # MOG2 marks shadows as 127 and they survive `bitwise_and`, which is what
        # you want: a shadowed part of a moving object is still the moving object.
        return cv2.bitwise_and(bgr, bgr, mask=mask)


class Pipeline:
    """The whole per-frame chain, plus the one piece of state it needs.

    One instance lives on the worker thread. `process()` is the only entry point.
    """

    def __init__(self) -> None:
        self.background = BackgroundModel()

    def reset_background(self) -> None:
        self.background.reset()

    def process(self, bgr: np.ndarray, s: Settings) -> tuple[np.ndarray, int]:
        """Run the chain. Returns the displayable frame and the contour count."""
        frame = adjust(bgr, s)

        if s.bgsub_on:
            frame = self.background.apply(frame, s)

        count = 0
        if s.contours_on:
            contours = find_contours(frame, s)
            count = len(contours)
            frame = draw_contours(frame, contours)

        # Last, so the colour space view is purely cosmetic and never feeds back
        # into what the detectors above measured.
        return to_color_space(frame, s.color_space), count


def _demo() -> None:
    """Smallest runnable check: the chain survives every toggle on a fake frame."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (60, 50), (255, 255, 255), -1)  # something to find

    pipe = Pipeline()
    base = Settings()

    out, n = pipe.process(frame, base)
    assert out.shape == frame.shape and n == 0, "defaults must be a passthrough"
    assert (out == frame).all(), "identity settings must not touch the pixels"

    tuned = replace(base, brightness=20, contrast=1.5, saturation=1.2, gamma=0.8)
    assert pipe.process(frame, tuned)[0].shape == frame.shape

    for name in COLOR_SPACES:
        out, _ = pipe.process(frame, replace(base, color_space=name))
        assert out.ndim == 3 and out.shape[2] == 3, f"{name} must stay displayable"

    # A zero kernel used to crash GaussianBlur; the clamp is what stops it.
    assert odd_kernel(0) == 1 and odd_kernel(4) == 5
    _, n = pipe.process(frame, replace(base, contours_on=True, blur_kernel=0, min_area=1))
    assert n > 0, "the white rectangle should produce at least one contour"

    # Background subtraction needs a few frames before it reports anything sane;
    # what matters here is that both models build and both view modes come back.
    for knn in (False, True):
        s = replace(base, bgsub_on=True, bgsub_knn=knn, learning_rate=0.5)
        for _ in range(3):
            assert pipe.process(frame, s)[0].shape == frame.shape
        assert pipe.process(frame, replace(s, mask_only=False))[0].shape == frame.shape

    print("pipeline ok")


if __name__ == "__main__":
    _demo()
