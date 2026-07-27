"""One check: the plume moves, the equipment does not, and the halo comes along."""

import numpy as np

from steamdet.plume import Config, build_config, plume_mask, save_config, temporal_stats


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


def test_saved_config_round_trips_and_explicit_flags_win(tmp_path):
    path = str(tmp_path / "tune.json")
    save_config(Config(p_hi=99.5, p_mot=93.0, grow_hot=42), path)

    assert build_config(path) == Config(p_hi=99.5, p_mot=93.0, grow_hot=42)
    # None means "not typed on the command line" and must not clobber the file.
    merged = build_config(path, p_mot=98.5, tau=None)
    assert (merged.p_mot, merged.p_hi, merged.grow_hot) == (98.5, 99.5, 42)
