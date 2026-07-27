import argparse
from pathlib import Path

import cv2
import numpy as np

from .plume import Config, iter_masks

# 0/127/255 so the PNGs are inspectable straight from Finder, no overlay pipeline.
GRAY = np.array([0, 127, 255], dtype=np.uint8)


def main() -> None:
    cfg = Config()
    p = argparse.ArgumentParser(description="Segment thermal steam plume: core + halo.")
    p.add_argument("video")
    p.add_argument("--out", required=True, help="directory for frame_%%06d.png masks")
    p.add_argument("--stride", type=int, default=cfg.stride)
    p.add_argument("--p-hi", type=float, default=cfg.p_hi)
    p.add_argument("--p-lo", type=float, default=cfg.p_lo)
    p.add_argument("--p-mot", type=float, default=cfg.p_mot)
    p.add_argument("--tau", type=int, default=cfg.tau)
    p.add_argument("--grad-w", type=float, default=cfg.grad_w)
    p.add_argument("--window", type=int, default=cfg.window)
    p.add_argument("--min-area", type=int, default=cfg.min_area)
    p.add_argument("--max-frames", type=int, default=None)
    a = p.parse_args()

    cfg = Config(
        p_hi=a.p_hi,
        p_lo=a.p_lo,
        p_mot=a.p_mot,
        tau=a.tau,
        grad_w=a.grad_w,
        window=a.window,
        stride=a.stride,
        min_area=a.min_area,
    )
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    for idx, mask in iter_masks(a.video, cfg, a.max_frames):
        cv2.imwrite(str(out / f"frame_{idx:06d}.png"), GRAY[mask])
        core, halo = int((mask == 2).sum()), int((mask == 1).sum())
        print(f"frame {idx:6d}  core={core:6d}  halo={halo:7d}")


if __name__ == "__main__":
    main()
