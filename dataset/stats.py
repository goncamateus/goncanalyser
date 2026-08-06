"""What separates annotated foreground from background, measured over a dataset.

Two passes, split because they cost three orders of magnitude apart:

* **Pass A — annotations.** Area, aspect, scale, mask complexity, class
  co-occurrence and spatial overlap. All of it is arithmetic on numbers already in
  the JSON, so it runs over *every* annotation in the file and costs nothing.
* **Pass B — pixels.** Colour, contrast, texture, edge density, spatial frequency
  and the mask heatmap. Each one needs the image decoded and the mask decoded with
  it, so it runs over a bounded sample.

Every pixel metric is measured **twice on the same image**: once under the mask,
once under its complement. A histogram of annotated pixels on its own says almost
nothing — the useful quantity is always the difference from the background it has
to be told apart from, and taking both from the same frame cancels exposure,
white balance and scene content out of the comparison.

Charts go to PNG through matplotlib rather than into the app's ndarray canvases.
`features/color.py` draws its histogram with `cv2.polylines` because that plot is
on the live per-frame path, where a millisecond matters and the result has to be a
canvas the viewer can show. This is a batch report written once at the end of a
run: a co-occurrence matrix and a box plot are not worth hand-rolling axes for.

Figures use the object-oriented `Figure` API rather than `pyplot`, because this
runs on a worker thread and pyplot keeps a process-wide registry of figures behind
a global current-figure pointer. `Figure` owns none of that.

There is a second, less obvious rule about matplotlib in this app, and it is
enforced by an import in `main.py` rather than by anything here: matplotlib has to
be imported before Qt builds its first widget, or every `savefig` below fails with
`FT_Render_Glyph … raster overflow`. See the comment there before moving it.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from core.settings import Settings
from features.color import SPACES
from features.texture import lbp_of

from .coco import load, plan, read

FIGURES = ("colour", "texture", "spatial", "geometry", "classes")

HEAT = 64  # heatmap grid; every mask is squashed to this regardless of frame size
RADIAL = 64  # buckets in the resampled radial frequency profile
LBP_BINS = 10  # uniform LBP with P=8 tops out at P + 1 codes
TOP_CLASSES = 12  # per-class panels stay readable up to about a dozen rows

# ponytail: LBP and the edge maps run at their default settings. Tuning them is
# what the app's own tabs are for; this is a survey, not a second control panel.
DEFAULTS = Settings()


# --- pass A: annotations only ------------------------------------------------


def geometry(coco) -> dict:
    """Shape and co-occurrence statistics over every annotation in the file."""
    per_class: dict[str, dict[str, list]] = defaultdict(
        lambda: {"area": [], "aspect": [], "scale": [], "complexity": []}
    )
    present: list[set[str]] = []
    overlap: dict[tuple[str, str], list[float]] = defaultdict(list)

    for image_id, anns in coco.anns.items():
        img = coco.images[image_id]
        frame_area = float(img["width"] * img["height"]) or 1.0
        here = set()

        for ann in anns:
            name = coco.names.get(ann["category_id"], str(ann["category_id"]))
            here.add(name)
            box = ann.get("bbox") or [0, 0, 0, 0]
            w, h = float(box[2]), float(box[3])
            area = float(ann.get("area") or w * h)

            stats = per_class[name]
            stats["area"].append(area / frame_area)
            if h > 0:
                stats["aspect"].append(w / h)
            stats["scale"].append(area**0.5)
            shape = _complexity(ann, area)
            if shape is not None:
                stats["complexity"].append(shape)

        present.append(here)
        # Spatial overlap between classes, not within one: two people overlapping
        # is a crowd, a person overlapping a horse is what the matrix is about.
        for a, b in _pairs(anns):
            first = coco.names.get(a["category_id"], "")
            second = coco.names.get(b["category_id"], "")
            if first and second and first != second:
                overlap[tuple(sorted((first, second)))].append(_box_iou(a["bbox"], b["bbox"]))

    counts = Counter(n for image in present for n in image)
    top = [n for n, _ in counts.most_common(TOP_CLASSES)]

    return {
        "per_class": {n: {k: np.asarray(v, float) for k, v in per_class[n].items()} for n in top},
        "top": top,
        "counts": dict(counts),
        "cooccurrence": _cooccurrence(present, top),
        "overlap": np.array(
            [[float(np.mean(overlap[tuple(sorted((a, b)))] or [0.0])) for b in top] for a in top]
        ),
        "centres": _centres(coco),
    }


def _pairs(items):
    """Every unordered pair, without pulling in itertools for one call site."""
    for i, first in enumerate(items):
        for second in items[i + 1 :]:
            yield first, second


def _box_iou(a, b) -> float:
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    x, y = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if right <= x or bottom <= y:
        return 0.0
    inter = (right - x) * (bottom - y)
    return inter / (aw * ah + bw * bh - inter or 1.0)


def _complexity(ann: dict, area: float) -> float | None:
    """Isoperimetric quotient P^2 / (4*pi*A). 1.0 is a circle; ragged shapes climb.

    Polygons only — a crowd RLE has no vertex list to take a perimeter from, and
    tracing its boundary would measure the resolution as much as the shape.
    """
    seg = ann.get("segmentation")
    if not isinstance(seg, list) or not seg or area <= 0:
        return None
    perimeter = 0.0
    for ring in seg:
        if len(ring) >= 6:
            pts = np.asarray(ring, np.float32).reshape(-1, 2)
            perimeter += float(cv2.arcLength(pts, True))
    return perimeter**2 / (4 * np.pi * area) if perimeter else None


def _cooccurrence(present: list[set[str]], top: list[str]) -> np.ndarray:
    """How many images hold both classes. The diagonal is each class' own count."""
    if not top:
        return np.zeros((0, 0))
    index = {n: i for i, n in enumerate(top)}
    table = np.zeros((len(present), len(top)), bool)
    for row, names in enumerate(present):
        for name in names:
            if name in index:
                table[row, index[name]] = True
    return (table.T.astype(np.int32) @ table.astype(np.int32)).astype(float)


