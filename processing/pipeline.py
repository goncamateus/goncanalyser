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
      -> plume detection (optional; outlines the plume, or shows the temperature
         index the thresholds are actually measuring)
      -> colour space view (last, so it never changes what the detector saw)
"""

from dataclasses import dataclass, fields, replace
from functools import lru_cache

import cv2
import numpy as np

from . import labels, plume

# Label -> OpenCV conversion code. `None` means "leave it as BGR".
# Order matters: the GUI combo box is built from these keys.
COLOR_SPACES: dict[str, int | None] = {
    "Default (BGR)": None,
    "Grayscale": cv2.COLOR_BGR2GRAY,
    "HLS": cv2.COLOR_BGR2HLS,
    "HSV": cv2.COLOR_BGR2HSV,
    "LAB": cv2.COLOR_BGR2LAB,
}

# The single channel each colour space hands the plume detector: (code, index).
# Section A picks one entry here, so the same choice drives what is measured and
# what is displayed — the detector no longer has a colour space of its own.
#
# Each is that space's lightness-like channel, because the detector wants a
# monotone stand-in for temperature. "Default (BGR)" keeps HLS lightness rather
# than mapping to blue: it is the validated proxy (r = 0.96), and the natural
# reading of "default" is "the one that works", not "the raw B plane".
DETECTOR_CHANNELS: dict[str, tuple[int, int]] = {
    "Default (BGR)": (cv2.COLOR_BGR2HLS, 1),  # L
    "Grayscale": (cv2.COLOR_BGR2GRAY, 0),
    "HLS": (cv2.COLOR_BGR2HLS, 1),  # L
    "HSV": (cv2.COLOR_BGR2HSV, 2),  # V
    "LAB": (cv2.COLOR_BGR2LAB, 0),  # L*
}

# What the plume section paints. "Outline" keeps the footage visible underneath,
# which is what you want while dragging a slider; the other two show the detector
# its own inputs and outputs.
PLUME_VIEWS = ("Outline", "Mask", "Temperature index")


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

    # --- Section B: plume detection ---
    # The detector's own knobs live in plume.PlumeConfig; these mirror it field
    # for field, so `plume_config()` below can build one straight from a Settings.
    plume_on: bool = False
    plume_view: str = "Outline"  # key into PLUME_VIEWS
    plume_boxes: bool = True  # draw each source's search region
    p_src: float = 99.0
    sd_min: float = 20.0
    src_close_k: int = 7
    src_min_area: int = 120
    p_hi: float = 99.0
    p_lo: float = 90.0
    sd_plume: float = 8.0
    open_k: int = 3
    close_k: int = 7
    min_area: int = 200
    grow_hot: int = 30
    grow_warm: int = 8
    roi_margin: int = 20


@lru_cache(maxsize=64)
def gamma_lut(gamma: float) -> np.ndarray:
    """256-entry gamma curve. Cached — rebuilding it per frame is pure waste."""
    return np.clip((np.arange(256) / 255.0) ** (1.0 / gamma) * 255, 0, 255).astype(np.uint8)


def adjust(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """Brightness, contrast, saturation, gamma and a denoise blur.

    Each stage is skipped when its knob sits at identity, so an untouched panel
    costs nothing per frame. Nothing is written in place — the caller's frame may
    be reused (e.g. re-rendered while paused), so it must stay pristine.

    None of this is only cosmetic: the background model reads the frame these
    knobs produce, so brightness, contrast, gamma and above all the blur are how
    you clean up the image *before* it is masked.
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


def plume_config(s: Settings) -> plume.PlumeConfig:
    """The detector's config, pulled out of Settings by matching field names.

    Settings mirrors PlumeConfig field for field, so copying by name means adding
    a knob touches the dataclass and the GUI section — never this function.
    """
    names = {f.name for f in fields(plume.PlumeConfig)}
    return plume.PlumeConfig(**{n: getattr(s, n) for n in names})


