import argparse
import json
from pathlib import Path

import cv2

from .export import Coco, write_data_yaml, yolo_lines
from .plume import build_config, iter_masks, polygons


def main() -> None:
    p = argparse.ArgumentParser(description="Segment thermal steam plume: core + halo.")
    p.add_argument("video")
    p.add_argument("--out", required=True, help="directory for frame_%%06d.png outlines")
    p.add_argument("--config", help="tune.json written by steam-tune; flags below win over it")
    p.add_argument("--coco", action="store_true", help="also write COCO annotations.json")
    p.add_argument(
        "--yolo",
        action="store_true",
        help="also write YOLO segmentation labels, in images/ + labels/ + data.yaml",
    )
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
    # ultralytics finds labels by swapping /images/ for /labels/ in the image path, so
    # --yolo has to move the frames into images/. Without it everything stays flat.
    images = out / "images" if a.yolo else out
    images.mkdir(parents=True, exist_ok=True)
    if a.yolo:
        (out / "labels").mkdir(exist_ok=True)
    coco = Coco() if a.coco else None

    for idx, frame, found in iter_masks(a.video, cfg, a.max_frames):
        name = f"frame_{idx:06d}"
        size = [frame.shape[1], frame.shape[0]]
        # The image is always untouched -- annotated pixels are for eyes, and eyes
        # have steam-tune. Every label format below is built from the same polygons.
        cv2.imwrite(str(images / f"{name}.png"), frame)
        if a.yolo:
            (out / "labels" / f"{name}.txt").write_text("\n".join(yolo_lines(found, size)) + "\n")
        if coco is not None:
            coco.add(str((images / f"{name}.png").relative_to(out)), size, found)

        meta = {"frame": idx, "size": size, "sources": []}
        if not found:
            print(f"frame {idx:6d}  no source")
        for i, ((x0, y0, x1, y1), box, mask) in enumerate(found):
            core, halo = int((mask == 2).sum()), int((mask == 1).sum())
            meta["sources"].append(
                {
                    "roi": [x0, y0, x1, y1],
                    "box": [int(v) for v in box],
                    "core_px": core,
                    "halo_px": halo,
                    "plume": polygons(mask, 1),  # halo boundary: the whole plume
                    "core": polygons(mask, 2),  # the saturated part inside it
                }
            )
            print(f"frame {idx:6d} #{i} roi={x0},{y0}-{x1},{y1} core={core:6d} halo={halo:7d}")
        (out / f"{name}.json").write_text(json.dumps(meta) + "\n")

    if coco is not None:
        coco.save(out / "annotations.json")
        print(f"wrote {out / 'annotations.json'}: {len(coco.annotations)} annotations")
    if a.yolo:
        write_data_yaml(out / "data.yaml")
        print(f"wrote {out / 'data.yaml'}")


if __name__ == "__main__":
    main()