def _centres(coco) -> np.ndarray:
    """Normalised bbox centres of every annotation, as a HEAT x HEAT count grid."""
    grid = np.zeros((HEAT, HEAT), float)
    for image_id, anns in coco.anns.items():
        img = coco.images[image_id]
        width, height = float(img["width"]), float(img["height"])
        for ann in anns:
            box = ann.get("bbox")
            if not box or width <= 0 or height <= 0:
                continue
            cx = (float(box[0]) + float(box[2]) / 2) / width
            cy = (float(box[1]) + float(box[3]) / 2) / height
            col = min(HEAT - 1, max(0, int(cx * HEAT)))
            row = min(HEAT - 1, max(0, int(cy * HEAT)))
            grid[row, col] += 1
    return grid


# --- pass B: one image's pixels, mask versus background ----------------------


class Pixels:
    """Running totals for the pixel metrics. One `add()` per sampled image."""

    def __init__(self):
        self.colour = {s: np.zeros((2, 3, 256)) for s in SPACES}  # [in/out, channel, bin]
        self.lbp = np.zeros((2, LBP_BINS))
        self.gradient = np.zeros((2, 64))  # magnitude histogram, 0..255 in 64 bins
        self.radial = np.zeros((2, RADIAL))
        self.heat = np.zeros((HEAT, HEAT))
        self.scalars: dict[str, list[float]] = defaultdict(list)
        self.images = 0

    def add(self, bgr: np.ndarray, mask: np.ndarray) -> None:
        inside = mask > 0
        outside = ~inside
        if not inside.any() or not outside.any():
            return  # a mask covering the whole frame has no background to compare to
        self.images += 1
        picks = (inside.view(np.uint8), outside.view(np.uint8))

        for space, (code, _, _) in SPACES.items():
            img = bgr if code is None else cv2.cvtColor(bgr, code)
            for side, pick in enumerate(picks):
                for channel in range(3):
                    self.colour[space][side, channel] += cv2.calcHist(
                        [img], [channel], pick, [256], [0, 256]
                    ).ravel()

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        codes = lbp_of(gray, DEFAULTS).astype(np.int64)
        magnitude = cv2.magnitude(
            cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        )
        edges = cv2.Canny(gray, DEFAULTS.canny_lo, DEFAULTS.canny_hi) > 0

        for side, sel in enumerate((inside, outside)):
            self.lbp[side] += np.bincount(codes[sel].ravel(), minlength=LBP_BINS)[:LBP_BINS]
            self.gradient[side] += np.histogram(magnitude[sel], bins=64, range=(0, 255))[0]
            values = gray[sel].astype(np.float64)
            tag = "mask" if side == 0 else "background"
            self.scalars[f"{tag}_mean"].append(float(values.mean()))
            self.scalars[f"{tag}_sd"].append(float(values.std()))
            self.scalars[f"{tag}_gradient"].append(float(magnitude[sel].mean()))
            self.scalars[f"{tag}_edge_density"].append(float(edges[sel].mean()))

        # Frequency: the object's own bounding box against the whole frame. A
        # masked-out patch would have a hard black border, and that step is a
        # broadband edge — it would dominate the spectrum it is meant to measure.
        x, y, w, h = cv2.boundingRect(mask)
        if w > 8 and h > 8:
            self.radial[0] += _radial(gray[y : y + h, x : x + w])
            self.radial[1] += _radial(gray)

        self.heat += cv2.resize(
            (inside).astype(np.float32), (HEAT, HEAT), interpolation=cv2.INTER_AREA
        )

    def summary(self) -> dict:
        """Headline numbers: the mask/background contrast the whole survey is for."""
        out = {"images_measured": self.images}
        for key, values in sorted(self.scalars.items()):
            out[key] = round(float(np.mean(values)), 4) if values else 0.0
        for metric in ("mean", "sd", "gradient", "edge_density"):
            back = out.get(f"background_{metric}", 0.0)
            out[f"{metric}_ratio"] = round(out.get(f"mask_{metric}", 0.0) / (back or 1.0), 3)
        return out


