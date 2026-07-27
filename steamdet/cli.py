import argparse
from pathlib import Path

import cv2

from .plume import Config, iter_masks

HALO_COLOR = (0, 255, 0)  # BGR: green, the plume's full extent
CORE_COLOR = (255, 255, 0)  # cyan, the saturated core inside it -- white would
# vanish against the clipped white plume it is drawn on top of


def outline(frame, mask):
    """Original frame with the plume outlined: halo boundary + core boundary."""
    out = frame.copy()
    # The core is speckled, so its raw mask yields a swarm of pinhole contours.
    # Close it first: one outline of where the core is beats a hundred true ones.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    for value, color in ((0, HALO_COLOR), (1, CORE_COLOR)):
        binary = cv2.morphologyEx((mask > value).astype("uint8"), cv2.MORPH_CLOSE, k)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, color, 2)
    return out


def main() -> None:
    cfg = Config()
    p = argparse.ArgumentParser(description="Segment thermal steam plume: core + halo.")
    p.add_argument("video")
    p.add_argument("--out", required=True, help="directory for frame_%%06d.png outlines")
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

    for idx, frame, mask in iter_masks(a.video, cfg, a.max_frames):
        cv2.imwrite(str(out / f"frame_{idx:06d}.png"), outline(frame, mask))
        core, halo = int((mask == 2).sum()), int((mask == 1).sum())
        print(f"frame {idx:6d}  core={core:6d}  halo={halo:7d}")


if __name__ == "__main__":
    main()
