"""Hold a plume steady across frames: Kalman per source, plus association.

Measured on 60 consecutive frames of `voo_1.mp4`, the raw detector changed how
many sources it found on **36 of 59** frame transitions, swinging between 2 and 5.
Sources blink out for a frame and come back. That is the flicker, and a Kalman
filter on its own does not fix it — a filter smooths a signal it is *given*, and
the problem is that the signal disappears.

So this is the standard three-part answer (the SORT recipe), of which the Kalman
filter is one part:

    associate   match this frame's detections to existing tracks by distance
    coast       a track that goes unmatched keeps predicting for `max_age`
                frames before it dies, which bridges a 1-2 frame dropout
    confirm     a new track stays hidden until seen `min_hits` times, so a
                one-frame speck never reaches the screen

The filter itself is a constant-velocity model over `[cx, cy, w, h]`. Velocity is
what makes coasting worth anything: a plume drifts with the wind and the drone
moves, so a coasted track has to keep moving too, or it is left behind within
three frames and the association fails anyway.

Written out longhand rather than pulled from a tracking library: the state is
four numbers, the update is two matrix lines, and a dependency that brings its
own detector and its own I/O to get them would be far larger than this file.

**This module is the only stateful thing in the processing chain.** Everything
else takes a frame and returns a result. Track state belongs to a contiguous run
of frames, so `Tracker.reset()` on a seek is not optional — see `Pipeline`.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TrackConfig:
    """Tuning for the tracker, mirroring the sliders in Section B."""

    on: bool = True
    max_age: int = 3  # frames a track may coast unmatched before it dies
    min_hits: int = 2  # detections before a new track is shown at all
    max_distance: float = 60.0  # px between a prediction and a detection to match
    process_var: float = 12.0  # how much the plume is expected to move on its own
    measure_var: float = 24.0  # how noisy a detection is; > process_var = smoother


class Track:
    """One source, followed across frames by a constant-velocity Kalman filter.

    State is `[cx, cy, w, h, vx, vy]`. Only position gets a velocity: a plume's
    width breathes but does not drift in a direction, so giving w/h velocity just
    lets a coasted box inflate without bound.

    The covariance is kept as a diagonal. A full 6x6 would be more correct, but
    the cross terms here are between position and its own velocity, and at 25 fps
    with a per-frame update they stay small — this keeps the update to arithmetic
    you can read, and the measured behaviour is what matters.
    """

    _next_id = 1

    def __init__(self, box, cfg: TrackConfig, payload=None):
        cx, cy, w, h = _to_state(box)
        self.id = Track._next_id
        Track._next_id += 1
        self.cfg = cfg
        self.x = np.array([cx, cy, w, h, 0.0, 0.0], float)
        # Start position confident (we just measured it) and velocity wide open,
        # so the first two frames set the direction instead of fighting a prior.
        self.p = np.array([cfg.measure_var, cfg.measure_var, cfg.measure_var,
                           cfg.measure_var, 1000.0, 1000.0], float)
        self.hits = 1
        self.age = 0  # frames since the last matched detection
        self.box = tuple(box)  # the last *measured* box, which is what gets drawn
        # Whatever the caller attached to this detection — here, the plume mask.
        # A coasting track hands its last one back, so a dropout keeps drawing
        # something instead of blinking, which is the entire point of coasting.
        self.payload = payload
        self.measured_at = self.centre  # where that payload was actually observed

    # --- filter -------------------------------------------------------------

    def predict(self) -> None:
        """Step the model forward one frame. Uncertainty grows until corrected."""
        self.x[0] += self.x[4]
        self.x[1] += self.x[5]
        self.p[:4] += self.cfg.process_var
        self.p[4:] += self.cfg.process_var * 0.5
        self.age += 1

    def update(self, box, payload=None) -> None:
        """Fold in a detection: the Kalman gain per component, diagonal P."""
        z = np.array(_to_state(box), float)
        gain = self.p[:4] / (self.p[:4] + self.cfg.measure_var)
        residual = z - self.x[:4]

        # Velocity learns from the *position* residual — that residual is exactly
        # how far the object moved beyond where the model predicted it.
        self.x[4:] += gain[:2] * residual[:2]
        self.x[:4] += gain * residual
        self.p[:4] *= 1 - gain

        self.hits += 1
        self.age = 0
        self.box = tuple(box)
        if payload is not None:
            self.payload = payload
            self.measured_at = self.centre

    @property
    def drift(self) -> tuple[int, int]:
        """How far the filter thinks the payload has moved since it was measured.

        Zero on a matched frame. On a coasted one it is the shift to apply to the
        stale mask so it lands where the plume is predicted to be now — the drone
        keeps moving during a dropout, and a mask pinned to where the plume was
        three frames ago is worse than useless.
        """
        cx, cy = self.centre
        return (cx - self.measured_at[0], cy - self.measured_at[1])

    # --- reporting ----------------------------------------------------------

    @property
    def centre(self) -> tuple[int, int]:
        """The filtered centre — steadier than the detection it came from."""
        return (int(round(self.x[0])), int(round(self.x[1])))

    @property
    def confirmed(self) -> bool:
        """Seen enough times to be worth showing.

        A track that is currently coasting counts as confirmed if it ever earned
        it: the point of coasting is to survive the gap, not to be hidden by it.
        """
        return self.hits >= self.cfg.min_hits

    def distance(self, box) -> float:
        cx, cy, _, _ = _to_state(box)
        return float(np.hypot(cx - self.x[0], cy - self.x[1]))


def _to_state(box) -> tuple[float, float, float, float]:
    """(x, y, w, h) box -> (centre x, centre y, w, h)."""
    x, y, w, h = box
    return (x + w / 2, y + h / 2, float(w), float(h))


class Tracker:
    """Associates detections to tracks, frame by frame.

    Greedy nearest-neighbour rather than the Hungarian algorithm: there are two
    to five sources in a frame, they are far apart compared to how far they move,
    and an optimal assignment over a 5x5 matrix would decide the same thing.
    """

    def __init__(self, cfg: TrackConfig | None = None):
        self.cfg = cfg or TrackConfig()
        self.tracks: list[Track] = []
        self.seen = 0

    def reset(self, cfg: TrackConfig | None = None) -> None:
        """Drop all state. Required whenever frames stop being consecutive."""
        if cfg is not None:
            self.cfg = cfg
        self.tracks = []
        self.seen = 0  # frames since the reset, for the warm-up below

    def update(self, boxes, payloads=None) -> list[Track]:
        """Feed one frame's source boxes; get back the tracks worth showing.

        Returned oldest-track-first, which is a stable order: a source that has
        been there all along keeps its place when a new one appears beside it.
        A track with `age > 0` is coasting — confirmed and predicted, but not
        seen this frame, and its `payload` is the last mask it did see.
        """
        payloads = payloads or [None] * len(boxes)
        for track in self.tracks:
            track.predict()

        # Greedy: closest pair first, so a detection cannot be stolen by a track
        # that merely got there first in list order.
        pairs = sorted(
            (
                (track.distance(box), t_i, b_i)
                for t_i, track in enumerate(self.tracks)
                for b_i, box in enumerate(boxes)
            ),
            key=lambda p: p[0],
        )
        taken_t: set[int] = set()
        taken_b: set[int] = set()
        for dist, t_i, b_i in pairs:
            if dist > self.cfg.max_distance or t_i in taken_t or b_i in taken_b:
                continue
            self.tracks[t_i].update(boxes[b_i], payloads[b_i])
            taken_t.add(t_i)
            taken_b.add(b_i)

        for b_i, box in enumerate(boxes):
            if b_i not in taken_b:
                self.tracks.append(Track(box, self.cfg, payloads[b_i]))

        # A track that has coasted past max_age is gone, not merely unseen.
        self.tracks = [t for t in self.tracks if t.age <= self.cfg.max_age]
        self.seen += 1

        # Warm-up: for the first `min_hits` frames after a reset, show everything.
        # Confirmation is meant to suppress a speck that flickers in mid-run, not
        # to blank the screen — and a seek resets the tracker, so without this a
        # frame you paused on would show no detections at all, forever, because
        # no further frames arrive to confirm anything.
        if self.seen <= self.cfg.min_hits:
            return list(self.tracks)
        return [t for t in self.tracks if t.confirmed]


def _demo() -> None:
    """The measured problem, reproduced: a source that blinks out for one frame."""
    cfg = TrackConfig(max_age=3, min_hits=2, max_distance=60)

    # Two vents. The right one drops out on frames 4 and 5, exactly the 1-2 frame
    # dropout that makes the panel flicker.
    left = [(100 + 2 * i, 200, 40, 40) for i in range(10)]
    right = [(400 + 2 * i, 210, 30, 30) for i in range(10)]
    frames = [
        [left[i]] if i in (4, 5) else [left[i], right[i]]
        for i in range(10)
    ]

    tracker = Tracker(cfg)
    counts, ids, coasting = [], [], []
    for i, boxes in enumerate(frames):
        # The payload stands in for a mask: whatever the caller attached.
        shown = tracker.update(boxes, [f"mask@{i}:{b[0]}" for b in boxes])
        counts.append(len(shown))
        ids.append([t.id for t in shown])
        coasting.append([t.id for t in shown if t.age > 0])

    # A freshly reset tracker shows what it has, rather than blanking the screen
    # while it waits for confirmation — a seek resets it, and a frame paused on
    # after a seek never receives another frame to confirm anything with.
    assert counts[0] == 2, f"warm-up must show detections immediately: {counts}"
    assert counts[1:] == [2] * 9, f"coasting failed to bridge the gap: {counts}"
    # Same ids throughout: the right vent kept its identity across the dropout.
    assert all(row == ids[1] for row in ids[1:]), f"identity churned: {ids}"
    # And frames 4-5 are reported as coasted rather than as fresh detections.
    assert coasting[4] and coasting[5], f"the dropout was not flagged: {coasting}"
    assert not coasting[6], "a re-detected track must stop claiming to coast"

    # A coasted track still carries a mask to draw, and says how far to shift it.
    right_track = next(t for t in tracker.tracks if t.id == ids[1][1])
    tracker.update([left[9]])  # right one drops out again
    assert right_track.payload is not None, "coasting with nothing to draw is useless"
    assert right_track.drift != (0, 0), "a coasted mask must be shifted to keep up"

    # Past max_age it must actually die, or a vanished plume would hang forever.
    for _ in range(cfg.max_age + 2):
        shown = tracker.update([left[9]])
    assert len(shown) == 1, f"a long-gone track must be dropped, got {shown}"

    # Past the warm-up, a one-frame speck must not reach the screen.
    t2 = Tracker(cfg)
    for _ in range(cfg.min_hits + 1):
        t2.update([(500, 500, 20, 20)])  # something steady, to get past warm-up
    t2.update([(500, 500, 20, 20), (50, 50, 10, 10)])  # a speck appears
    shown = t2.update([(500, 500, 20, 20)])
    assert len(shown) == 1, f"an unconfirmed speck must not be shown: {shown}"

    # The filtered centre must be steadier than the raw detections feeding it.
    jitter = Tracker(TrackConfig(min_hits=1, measure_var=60.0, process_var=4.0))
    rng = np.random.default_rng(3)
    raw, filtered = [], []
    for i in range(30):
        noisy = (300 + rng.integers(-8, 9), 200 + rng.integers(-8, 9), 40, 40)
        jitter.update([noisy])
        raw.append(noisy[0] + 20)
        filtered.append(jitter.tracks[0].centre[0])
    spread_raw = float(np.std(np.diff(raw)))
    spread_filtered = float(np.std(np.diff(filtered)))
    assert spread_filtered < spread_raw / 2, (spread_raw, spread_filtered)

    print(
        f"tracking ok — dropout bridged, identity held, "
        f"centre jitter {spread_raw:.1f} -> {spread_filtered:.1f} px/frame"
    )


if __name__ == "__main__":
    _demo()
