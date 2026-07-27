"""One check: the plume moves, the equipment does not, and the halo comes along."""

import numpy as np

from steamdet.plume import (
    Config,
    build_config,
    frame_mask,
    plume_mask,
    plume_masks,
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


def test_label_mask_lets_core_win_over_halo():
    a, b = np.zeros((10, 10), np.uint8), np.zeros((10, 10), np.uint8)
    a[2:8, 2:8] = 1  # one plume's halo
    b[4:6, 4:6] = 2  # another plume's core, overlapping it

    mask = frame_mask([(None, None, a), (None, None, b)], (10, 10))
    assert mask[5, 5] == 2, "core must survive an overlapping halo"
    assert mask[3, 3] == 1 and mask[0, 0] == 0


def test_saved_config_round_trips_and_explicit_flags_win(tmp_path):
    path = str(tmp_path / "tune.json")
    save_config(Config(p_hi=99.5, p_mot=93.0, grow_hot=42), path)

    assert build_config(path) == Config(p_hi=99.5, p_mot=93.0, grow_hot=42)
    # None means "not typed on the command line" and must not clobber the file.
    merged = build_config(path, p_mot=98.5, tau=None)
    assert (merged.p_mot, merged.p_hi, merged.grow_hot) == (98.5, 99.5, 42)
