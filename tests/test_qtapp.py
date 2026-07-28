"""Checks for the Qt app's pure half: adjustments, contours, and the saved session.

No QApplication is created, so this runs headless. The widget wiring is not tested --
that is what running `steam-gui` is for.
"""

import numpy as np

from steamdet.plume import Config
from steamdet.qtapp import Settings, adjust, confine, contours_of, load_session, save_session, to_space


def frame() -> np.ndarray:
    """A mid-grey ramp with colour in it, so saturation and gamma both have something."""
    img = np.zeros((40, 60, 3), np.uint8)
    img[:, :, 0] = np.linspace(30, 220, 60, dtype=np.uint8)
    img[:, :, 1] = 90
    img[:, :, 2] = 160
    return img


def test_adjustments():
    img = frame()
    assert np.array_equal(adjust(img, Settings()), img), "defaults must be a no-op"
    assert adjust(img, Settings(brightness=40)).mean() > img.mean()
    # gamma < 1 pushes the curve up; the sliders label it as the exponent's inverse
    assert adjust(img, Settings(gamma=2.0)).mean() > img.mean()

    grey = adjust(img, Settings(saturation=0.0))
    assert grey[..., 0].max() == grey[..., 1].max() == grey[..., 2].max(), "no saturation left"

    assert to_space(img, 0) is img
    for space in (1, 2, 3):
        assert to_space(img, space).shape == img.shape, "every view stays 3-channel"


def test_contours_filter_by_area_and_confine_the_plume():
    img = np.zeros((100, 100, 3), np.uint8)
    img[10:40, 10:40] = 200  # 900 px, kept
    img[80:85, 80:85] = 200  # 25 px, too small
    s = Settings(contours=True, contour_thresh=100, contour_min_area=100)

    polys, inside = contours_of(img, s)
    assert len(polys) == 1, "the speck should have been dropped by min area"
    assert inside[20, 20] == 1 and inside[82, 82] == 0

    # A plume mask straddling the contour: the half outside has to go, and the core
    # value 2 inside has to survive -- a bitwise and against 1 would have erased it.
    mask = np.zeros((100, 100), np.uint8)
    mask[15:35, 15:35] = 2
    mask[60:90, 60:90] = 1
    kept = confine([((0, 0, 100, 100), (0, 0, 10, 10), mask)], inside)
    assert len(kept) == 1
    out = kept[0][2]
    assert out[20, 20] == 2, "core inside the contour was lost"
    assert out[70, 70] == 0, "halo outside the contour was kept"

    # A plume entirely outside the contours drops out of the list altogether.
    away = np.zeros((100, 100), np.uint8)
    away[60:90, 60:90] = 2
    assert confine([((0, 0, 100, 100), (0, 0, 10, 10), away)], inside) == []


def test_session_round_trip(tmp_path):
    """One file holds both halves, and steam-detect still reads its half of it."""
    cfg = Config(**{**vars(Config()), "p_hi": 97.5, "stride": 4, "min_area": 333})
    settings = Settings(gamma=1.4, contours=True, contour_thresh=90, steam=True, scale=0.5)
    path = tmp_path / "tune.json"
    save_session(cfg, settings, str(path))
    assert load_session(str(path)) == (cfg, settings)

    # A tune.json written by steam-tune has no "view" block; that must load, not crash.
    (tmp_path / "old.json").write_text('{"p_hi": 98.0}')
    assert load_session(str(tmp_path / "old.json")) == (Config(p_hi=98.0), Settings())
