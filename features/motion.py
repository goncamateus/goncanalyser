"""Motion: what changed between frames — heatmap, foreground, moving objects.

The one feature that reads more than one frame, which makes it the one feature
with state behind it. Everything else in `features/` is a pure function of the
frame it is handed; this module needs the previous frame, a live OpenCV
background model, and a running heat accumulator. All three live in
`MotionState`, which the *caller* owns — the worker has one, the report exporter
has its own — so two analyses can run at once without sharing a model.

**Six algorithms, one set of knobs.** Each one measures motion differently, but
every one of them reports it as a single-channel 0..255 "heat" image, and
everything after that — threshold, morphology, contours, speed, the heatmap — is
shared. So `motion_threshold` means the same thing whichever algorithm is
selected, and switching algorithms does not mean re-learning the panel.

    MOG2 / KNN                statistical background model, per pixel
    Farneback                 dense optical flow, magnitude per pixel
    Lucas-Kanade              sparse flow at corners, splatted into an image
    Frame / three-frame diff  plain absolute difference

The region of interest is not handled here and does not need to be: `adjust`
crops before any feature runs, so the frame this module sees *is* the region, and
the heatmap is localised to it for free.
"""

from dataclasses import replace

import cv2
import numpy as np

from core.settings import Settings

from .adjust import odd_kernel, to_bgr, to_gray

MOTION_ALGOS = (
    "None",
    "MOG2",
    "KNN",
    "Farneback",
    "Lucas-Kanade",
    "Frame difference",
    "Three-frame difference",
)

BOX_COLOR = (0, 200, 255)
ARROW_COLOR = (255, 255, 255)

# Optical flow is measured in pixels per frame; everything else here is measured
# in grey levels. This is the conversion that lets one threshold knob serve both:
# 8 px/frame of flow reads as full scale. It is a calibration constant, not a
# derived one — a slow wide-angle plume may want it higher.
FLOW_GAIN = 32.0

# MOG2 and KNN label shadows 127 and real foreground 255. Shadows are the moving
# thing's effect on the background, not the moving thing, so they are dropped.
FOREGROUND = 255


def _key(shape, s: Settings) -> tuple:
    """What the carried state is only valid for.

    Frame shape (so a resized region invalidates it) plus the parameters that are
    baked into a background model at construction time. The per-frame knobs —
    threshold, morphology, the flow parameters — are deliberately absent: they are
    applied fresh every frame and must stay live while paused.
    """
    return (
        shape,
        s.motion_algo,
        int(s.mog_history),
        float(s.mog_var),
        bool(s.mog_shadows),
        int(s.knn_history),
        float(s.knn_dist),
        bool(s.knn_shadows),
    )


def _subtractor(s: Settings):
    if s.motion_algo == "KNN":
        return cv2.createBackgroundSubtractorKNN(
            history=max(1, int(s.knn_history)),
            dist2Threshold=max(1.0, float(s.knn_dist)),
            detectShadows=bool(s.knn_shadows),
        )
    return cv2.createBackgroundSubtractorMOG2(
        history=max(1, int(s.mog_history)),
        varThreshold=max(1.0, float(s.mog_var)),
        detectShadows=bool(s.mog_shadows),
    )


