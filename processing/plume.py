"""Single-frame steam plume segmentation for thermal video.

Ported from this repo's earlier `steamdet/plume.py` (git commit 9fdd3dd^) with
the temporal half removed. The original ANDed three cues together — hot, textured
and *moving* — and got the motion term by aligning neighbouring frames. Camera
motion compensation never worked well enough on the drone clips to be worth its
cost, so this keeps the two cues that need only the frame in front of you.

What is left still separates a plume from the plant, because a plume differs from
hot equipment in more than one way:

    temperature   the plume is in the top percentiles of the frame
    texture       above the top of the camera's palette the sensor dithers, so
                  the hottest things come out speckled, not flat. High local
                  sigma is the plume's signature; smooth hot metal fails it
    geometry      plumes rise, so a source's search region is everything above
                  its own base. That one line keeps hot ground, cars and pipework
                  out of the mask no matter how bright they are

Every threshold is a *percentile* of the frame, never a fixed grey level: the
camera runs AGC, so the same brightness is not the same temperature two seconds
later. That is also why the adjustment sliders in Section A must be left alone
once you have calibrated here — they move the histogram this section measures.

Masks use 0 = background, 1 = halo, 2 = core, so one array carries both extents.
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PlumeConfig:
    """The tuning knobs, mirroring the sliders in Section B."""

    p_src: float = 99.0  # temperature percentile a source has to reach
    sd_min: float = 20.0  # local sigma a *source* needs: the dither signature
    src_close_k: int = 7  # closing that glues the dither speckle into one blob
    src_min_area: int = 120  # drop source blobs smaller than this (px)
    p_hi: float = 99.0  # percentile for the saturated core
    p_lo: float = 90.0  # below this a pixel is background, period
    sd_plume: float = 8.0  # local sigma a plume *pixel* needs; 0 disables the test
    open_k: int = 3  # speckle removal
    close_k: int = 7  # fills the wispy halo
    min_area: int = 200  # drop plume components smaller than this (px)
    grow_hot: int = 30  # geodesic steps along saturated pixels (2 px each)
    grow_warm: int = 8  # then this many steps into merely warm pixels
    roi_margin: int = 20  # px of slack around each source's search box


HALO_COLOR = (0, 255, 0)  # BGR green: the plume's full extent
CORE_COLOR = (255, 255, 0)  # cyan: the saturated core — white would vanish on white
ROI_COLOR = (80, 80, 255)  # red: the box a source was allowed to claim
PICK_COLOR = (0, 255, 255)  # yellow: the one a human labelled as the real plume


def temp_index(bgr: np.ndarray, code: int = cv2.COLOR_BGR2HLS, channel: int = 1) -> np.ndarray:
    """Relative temperature (uint8): one channel of one colour space.

    The default is the L channel of HLS. The video is not radiometric — the
    camera baked a colormap into the pixels — but along that palette (black ->
    purple -> red -> orange -> yellow -> white) HLS lightness rises
    monotonically, so L is a temperature proxy, checked against a full
    inverse-LUT reconstruction on these clips at r = 0.96.

    It is *relative* whichever channel you pick: threshold by percentile, never
    by a fixed value, because the camera runs AGC.

    `code`/`channel` come from Section A's colour space, so the panel picks what
    the detector measures rather than only what the screen shows.
    """
    converted = cv2.cvtColor(bgr, code)
    return converted if converted.ndim == 2 else converted[:, :, channel]


def kernel(k: int) -> np.ndarray:
    """Elliptical structuring element. A slider at zero means "no morphology",
    which OpenCV spells 1x1 — `getStructuringElement` throws on 0x0."""
    k = max(1, int(k))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def local_sigma(temp: np.ndarray, win: int = 5) -> np.ndarray:
    """Standard deviation in a `win` x `win` window, via the E[x^2] - E[x]^2 trick.

    Two box filters instead of a per-pixel loop: on a 1080p frame that is the
    difference between a slider you can drag and one you cannot.
    """
    f = temp.astype(np.float32)
    mu = cv2.blur(f, (win, win))
    return np.sqrt(np.maximum(cv2.blur(f * f, (win, win)) - mu * mu, 0))


def sources(temp: np.ndarray, sigma: np.ndarray, cfg: PlumeConfig) -> list[tuple[int, int, int, int]]:
    """Boxes around the places that look like a vent: hot *and* dithered.

    Smooth hot metal fails the sigma test, warm dithered nothing fails the
    temperature test. Only where both hold does the image look like the top of the
    palette, which is where steam leaves a pipe.

    The closing is deliberately small. A wider kernel bridges the gap between a
    plume and the hot equipment beside it and merges the two into one useless box
    — measured on voo_1, k=7 separates them and k=15 does not.
    """
    lava = ((sigma >= cfg.sd_min) & (temp >= np.percentile(temp, cfg.p_src))).astype(np.uint8)
    lava = cv2.morphologyEx(lava, cv2.MORPH_CLOSE, kernel(cfg.src_close_k))
    count, _, stats, _ = cv2.connectedComponentsWithStats(lava, connectivity=8)
    return [
        tuple(int(v) for v in stats[i, :4])
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= cfg.src_min_area
    ]


def source_roi(box, shape, cfg: PlumeConfig) -> tuple[int, int, int, int]:
    """Search region for one source: everything above its base, padded sideways.

    Plumes rise. Cutting the region off at the bottom of the source box is the
    single cheapest way to keep hot ground, vehicles and pipe runs out of the
    mask — they are as bright as the plume, but they are never above it.

    The cut is *exactly* the source base, with no downward slack. The original
    padded below by `roi_margin` and could afford to, because its motion cue
    rejected the static equipment that padding let in. Without motion the growth
    step walks straight down into any hot slab under the vent, so the geometry
    has to do that work alone. `roi_margin` still pads sideways, where a plume
    genuinely drifts with the wind.
    """
    h_img, w_img = shape
    x, y, w, h = box
    return (
        max(0, x - cfg.roi_margin),
        0,
        min(w_img, x + w + cfg.roi_margin),
        min(h_img, y + h),
    )


def plume_mask(temp: np.ndarray, sigma: np.ndarray, cfg: PlumeConfig, roi=None) -> np.ndarray:
    """0 = background, 1 = halo, 2 = core, over the whole frame.

    `roi` (x0, y0, x1, y1) confines the segmentation to one source's box. The
    thresholds are still percentiles of the **whole frame** — a box that is mostly
    plume would push its own p_hi through the roof and then find nothing.

    Every test below is `hot AND textured`. The original ANDed `hot AND moving`
    here; with motion gone, texture is what carries the discrimination. Dropping
    it entirely does not work: a smooth hot slab of equipment touching the base of
    the plume is above every temperature threshold, so the growth step walks
    straight out of the plume and fills the plant. `sd_plume = 0` disables the
    test if you ever want that behaviour back.
    """
    t_hi = np.percentile(temp, cfg.p_hi)
    t_lo = np.percentile(temp, cfg.p_lo)

    shape = temp.shape
    x0, y0, x1, y1 = roi if roi else (0, 0, shape[1], shape[0])
    box = (slice(y0, y1), slice(x0, x1))
    temp = temp[box]
    rough = sigma[box] >= cfg.sd_plume if cfg.sd_plume else np.ones(temp.shape, bool)

    seed = ((temp >= t_hi) & rough).astype(np.uint8)
    cand = ((temp >= t_lo) & rough).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, kernel(cfg.open_k))
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, kernel(cfg.close_k))
    cand |= seed  # the closing must never eat the seeds

    # Keep only the blobs that actually contain a core pixel, and only if they are
    # big enough to be a plume rather than a speck of sensor noise.
    _, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = [
        lab
        for lab in np.unique(labels[seed > 0])
        if lab != 0 and stats[lab, cv2.CC_STAT_AREA] >= cfg.min_area
    ]
    plume = np.isin(labels, keep).astype(np.uint8) if keep else np.zeros_like(cand)

    # Hysteresis growth: walk out from what was found, first through the saturated
    # column and then a few steps into the cooler halo around it. Bounded steps, so
    # a leak into the plant can only travel so far.
    #
    # The reach is temperature *only* — deliberately looser than `cand` above,
    # which also demands texture. That gap is the entire mechanism: if the reach
    # were the same predicate the candidate blob was built from, every pixel it
    # could add would already be in the blob's connected component, and both
    # sliders would move nothing at all. What growth recovers is the part of the
    # plume that is hot and connected but *smooth* — a clipped, saturated column
    # reads as flat, and the wispy outer halo is only half textured.
    for level, steps in ((t_hi, cfg.grow_hot), (t_lo, cfg.grow_warm)):
        reach = (temp >= level).astype(np.uint8)
        for _ in range(steps):
            plume |= cv2.dilate(plume, kernel(5)) & reach

    plume[(plume > 0) & (temp >= t_hi)] = 2
    mask = np.zeros(shape, np.uint8)
    mask[box] = plume
    return mask


def plume_masks(temp: np.ndarray, cfg: PlumeConfig) -> list[tuple[tuple, tuple, np.ndarray]]:
    """[(roi, source box, mask)] — one entry per source that actually vents.

    The local sigma is computed once here and threaded through both stages: it is
    two box filters over the whole frame, and recomputing it per source would be
    the most expensive thing in the module.
    """
    sigma = local_sigma(temp)
    found = []
    for box in sources(temp, sigma, cfg):
        roi = source_roi(box, temp.shape, cfg)
        mask = plume_mask(temp, sigma, cfg, roi)
        if mask.any():
            found.append((roi, box, mask, int((mask > 0).sum())))

    # Sources stack: the vent structure sits right under its own plume and claims
    # it a second time. Biggest claim wins; the duplicates underneath go. This
    # pass *must* run largest-first — that is what "biggest claim" means.
    kept: list[tuple[tuple, tuple, np.ndarray]] = []
    for roi, box, mask, area in sorted(found, key=lambda f: -f[3]):
        if all(int(((mask > 0) & (k > 0)).sum()) < 0.5 * area for _, _, k in kept):
            kept.append((roi, box, mask))

    # Number them left to right, x = 0 to x = width. Area order is an artefact of
    # the dedup above and makes #0 jump between sources the moment one grows past
    # another; position is stable, so a label keeps meaning the same vent from
    # frame to frame and while you drag a slider.
    return sorted(kept, key=lambda entry: (entry[1][0], entry[1][1]))


def polygons(mask: np.ndarray, value: int) -> list[np.ndarray]:
    """Outlines of `mask >= value`.

    The core is speckled, so its raw mask yields a swarm of pinhole contours;
    closing first gives one outline of where the core is instead of a hundred
    true ones.
    """
    binary = cv2.morphologyEx((mask >= value).astype(np.uint8), cv2.MORPH_CLOSE, kernel(9))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.approxPolyDP(c, 1.0, True) for c in contours if cv2.contourArea(c) >= 32]


def annotate(bgr: np.ndarray, found, boxes: bool = True, chosen: int | None = None) -> np.ndarray:
    """`bgr` with every plume outlined, drawn on a copy.

    Halo and core are drawn as separate outlines rather than as a filled mask, so
    you can still see the footage underneath while tuning — which is the whole
    point of a live tuner.

    `chosen` is the index a human labelled as the real plume. It is drawn thicker
    and ticked, because pressing a number key has to be visibly acknowledged —
    otherwise there is no way to tell a registered pick from a missed keystroke.
    """
    out = bgr.copy()
    for i, (roi, _, mask) in enumerate(found):
        picked = i == chosen
        for value, color in ((1, HALO_COLOR), (2, CORE_COLOR)):
            cv2.polylines(out, polygons(mask, value), True, color, 3 if picked else 2)
        if boxes:
            x0, y0, x1, y1 = roi
            color = PICK_COLOR if picked else ROI_COLOR
            cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), color, 2 if picked else 1)
            cv2.putText(
                out, f"#{i}" + (" OK" if picked else ""), (x0 + 4, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA,
            )
    return out


def heatmap(temp: np.ndarray) -> np.ndarray:
    """The temperature index as false colour — what the thresholds actually see."""
    return cv2.applyColorMap(temp, cv2.COLORMAP_INFERNO)


def _scene(columns, slab: bool) -> np.ndarray:
    """A synthetic thermal frame: dithered plume columns, optionally over a slab.

    `columns` is [(centre x, top y)]. Each is speckled, because that dither above
    the top of the palette is the only thing marking a plume as a plume here.
    """
    rng = np.random.default_rng(11)
    frame = np.full((240, 320, 3), 40, np.uint8)
    if slab:
        # Smooth hot equipment across the bottom: bright, flat, must be rejected.
        cv2.rectangle(frame, (0, 190), (320, 240), (255, 255, 255), -1)
    for cx, top in columns:
        for y in range(top, 195):
            width = 8 + (195 - y) // 8  # widens as it rises, like a real plume
            for x in range(cx - width, cx + width):
                if rng.random() < 0.65:
                    frame[y, x] = (255, 255, 255)
                elif rng.random() < 0.5:
                    frame[y, x] = (170, 170, 200)  # the cooler halo around the core
    return frame


def _demo() -> None:
    """Two scenes, because they test different things and interfere with each other.

    The slab is the point of the first: it is *hotter* than parts of the plume
    and it is not moving, so temperature alone cannot reject it — only the
    texture test and the plumes-rise geometry can. But its top edge is a
    full-width ridge of high local sigma, and that ridge bridges two columns into
    one source, which is exactly what the second scene must not have.
    """
    cfg = PlumeConfig(p_src=95.0, sd_min=12.0, sd_plume=8.0, p_hi=95.0, p_lo=70.0, min_area=50)

    # --- one vent over hot equipment: the equipment must stay out --------------
    frame = _scene([(150, 60)], slab=True)
    temp = temp_index(frame)
    sigma = local_sigma(temp)
    assert sigma[120, 150] > sigma[215, 160], "the dithered column must out-texture the slab"

    found = plume_masks(temp, cfg)
    assert found, "no plume found at all"
    mask = found[0][2]
    assert (mask[60:190, 130:170] > 0).mean() > 0.5, "most of the column should be masked"
    assert (mask[210:240] > 0).mean() < 0.05, "the smooth hot slab must stay out of the mask"
    assert (mask == 2).any(), "a core should have been marked inside the halo"

    # Annotation must not scribble on the caller's frame.
    before = frame.copy()
    annotate(frame, found)
    assert (frame == before).all(), "annotate wrote into its input"

    # --- two vents: numbering runs left to right, never by size ---------------
    # The right column is the taller one, so it masks more pixels — which is what
    # would put it at #0 if the dedup pass's area ordering leaked into the result.
    pair = temp_index(_scene([(90, 100), (220, 40)], slab=False))
    both = plume_masks(pair, cfg)
    assert len(both) == 2, f"expected both vents, got {len(both)}"

    xs = [box[0] for _, box, _ in both]
    areas = [int((m > 0).sum()) for *_, m in both]
    assert xs == sorted(xs), f"sources are not ordered left to right: {xs}"
    assert areas[1] > areas[0], "toothless unless the right-hand plume is the larger one"

    print(f"plume ok — vents left-to-right at x={xs}, areas={areas}")


if __name__ == "__main__":
    _demo()
