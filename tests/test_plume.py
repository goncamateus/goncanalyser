"""One check: the plume moves, the equipment does not, and the halo comes along."""

import cv2
import numpy as np
import pytest

from steamdet.export import Coco, yolo_lines
from steamdet.plume import (
    Config,
    build_config,
    plume_mask,
    plume_masks,
    polygons,
    save_config,
    sources,
    temporal_stats,
)


def scene(plume_x: int) -> np.ndarray:
    """Cold background + a static hot blob + a hot blob with a warm halo at plume_x."""
    img = np.full((200, 200), 20, np.uint8)
    img[20:60, 20:60] = 250  # static hot equipment
    img[80:140, plume_x - 30 : plume_x + 30] = 160  # halo (warm, not hot)
    img[95:125, plume_x - 12 : plume_x + 12] = 250  # core
    return img


def test_moving_plume_kept_with_halo_static_equipment_dropped():
    cfg = Config(p_hi=98.0, p_lo=85.0, tau=6, min_area=50, close_k=5)
    center = scene(140)
    # neighbours far enough that the plume does not overlap itself: a real plume
    # churns into a different shape between sampled frames, a rigid shift by 4px
    # would not test anything.
    motion, bg = temporal_stats(center, [scene(50), scene(60), scene(60), scene(50)])
    mask = plume_mask(center, motion, bg, cfg)

    assert mask[105, 140] == 2, "plume core missing"
    assert mask[85, 140] == 1, "cooler halo not attached to the core"
    assert mask[20:60, 20:60].sum() == 0, "static hot equipment leaked into the mask"


def dithered(img, box):
    """Paint a saturated checkerboard -- how the camera renders off-scale heat."""
    x0, y0, x1, y1 = box
    img[y0:y1, x0:x1] = 200
    img[y0:y1:2, x0:x1:2] = 255
    img[y0 + 1 : y1 : 2, x0 + 1 : x1 : 2] = 255


def sourced_scene(plume_x: int) -> np.ndarray:
    """Two lava sources -- one venting, one not -- plus a hot 'car' below the vent."""
    img = np.full((240, 240), 20, np.uint8)
    dithered(img, (30, 150, 70, 190))  # static equipment: hot, dithered, vents nothing
    dithered(img, (140, 150, 180, 190))  # the vent
    img[200:220, 130:200] = 190  # hot car, below the vent's base
    img[60:150, plume_x - 30 : plume_x + 30] = 150  # halo above the vent
    img[70:140, plume_x - 12 : plume_x + 12] = 245  # core
    return img


def test_only_the_venting_source_survives_and_stays_above_its_base():
    cfg = Config(p_hi=95.0, p_lo=80.0, p_mot=90.0, min_area=50, src_min_area=100, close_k=5)
    center = sourced_scene(160)
    motion, bg = temporal_stats(
        center, [sourced_scene(60), sourced_scene(70), sourced_scene(70), sourced_scene(60)]
    )

    _, boxes = sources(center, cfg)
    assert len(boxes) == 2, "both dithered blobs are sources"

    found = plume_masks(center, motion, bg, cfg)
    assert len(found) == 1, "the source that vents nothing must drop out"
    (_, _, _, y1), _, mask = found[0]
    assert mask[100, 160] > 0, "plume missing above its own source"
    assert mask[y1:].sum() == 0, "mask reached below the source base"
    assert mask[:, :100].sum() == 0, "mask leaked into the static source's column"


def test_kernel_knobs_at_zero_do_not_blow_up():
    """Every kernel slider can be dragged to 0; that means "no morphology", not a crash."""
    cfg = Config(src_close_k=0, open_k=0, close_k=0, min_area=50, src_min_area=100)
    center = sourced_scene(160)
    motion, bg = temporal_stats(center, [sourced_scene(60), sourced_scene(70)])

    sources(center, cfg)
    plume_masks(center, motion, bg, cfg)


def test_label_polygons_redraw_the_mask_they_came_from():
    """The json is the only label now, so it has to reproduce the mask it replaced."""
    mask = np.zeros((120, 120), np.uint8)
    mask[20:100, 30:90] = 1  # halo
    mask[40:80, 45:75] = 2  # core inside it

    for value in (1, 2):
        drawn = np.zeros_like(mask)
        cv2.fillPoly(drawn, [np.array(p, np.int32) for p in polygons(mask, value)], 1)
        want = (mask >= value).astype(np.uint8)
        agree = int((drawn == want).sum()) / want.size
        assert agree > 0.99, f"polygons for {value} redraw {agree:.1%} of the mask"


def test_dataset_exports_agree_with_the_polygons():
    """A wrong normalisation or a swapped axis silently ruins a whole dataset."""
    mask = np.zeros((100, 200), np.uint8)
    mask[20:60, 40:120] = 1
    mask[30:50, 60:100] = 2
    found = [(None, None, mask)]
    size = [200, 100]

    lines = yolo_lines(found, size)
    assert [line[0] for line in lines] == ["0", "1"], "one plume line, one core line"
    for line in lines:
        coords = [float(v) for v in line.split()[1:]]
        assert len(coords) % 2 == 0
        assert all(0.0 <= v <= 1.0 for v in coords), "yolo coordinates must be normalised"
    # x normalises by width, y by height -- swapping them still yields 0..1 numbers, so
    # check a corner: the plume starts at x=40/200, y=20/100.
    xs = [float(v) for v in lines[0].split()[1::2]]
    ys = [float(v) for v in lines[0].split()[2::2]]
    assert min(xs) == pytest.approx(0.2, abs=0.02) and min(ys) == pytest.approx(0.2, abs=0.02)

    coco = Coco()
    coco.add("frame_000000.png", size, found)
    assert len(coco.images) == 1 and len(coco.annotations) == 2
    plume = coco.annotations[0]
    assert plume["category_id"] == 1 and plume["iscrowd"] == 0
    assert len(plume["segmentation"][0]) % 2 == 0, "COCO segmentation is a flat x,y list"
    x, y, w, h = plume["bbox"]
    assert (x, y) == pytest.approx((40, 20), abs=2) and (w, h) == pytest.approx((80, 40), abs=2)
    assert plume["area"] == pytest.approx(80 * 40, rel=0.1)


def test_saved_config_round_trips_and_explicit_flags_win(tmp_path):
    path = str(tmp_path / "tune.json")
    save_config(Config(p_hi=99.5, p_mot=93.0, grow_hot=42), path)

    assert build_config(path) == Config(p_hi=99.5, p_mot=93.0, grow_hot=42)
    # None means "not typed on the command line" and must not clobber the file.
    merged = build_config(path, p_mot=98.5, tau=None)
    assert (merged.p_mot, merged.p_hi, merged.grow_hot) == (98.5, 99.5, 42)