class MotionState:
    """Everything motion carries from one frame to the next.

    Created by whoever drives the frames and handed to `pipeline.analyse`. Three
    rules keep it honest, and all three are things that happen in normal use:

    1. **The same frame twice must not advance it.** Dragging a knob while paused
       re-analyses the frame on screen, over and over. Feeding a background model
       the same image fifty times teaches it that image is the background, so a
       still frame would fade to nothing while you tuned it.
    2. **A jump resets it.** Seeking or stepping backwards means the previous
       frame is no longer the previous frame; differencing against it would light
       up the whole image.
    3. **A changed model resets it.** Switching algorithm, or moving the region,
       leaves a model that is either the wrong kind or the wrong shape.
    """

    def __init__(self):
        self.pending = 0  # the frame index about to be analysed
        self.reset(None)

    def at(self, index: int) -> "MotionState":
        """Name the frame index that is about to be analysed. Returns self.

        Called at the point of use — `analyse(raw, s, state.at(i))` — so the index
        travels with the state instead of becoming a fourth argument to `analyse`
        that only one of five features has any use for.
        """
        self.pending = int(index)
        return self

    def reset(self, key) -> None:
        self.key = key
        self.prev: np.ndarray | None = None
        self.prev2: np.ndarray | None = None
        self.subtractor = None
        self.heat: np.ndarray | None = None  # the accumulator, float32
        self.heat_now: np.ndarray | None = None  # this frame alone, float32
        # Object centroids: `ref` is what speeds are measured against and only
        # rotates when the frame advances, `centres` is whatever the current
        # threshold produced. Two of them, because re-rendering a paused frame
        # recomputes the centroids and would otherwise measure the frame against
        # itself and report everything stationary.
        self.ref: list[tuple[float, float]] = []
        self.centres: list[tuple[float, float]] = []
        self.index: int | None = None

    def update(self, gray: np.ndarray, s: Settings) -> np.ndarray:
        """This frame's heat, 0..255. The three rules above live here."""
        key = _key(gray.shape, s)
        if key != self.key or self.index is None:
            self.reset(key)  # rule 3
        elif self.pending == self.index:
            return self.heat_now  # rule 1
        elif self.pending != self.index + 1:
            self.reset(key)  # rule 2

        heat = _measure(self, gray, s)
        if self.heat is None:
            self.heat = np.zeros(gray.shape, np.float32)
        # An exponential average, not a true N-frame window: one call, no ring
        # buffer, and the difference is a soft tail rather than a hard cutoff.
        # ponytail: swap for a deque of frames if a hard cutoff is ever needed.
        cv2.accumulateWeighted(heat, self.heat, 1.0 / max(1, int(s.heat_window)))

        self.prev, self.prev2 = gray, self.prev
        self.ref, self.centres = self.centres, []
        self.index, self.heat_now = self.pending, heat
        return heat


def _measure(state: MotionState, gray: np.ndarray, s: Settings) -> np.ndarray:
    """One frame's motion as a float32 0..255 image, by the chosen algorithm."""
    if s.motion_algo in ("MOG2", "KNN"):
        if state.subtractor is None:
            state.subtractor = _subtractor(s)
        # learningRate -1 lets OpenCV pick from `history`, which is what the
        # history knob is for; anything else overrides it.
        fg = state.subtractor.apply(gray, learningRate=float(s.motion_learning))
        return np.where(fg == FOREGROUND, 255.0, 0.0).astype(np.float32)

    if state.prev is None:
        return np.zeros(gray.shape, np.float32)  # first frame: nothing to compare

    if s.motion_algo == "Farneback":
        flow = cv2.calcOpticalFlowFarneback(
            state.prev,
            gray,
            None,
            min(0.9, max(0.1, float(s.fb_pyr_scale))),
            max(1, int(s.fb_levels)),
            max(3, int(s.fb_winsize)),
            max(1, int(s.fb_iterations)),
            5,
            1.2,
            0,
        )
        return np.clip(cv2.magnitude(flow[..., 0], flow[..., 1]) * FLOW_GAIN, 0, 255)

    if s.motion_algo == "Lucas-Kanade":
        return _sparse_flow(state.prev, gray, s)

    if s.motion_algo == "Frame difference":
        return cv2.absdiff(state.prev, gray).astype(np.float32)

    if state.prev2 is None:
        return np.zeros(gray.shape, np.float32)
    # Three-frame: a pixel counts only where it changed *and* is still changing,
    # which is what removes the ghost a plain difference leaves behind the object.
    # The AND is a per-pixel minimum, not `bitwise_and` — these are grey levels,
    # not flags, and ANDing the bits of 128 and 64 gives 0 for two large changes.
    return cv2.min(
        cv2.absdiff(state.prev2, state.prev), cv2.absdiff(state.prev, gray)
    ).astype(np.float32)


