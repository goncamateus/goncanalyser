"""Global texture descriptors: Histograms of Oriented Gradients, Local Binary Patterns.

Both come from scikit-image. OpenCV's `HOGDescriptor` is built for the pedestrian
detector — it has no visualisation and a rigid window contract — and OpenCV has
no LBP in its Python API at all. `skimage.feature` gives both as one call each,
with the reference parameterisation.

**HOG is the expensive thing in this app**: roughly 150-300 ms on a 640x512
frame, which is slower than a video frame arrives. It runs on the worker thread
so the window never freezes, but playback will drop frames while it is on. That
is why it is off by default and why the tab says so.
"""

from dataclasses import replace

import cv2
import numpy as np
from skimage.feature import hog, local_binary_pattern

from core.settings import Settings

from .adjust import to_bgr, to_gray

LBP_METHODS = ("uniform", "default", "ror", "nri_uniform", "var")


def hog_of(gray: np.ndarray, s: Settings) -> tuple[np.ndarray, np.ndarray]:
    """(descriptor vector, visualisation as uint8)."""
    cell = max(2, int(s.hog_cell))
    block = max(1, int(s.hog_block))
    vector, image = hog(
        gray,
        orientations=max(2, int(s.hog_orientations)),
        pixels_per_cell=(cell, cell),
        cells_per_block=(block, block),
        visualize=True,
        feature_vector=True,
    )
    return vector, cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def lbp_of(gray: np.ndarray, s: Settings) -> np.ndarray:
    """LBP codes as a float array, in whatever range the method produces."""
    return local_binary_pattern(
        gray,
        P=max(1, int(s.lbp_points)),
        R=max(1, int(s.lbp_radius)),
        method=s.lbp_method,
    )


def run(frame: np.ndarray, s: Settings, out) -> None:
    if not (s.hog_on or s.lbp_on):
        return
    gray = to_gray(frame)

    if s.hog_on:
        vector, image = hog_of(gray, s)
        out.canvases["HOG"] = to_bgr(image)
        out.metrics["hog_dim"] = int(vector.size)
        out.metrics["hog_mean"] = round(float(vector.mean()), 4)

    if s.lbp_on:
        codes = lbp_of(gray, s)
        # Stretch to the full 0..255 range for display: "uniform" tops out at
        # P + 1 (10 by default), which as raw greys is a black rectangle.
        out.canvases["LBP"] = to_bgr(
            cv2.normalize(codes, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        )
        # One bin per distinct code. "var" is continuous, so cap the bin count
        # rather than trying to enumerate every float it produces.
        top = int(codes.max()) + 1
        counts = np.bincount(codes.astype(np.int64).ravel(), minlength=top)[: min(top, 256)]
        share = counts / (counts.sum() or 1)
        out.metrics["lbp_bins"] = int(len(counts))
        # Entropy is the one number that says whether the texture is varied or
        # dominated by one pattern, which is what the descriptor is for.
        nonzero = share[share > 0]
        out.metrics["lbp_entropy"] = round(float(-(nonzero * np.log2(nonzero)).sum()), 3)
        out.rows["lbp"] = [{"code": i, "count": int(c)} for i, c in enumerate(counts)]


def _demo() -> None:
    """Textured and flat images must not describe the same."""
    from core.pipeline import Result

    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (64, 64), dtype=np.uint8)
    flat = np.full((64, 64), 128, np.uint8)
    base = Settings(hog_on=True, lbp_on=True)

    # HOG length is fully determined by the geometry; getting it wrong silently
    # is the classic HOG bug, so pin it against the formula.
    vector, image = hog_of(noise, base)
    cells = 64 // base.hog_cell
    blocks = cells - base.hog_block + 1
    expected = blocks * blocks * base.hog_block**2 * base.hog_orientations
    assert vector.size == expected, f"{vector.size} != {expected}"
    assert image.shape == noise.shape and image.dtype == np.uint8

    # "uniform" is defined to produce codes in 0..P+1 and nothing outside it.
    codes = lbp_of(noise, base)
    assert codes.min() >= 0 and codes.max() <= base.lbp_points + 1, (codes.min(), codes.max())
    for method in LBP_METHODS:
        assert lbp_of(flat, replace(base, lbp_method=method)).shape == flat.shape, method

    def measure(img, s=base):
        out = Result()
        run(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), s, out)
        return out

    busy, plain = measure(noise), measure(flat)
    assert busy.metrics["lbp_entropy"] > plain.metrics["lbp_entropy"], "noise must be busier"
    assert busy.canvases["HOG"].shape[:2] == noise.shape
    assert busy.canvases["LBP"].shape[:2] == noise.shape
    assert len(busy.rows["lbp"]) == busy.metrics["lbp_bins"]

    # Off is off — this is the gate that keeps a 200 ms call off the video path.
    off = measure(noise, Settings())
    assert not off.metrics and not off.canvases

    print("texture ok")


if __name__ == "__main__":
    _demo()
