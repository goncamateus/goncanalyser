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

import json
from collections import deque
from dataclasses import asdict, dataclass, fields
from pathlib import Path

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
    p_src: float = 99.0  # percentile of temp a plume source has to reach
    sd_min: float = 20.0  # local stddev that tells dithered "lava" from smooth hot metal
    src_close_k: int = 7  # closing that glues the dither into one source blob
    src_min_area: int = 120  # drop source blobs smaller than this (px)
    roi_margin: int = 20  # px of slack around each source's region of interest
    grow_hot: int = 30  # geodesic steps along saturated pixels (2 px each)
    grow_warm: int = 8  # then this many steps into merely warm pixels
    open_k: int = 3  # kernel for speckle removal
    close_k: int = 7  # kernel for filling the wispy halo


def build_config(path: str | None = None, **overrides) -> Config:
    """Defaults, then a saved JSON, then whatever was passed explicitly.

    `overrides` come straight from argparse, where a knob nobody typed is None --
    those must not clobber the file, which is the whole point of saving one.
    """
    known = {f.name for f in fields(Config)}
    data = {}
    if path:
        data = {k: v for k, v in json.loads(Path(path).read_text()).items() if k in known}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Config(**data)


def save_config(cfg: Config, path: str) -> None:
    Path(path).write_text(json.dumps(asdict(cfg), indent=2) + "\n")


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


def moving_mask(motion: np.ndarray, bg: np.ndarray, cfg: Config, bar: float | None = None):
    """Pixels changing by more than misregistration can account for.

    How well the frames registered depends on the flight and the resolution -- on
    the 1080p clip half the pixels carry a residual of 7 -- so the bar is a
    percentile of the frame's own residual, exactly like the temperatures. On top
    of that: the drone translates, so a flat affine warp cannot register a 3D
    scene, and sharp static edges (car roofs, equipment rims) leave a residual
    proportional to their gradient. Charge each pixel grad_w px worth of that.
    Gradient measured on the background median, not on the frame -- the plume's own
    speckle is a strong gradient too, and charging it would erase the plume.

    `bar` is passed in when working on a crop, so the threshold stays the whole
    frame's and does not drift with whatever happens to be inside the crop.
    """
    if bar is None:
        bar = max(cfg.tau, np.percentile(motion, cfg.p_mot))
    return motion >= bar + cfg.grad_w * edge_strength(bg)


