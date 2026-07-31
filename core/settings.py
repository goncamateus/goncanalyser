"""Every knob in the workspace, as one immutable bundle — plus its disk cache.

Split out of the pipeline so `features/*` can import `Settings` without importing
the chain that calls them, which would be a cycle.

Frozen on purpose. The GUI thread never mutates a `Settings` the worker is
reading; it builds a whole new one and rebinds a single attribute, which is
atomic in CPython. The worker therefore always sees a self-consistent set of
values and neither side needs a lock.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

# What the viewer paints. A view whose feature is switched off is not produced,
# and `pipeline.process` falls back to "Source" rather than showing nothing.
VIEWS = (
    "Source",
    "Grayscale",
    "Threshold",
    "Edges",
    "Contour mask",
    "Motion mask",
    "Motion heatmap",
    "HOG",
    "LBP",
    "Histogram",
)


@dataclass(frozen=True)
class Settings:
    """Flat by design: one field per control, so `Section` can map both ways."""

    view: str = "Source"

    # --- Image Adjustment, in the order they run ---
    brightness: int = 0  # additive offset, -100..100
    contrast: float = 1.0  # multiplicative gain, 1.0 = identity
    saturation: float = 1.0  # HSV S gain, 1.0 = identity
    gamma: float = 1.0  # <1 darkens, >1 lifts shadows
    color_space: str = "BGR"  # BGR | Grayscale | HSV | LAB | HLS
    blur_kind: str = "None"  # None | Gaussian | Median
    blur: int = 0  # kernel; 0 or 1 = off
    threshold_kind: str = "None"  # None | Binary | Binary inverted | Otsu | Adaptive …
    threshold: int = 127
    adaptive_block: int = 11  # neighbourhood for the two adaptive modes; odd, >= 3

    # --- Image Adjustment: region of interest ---
    # Everything downstream sees only this rectangle. `0` for width or height
    # means "out to the edge", which keeps the frame size out of Settings — it
    # would otherwise have to be kept in step with whatever source is open.
    roi_on: bool = False
    roi_x: int = 0
    roi_y: int = 0
    roi_w: int = 0
    roi_h: int = 0

    # --- Global: colour ---
    hist_space: str = "RGB"  # RGB | HSV | LAB

    # --- Global: texture ---
    hog_on: bool = False
    hog_orientations: int = 9
    hog_cell: int = 8
    hog_block: int = 2
    lbp_on: bool = False
    lbp_points: int = 8
    lbp_radius: int = 1
    lbp_method: str = "uniform"  # uniform | default | ror | nri_uniform | var

    # --- Local: keypoints ---
    detector: str = "None"  # None | SIFT | ORB
    kp_max: int = 500
    # 0..1, mapped onto each detector's own threshold — they are not comparable
    # numbers (SIFT wants ~0.04, ORB wants ~20), so the panel exposes one
    # normalised knob and `keypoints.SENSITIVITY` holds the per-detector range.
    kp_sensitivity: float = 0.5
    kp_octaves: int = 3
    kp_edge: float = 10.0
    kp_rich: bool = True  # draw size + orientation, not bare dots

    # --- Structures: edges ---
    edge_kind: str = "None"  # None | Canny | Sobel | Laplacian
    canny_lo: int = 100
    canny_hi: int = 200
    sobel_k: int = 3
    sobel_dx: int = 1
    sobel_dy: int = 1
    lap_k: int = 3

    # --- Structures: Hough ---
    hough_kind: str = "None"  # None | Lines | Circles
    hough_thresh: int = 120
    hough_min_len: int = 50
    hough_max_gap: int = 10

    # --- Structures: corners ---
    corner_kind: str = "None"  # None | Harris | Shi-Tomasi
    corner_max: int = 200
    corner_quality: float = 0.01
    corner_min_dist: int = 10
    harris_k: float = 0.04

    # --- Structures: contours ---
    contours_on: bool = False
    contour_mode: str = "External"  # External | List | Tree
    contour_min_area: int = 50
    contour_boxes: bool = True

    # --- Structures: blobs ---
    blobs_on: bool = False
    blob_min_area: int = 50
    blob_max_area: int = 5000
    blob_circularity: float = 0.0  # 0 disables the filter
    blob_convexity: float = 0.0
    blob_dark: bool = True  # look for dark blobs on light, the OpenCV default

    # --- Motion ---
    # The only feature that reads more than one frame, so it is also the only one
    # with state behind it — see `features.motion.MotionState`.
    motion_algo: str = "None"  # None | MOG2 | KNN | Farneback | Lucas-Kanade | …
    # Grey levels, and it means the same thing under all six algorithms: each one
    # reports its motion as a 0..255 image before this cuts it into a mask.
    motion_threshold: int = 25
    motion_learning: float = -1.0  # MOG2/KNN adaptation rate; -1 = automatic
    motion_open: int = 3  # morphological open kernel; 0 or 1 = off

    mog_history: int = 500
    mog_var: float = 16.0
    mog_shadows: bool = True
    knn_history: int = 500
    knn_dist: float = 400.0
    knn_shadows: bool = True

    fb_pyr_scale: float = 0.5
    fb_levels: int = 3
    fb_winsize: int = 15
    fb_iterations: int = 3
    lk_max_points: int = 200
    lk_win: int = 15

    heat_on: bool = False  # paint the heatmap over whatever view is showing
    heat_opacity: float = 0.5
    heat_window: int = 20  # frames the heat is averaged over
    heat_threshold: float = 0.05  # 0..1 of full scale; below this stays cold

    motion_min_area: int = 50
    motion_boxes: bool = True
    motion_metrics: bool = False  # speed and area labels on every box
    motion_max_travel: int = 60  # px/frame beyond which two blobs are not the same


def cache_file() -> Path:
    """Where the panel's state lives between runs.

    Qt already knows the per-platform config directory, so there is no path to
    hard-code and nothing to get wrong on Windows — ~/.config/analyser on
    Linux, ~/Library/Preferences/analyser on macOS.
    """
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(root) / "settings.json"


def load_cached() -> dict:
    """The last session's settings, or an empty dict if there is no usable file.

    Never raises. A missing, unreadable or half-written cache is not worth
    refusing to start over — the tabs fall back to their own defaults, and the
    next quit overwrites it.
    """
    try:
        data = json.loads(cache_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cached(settings: Settings) -> None:
    """Write the settings back. Also never raises — this runs during shutdown."""
    try:
        path = cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2) + "\n")
    except OSError:
        pass