class Pipeline:
    """The whole per-frame chain.

    Stateless now that the background models are gone: the plume detector reads
    one frame and holds nothing between calls, which is why seeking backwards is
    instant and why a slider change re-renders the paused frame exactly.
    """

    def process(
        self, bgr: np.ndarray, s: Settings, chosen: int | None = None
    ) -> tuple[np.ndarray, str, list]:
        """Run the chain. Returns (frame to display, status note, source centres).

        The centres go back to the GUI so a human can pick one by number and have
        the choice stored as a point in the image. Centres rather than masks:
        they are all the picking needs, and they cost nothing to queue across the
        thread boundary — a per-frame list of masks would not.

        `chosen` is the index already labelled for this frame, drawn ticked.
        """
        # Section A feeds the detector: brightness, contrast, gamma and the blur
        # all land before the temperature index is taken. That is also the catch —
        # every threshold below is a percentile of this frame's histogram, so
        # moving a Section A slider re-tunes the detector under you.
        frame = adjust(bgr, s)

        note, anchors = "", []
        if s.plume_on:
            # One colour space choice, two jobs: it names the channel the detector
            # measures here, and the view it is painted on at the end.
            # .get, not []: a settings cache written before a space existed must
            # not crash the worker thread on the first frame.
            code, channel = DETECTOR_CHANNELS.get(
                s.color_space, DETECTOR_CHANNELS["Default (BGR)"]
            )
            temp = plume.temp_index(frame, code, channel)
            found = plume.plume_masks(temp, plume_config(s))
            anchors = [labels.centre(box) for _, box, _ in found]
            if s.plume_view == PLUME_VIEWS[1]:  # Mask
                # Halo mid-grey, core white: one image showing both extents.
                stack = sum((m for *_, m in found), np.zeros(temp.shape, np.uint8))
                frame = cv2.cvtColor(np.clip(stack, 0, 2) * 127, cv2.COLOR_GRAY2BGR)
            else:
                if s.plume_view == PLUME_VIEWS[2]:  # Temperature index
                    frame = plume.heatmap(temp)
                frame = plume.annotate(frame, found, s.plume_boxes, chosen)
            core = sum(int((m == 2).sum()) for *_, m in found)
            halo = sum(int((m == 1).sum()) for *_, m in found)
            note = f"  plumes={len(found)} core={core} halo={halo}"

        # Last, so the colour space view is purely cosmetic and never feeds back
        # into what the detector above measured.
        return to_color_space(frame, s.color_space), note, anchors


def _demo() -> None:
    """Smallest runnable check: the chain survives every toggle on a fake frame."""
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (60, 50), (255, 255, 255), -1)  # something to find

    pipe = Pipeline()
    base = Settings()

    out, note, _ = pipe.process(frame, base)
    assert out.shape == frame.shape and note == "", "defaults must be a passthrough"
    assert (out == frame).all(), "identity settings must not touch the pixels"

    tuned = replace(base, brightness=20, contrast=1.5, saturation=1.2, gamma=0.8)
    assert pipe.process(frame, tuned)[0].shape == frame.shape

    # Blur off means *off*, not a 1x1 kernel copy — the identity check above is
    # what the paused-frame cache relies on.
    assert (pipe.process(frame, replace(base, blur=1))[0] == frame).all()
    smoothed = pipe.process(frame, replace(base, blur=5))[0]
    assert smoothed.shape == frame.shape and not (smoothed == frame).all()

    # Every space must be displayable *and* offer the detector a channel — the
    # two tables are read by different code paths and would drift apart silently.
    assert COLOR_SPACES.keys() == DETECTOR_CHANNELS.keys()
    for name in COLOR_SPACES:
        out, *_ = pipe.process(frame, replace(base, color_space=name))
        assert out.ndim == 3 and out.shape[2] == 3, f"{name} must stay displayable"
        code, channel = DETECTOR_CHANNELS[name]
        assert plume.temp_index(frame, code, channel).ndim == 2, f"{name} channel is not 2-D"

    # A zero kernel used to crash GaussianBlur; the clamp is what stops it.
    assert odd_kernel(0) == 1 and odd_kernel(4) == 5

    # Every plume knob must reach the detector. Copying by field name is silent
    # when it misses, so check the two dataclasses still agree.
    missing = {f.name for f in fields(plume.PlumeConfig)} - {f.name for f in fields(Settings)}
    assert not missing, f"Settings is missing plume knobs: {missing}"
    assert plume_config(replace(base, p_hi=97.5)).p_hi == 97.5

    # Section A feeds the detector: the temperature index is taken from the
    # *adjusted* frame, never the raw one.
    lit = replace(base, brightness=60, blur=5)
    assert (plume.temp_index(adjust(frame, lit)) != plume.temp_index(frame)).any()

    # Every view must come back displayable, with or without anything to find.
    for view in PLUME_VIEWS:
        s = replace(base, plume_on=True, plume_view=view, p_src=90.0, sd_min=5.0, min_area=10)
        out, note, _ = pipe.process(frame, s)
        assert out.shape == frame.shape, f"{view} changed the frame size"
        assert "plumes=" in note, note

    print("pipeline ok")


if __name__ == "__main__":
    _demo()
