"""Reading a COCO segmentation dataset. No pycocotools.

An `instances_*.json` is a plain JSON document with three lists — `images`,
`annotations`, `categories` — and the only part that needs decoding is the
`segmentation` field. It comes in two shapes and both are short:

* **polygons** — `[[x, y, x, y, …], …]`, which is what `cv2.fillPoly` takes.
* **RLE**, on `iscrowd=1` regions — `{"counts": [...], "size": [h, w]}`, run
  lengths alternating from zero, laid out **column-major**.

That is the whole reason a dependency would otherwise be here. The one case not
covered is `counts` as a string: that is *compressed* RLE, a real codec, and it
does not appear in the official annotation files. Those annotations are counted
and skipped rather than being allowed to fail a run that is otherwise fine.

Images are scaled down to `LONG_EDGE` on the way out. Every measurement taken
against these masks is a ratio or a distribution, none of which move meaningfully
between 640px and 1600px, and it makes the whole package about four times faster.
"""

import json
import random
from pathlib import Path

import cv2
import numpy as np

# Long edge every sampled image and mask is fitted to. Images already smaller are
# left alone — upscaling invents detail the metrics would then measure.
LONG_EDGE = 640


class Coco:
    """One annotation file, with the lookups the two analyses need.

    `skipped` counts compressed-RLE annotations passed over during decoding, so a
    run can report them instead of quietly under-measuring.
    """

    def __init__(self, data: dict):
        for key in ("images", "annotations", "categories"):
            if not isinstance(data.get(key), list):
                raise ValueError(f"not a COCO annotation file: no '{key}' list")

        self.images: dict[int, dict] = {img["id"]: img for img in data["images"]}
        self.names: dict[int, str] = {c["id"]: c["name"] for c in data["categories"]}
        self.skipped = 0

        self.anns: dict[int, list[dict]] = {}
        for ann in data["annotations"]:
            # An annotation pointing at an image the file does not list cannot be
            # placed on anything, and would crash later rather than here.
            if ann["image_id"] in self.images:
                self.anns.setdefault(ann["image_id"], []).append(ann)

    # --- categories ---------------------------------------------------------

    def category_id(self, name: str) -> int:
        """The id for a class name. Raises with the valid names, which is the fix."""
        for cid, known in self.names.items():
            if known == name:
                return cid
        raise ValueError(f"no class called {name!r}. Classes: {', '.join(sorted(self.names.values()))}")

    def select(self, image_id: int, category: int | None = None) -> list[dict]:
        """This image's annotations, optionally only one class'."""
        anns = self.anns.get(image_id, ())
        if category is None:
            return list(anns)
        return [a for a in anns if a["category_id"] == category]

    def image_ids(self, category: int | None = None) -> list[int]:
        """Images with at least one annotation to measure. Sorted, so it is stable."""
        return sorted(i for i in self.images if self.select(i, category))

    # --- masks --------------------------------------------------------------

    def mask(self, image_id: int, category: int | None = None) -> np.ndarray:
        """Union of every instance on this image, as uint8 0/255 at native size."""
        img = self.images[image_id]
        out = np.zeros((int(img["height"]), int(img["width"])), np.uint8)
        for ann in self.select(image_id, category):
            piece = self.instance(ann, out.shape[0], out.shape[1])
            if piece is not None:
                out |= piece
        return out


    def instance(self, ann: dict, height: int, width: int) -> np.ndarray | None:
        """One annotation as uint8 0/255, or None if it cannot be decoded."""
        seg = ann.get("segmentation")
        if isinstance(seg, dict):
            if isinstance(seg.get("counts"), str):
                self.skipped += 1  # compressed RLE — see the module docstring
                return None
            return _rle(seg["counts"], seg["size"]) * 255
        if not seg:
            return None

        mask = np.zeros((height, width), np.uint8)
        # Rounded, not truncated: COCO polygon vertices are floats, and int() on
        # them walks every boundary half a pixel towards the origin.
        rings = [
            np.round(np.asarray(p, np.float64).reshape(-1, 2)).astype(np.int32)
            for p in seg
            if len(p) >= 6  # fewer than three vertices is not a polygon
        ]
        if not rings:
            return None
        cv2.fillPoly(mask, rings, 255)
        return mask