def _sparse_flow(prev: np.ndarray, gray: np.ndarray, s: Settings) -> np.ndarray:
    """Lucas-Kanade at tracked corners, painted into a dense image.

    LK is sparse by construction — it answers "how fast did *this point* move",
    not "which pixels moved". Splatting each vector as a disc the size of its
    search window is what lets it feed the same mask and heatmap as the other
    five. ponytail: a disc is not a segmentation; use Farneback when the shape of
    the moving thing matters.
    """
    heat = np.zeros(gray.shape, np.float32)
    points = cv2.goodFeaturesToTrack(
        prev, maxCorners=max(1, int(s.lk_max_points)), qualityLevel=0.01, minDistance=7
    )
    if points is None:
        return heat

    win = max(3, odd_kernel(s.lk_win))
    moved, found, _ = cv2.calcOpticalFlowPyrLK(
        prev, gray, points, None, winSize=(win, win), maxLevel=3
    )
    for (x0, y0), (x1, y1), ok in zip(
        points.reshape(-1, 2), moved.reshape(-1, 2), found.ravel()
    ):
        if not ok:
            continue
        value = min(255.0, float(np.hypot(x1 - x0, y1 - y0)) * FLOW_GAIN)
        cv2.circle(heat, (int(x1), int(y1)), win // 2, value, cv2.FILLED)
    return heat


def _blend(canvas: np.ndarray, heat: np.ndarray, s: Settings) -> None:
    """Paint the heatmap over `canvas`, in place. Silently skips a mismatch.

    Per-pixel alpha rather than one opacity over the whole frame: JET maps zero
    to dark blue, so a flat blend would wash the entire image blue wherever
    nothing is happening. Weighting the blend by the heat itself leaves cold
    areas as the untouched frame, which is what makes the overlay readable.

    The shape guard is for the Histogram view, whose canvas is a 512x256 plot
    rather than the frame — an overlay has no business there.
    """
    if heat is None or canvas.shape[:2] != heat.shape[:2]:
        return
    level = np.clip(heat / 255.0, 0.0, 1.0)
    level[level < max(0.0, float(s.heat_threshold))] = 0.0
    colored = cv2.applyColorMap((level * 255).astype(np.uint8), cv2.COLORMAP_JET)
    alpha = (level * float(s.heat_opacity))[..., None]
    canvas[:] = (canvas * (1 - alpha) + colored * alpha).astype(np.uint8)


def _speeds(centres, previous, limit: float) -> list[float]:
    """Pixels moved since the last frame, by nearest previous centroid.

    Greedy and identity-free: it answers "how fast is something moving here",
    not "where did object 7 go". ponytail: two blobs that cross swap speeds; add
    a real tracker (Hungarian, or cv2.TrackerCSRT) only if per-object identity
    is ever needed.
    """
    out = []
    for cx, cy in centres:
        best = min((np.hypot(cx - px, cy - py) for px, py in previous), default=None)
        out.append(round(float(best), 1) if best is not None and best <= limit else 0.0)
    return out


def run(frame: np.ndarray, s: Settings, out, state: MotionState | None = None) -> None:
    """Motion for one frame. Does nothing without a state to carry — by design.

    `state=None` is not an error: it is what `pipeline.process` and every
    single-frame caller pass, and motion between one frame and no other frame is
    not a defined quantity.
    """
    if s.motion_algo == "None" or state is None:
        return

    gray = to_gray(frame)
    heat = state.update(gray, s)

    # Derived outside the state on purpose: threshold and kernel stay live while
    # paused, so the mask re-renders as you drag them.
    mask = ((heat > s.motion_threshold) * 255).astype(np.uint8)
    k = odd_kernel(s.motion_open)
    if k > 1:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))

    out.canvases["Motion mask"] = to_bgr(mask)
    heatmap = frame.copy()
    _blend(heatmap, state.heat, s)
    out.canvases["Motion heatmap"] = heatmap
    if s.heat_on:
        out.ops.append(lambda canvas: _blend(canvas, state.heat, s))

    found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    kept = [c for c in found if cv2.contourArea(c) >= s.motion_min_area]
    boxes = [cv2.boundingRect(c) for c in kept]
    centres = [(x + w / 2, y + h / 2) for x, y, w, h in boxes]
    speeds = _speeds(centres, state.ref, float(s.motion_max_travel))
    state.centres = centres

    moving = int(np.count_nonzero(mask))
    out.metrics["motion_px"] = moving
    out.metrics["motion_frac"] = round(moving / mask.size, 4)
    out.metrics["motion_objects"] = len(kept)
    out.metrics["motion_speed"] = max(speeds, default=0.0)
    out.rows["motion"] = [
        {
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "area": float(cv2.contourArea(c)),
            "speed": speed,
        }
        for c, (x, y, w, h), speed in zip(kept, boxes, speeds)
    ]

    if s.motion_boxes:
        out.ops.append(lambda canvas, bs=boxes, sp=speeds: _draw(canvas, bs, sp, s))


