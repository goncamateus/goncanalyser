"""Multi-channel colour histograms, drawn with OpenCV rather than a plot library.

The histogram is a picture, and this app already has a fast, correct path for
turning a BGR ndarray into something on screen. Drawing the plot with
`cv2.polylines` reuses that path exactly, so the same function serves the
in-tab preview, the "Histogram" viewer mode and the exported overlay — and adds
no dependency for what is thirty lines of line drawing.

Always on: three `calcHist` calls over a 640x512 frame cost about a millisecond,
which is not worth a checkbox or the bug of forgetting to tick it.
"""

import cv2
import numpy as np

from core.settings import Settings

# space -> (conversion from BGR, channel names, per-channel draw colour in BGR).
# Colours are the channel's own where that means something (R drawn red) and
# merely distinguishable where it does not (there is no colour for "hue").
SPACES: dict[str, tuple[int | None, tuple[str, ...], tuple[tuple[int, int, int], ...]]] = {
    "RGB": (None, ("B", "G", "R"), ((255, 80, 80), (80, 255, 80), (80, 80, 255))),
    "HSV": (cv2.COLOR_BGR2HSV, ("H", "S", "V"), ((255, 128, 0), (0, 200, 255), (230, 230, 230))),
    "LAB": (cv2.COLOR_BGR2LAB, ("L", "a", "b"), ((230, 230, 230), (128, 128, 255), (255, 200, 0))),
}

PLOT_W, PLOT_H = 512, 256
GRID = (60, 60, 60)


def histograms(bgr: np.ndarray, space: str) -> np.ndarray:
    """(3, 256) counts for the chosen space, one row per channel."""
    code, _, _ = SPACES.get(space, SPACES["RGB"])
    img = bgr if code is None else cv2.cvtColor(bgr, code)
    return np.stack(
        [cv2.calcHist([img], [c], None, [256], [0, 256]).ravel() for c in range(3)]
    )


def plot(counts: np.ndarray, space: str, w: int = PLOT_W, h: int = PLOT_H) -> np.ndarray:
    """The histograms as a BGR image: one polyline per channel, plus a legend."""
    _, names, colors = SPACES.get(space, SPACES["RGB"])
    canvas = np.zeros((h, w, 3), np.uint8)
    for i in range(1, 4):  # quarter gridlines, so the shape is readable
        cv2.line(canvas, (w * i // 4, 0), (w * i // 4, h), GRID, 1)
        cv2.line(canvas, (0, h * i // 4), (w, h * i // 4), GRID, 1)

    # One shared scale across the three channels: normalising each on its own
    # would make a flat channel look as busy as a peaked one.
    peak = counts.max() or 1.0
    xs = np.linspace(0, w - 1, 256).astype(np.int32)
    for row, name, color in zip(counts, names, colors):
        ys = (h - 1 - row / peak * (h - 1)).astype(np.int32)
        cv2.polylines(canvas, [np.column_stack((xs, ys))], False, color, 1, cv2.LINE_AA)

    for i, (name, color) in enumerate(zip(names, colors)):
        cv2.putText(
            canvas, name, (8 + i * 22, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA
        )
    return canvas


def run(frame: np.ndarray, s: Settings, out) -> None:
    counts = histograms(frame, s.hist_space)
    out.canvases["Histogram"] = plot(counts, s.hist_space)

    _, names, _ = SPACES.get(s.hist_space, SPACES["RGB"])
    # Bin centres, so the mean is the mean intensity rather than the mean count.
    bins = np.arange(256)
    for row, name in zip(counts, names):
        total = row.sum() or 1.0
        mean = float((row * bins).sum() / total)
        var = float((row * (bins - mean) ** 2).sum() / total)
        out.metrics[f"{name}_mean"] = round(mean, 1)
        out.metrics[f"{name}_sd"] = round(var**0.5, 1)

    out.rows["histogram"] = [
        {"bin": int(b), **{n: int(c) for n, c in zip(names, counts[:, b])}} for b in bins
    ]


def _demo() -> None:
    """Known images have known histograms."""
    black = np.zeros((32, 32, 3), np.uint8)
    counts = histograms(black, "RGB")
    assert counts.shape == (3, 256)
    assert counts[0, 0] == 32 * 32 and counts[0, 1:].sum() == 0, "all black is bin 0"

    grey = np.full((32, 32, 3), 128, np.uint8)
    assert histograms(grey, "RGB")[1, 128] == 32 * 32

    for space in SPACES:
        img = plot(histograms(grey, space), space)
        assert img.shape == (PLOT_H, PLOT_W, 3) and img.dtype == np.uint8, space
        assert img.any(), f"{space} drew nothing"

    # A flat grey image: mean 128, zero spread, in every channel that measures
    # intensity. Guards the bin-centre weighting — a plain row.mean() would give
    # the mean *count*, which is 4.0 here and obviously wrong.
    from core.pipeline import Result

    out = Result()
    run(grey, Settings(hist_space="RGB"), out)
    assert out.metrics["R_mean"] == 128.0, out.metrics
    assert out.metrics["R_sd"] == 0.0, out.metrics
    assert len(out.rows["histogram"]) == 256
    assert out.canvases["Histogram"].shape == (PLOT_H, PLOT_W, 3)

    print("color ok")


if __name__ == "__main__":
    _demo()
