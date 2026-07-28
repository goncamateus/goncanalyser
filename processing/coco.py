"""COCO segmentation export: one `plume` class, one plume per image.

Ported from this repo's earlier `steamdet/export.py`
(`git show 9fdd3dd^:steamdet/export.py`), which already had a working accumulator,
bbox and shoelace area. Two things are different here:

* **One category.** The old export shipped `plume` and `core` as overlapping
  classes. The plume now envelops everything — polygons come from
  `plume.polygons(mask, 1)`, and since the core is stored as 2, `>= 1` unions core
  and halo into a single outline.
* **One annotation per image, not per polygon.** Growth can leave a mask in
  several disconnected pieces. COCO models that as *one* annotation whose
  `segmentation` is a list of polygons; emitting one annotation per polygon —
  which the old code did — would claim three plumes in a frame the user just said
  has exactly one.

Rejected frames still contribute an image entry, with no annotation. That is a
negative sample, and a segmentation set made only of frames containing plumes
teaches a model that every frame contains a plume.

Qt-free on purpose: `export_dataset` is a generator yielding progress, so the GUI
can drive a progress bar without this module knowing Qt exists.
"""

import json
from pathlib import Path

import cv2

from . import plume
from .labels import centre, match

CATEGORIES = [{"id": 1, "supercategory": "plume", "name": "plume"}]