def _draw(canvas: np.ndarray, boxes, speeds, s: Settings) -> None:
    for (x, y, w, h), speed in zip(boxes, speeds):
        cv2.rectangle(canvas, (x, y), (x + w, y + h), BOX_COLOR, 1)
        if s.motion_metrics:
            cv2.putText(
                canvas,
                f"{w * h}px {speed:g}/f",
                (x, max(10, y - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                ARROW_COLOR,
                1,
                cv2.LINE_AA,
            )


def _demo() -> None:
    """A square moving across a black field: every algorithm must see it move."""
    from core.pipeline import Result

    # A textured object, not a flat white square. Three-frame differencing takes
    # the *minimum* of two consecutive differences, and the interior of a uniform
    # object is identical in both, so a flat square is invisible to it by
    # construction. A smooth ramp rather than noise: the difference across one
    # step then stays well clear of the threshold instead of averaging out.
    ramp = 40 + 7 * np.arange(20)[None, :] + 3 * np.arange(20)[:, None]
    patch = np.repeat(ramp.astype(np.uint8)[:, :, None], 3, axis=2)

    def clip(step: int, frames: int = 6) -> list:
        """`frames` frames of a 20px textured square translating `step` px each time."""
        out = []
        for i in range(frames):
            img = np.zeros((120, 160, 3), np.uint8)
            left = 20 + i * step
            img[50:70, left : left + 20] = patch
            out.append(img)
        return out

    def play(images, s, state=None, start=0):
        """Run a sequence through `run` the way the worker does. Last Result out."""
        state = state or MotionState()
        result = None
        for i, img in enumerate(images):
            result = Result()
            run(img, s, result, state.at(start + i))
        return result, state

    base = Settings(motion_algo="MOG2", motion_min_area=20, heat_on=True)

    for algo in MOTION_ALGOS[1:]:
        s = replace(base, motion_algo=algo)
        moving, _ = play(clip(8), s)
        assert moving.metrics["motion_objects"] >= 1, f"{algo} missed a moving square"
        assert moving.metrics["motion_px"] > 0, algo
        assert moving.canvases["Motion mask"].shape == (120, 160, 3), algo

        # The negative, and the one that catches a model being fed noise: the
        # same frame over and over is a still image, and still is not moving.
        still, _ = play([clip(0)[0]] * 6, s)
        assert still.metrics["motion_px"] == 0, f"{algo} found motion in a still clip"

        # Rows describe the boxes that were drawn, and carry the geometry the
        # CSV export joins on.
        assert set(moving.rows["motion"][0]) == {"x", "y", "w", "h", "area", "speed"}

    # Rule 1: re-analysing the frame on screen — which is what dragging a knob
    # while paused does — must not advance the model or move a single number.
    # Checked on MOG2 because it is the algorithm a repeat feed actually damages:
    # show it the same image often enough and it learns that image as background.
    images = clip(8)
    first, model = play(images, base)
    again = Result()
    run(images[-1], base, again, model.at(len(images) - 1))
    assert again.metrics == first.metrics, "a paused re-render moved the state"

    diff = replace(base, motion_algo="Frame difference")
    played, state = play(images, diff)
    last = len(images) - 1

    # …and the knobs must stay live while it is frozen, or tuning a paused frame
    # would do nothing. Only the carried state is pinned, not the thresholds.
    loose = Result()
    run(images[-1], replace(diff, motion_threshold=250), loose, state.at(last))
    assert loose.metrics["motion_px"] < played.metrics["motion_px"]

    # Rule 2: a seek backwards is not a frame difference. Differencing frame 5
    # against frame 0 would light up both positions of the square.
    jumped = Result()
    run(images[0], diff, jumped, state.at(0))
    assert jumped.metrics["motion_px"] == 0, "a backwards seek differenced across the jump"

    # Rule 3: the region can be resized mid-clip, so the frames change shape
    # underneath the state. Unhandled, that is a raw OpenCV size assertion.
    _, state = play(images, diff)
    small = Result()
    run(images[0][:60, :80], diff, small, state.at(len(images)))
    assert small.canvases["Motion mask"].shape == (60, 80, 3)

    # Speed is measured, not invented: 8 px a frame reads as roughly 8.
    fast, _ = play(clip(8), diff)
    assert 6 <= fast.metrics["motion_speed"] <= 10, fast.metrics["motion_speed"]
    slow, _ = play(clip(2), diff)
    assert slow.metrics["motion_speed"] < fast.metrics["motion_speed"]

    # Small blobs are noise, and the area filter is what removes them.
    assert not play(clip(8), replace(diff, motion_min_area=100_000))[0].rows["motion"]

    # Off is off — the gate that keeps a dense optical flow off the video path.
    off, _ = play(clip(8), Settings())
    assert not off.metrics and not off.canvases and not off.ops

    # The heatmap is an overlay like any other: it composites onto any canvas and
    # leaves the odd-shaped one alone rather than raising.
    canvas = np.zeros((120, 160, 3), np.uint8)
    for op in first.ops:
        op(canvas)
    assert canvas.any(), "the heat overlay painted nothing"
    plot = np.zeros((256, 512, 3), np.uint8)
    for op in first.ops:
        op(plot)  # a Histogram-shaped canvas must not be a crash

    print("motion ok")


if __name__ == "__main__":
    _demo()
