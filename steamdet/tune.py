"""Live parameter tuner: sliders, video playback, contours redrawn as you drag.

Calibrating by editing flags and re-running the CLI is the slow part of this repo,
so this puts the knobs under your fingers. The trick that makes it interactive is
that the expensive half of the pipeline -- reading frames, aligning neighbours,
the temporal median -- does not depend on any knob. Cache that per frame and a
slider only re-runs `plume_mask`: 17 ms on voo_1, 67 ms on voo_2.

Keys: space play/pause . , step  1 2 3 4 view  s save  w write PNG  q quit
"""

import argparse
import time
from dataclasses import asdict

import cv2
import numpy as np

from .plume import (
    ROI_COLOR,
    Config,
    align,
    annotate,
    build_config,
    crop_box,
    plume_masks,
    save_config,
    sources,
    temp_index,
    temporal_stats,
)

WINDOW = "steam-tune"
PANEL = "steam-tune params"  # the knobs live in their own window, or they eat the video

# (trackbar label, Config field, max, scale) -- HighGUI trackbars are integers, so
# the percentile knobs live at x10 and get divided on the way out.
KNOBS = [
    ("p_hi x10", "p_hi", 1000, 10),
    ("p_lo x10", "p_lo", 1000, 10),
    ("p_mot x10", "p_mot", 1000, 10),
    ("tau", "tau", 40, 1),
    ("grad_w x10", "grad_w", 60, 10),
    ("min_area", "min_area", 2000, 1),
    ("grow_hot", "grow_hot", 60, 1),
    ("grow_warm", "grow_warm", 30, 1),
    ("stride", "stride", 60, 1),
    ("window", "window", 5, 1),
    ("p_src x10", "p_src", 1000, 10),
    ("sd_min", "sd_min", 60, 1),
    ("src_close_k", "src_close_k", 31, 1),
    ("src_min_area", "src_min_area", 2000, 1),
    ("roi_margin", "roi_margin", 200, 1),
]
INT_FIELDS = {
    "tau",
    "min_area",
    "grow_hot",
    "grow_warm",
    "stride",
    "window",
    "src_close_k",
    "src_min_area",
    "roi_margin",
}
CLI_FLAGS = ("p_hi", "p_lo", "p_mot", "tau", "grad_w", "window", "stride", "min_area")


class Clip:
    """Video reader that caches raw frames and per-frame temporal statistics."""

    def __init__(self, path: str, scale: float):
        self.cap = cv2.VideoCapture(path)
        ok, first = self.cap.read()
        if not ok:
            raise SystemExit(f"cannot read {path}")
        self.x, self.y, self.w, self.h = crop_box(first)
        self.scale = scale
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._raw: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._stats: dict[tuple, tuple] = {}

    def _at(self, idx: int):
        """(frame, temp) for one raw frame index, cached.

        The cache is what makes playback bearable: stepping forward re-uses the
        neighbours the previous step already decoded, so only one frame is new.
        """
        idx = max(0, min(self.count - 1, idx))
        if idx not in self._raw:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = self.cap.read()
            if not ok:
                return None
            crop = frame[self.y : self.y + self.h, self.x : self.x + self.w]
            if self.scale != 1.0:
                crop = cv2.resize(crop, None, fx=self.scale, fy=self.scale)
            if len(self._raw) > 64:
                self._raw.pop(next(iter(self._raw)))
            self._raw[idx] = (crop, temp_index(crop))
        return self._raw[idx]

    def stats(self, idx: int, cfg):
        """(frame, temp, motion, bg) around sampled frame `idx`. None if unreadable."""
        key = (idx, cfg.window, cfg.stride)
        if key not in self._stats:
            got = [self._at(idx + k * cfg.stride) for k in range(-cfg.window, cfg.window + 1)]
            if any(g is None for g in got):
                return None
            temps = [t for _, t in got]
            center = temps[cfg.window]
            nb = [align(t, center) for i, t in enumerate(temps) if i != cfg.window]
            motion, bg = temporal_stats(center, nb)
            if len(self._stats) > 32:
                self._stats.pop(next(iter(self._stats)))
            self._stats[key] = (got[cfg.window][0], center, motion, bg)
        return self._stats[key]


def read_knobs(base: Config) -> Config:
    """Current trackbar positions as a Config, keeping `base` for untuned fields."""
    values = {}
    for label, field, _, scale in KNOBS:
        raw = cv2.getTrackbarPos(label, PANEL) / scale
        if field in ("stride", "window"):
            raw = max(1, raw)  # a stride or window of zero is a crash, not a setting
        values[field] = int(raw) if field in INT_FIELDS else raw
    return Config(**{**asdict(base), **values})