def _bbox(polys) -> list[float]:
    """x, y, w, h covering *every* polygon of the annotation."""
    xs = [x for poly in polys for x, _ in poly]
    ys = [y for poly in polys for _, y in poly]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _area(poly) -> float:
    """Shoelace. Kept local so an area always comes from the polygon it describes."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def mask_polygons(mask) -> list[list[tuple[int, int]]]:
    """The whole plume as point lists — halo and core as one outline."""
    return [c.reshape(-1, 2).tolist() for c in plume.polygons(mask, 1)]


class Coco:
    """Accumulates one COCO instances file across an export run."""

    def __init__(self) -> None:
        self.images: list[dict] = []
        self.annotations: list[dict] = []

    def add(self, file_name: str, size, polys) -> None:
        """One image, and at most one annotation covering all of `polys`."""
        w, h = size
        image_id = len(self.images) + 1
        self.images.append({"id": image_id, "file_name": file_name, "width": w, "height": h})
        if not polys:
            return  # reviewed, nothing in it: a negative sample
        self.annotations.append(
            {
                "id": len(self.annotations) + 1,
                "image_id": image_id,
                "category_id": 1,
                "segmentation": [[c for point in poly for c in point] for poly in polys],
                "bbox": _bbox(polys),
                "area": sum(_area(poly) for poly in polys),
                "iscrowd": 0,
            }
        )

    def as_dict(self) -> dict:
        return {
            "images": self.images,
            "annotations": self.annotations,
            "categories": CATEGORIES,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict()) + "\n")


def _detect_at(cap, pipeline, settings, index: int, warmup: int):
    """Decode up to `warmup` frames before `index`, then detect on `index`.

    Returns `(raw frame, detections)`, or None if the frame could not be read.

    The warm-up is what gives the tracker the history it has during playback. It
    is fed frames through the same `Pipeline.process`, so the state it arrives in
    is the state the GUI was in — there is no second code path to keep in step.
    """
    start = max(0, index - warmup)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    raw = None
    for at in range(start, index + 1):
        ok, frame = cap.read()
        if not ok:
            return None
        raw = frame
        _, _, _ = pipeline.process(raw, settings, None, at)
    # Re-run the emitted frame to read its detections back out. `process` is
    # idempotent on a repeat of the same index — that is exactly what the
    # tracker's rewind guarantees — so this does not advance anything.
    return raw, pipeline.detections(raw, settings, index)


def export_dataset(video: str, settings, store, out_dir, warmup: int = 12):
    """Write images + annotations for every labelled frame. Yields (done, total).

    A generator rather than a function so a caller can show progress and cancel by
    simply not asking for the next item — and so this module never imports Qt.

    Detection is re-run here rather than trusting anything cached: the point of
    storing an anchor instead of an index is that the mask is recomputed under the
    *current* parameters and the anchor re-bound to it.

    With tracking on, that re-run needs history. Labelled frames are scattered
    through the clip, so each one is preceded by a **warm-up**: `warmup` frames
    are decoded and fed to the tracker before the labelled frame is emitted. That
    is what makes the exported mask the same one that was on screen when the pick
    was made — including a frame where the plume was being coasted through a
    dropout, which without warm-up would export nothing at all.

    The image written out is the **raw** decoded frame. Section A's brightness and
    blur are tuning aids for the detector, not part of the data — baking them in
    would ship a dataset nobody could reproduce from the source video. The mask
    coordinates are identical either way.
    """
    from .pipeline import Pipeline

    out = Path(out_dir)
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    frames = sorted(store.labels)
    total = len(frames)
    coco = Coco()
    lost: list[int] = []
    pipeline = Pipeline()

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise OSError(f"cannot open {video}")

    try:
        for done, index in enumerate(frames, start=1):
            found = _detect_at(cap, pipeline, settings, index, warmup)
            if found is None:
                lost.append(index)
                yield done, total
                continue
            raw, detections = found

            label = store.labels[index]
            polys: list = []
            if not label.rejected:
                anchors = [centre(box) for _, box, _ in detections]
                which = match(label.anchor, anchors, raw.shape)
                if which is None:
                    # The anchor no longer names anything. Skipping the image
                    # entirely is the honest move: writing it with no annotation
                    # would file a lost label as a negative sample.
                    lost.append(index)
                    yield done, total
                    continue
                polys = mask_polygons(found[which][2])

            name = f"frame_{index:06d}.png"
            cv2.imwrite(str(images_dir / name), raw)
            coco.add(name, (raw.shape[1], raw.shape[0]), polys)
            yield done, total
    finally:
        cap.release()

    coco.save(out / "annotations" / "instances.json")
    return {"images": len(coco.images), "annotations": len(coco.annotations), "lost": lost}


def _demo() -> None:
    """Schema check by hand — pycocotools is not worth a dependency for this."""
    import numpy as np

    # A mask in two disconnected pieces: one plume, two polygons.
    split = np.zeros((120, 200), np.uint8)
    split[20:60, 20:70] = 1
    split[20:60, 120:170] = 1
    split[30:50, 30:60] = 2  # a core inside the left piece

    solid = np.zeros((120, 200), np.uint8)
    solid[40:90, 60:140] = 1

    coco = Coco()
    coco.add("a.png", (200, 120), mask_polygons(split))
    coco.add("b.png", (200, 120), mask_polygons(solid))
    coco.add("negative.png", (200, 120), [])  # reviewed, no plume
    data = coco.as_dict()

    assert len(data["categories"]) == 1 and data["categories"][0]["name"] == "plume"
    assert len(data["images"]) == 3, "a negative still contributes an image"
    assert len(data["annotations"]) == 2, "one annotation per positive image, never per polygon"

    first = data["annotations"][0]
    assert len(first["segmentation"]) == 2, "a split mask is one annotation, two polygons"
    for poly in first["segmentation"]:
        assert len(poly) >= 6 and len(poly) % 2 == 0, "flat [x, y, ...] with >= 3 points"
    x, y, w, h = first["bbox"]
    xs = [c for poly in first["segmentation"] for c in poly[0::2]]
    ys = [c for poly in first["segmentation"] for c in poly[1::2]]
    assert x <= min(xs) and y <= min(ys) and x + w >= max(xs) and y + h >= max(ys), first["bbox"]
    assert w > 100, "the bbox must span both pieces, not just one"
    assert first["area"] > 0 and first["iscrowd"] == 0

    # The core must not become its own class or its own annotation.
    assert all(a["category_id"] == 1 for a in data["annotations"])
    ids = {a["image_id"] for a in data["annotations"]}
    assert ids == {1, 2}, "the negative image must own no annotation"

    print(f"coco ok — {len(data['images'])} images, {len(data['annotations'])} annotations")


if __name__ == "__main__":
    _demo()
