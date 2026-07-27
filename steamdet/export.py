"""Turn the per-frame findings into the two dataset formats people actually train on.

Both are built from the same polygons the json label carries, so the three outputs
never disagree about where the plume is. Two classes throughout: the whole plume
(halo included) and the saturated core inside it. They overlap on purpose -- core is
a region *within* plume, which both formats allow.
"""

import json
from pathlib import Path

from .plume import polygons

CLASSES = ("plume", "core")  # index 0/1 for YOLO, id 1/2 for COCO


def _shapes(found):
    """(class index, polygon) for every polygon of every source in a frame."""
    for _roi, _box, mask in found:
        for cls, value in enumerate((1, 2)):  # mask >= 1 is the plume, >= 2 the core
            for poly in polygons(mask, value):
                yield cls, poly


def _bbox(poly):
    """x, y, w, h of a polygon -- taken from the points, so it matches the mask."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _area(poly):
    """Shoelace. Kept local so a polygon's area always comes from the polygon."""
    total = 0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def yolo_lines(found, size) -> list[str]:
    """YOLO segmentation labels: `cls x1 y1 x2 y2 ...`, normalised, one polygon per line.

    Segmentation rather than boxes because the polygons already exist, and a detector
    trained on segmentation labels just ignores the extra points.
    """
    w, h = size
    lines = []
    for cls, poly in _shapes(found):
        coords = " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in poly)
        lines.append(f"{cls} {coords}")
    return lines


class Coco:
    """Accumulates one COCO annotations file across the whole run."""

    def __init__(self):
        self.images: list[dict] = []
        self.annotations: list[dict] = []

    def add(self, file_name: str, size, found) -> None:
        w, h = size
        image_id = len(self.images) + 1
        self.images.append({"id": image_id, "file_name": file_name, "width": w, "height": h})
        for cls, poly in _shapes(found):
            self.annotations.append(
                {
                    "id": len(self.annotations) + 1,
                    "image_id": image_id,
                    "category_id": cls + 1,
                    "segmentation": [[c for point in poly for c in point]],
                    "bbox": _bbox(poly),
                    "area": _area(poly),
                    "iscrowd": 0,
                }
            )

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "images": self.images,
                    "annotations": self.annotations,
                    "categories": [{"id": i + 1, "name": n} for i, n in enumerate(CLASSES)],
                }
            )
            + "\n"
        )


def write_data_yaml(path: Path) -> None:
    """The dataset descriptor ultralytics wants alongside images/ and labels/."""
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASSES))
    path.write_text(f"path: {path.parent.resolve()}\ntrain: images\nval: images\nnames:\n{names}\n")
