"""Live parameter tuner: sliders, video playback, contours redrawn as you drag.

Calibrating by editing flags and re-running the CLI is the slow part of this repo,
so this puts the knobs under your fingers. The trick that makes it interactive is
that the expensive half of the pipeline -- reading frames, aligning neighbours,
the temporal median -- does not depend on any knob. Cache that per frame and a
slider only re-runs `plume_mask`: 17 ms on voo_1, 67 ms on voo_2.

Keys: space play/pause . , step  1 2 3 view  s save  w write PNG  q quit
"""

import argparse
import time
from dataclasses import asdict

import cv2
import numpy as np

from .plume import (
    Config,
    align,
    build_config,
    crop_box,
    outline,
    plume_mask,
    save_config,
    temp_index,
    temporal_stats,
)

WINDOW = "steam-tune"

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
]
INT_FIELDS = {"tau", "min_area", "grow_hot", "grow_warm", "stride", "window"}
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
        raw = cv2.getTrackbarPos(label, WINDOW) / scale
        if field in ("stride", "window"):
            raw = max(1, raw)  # a stride or window of zero is a crash, not a setting
        values[field] = int(raw) if field in INT_FIELDS else raw
    return Config(**{**asdict(base), **values})


def render(view: int, stats, mask) -> np.ndarray:
    """View 1 = frame, 2 = temperature, 3 = motion. Contours drawn on all three."""
    frame, temp, motion, _ = stats
    if view == 2:
        base = cv2.applyColorMap(temp, cv2.COLORMAP_INFERNO)
    elif view == 3:
        base = cv2.applyColorMap(np.clip(motion * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    else:
        base = frame
    return outline(base, mask)


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

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    for label, field, hi, scale in KNOBS:
        cv2.createTrackbar(label, WINDOW, int(getattr(cfg, field) * scale), hi, lambda _: None)
    cv2.createTrackbar("frame", WINDOW, 0, max(1, clip.count - 1), lambda _: None)

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
        mask = plume_mask(stats[1], stats[2], stats[3], cfg)
        ms = (time.perf_counter() - t0) * 1000

        img = render(view, stats, mask)
        core, halo = int((mask == 2).sum()), int((mask == 1).sum())
        hud(img, f"f{idx} view{view} core={core} halo={halo} mask={ms:.0f}ms {'>' if playing else '||'}")
        cv2.imshow(WINDOW, img)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord(" "):
            playing = not playing
        elif key == ord("."):
            idx, playing = idx + cfg.stride, False
        elif key == ord(","):
            idx, playing = max(0, idx - cfg.stride), False
        elif key in (ord("1"), ord("2"), ord("3")):
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
