"""Which detection is the real plume, remembered per frame.

The detector cannot tell a steam plume from hot dithered equipment — measured on
`voo_1.mp4`, plume local sigma averages 24.2 and the equipment 25.1, so there is
no threshold between them. A human picks; this module remembers the picks.

A label stores an **anchor point**, not the `#N` index shown on screen. Indices
are a property of the current parameters: nudge a percentile and a source appears
or vanishes, and every index after it shifts by one. An anchor is a property of
the *scene* — the plume leaves the same pipe whatever the sliders say — so a
labelling pass survives re-tuning, and `match` re-binds each anchor to whichever
detection is now nearest it.

Three states per frame, and they are all different:

    absent      never reviewed
    anchor      reviewed, this is the plume
    rejected    reviewed, none of these is the plume  (anchor is None)

The last one is not a missing label. It is a negative sample, and it exports as a
COCO image with no annotations.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Beyond this fraction of the frame diagonal, a stored anchor is not considered a
# match for a detection. Generous on purpose: re-tuning is allowed to move a
# plume around, and a *lost* label the user is told about beats a silently wrong
# one bound to whatever happened to be closest.
TOLERANCE = 0.125


@dataclass(frozen=True)
class Label:
    """One reviewed frame. `anchor=None` means reviewed and rejected."""

    anchor: tuple[int, int] | None = None

    @property
    def rejected(self) -> bool:
        return self.anchor is None


def centre(box) -> tuple[int, int]:
    """Centre of an (x, y, w, h) source box — what gets stored as the anchor."""
    x, y, w, h = box
    return (int(x + w / 2), int(y + h / 2))


def match(anchor, anchors, shape, tol: float = TOLERANCE) -> int | None:
    """Index of the detection nearest `anchor`, or None if nothing is close.

    `shape` is the frame's (h, w); the tolerance scales with the diagonal so the
    same setting behaves the same on a 640x512 clip and a 1080p one.
    """
    if anchor is None or not anchors:
        return None
    h, w = shape[:2]
    limit = (tol * (h**2 + w**2) ** 0.5) ** 2
    ax, ay = anchor
    best, best_d = None, limit
    for i, (cx, cy) in enumerate(anchors):
        d = (cx - ax) ** 2 + (cy - ay) ** 2
        if d <= best_d:
            best, best_d = i, d
    return best


class LabelStore:
    """The picks for one video, plus the settings they were made under.

    Written on **every** change rather than at quit. The file is a few KB and an
    afternoon of labelling is not something to lose to a crash.
    """

    def __init__(self, video: str, root: Path, config: dict | None = None):
        self.video = str(Path(video).resolve())
        self.root = Path(root)
        self.config = config or {}
        self.labels: dict[int, Label] = {}

    # --- where it lives -----------------------------------------------------

    @property
    def path(self) -> Path:
        """One file per video. The hash keeps two clips of the same name apart."""
        digest = hashlib.sha1(self.video.encode()).hexdigest()[:8]
        return self.root / f"{Path(self.video).stem}-{digest}.json"

    # --- editing ------------------------------------------------------------

    def pick(self, frame: int, anchors, index: int) -> bool:
        """Mark detection `index` on `frame` as the plume. False if it does not exist."""
        if not 0 <= index < len(anchors):
            return False
        self.labels[frame] = Label(anchor=tuple(anchors[index]))
        self.save()
        return True

    def reject(self, frame: int) -> None:
        """Mark the frame reviewed with no plume in it — a negative sample."""
        self.labels[frame] = Label(anchor=None)
        self.save()

    def clear(self, frame: int) -> None:
        """Back to never-reviewed. Absent is not the same as rejected."""
        if self.labels.pop(frame, None) is not None:
            self.save()

    def clear_all(self) -> None:
        self.labels.clear()
        self.save()

    # --- reading ------------------------------------------------------------

    def get(self, frame: int) -> Label | None:
        return self.labels.get(frame)

    def chosen(self, frame: int, anchors, shape) -> int | None:
        """Which detection is currently the labelled one, re-anchored to now.

        Returns None both when the frame is unlabelled and when the anchor no
        longer matches anything — the caller distinguishes those through `get`.
        """
        label = self.labels.get(frame)
        return None if label is None else match(label.anchor, anchors, shape)

    def summary(self) -> dict[str, int]:
        rejected = sum(1 for lab in self.labels.values() if lab.rejected)
        return {
            "labelled": len(self.labels) - rejected,
            "negative": rejected,
            "total": len(self.labels),
        }

    # --- persistence --------------------------------------------------------

    def save(self) -> None:
        """Never raises: this runs from a keystroke handler and from shutdown."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "video": self.video,
                        "config": self.config,
                        "labels": {
                            str(frame): asdict(label)
                            for frame, label in sorted(self.labels.items())
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
        except OSError:
            pass

    def load(self) -> "LabelStore":
        """Read the file back if there is a usable one. Returns self for chaining.

        A corrupt or half-written file is ignored rather than fatal — the same
        call sits between the user and the app starting at all.
        """
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return self
        if not isinstance(data, dict):
            return self
        self.config = data.get("config") or {}
        for frame, raw in (data.get("labels") or {}).items():
            try:
                anchor = raw.get("anchor")
                self.labels[int(frame)] = Label(
                    anchor=tuple(anchor) if anchor is not None else None
                )
            except (AttributeError, TypeError, ValueError):
                continue  # one bad entry must not lose the rest of the pass
        return self


def _demo() -> None:
    """The point of the module: a label must survive re-tuning, or say it did not."""
    import tempfile

    shape = (512, 640)  # tolerance is 0.125 * diagonal ~= 102 px
    anchors = [(100, 200), (300, 250), (500, 260)]

    assert match((100, 200), anchors, shape) == 0, "exact hit"
    assert match((108, 206), anchors, shape) == 0, "a small drift must still match"
    assert match((290, 240), anchors, shape) == 1, "nearest wins"
    assert match((100, 200), [], shape) is None, "nothing detected, nothing to match"
    assert match(None, anchors, shape) is None, "a rejection matches nothing"
    # Far from every detection: report lost rather than binding to the closest.
    assert match((100, 480), anchors, shape) is None, "beyond tolerance must be lost"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LabelStore("/clips/voo_1.mp4", root, {"p_hi": 99.0})
        assert store.pick(10, anchors, 1), "picking an existing detection"
        assert not store.pick(11, anchors, 7), "picking past the end must fail, not crash"
        store.reject(20)
        store.pick(30, anchors, 0)
        store.clear(30)

        assert store.summary() == {"labelled": 1, "negative": 1, "total": 2}
        assert store.get(30) is None, "cleared is absent"
        assert store.get(20).rejected, "rejected is reviewed, not absent"

        # Round trip, and the three states must come back distinguishable.
        again = LabelStore("/clips/voo_1.mp4", root).load()
        assert again.config == {"p_hi": 99.0}, "the config the picks were made under"
        assert again.get(10).anchor == (300, 250)
        assert again.get(20).rejected and again.get(30) is None

        # Re-tuning: detections shifted and one new source appeared before it, so
        # every index moved. The anchor still finds the same plume.
        shifted = [(50, 100), (104, 205), (296, 244), (500, 260)]
        assert again.chosen(10, shifted, shape) == 2, "anchor re-bound past a new source"
        assert again.chosen(20, shifted, shape) is None, "a rejection chooses nothing"
        # And when the source it named is gone, it reports lost instead of guessing.
        assert again.chosen(10, [(50, 100), (500, 260)], shape) is None

    print("labels ok — anchors survive re-tuning, and say so when they do not")


if __name__ == "__main__":
    _demo()
