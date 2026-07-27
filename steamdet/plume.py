"""Segment a steam plume into hot core + cooler halo, on drone thermal video.

The plume and the hot equipment below it look the same to a threshold: both are
bright. What separates them is that the plume churns and the equipment does not.
So every mask here is (bright enough) AND (changing in time), with the drone's
own motion cancelled out first by aligning neighbour frames onto the current one.

The cooler halo is recovered by hysteresis: a lukewarm pixel joins the plume only
if it is connected to a core pixel. That is the "arredor mais frio que ainda faz
parte" -- warm but static ground never connects, and warm moving vegetation never
touches the core.
"""

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np


def temp_index(bgr: np.ndarray) -> np.ndarray:
    """Relative temperature (uint8) = the L channel of HLS.

    The video is not radiometric: the camera baked a colormap into the pixels.
    Along that palette (black -> purple -> red -> orange -> yellow -> white) HLS
    lightness rises monotonically, so L is a temperature proxy -- checked against
    a full inverse-LUT reconstruction on these clips, r = 0.96. It is *relative*:
    the camera runs AGC, so the same L is not the same temperature in the next
    frame. Threshold by percentile, never by a fixed value.
    """
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HLS)[:, :, 1]


@dataclass
class Config:
    # All of these are calibration knobs, not constants -- see README.
    p_hi: float = 99.0  # percentile of temp index for the saturated core
    p_lo: float = 90.0  # percentile below which a pixel is background, period
    p_mot: float = 95.0  # percentile of the residual above which a pixel is "moving"
    tau: int = 6  # floor for that threshold, so a static scene stays empty
    grad_w: float = 1.5  # px of residual misalignment tolerated (see plume_mask)
    window: int = 2  # neighbour frames on each side used for the median
    stride: int = 10  # process every Nth video frame
    min_area: int = 200  # drop plume components smaller than this (px)
    grow_hot: int = 30  # geodesic steps along saturated pixels (2 px each)
    grow_warm: int = 8  # then this many steps into merely warm pixels
    open_k: int = 3  # kernel for speckle removal
    close_k: int = 7  # kernel for filling the wispy halo


def crop_box(frame: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the non-letterboxed image (no-op when there are no bars)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.boundingRect((gray > 2).astype(np.uint8))


def align(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Warp `src` onto `dst` (both uint8) via ORB + partial affine. None if it fails."""
    orb = cv2.ORB_create(500)
    k1, d1 = orb.detectAndCompute(src, None)
    k2, d2 = orb.detectAndCompute(dst, None)
    if d1 is None or d2 is None or len(k1) < 10 or len(k2) < 10:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    if len(matches) < 10:
        return None
    p1 = np.float32([k1[m.queryIdx].pt for m in matches])
    p2 = np.float32([k2[m.trainIdx].pt for m in matches])
    M, _ = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None:
        return None
    h, w = dst.shape
    # REPLICATE so pixels pulled in from outside read as "same as the edge" rather
    # than as a hard black/white step that would fake motion along the border.
    return cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def temporal_stats(center: np.ndarray, neighbours: list[np.ndarray]):
    """(motion, background) where background is the median of the aligned neighbours.

    The median across frames keeps whatever stays put (the plant) and washes out
    whatever moves (the plume), so it doubles as a plume-free reference image.
    Neighbours that failed to align are dropped; with none left the frame reads as
    zero motion, which yields an empty mask rather than a wrong one.
    """
    good = [n for n in neighbours if n is not None]
    if not good:
        return np.zeros(center.shape, np.int16), center
    bg = np.median(np.stack(good), axis=0).astype(np.int16)
    return np.abs(center.astype(np.int16) - bg), bg


def edge_strength(temp: np.ndarray) -> np.ndarray:
    """Sobel magnitude, dilated: how much a 1 px misalignment would cost here."""
    gx = cv2.Sobel(temp.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(temp.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3) / 8.0
    return cv2.dilate(cv2.magnitude(gx, gy), _kernel(5))


def plume_mask(temp: np.ndarray, motion: np.ndarray, bg: np.ndarray, cfg: Config) -> np.ndarray:
    """0 = background, 1 = halo, 2 = core."""
    t_hi = np.percentile(temp, cfg.p_hi)
    t_lo = np.percentile(temp, cfg.p_lo)
    # How well the frames registered depends on the flight and the resolution --
    # on the 1080p clip half the pixels carry a residual of 7 -- so the motion bar
    # is a percentile of this frame's own residual, exactly like the temperatures.
    # On top of that: the drone translates, so a flat affine warp cannot register a
    # 3D scene, and sharp static edges (car roofs, equipment rims) leave a residual
    # proportional to their gradient. Charge each pixel grad_w px worth of that.
    # Gradient measured on the background median, not on the frame -- the plume's
    # own speckle is a strong gradient too, and charging it would erase the plume.
    bar = max(cfg.tau, np.percentile(motion, cfg.p_mot))
    moving = motion >= bar + cfg.grad_w * edge_strength(bg)

    seed = ((temp >= t_hi) & moving).astype(np.uint8)
    cand = ((temp >= t_lo) & moving).astype(np.uint8)

    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, _kernel(cfg.open_k))
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, _kernel(cfg.close_k))
    cand |= seed  # closing must never eat the seeds

    _, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = [
        lab
        for lab in np.unique(labels[seed > 0])
        if lab != 0 and stats[lab, cv2.CC_STAT_AREA] >= cfg.min_area
    ]
    plume = np.isin(labels, keep).astype(np.uint8) if keep else np.zeros_like(cand)

    # The anchored part of the jet is invisible to the motion test: it is clipped
    # white in every frame, so its residual is zero no matter how hard it churns.
    # Grow the mask back along whatever is connected to what we did find -- first
    # through the saturated column, then a few steps into the cooler halo around
    # it. Bounded steps, so a leak into the plant can only travel so far.
    for k, steps in ((t_hi, cfg.grow_hot), (t_lo, cfg.grow_warm)):
        reach = (temp >= k).astype(np.uint8)
        for _ in range(steps):
            plume |= cv2.dilate(plume, _kernel(5)) & reach

    mask = plume.copy()
    mask[(plume > 0) & (temp >= t_hi)] = 2
    return mask


def _kernel(k: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def iter_masks(path: str, cfg: Config, max_frames: int | None = None):
    """Yield (frame_index, cropped BGR frame, mask) for every stride-th frame.

    Frames only start coming out once the buffer holds a full window, so the first
    `window` sampled frames have no output of their own.
    """
    cap = cv2.VideoCapture(path)
    ok, first = cap.read()
    if not ok:
        raise SystemExit(f"cannot read {path}")

    x, y, w, h = crop_box(first)
    print(f"crop={w}x{h}+{x}+{y}")

    buf: deque[tuple[int, np.ndarray, np.ndarray]] = deque(maxlen=2 * cfg.window + 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    idx, emitted = -1, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % cfg.stride:
            continue
        crop = frame[y : y + h, x : x + w]
        buf.append((idx, crop, temp_index(crop)))
        if len(buf) < buf.maxlen:
            continue

        c_idx, c_frame, center = buf[cfg.window]
        neighbours = [align(t, center) for i, (_, _, t) in enumerate(buf) if i != cfg.window]
        motion, bg = temporal_stats(center, neighbours)
        yield c_idx, c_frame, plume_mask(center, motion, bg, cfg)

        emitted += 1
        if max_frames and emitted >= max_frames:
            break
    cap.release()