def _rle(counts, size) -> np.ndarray:
    """Uncompressed COCO RLE to a uint8 0/1 mask.

    Runs alternate starting from zero, and they run **down the columns** — so the
    flat array is reshaped (width, height) and transposed, not reshaped (height,
    width). On a square fixture the difference is invisible, which is why the
    check below uses a rectangle.
    """
    height, width = int(size[0]), int(size[1])
    flat = np.zeros(height * width, np.uint8)
    at, value = 0, 0
    for run in counts:
        run = int(run)
        if value:
            flat[at : at + run] = 1  # numpy clips a run that overshoots
        at += run
        value ^= 1
    return flat.reshape((width, height)).T


def load(ann_path: str) -> Coco:
    """Parse an annotation file. A 45 MB val2017 takes a second or two."""
    return Coco(json.loads(Path(ann_path).read_text()))


def plan(coco: Coco, n: int, category: int | None = None, seed: int = 0) -> list[int]:
    """Which images to measure: a deterministic sample of the ones with content.

    Deterministic on purpose. A score compared against another score has to be
    over the same images, and re-drawing the sample between runs — or between
    optimiser trials — turns the objective into noise.
    """
    ids = coco.image_ids(category)
    return sorted(random.Random(seed).sample(ids, min(int(n), len(ids))))


def read(
    coco: Coco, images_dir: str, image_id: int, category: int | None = None
) -> tuple[str, np.ndarray, np.ndarray] | None:
    """(file name, BGR frame, GT mask), scaled to `LONG_EDGE`. None if unusable.

    ponytail: decodes from disk every call, with no mask cache. The optimiser,
    which is the only caller that wants the same image twice, holds its sample in
    a list for the whole study — so a cache here would be a second copy of what it
    already has. Worth adding if something ever streams the sample instead.

    None covers the three things that go wrong with a real dataset and are not
    worth stopping for: the image file is missing, it is not decodable, or every
    annotation on it was crowd RLE this module does not decode.
    """
    name = coco.images[image_id]["file_name"]
    bgr = cv2.imread(str(Path(images_dir) / name))
    if bgr is None:
        return None

    mask = coco.mask(image_id, category)
    if mask.shape != bgr.shape[:2]:
        # The annotation's idea of the size wins: every polygon is in its
        # coordinates. Trust the pixels for aspect, the JSON for geometry.
        mask = cv2.resize(mask, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    if not mask.any():
        return None

    height, width = bgr.shape[:2]
    scale = LONG_EDGE / max(height, width)
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
        # Nearest for the mask: anything smoother invents grey edge pixels, and a
        # ground-truth mask with a soft edge is not a ground truth.
        mask = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
    return name, bgr, mask


# --- fixtures, shared with the other two modules' checks ---------------------


def fixture(root: Path, count: int = 4) -> tuple[str, str]:
    """A tiny dataset on disk: bright squares on dark noise. (annotations, images).

    Deliberately **non-square** images — the RLE reshape, and every (h, w) versus
    (w, h) slip in the package, are invisible on a square one.

    Two mid-grey distractors are annotated by nobody, and they are the point. The
    annotated squares are separable by a plain threshold, so a perfect score
    exists; but they sit *above* the distractors, which sit above the default
    threshold of 127. So the defaults find all three shapes and are punished for
    two of them, and an optimiser that is not really searching cannot pass.
    """
    images_dir = root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    width, height = 80, 60
    rng = np.random.default_rng(0)

    images, annotations = [], []
    for i in range(count):
        img = rng.integers(0, 60, (height, width, 3), dtype=np.uint8)
        for corner in ((2, 40), (55, 3)):  # unannotated, and bright enough to be found
            cv2.rectangle(img, corner, (corner[0] + 18, corner[1] + 14), (180, 180, 180), -1)
        x, y = 10 + i * 4, 12
        cv2.rectangle(img, (x, y), (x + 24, y + 20), (250, 250, 250), -1)
        cv2.imwrite(str(images_dir / f"{i}.png"), img)

        images.append({"id": i, "file_name": f"{i}.png", "width": width, "height": height})
        annotations.append({
            "id": i, "image_id": i, "category_id": 1, "iscrowd": 0,
            "area": float(25 * 21), "bbox": [x, y, 25, 21],
            "segmentation": [[x, y, x + 24, y, x + 24, y + 20, x, y + 20]],
        })

    ann_path = root / "instances.json"
    ann_path.write_text(json.dumps({
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "square"}, {"id": 2, "name": "unused"}],
    }))
    return str(ann_path), str(images_dir)