def render(view: int, stats, found, cfg) -> np.ndarray:
    """1 = frame, 2 = temperature, 3 = motion, 4 = the lava blobs every source came from.

    The contours go on all four, so each map is read against the same result.
    """
    frame, temp, motion, _ = stats
    if view == 2:
        base = cv2.applyColorMap(temp, cv2.COLORMAP_INFERNO)
    elif view == 3:
        base = cv2.applyColorMap(np.clip(motion * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    elif view == 4:
        lava, boxes = sources(temp, cfg)
        base = frame.copy()
        base[lava > 0] = (0, 255, 255)
        for x, y, w, h in boxes:  # every candidate, including the ones later dropped
            cv2.rectangle(base, (x, y), (x + w, y + h), ROI_COLOR, 1)
    else:
        base = frame
    return annotate(base, found)


def hud(img, text: str) -> None:
    for color, thick in (((0, 0, 0), 4), ((255, 255, 255), 1)):
        cv2.putText(img, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, thick, cv2.LINE_AA)


def flag_line(video: str, cfg) -> str:
    knobs = " ".join(f"--{k.replace('_', '-')} {v}" for k, v in asdict(cfg).items() if k in CLI_FLAGS)
    return f"steam-detect {video} --out out/tuned {knobs}"


def main() -> None:
    p = argparse.ArgumentParser(description="Tune plume parameters with sliders, live.")
    p.add_argument("video")
    p.add_argument("--scale", type=float, default=1.0, help="work at this fraction of full size")
    p.add_argument("--config", help="start from a tune.json")
    p.add_argument("--save", default="tune.json", help="where 's' writes the config")
    a = p.parse_args()

    cfg = build_config(a.config)
    clip = Clip(a.video, a.scale)
    if a.scale != 1.0:
        # Areas count pixels of the working image, so half the scale is a quarter of
        # every blob -- at the defaults every source falls under src_min_area and the
        # app finds nothing at all. Divide the two area knobs by scale^2 yourself.
        print(f"scale {a.scale}: divide min_area and src_min_area by {1 / a.scale**2:.0f}")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.namedWindow(PANEL, cv2.WINDOW_NORMAL)
    for label, field, hi, scale in KNOBS:
        cv2.createTrackbar(label, PANEL, int(getattr(cfg, field) * scale), hi, lambda _: None)
    # The seek bar is the one control that belongs on the video, like any player.
    cv2.createTrackbar("frame", WINDOW, 0, max(1, clip.count - 1), lambda _: None)
    cv2.resizeWindow(PANEL, 420, 34 * len(KNOBS))
    panel_strip = np.zeros((1, 420, 3), np.uint8)  # HighGUI needs something to draw

    idx, shown, playing, view = 0, 0, False, 1
    while True:
        cfg = read_knobs(cfg)
        pos = cv2.getTrackbarPos("frame", WINDOW)
        if pos != shown:  # moved by the user, not by us -> seek
            idx = pos

        stats = clip.stats(idx, cfg)
        if stats is None:
            idx = max(0, idx - cfg.stride)
            playing = False
            continue

        t0 = time.perf_counter()
        found = plume_masks(stats[1], stats[2], stats[3], cfg)
        ms = (time.perf_counter() - t0) * 1000

        img = render(view, stats, found, cfg)
        core = sum(int((m == 2).sum()) for *_, m in found)
        halo = sum(int((m == 1).sum()) for *_, m in found)
        hud(
            img,
            f"f{idx} view{view} src={len(found)} core={core} halo={halo}"
            f" {ms:.0f}ms {'>' if playing else '||'}",
        )
        cv2.imshow(WINDOW, img)
        cv2.imshow(PANEL, panel_strip)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord(" "):
            playing = not playing
        elif key == ord("."):
            idx, playing = idx + cfg.stride, False
        elif key == ord(","):
            idx, playing = max(0, idx - cfg.stride), False
        elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
            view = key - ord("0")
        elif key == ord("s"):
            save_config(cfg, a.save)
            print(f"saved {a.save}\n{flag_line(a.video, cfg)}")
        elif key == ord("w"):
            name = f"tuned_{idx:06d}.png"
            cv2.imwrite(name, img)
            print(f"wrote {name}")
        elif playing:
            idx += cfg.stride

        idx = max(0, min(clip.count - 1, idx))
        if idx != shown:
            cv2.setTrackbarPos("frame", WINDOW, idx)
            shown = idx

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