def plume_mask(
    temp: np.ndarray,
    motion: np.ndarray,
    bg: np.ndarray,
    cfg: Config,
    roi: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """0 = background, 1 = halo, 2 = core, over the whole frame.

    `roi` (x0, y0, x1, y1) confines the segmentation to one source's box. The
    thresholds are still percentiles of the **whole frame** -- a box that is mostly
    plume would push its own p_hi through the roof and then find nothing.
    """
    t_hi = np.percentile(temp, cfg.p_hi)
    t_lo = np.percentile(temp, cfg.p_lo)
    bar = max(cfg.tau, np.percentile(motion, cfg.p_mot))

    shape = temp.shape
    x0, y0, x1, y1 = roi if roi else (0, 0, shape[1], shape[0])
    box = (slice(y0, y1), slice(x0, x1))
    temp, motion, bg = temp[box], motion[box], bg[box]

    moving = moving_mask(motion, bg, cfg, bar)
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

    plume[(plume > 0) & (temp >= t_hi)] = 2
    mask = np.zeros(shape, np.uint8)
    mask[box] = plume
    return mask


def _kernel(k: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def sources(temp: np.ndarray, cfg: Config):
    """(lava mask, boxes) -- where the image looks like lava, i.e. plume sources.

    Above the top of the palette the camera dithers, so the hottest things come out
    speckled instead of flat. That texture is the signature: high local standard
    deviation *and* a temperature in the top percentile. Smooth hot metal fails the
    first test, warm dithered nothing fails the second.

    It finds sources, not plumes -- a dithered heat exchanger looks identical here.
    What throws those out is the next step: no motion above them, no mask, no source.
    """
    f = temp.astype(np.float32)
    mu = cv2.blur(f, (5, 5))
    sd = np.sqrt(np.maximum(cv2.blur(f * f, (5, 5)) - mu * mu, 0))
    lava = ((sd >= cfg.sd_min) & (temp >= np.percentile(temp, cfg.p_src))).astype(np.uint8)
    # Closing glues the speckle into blobs -- but only just. A wider kernel bridges
    # the gap between a plume and the hot equipment beside it and merges the two
    # into one useless box (measured on voo_1: k=7 separates, k=15 does not).
    lava = cv2.morphologyEx(lava, cv2.MORPH_CLOSE, _kernel(cfg.src_close_k))
    n, _, stats, _ = cv2.connectedComponentsWithStats(lava, connectivity=8)
    boxes = [
        tuple(int(v) for v in stats[i, :4])
        for i in range(1, n)
        if stats[i, cv2.CC_STAT_AREA] >= cfg.src_min_area
    ]
    return lava, boxes


def source_roi(box, moving: np.ndarray, cfg: Config) -> tuple[int, int, int, int]:
    """Region of interest for one source: everything above its base, cropped in x.

    Plumes rise, so the base of the source is the floor -- that one line is what
    keeps cars, ground and the plant out, no matter how hot they are. Sideways, the
    box follows the motion that overlaps the source in x, since a plume drifts with
    the wind and the box has to drift with it.
    """
    h_img, w_img = moving.shape
    x, y, w, h = box
    y1 = min(h_img, y + h + cfg.roi_margin)

    n, _, stats, _ = cv2.connectedComponentsWithStats(moving[:y1].astype(np.uint8), 8)
    edges = [x, x + w]
    for i in range(1, n):
        sx, sw, area = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_WIDTH], stats[i, 4]
        if area >= cfg.min_area and sx < x + w and sx + sw > x:
            edges += [int(sx), int(sx + sw)]
    return (
        max(0, min(edges) - cfg.roi_margin),
        0,
        min(w_img, max(edges) + cfg.roi_margin),
        y1,
    )


def plume_masks(temp: np.ndarray, motion: np.ndarray, bg: np.ndarray, cfg: Config):
    """[(roi, source box, mask)] -- one entry per source that actually vents something."""
    _, boxes = sources(temp, cfg)
    moving = moving_mask(motion, bg, cfg)

    found = []
    for box in boxes:
        roi = source_roi(box, moving, cfg)
        mask = plume_mask(temp, motion, bg, cfg, roi)
        if mask.any():  # a static hot blob yields nothing and drops out here
            found.append((roi, box, mask, int((mask > 0).sum())))

    # Sources stack: the vent structure sits right under its own plume and claims it
    # a second time. Biggest claim wins, the duplicates underneath go.
    kept = []
    for roi, box, mask, area in sorted(found, key=lambda f: -f[3]):
        if all(int(((mask > 0) & (k > 0)).sum()) < 0.5 * area for _, _, k in kept):
            kept.append((roi, box, mask))
    return kept


def frame_mask(found, shape) -> np.ndarray:
    """The per-source masks merged into one label image: 0 background, 1 halo, 2 core.

    Where two plumes overlap, `maximum` lets core win over halo -- a pixel that is
    core for anybody is core. Which plume a pixel belongs to is not in here; that
    lives in the boxes the CLI writes alongside.
    """
    mask = np.zeros(shape, np.uint8)
    for _, _, m in found:
        np.maximum(mask, m, out=mask)
    return mask


HALO_COLOR = (0, 255, 0)  # BGR: green, the plume's full extent
CORE_COLOR = (255, 255, 0)  # cyan, the saturated core inside it -- white would
# vanish against the clipped white plume it is drawn on top of
ROI_COLOR = (80, 80, 255)  # red, the box the source was allowed to claim


def outline(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """`frame` with the plume outlined: halo boundary + core boundary."""
    out = frame.copy()
    # The core is speckled, so its raw mask yields a swarm of pinhole contours.
    # Close it first: one outline of where the core is beats a hundred true ones.
    for value, color in ((0, HALO_COLOR), (1, CORE_COLOR)):
        binary = cv2.morphologyEx((mask > value).astype(np.uint8), cv2.MORPH_CLOSE, _kernel(9))
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, color, 2)
    return out


def annotate(frame: np.ndarray, found) -> np.ndarray:
    """`frame` with every plume outlined, its ROI boxed and its index written."""
    out = frame.copy()
    for i, (roi, _, mask) in enumerate(found):
        out = outline(out, mask)
        x0, y0, x1, y1 = roi
        cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), ROI_COLOR, 1)
        cv2.putText(
            out, f"#{i}", (x0 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, ROI_COLOR, 2, cv2.LINE_AA
        )
    return out


def iter_masks(path: str, cfg: Config, max_frames: int | None = None):
    """Yield (frame_index, cropped BGR frame, [(roi, mask)]) for every stride-th frame.

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
        yield c_idx, c_frame, plume_masks(center, motion, bg, cfg)

        emitted += 1
        if max_frames and emitted >= max_frames:
            break
    cap.release()