def _demo() -> None:
    """Both segmentation shapes decode, and neither comes back transposed."""
    import tempfile
    from itertools import groupby

    coco = Coco({"images": [], "annotations": [], "categories": []})

    # A rectangle that is not symmetric under transpose, encoded the way COCO
    # does it — column-major, runs alternating from zero — and decoded back.
    height, width = 60, 80
    truth = np.zeros((height, width), np.uint8)
    truth[10:20, 5:15] = 1
    flat = truth.T.ravel()  # column-major, which is the whole point
    counts = [len(list(g)) for _, g in groupby(flat)]
    if flat[0]:
        counts.insert(0, 0)  # the first run is always background
    assert sum(counts) == height * width
    got = _rle(counts, [height, width])
    assert got.shape == (height, width), got.shape
    assert (got == truth).all(), "RLE came back transposed or shifted"

    # The same region as an annotation, via the public path.
    crowd = {"segmentation": {"counts": counts, "size": [height, width]}, "iscrowd": 1}
    assert (coco.instance(crowd, height, width) == truth * 255).all()

    # Compressed RLE is skipped and counted, not fatal.
    assert coco.instance({"segmentation": {"counts": "abc", "size": [1, 1]}}, 1, 1) is None
    assert coco.skipped == 1

    # A polygon fills its interior and nothing else, and a degenerate one is None.
    poly = coco.instance({"segmentation": [[5, 10, 15, 10, 15, 20, 5, 20]]}, height, width)
    assert poly[15, 10] == 255 and poly[5, 5] == 0, "polygon landed in the wrong place"
    assert coco.instance({"segmentation": [[1, 2, 3, 4]]}, height, width) is None
    assert coco.instance({"segmentation": []}, height, width) is None

    with tempfile.TemporaryDirectory() as tmp:
        ann_path, images_dir = fixture(Path(tmp))
        data = load(ann_path)
        assert len(data.images) == 4 and len(data.anns) == 4

        square = data.category_id("square")
        assert data.image_ids(square) == [0, 1, 2, 3]
        # A class nobody annotated has no images, and so is never sampled.
        assert data.image_ids(data.category_id("unused")) == []
        try:
            data.category_id("aardvark")
        except ValueError as exc:
            assert "square" in str(exc), "the error must list the valid names"
        else:
            raise AssertionError("an unknown class name must raise")

        # The sample is a subset, sorted, and the same every time.
        assert plan(data, 2, square) == plan(data, 2, square)
        assert len(plan(data, 2, square)) == 2 and len(plan(data, 99, square)) == 4

        name, bgr, mask = read(data, images_dir, 0, square)
        assert name == "0.png" and bgr.shape[:2] == mask.shape == (60, 80)
        assert set(np.unique(mask)) <= {0, 255}, "a GT mask must stay binary"
        # The square is where the annotation says, and the surround is empty.
        assert mask[22, 22] == 255 and mask[2, 2] == 0
        assert 0.05 < np.count_nonzero(mask) / mask.size < 0.2, "the fixture drifted"

        # A missing image file is skipped, not fatal.
        data.images[0]["file_name"] = "gone.png"
        assert read(data, images_dir, 0, square) is None

    print("coco ok")


if __name__ == "__main__":
    _demo()