def _radial(gray: np.ndarray) -> np.ndarray:
    """Radially averaged log spectrum, resampled to RADIAL buckets.

    Resampled because the profile's natural length is half the image diagonal, and
    the crop and the frame it came from are never the same size — averaging them
    raw would add a large object's low frequencies to a small one's high ones.
    """
    spectrum = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(gray.astype(np.float64)))))
    h, w = spectrum.shape
    ys, xs = np.ogrid[:h, :w]
    radius = np.hypot(ys - h / 2, xs - w / 2).astype(np.int32).ravel()
    totals = np.bincount(radius, weights=spectrum.ravel())
    counts = np.bincount(radius)
    profile = totals / np.maximum(counts, 1)
    profile = profile[: max(2, min(h, w) // 2)]  # past this the corners alias in
    return np.interp(
        np.linspace(0, 1, RADIAL), np.linspace(0, 1, len(profile)), profile / (profile[0] or 1.0)
    )


# --- charts ------------------------------------------------------------------


def _rgb(bgr: tuple[int, int, int]) -> tuple[float, float, float]:
    """A `features.color.SPACES` draw colour as matplotlib wants it."""
    return tuple(c / 255 for c in reversed(bgr))


def _draw(pixels: Pixels, shapes: dict, out: Path) -> list[str]:
    """Write every figure. Returns the file names, in FIGURES order."""
    written = []
    for name in FIGURES:
        figure = globals()[f"_fig_{name}"](pixels, shapes)
        FigureCanvasAgg(figure)  # attaching the canvas is what picks the renderer
        figure.savefig(out / f"{name}.png", dpi=110, bbox_inches="tight")
        written.append(f"{name}.png")
    return written


def _panels(rows: int, columns: int, width: float, height: float):
    """A figure and its axes, with no pyplot and so no process-wide figure list."""
    figure = Figure(figsize=(width, height))
    return figure, figure.subplots(rows, columns)


def _fig_colour(pixels: Pixels, shapes: dict):
    figure, axes = _panels(1, 3, 15, 4)
    figure.suptitle("Colour — mask (solid) vs background (dashed), area-normalised")
    for ax, (space, (_, names, colours)) in zip(axes, SPACES.items()):
        counts = pixels.colour[space]
        for channel, (label, colour) in enumerate(zip(names, colours)):
            for side, style in ((0, "-"), (1, "--")):
                row = counts[side, channel]
                ax.plot(
                    row / (row.sum() or 1.0), style, color=_rgb(colour), lw=1.2,
                    label=f"{label} {'mask' if side == 0 else 'bg'}",
                )
        ax.set_title(space)
        ax.set_xlabel("value")
        ax.legend(fontsize=6, ncol=2)
    return figure


def _fig_texture(pixels: Pixels, shapes: dict):
    figure, axes = _panels(1, 3, 15, 4)
    figure.suptitle("Texture and edges — mask vs background")

    offsets = np.arange(LBP_BINS)
    for side, (label, shift) in enumerate((("mask", -0.2), ("background", 0.2))):
        row = pixels.lbp[side]
        axes[0].bar(offsets + shift, row / (row.sum() or 1.0), 0.4, label=label)
    axes[0].set_title(f"LBP codes (P={DEFAULTS.lbp_points}, {DEFAULTS.lbp_method})")
    axes[0].set_xlabel("code")
    axes[0].legend(fontsize=8)

    centres = np.linspace(0, 255, 64)
    for side, (label, style) in enumerate((("mask", "-"), ("background", "--"))):
        row = pixels.gradient[side]
        axes[1].plot(centres, row / (row.sum() or 1.0), style, label=label)
    axes[1].set_title("Sobel gradient magnitude")
    axes[1].set_xlabel("magnitude")
    axes[1].set_yscale("log")
    axes[1].legend(fontsize=8)

    summary = pixels.summary()
    metrics = ("mean", "sd", "gradient", "edge_density")
    spots = np.arange(len(metrics))
    for side, (tag, shift) in enumerate((("mask", -0.2), ("background", 0.2))):
        axes[2].bar(spots + shift, [summary.get(f"{tag}_{m}", 0.0) for m in metrics], 0.4, label=tag)
    axes[2].set_xticks(spots, metrics, rotation=20)
    axes[2].set_title("Contrast and edge density")
    axes[2].set_yscale("symlog")
    axes[2].legend(fontsize=8)
    return figure


def _fig_spatial(pixels: Pixels, shapes: dict):
    figure, axes = _panels(1, 3, 15, 4)
    figure.suptitle("Where objects are, and at what spatial frequencies")

    heat = pixels.heat / (pixels.images or 1)
    im = axes[0].imshow(heat, cmap="magma", extent=(0, 1, 1, 0))
    axes[0].set_title("Mask occupancy (sampled)")
    figure.colorbar(im, ax=axes[0], fraction=0.046)

    centres = shapes["centres"]
    im = axes[1].imshow(np.log1p(centres), cmap="viridis", extent=(0, 1, 1, 0))
    axes[1].set_title(f"Bbox centres, log count (all {int(centres.sum())})")
    figure.colorbar(im, ax=axes[1], fraction=0.046)

    axis = np.linspace(0, 1, RADIAL)
    scale = pixels.images or 1
    axes[2].plot(axis, pixels.radial[0] / scale, "-", label="object bbox")
    axes[2].plot(axis, pixels.radial[1] / scale, "--", label="whole frame")
    axes[2].set_title("Radial FFT profile (normalised to DC)")
    axes[2].set_xlabel("spatial frequency, 0 = DC")
    axes[2].legend(fontsize=8)
    return figure


def _fig_geometry(pixels: Pixels, shapes: dict):
    figure, axes = _panels(2, 2, 13, 8)
    figure.suptitle(f"Dataset geometry — top {len(shapes['top'])} classes, every annotation")
    top, per_class = shapes["top"], shapes["per_class"]
    (area_ax, aspect_ax), (scale_ax, shape_ax) = axes

    for name in top:
        values = per_class[name]["area"]
        values = values[values > 0]
        if values.size:
            area_ax.hist(values, bins=np.logspace(-5, 0, 40), histtype="step", label=name)
    area_ax.set_xscale("log")
    area_ax.set_title("Object area / image area")
    area_ax.legend(fontsize=6, ncol=2)

    aspects = [np.clip(per_class[n]["aspect"], 0, 6) for n in top]
    if aspects:
        aspect_ax.boxplot(aspects, tick_labels=top, showfliers=False)
    aspect_ax.tick_params(axis="x", rotation=70, labelsize=7)
    aspect_ax.set_title("Bounding box aspect ratio (w/h, clipped at 6)")

    scale_ax.bar(
        range(len(top)),
        [float(per_class[n]["scale"].std() or 0.0) for n in top],
        color="tab:orange",
    )
    scale_ax.set_xticks(range(len(top)), top, rotation=70, fontsize=7)
    scale_ax.set_title("Scale variance — sd of sqrt(area), px")

    complexity = np.concatenate(
        [per_class[n]["complexity"] for n in top if per_class[n]["complexity"].size] or [np.zeros(0)]
    )
    if complexity.size:
        shape_ax.hist(np.clip(complexity, 0, 20), bins=50, color="tab:green")
    shape_ax.axvline(1.0, color="k", ls="--", lw=1)
    shape_ax.set_title("Mask complexity — P^2/(4·pi·A), 1.0 = circle")
    figure.tight_layout()
    return figure


def _fig_classes(pixels: Pixels, shapes: dict):
    figure, axes = _panels(1, 2, 14, 6)
    figure.suptitle("Class relations")
    top = shapes["top"]
    for ax, data, title, cmap in (
        (axes[0], np.log1p(shapes["cooccurrence"]), "Co-occurrence, log images", "Blues"),
        (axes[1], shapes["overlap"], "Mean bbox IoU between classes", "Reds"),
    ):
        im = ax.imshow(data, cmap=cmap)
        ax.set_xticks(range(len(top)), top, rotation=70, fontsize=7)
        ax.set_yticks(range(len(top)), top, fontsize=7)
        ax.set_title(title)
        figure.colorbar(im, ax=ax, fraction=0.046)
    figure.tight_layout()
    return figure


# --- the run -----------------------------------------------------------------


def analyse(ann_path: str, images_dir: str, out_dir: str, n: int = 200, category: str = ""):
    """Generator yielding (done, total); returns a summary dict when exhausted.

    Same shape as `features.report.write`, and for the same reason: it lets the Qt
    wrapper be a progress bar and nothing else.
    """
    coco = load(ann_path)
    cat = coco.category_id(category) if category else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    shapes = geometry(coco)
    ids = plan(coco, n, cat)
    total = len(ids)
    pixels = Pixels()

    for done, image_id in enumerate(ids, 1):
        got = read(coco, images_dir, image_id, cat)
        if got is not None:
            pixels.add(got[1], got[2])
        yield done, total

    summary = {
        "annotations": sum(len(a) for a in coco.anns.values()),
        "images_in_file": len(coco.images),
        "images_sampled": total,
        "classes": len(coco.names),
        "category": category or "all",
        "crowd_skipped": coco.skipped,
        **pixels.summary(),
    }
    written = _draw(pixels, shapes, out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    return {"dir": str(out), "summary": summary, "figures": written}


def _demo() -> None:
    """The fixture's bright squares must read as brighter than their background."""
    import tempfile

    from .coco import fixture

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ann_path, images_dir = fixture(root, count=4)
        dest = root / "out"

        steps = analyse(ann_path, images_dir, str(dest), n=4, category="square")
        seen, result = [], None
        while result is None:
            try:
                seen.append(next(steps))
            except StopIteration as finished:
                result = finished.value
        assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)], seen

        assert result["figures"] == [f"{n}.png" for n in FIGURES], result["figures"]
        assert json.dumps(result), "the result must be plain data — it crosses a signal"

        summary = result["summary"]
        assert summary["images_sampled"] == 4 and summary["images_measured"] == 4, summary
        assert summary["annotations"] == 4 and summary["crowd_skipped"] == 0

        # The fixture is white squares on dark noise, so every contrast metric has
        # a known direction. A mask/background mix-up flips all four at once.
        assert summary["mask_mean"] > summary["background_mean"] * 3, summary
        assert summary["mean_ratio"] > 3, summary
        assert summary["background_sd"] > 0, "the background is noise, not flat"

        # Every figure exists and has ink on it — savefig writes a valid PNG for an
        # empty axis too, so the file existing proves nothing on its own.
        for name in FIGURES:
            img = cv2.imread(str(dest / f"{name}.png"))
            assert img is not None and img.shape[0] > 100, name
            assert img.std() > 5, f"{name}.png is blank"

        assert json.loads((dest / "summary.json").read_text()) == summary

        # Pass A reads the annotations, not the sample, so it sees all four even
        # when only one image is opened.
        one = _drain(analyse(ann_path, images_dir, str(root / "one"), n=1, category="square"))
        assert one["summary"]["annotations"] == 4, one["summary"]
        assert one["summary"]["images_measured"] == 1, one["summary"]

        # An unknown class is refused before anything is written, with the names.
        try:
            _drain(analyse(ann_path, images_dir, str(root / "no"), n=1, category="aardvark"))
        except ValueError as exc:
            assert "square" in str(exc), exc
        else:
            raise AssertionError("an unknown class must raise")

    # A mask with no background to compare against is not measurable, and must be
    # dropped rather than dividing by zero.
    pixels = Pixels()
    pixels.add(np.full((20, 30, 3), 200, np.uint8), np.full((20, 30), 255, np.uint8))
    assert pixels.images == 0, "a full-frame mask was measured against nothing"

    print("stats ok")


def _drain(steps):
    """Run a generator out and hand back its return value."""
    while True:
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value


if __name__ == "__main__":
    _demo()
