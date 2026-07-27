import argparse
from pathlib import Path

import cv2

from .plume import build_config, iter_masks, outline


def main() -> None:
    p = argparse.ArgumentParser(description="Segment thermal steam plume: core + halo.")
    p.add_argument("video")
    p.add_argument("--out", required=True, help="directory for frame_%%06d.png outlines")
    p.add_argument("--config", help="tune.json written by steam-tune; flags below win over it")
    # Every knob defaults to None so build_config can tell "not typed" from "typed".
    p.add_argument("--stride", type=int)
    p.add_argument("--p-hi", type=float)
    p.add_argument("--p-lo", type=float)
    p.add_argument("--p-mot", type=float)
    p.add_argument("--tau", type=int)
    p.add_argument("--grad-w", type=float)
    p.add_argument("--window", type=int)
    p.add_argument("--min-area", type=int)
    p.add_argument("--max-frames", type=int)
    a = p.parse_args()

    cfg = build_config(
        a.config,
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
