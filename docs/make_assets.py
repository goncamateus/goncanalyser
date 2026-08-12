"""Every figure the documentation shows, generated from the repo's own inputs.

Run it, get `docs/assets/images/`. Nothing here is a mock-up: the comparison
strips are real `core.pipeline` output, the screenshots are real `ui` widgets
grabbed through Qt, and the dataset panels are a real `dataset.stats` survey of
`sample/`.

    uv run --group dataset python docs/make_assets.py
    uv run --group dataset python docs/make_assets.py --only strips

Three blocks, each skipped with a printed reason when its input is missing —
`voo1.mp4` and `sample/` are gitignored, so a fresh clone has neither and must
still be able to run the parts it does have:

1. **strips** — parameter sweeps, side by side under a caption bar. Headless.
2. **shots** — the window, the five tabs and the dialogs. Needs a display.
3. **dataset** — the five survey figures and the optimiser's Pareto table.

JPEG for anything photographic and PNG for anything with text in it: at 960 px
wide a plume frame is ~120 KB as JPEG and ~700 KB as PNG, and thirty of those is
the difference between a repo you can clone and one you cannot.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pipeline import analyse, composite, process  # noqa: E402
from core.settings import Settings  # noqa: E402
from features.motion import MotionState  # noqa: E402

OUT = ROOT / "docs" / "assets" / "images"
VIDEO = ROOT / "voo1.mp4"
SAMPLE = ROOT / "sample"

FRAME = 450  # the plume is well developed by here and the camera is steady
SEQ = 40  # frames fed to the motion models before the one that gets captured
PANEL_H = 340  # every panel in a strip is scaled to this before concatenation
WIDTH = 1400  # strips are downscaled to this; wider than the content column
COLS = 3  # panels per row. The source is 1920x1080, so five across is unreadable
BAR = 26  # caption bar above each panel
JPEG = (cv2.IMWRITE_JPEG_QUALITY, 85)


# --- strip drawing ---------------------------------------------------------


def _caption(panel: np.ndarray, text: str) -> np.ndarray:
    """A dark bar above a panel with the parameter value that produced it.

    Baked into the image rather than written as a Markdown caption under it:
    these are side-by-side comparisons, and a caption listing four values in
    order forces the reader to count panels to find out which is which.
    """
    bar = np.full((BAR, panel.shape[1], 3), 24, np.uint8)
    cv2.putText(bar, text, (8, BAR - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1,
                cv2.LINE_AA)
    return cv2.vconcat([bar, panel])


def _fit(panel: np.ndarray, height: int = PANEL_H) -> np.ndarray:
    """One common height, so panels of different sizes can sit in a row.

    The Histogram view is a 512x256 plot whatever the frame is, so mixed sizes
    are normal rather than exceptional.
    """
    scale = height / panel.shape[0]
    return cv2.resize(panel, (max(1, round(panel.shape[1] * scale)), height),
                      interpolation=cv2.INTER_AREA)


def strip(name: str, panels: list[tuple[str, np.ndarray]], cols: int = COLS) -> None:
    """Write one labelled comparison figure. Wraps into rows past `cols`."""
    tiles = [_caption(_fit(img), text) for text, img in panels]
    cols = min(cols, len(tiles))
    rows = []
    for start in range(0, len(tiles), cols):
        row = tiles[start : start + cols]
        rows.append(cv2.hconcat(row))
    # A trailing row with fewer panels is narrower; pad it rather than stretch it.
    widest = max(row.shape[1] for row in rows)
    rows = [
        cv2.copyMakeBorder(row, 4, 4, 0, widest - row.shape[1], cv2.BORDER_CONSTANT, value=(24, 24, 24))
        for row in rows
    ]
    figure = cv2.vconcat(rows)
    if figure.shape[1] > WIDTH:
        scale = WIDTH / figure.shape[1]
        figure = cv2.resize(figure, (WIDTH, round(figure.shape[0] * scale)),
                            interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(OUT / f"{name}.jpg"), figure, JPEG)
    print(f"  {name}.jpg  {figure.shape[1]}x{figure.shape[0]}")


def shot(name: str, pixmap) -> None:
    """A Qt grab. PNG — these are full of small text and JPEG rings around it."""
    pixmap.save(str(OUT / f"{name}.png"))
    print(f"  {name}.png  {pixmap.width()}x{pixmap.height()}")


# --- running the chain -----------------------------------------------------


def shown(bgr: np.ndarray, **overrides) -> np.ndarray:
    """What the viewer would show for these settings. One frame, no motion."""
    frame, _ = process(bgr, Settings(**overrides))
    return frame


def moving(frames: list[np.ndarray], **overrides) -> np.ndarray:
    """The same, for the one feature that needs a history to mean anything.

    `pipeline.process` passes `state=None`, which is exactly right for a still
    image and exactly wrong here — `motion.run` returns immediately without one.
    So this drives the chain the way the worker does, over a real sequence, and
    composites only the last frame.

    `state.at(i)` is not optional. Without it the frame index never changes, the
    state's first rule reads every frame as the paused one being re-rendered, and
    the model spends the whole sequence looking at frame zero.
    """
    settings = Settings(**overrides)
    state = MotionState()
    out = None
    for index, bgr in enumerate(frames):
        out = analyse(bgr, settings, state.at(index))
    return composite(out, settings)


# --- inputs ----------------------------------------------------------------


def video_frames() -> list[np.ndarray] | None:
    """`SEQ` consecutive frames ending at `FRAME`, or None if there is no video.

    Trailing duplicates are trimmed. The clip is a 30 fps container carrying a
    slower source, so roughly every sixth frame is a repeat of the one before it,
    and a repeat is a true zero for every differencing algorithm — three-frame
    difference in particular is the minimum of two consecutive differences, so one
    repeat anywhere in the last three frames blanks the figure entirely. Landing
    on a moving frame is a choice about which frame to photograph, not a thumb on
    the scale: nothing about the settings or the algorithms is changed.
    """
    if not VIDEO.exists():
        return None
    cap = cv2.VideoCapture(str(VIDEO))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, FRAME - SEQ))
    frames = []
    for _ in range(SEQ):
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        return None

    def moved(a, b) -> bool:
        return cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
                           cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)).mean() > 0.5

    while len(frames) > 4 and not (moved(frames[-1], frames[-2])
                                   and moved(frames[-2], frames[-3])):
        frames.pop()

    # The recording is a 4:3 thermal camera in a 16:9 container, so a quarter of
    # every frame is the container's own black border. Dropping it is not a crop
    # of the scene — it is not showing the reader 500 columns of nothing in a
    # figure that is 460 px wide by the time it reaches the page.
    gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    xs = np.where(gray.std(axis=0) > 3)[0]
    ys = np.where(gray.std(axis=1) > 3)[0]
    if len(xs) and len(ys):
        frames = [f[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] for f in frames]
    return frames


def sample_images() -> list[Path]:
    return sorted(SAMPLE.glob("*.jpg")) if SAMPLE.is_dir() else []


# --- block 1: parameter sweeps ---------------------------------------------


def strips() -> None:
    frames = video_frames()
    if frames is None:
        print("skipped strips: voo1.mp4 is not here (it is gitignored)")
        return
    f = frames[-1]
    print("strips:")

    strip("adjust_brightness", [
        (f"brightness = {v}", shown(f, brightness=v)) for v in (-100, -40, 0, 40, 100)
    ])
    strip("adjust_contrast", [
        (f"contrast = {v}", shown(f, contrast=v)) for v in (0.3, 0.7, 1.0, 2.0, 3.0)
    ])
    strip("adjust_gamma", [
        (f"gamma = {v}", shown(f, gamma=v)) for v in (0.3, 0.6, 1.0, 1.8, 3.0)
    ])
    strip("adjust_saturation", [
        (f"saturation = {v}", shown(f, saturation=v)) for v in (0.0, 0.5, 1.0, 2.0, 3.0)
    ])
    strip("adjust_colorspace", [
        (space, shown(f, color_space=space))
        for space in ("BGR", "Grayscale", "HSV", "LAB", "HLS")
    ])
    strip("adjust_blur", [
        ("None", shown(f)),
        ("Gaussian, kernel 9", shown(f, blur_kind="Gaussian", blur=9)),
        ("Gaussian, kernel 31", shown(f, blur_kind="Gaussian", blur=31)),
        ("Median, kernel 9", shown(f, blur_kind="Median", blur=9)),
        ("Median, kernel 31", shown(f, blur_kind="Median", blur=31)),
    ])
    strip("adjust_threshold_level", [
        (f"Binary, level {v}", shown(f, view="Threshold", threshold_kind="Binary", threshold=v))
        for v in (60, 100, 127, 170, 210)
    ])
    strip("adjust_threshold_kind", [
        ("Binary, 127", shown(f, view="Threshold", threshold_kind="Binary")),
        ("Binary inverted, 127", shown(f, view="Threshold", threshold_kind="Binary inverted")),
        ("Otsu", shown(f, view="Threshold", threshold_kind="Otsu")),
        ("Adaptive mean, block 11", shown(f, view="Threshold", threshold_kind="Adaptive mean")),
        ("Adaptive Gaussian, block 31",
         shown(f, view="Threshold", threshold_kind="Adaptive Gaussian", adaptive_block=31)),
    ])
    h, w = f.shape[:2]
    region = dict(roi_on=True, roi_x=w // 4, roi_y=h // 4, roi_w=w // 2, roi_h=h // 2)
    strip("adjust_roi", [
        ("region off — Otsu reads the whole frame",
         shown(f, view="Threshold", threshold_kind="Otsu")),
        ("region on — Otsu reads the rectangle only",
         shown(f, view="Threshold", threshold_kind="Otsu", **region)),
    ])

    strip("color_histogram", [
        (f"{space} histogram", shown(f, view="Histogram", hist_space=space))
        for space in ("RGB", "HSV", "LAB")
    ])
    strip("texture_hog", [
        (f"cell {c} px, {o} orientations", shown(f, view="HOG", hog_on=True, hog_cell=c,
                                                 hog_orientations=o))
        for c, o in ((4, 9), (8, 9), (16, 9), (8, 4), (8, 18))
    ])
    strip("texture_lbp", [
        (f"P = {p}, R = {r}", shown(f, view="LBP", lbp_on=True, lbp_points=p, lbp_radius=r))
        for p, r in ((8, 1), (8, 3), (16, 2), (24, 4))
    ])

    # Two columns wherever the figure is about geometry drawn *on* the frame — a
    # keypoint circle or a bounding box is a few pixels wide, and three across
    # scales it below the point of showing it.
    strip("keypoints_detectors", [
        ("SIFT, sensitivity 0.5", shown(f, detector="SIFT")),
        ("ORB, sensitivity 0.5", shown(f, detector="ORB")),
        ("SIFT, plain dots", shown(f, detector="SIFT", kp_rich=False)),
        ("ORB, plain dots", shown(f, detector="ORB", kp_rich=False)),
    ], cols=2)
    strip("keypoints_sensitivity", [
        (f"SIFT, sensitivity {v}", shown(f, detector="SIFT", kp_sensitivity=v, kp_max=2000))
        for v in (0.1, 0.5, 0.9)
    ], cols=2)

    strip("edges_canny", [
        (f"Canny {lo}/{hi}", shown(f, view="Edges", edge_kind="Canny", canny_lo=lo, canny_hi=hi))
        for lo, hi in ((30, 90), (100, 200), (200, 400))
    ])
    strip("edges_kinds", [
        ("Canny 100/200", shown(f, view="Edges", edge_kind="Canny")),
        ("Sobel, kernel 3", shown(f, view="Edges", edge_kind="Sobel")),
        ("Sobel, kernel 7", shown(f, view="Edges", edge_kind="Sobel", sobel_k=7)),
        ("Laplacian, kernel 5", shown(f, view="Edges", edge_kind="Laplacian", lap_k=5)),
    ])
    strip("hough_lines", [
        (f"Lines, {v} votes", shown(f, hough_kind="Lines", hough_thresh=v))
        for v in (60, 120, 240)
    ], cols=2)
    strip("corners", [
        ("Harris, k = 0.04", shown(f, corner_kind="Harris")),
        ("Harris, k = 0.15", shown(f, corner_kind="Harris", harris_k=0.15)),
        ("Shi-Tomasi, quality 0.01", shown(f, corner_kind="Shi-Tomasi")),
        ("Shi-Tomasi, quality 0.1", shown(f, corner_kind="Shi-Tomasi", corner_quality=0.1)),
    ], cols=2)

    # No `threshold_kind` here on purpose. The contour finder reads the Threshold
    # canvas, which `adjust.run` derives at Binary/`threshold` even when the combo
    # says None — so contours work, and the Source view stays in colour with the
    # boxes drawn over it. Setting the combo would threshold the working frame
    # itself and every panel below would be black and white.
    # Level 190 rather than the default 127: this is a thermal image where most of
    # the frame is above 127, so the default binarises the whole plant into one
    # 207,000 px contour and a min-area sweep over it shows nothing changing.
    contours = dict(contours_on=True, threshold=190)
    strip("contours_min_area", [
        (f"min area {v} px", shown(f, contour_min_area=v, **contours))
        for v in (0, 50, 500, 5000)
    ], cols=2)
    strip("contours_mask", [
        ("Threshold view — what the finder reads", shown(f, view="Threshold", threshold=190)),
        ("Contour mask — what it produced", shown(f, view="Contour mask", **contours)),
        ("Source view — the same contours as boxes", shown(f, **contours)),
    ])
    strip("blobs", [
        (f"min area {lo}, max area {hi}",
         shown(f, blobs_on=True, blob_min_area=lo, blob_max_area=hi))
        for lo, hi in ((50, 5000), (500, 50000))
    ])

    print("motion strips (each drives the model over 40 frames):")
    algos = ("MOG2", "KNN", "Farneback", "Lucas-Kanade", "Frame difference",
             "Three-frame difference")
    strip("motion_algorithms", [
        (algo, moving(frames, view="Motion mask", motion_algo=algo)) for algo in algos
    ], cols=3)
    strip("motion_sensitivity", [
        (f"sensitivity {v}", moving(frames, view="Motion mask", motion_algo="MOG2",
                                    motion_threshold=v))
        for v in (5, 25, 80, 200)
    ])
    strip("motion_open", [
        (f"noise removal {v}", moving(frames, view="Motion mask", motion_algo="Frame difference",
                                      motion_open=v))
        for v in (0, 3, 9, 15)
    ])
    # Farneback for the heat figures: the accumulator averages whatever the
    # algorithm reports, and a binary MOG2 mask of a thermal plume is too sparse
    # to show a window length changing anything. Dense flow is what the heatmap
    # was built to display.
    strip("motion_heatmap", [
        (f"window {v} frames", moving(frames, view="Motion heatmap", motion_algo="Farneback",
                                      heat_window=v))
        for v in (3, 20, 60)
    ])
    strip("motion_boxes", [
        ("boxes only", moving(frames, motion_algo="Farneback", motion_boxes=True)),
        ("boxes with area and speed",
         moving(frames, motion_algo="Farneback", motion_metrics=True)),
        ("heatmap overlaid, opacity 0.7",
         moving(frames, motion_algo="Farneback", heat_on=True, heat_opacity=0.7)),
    ], cols=2)


# --- block 2: the window and its dialogs -----------------------------------


def shots() -> None:
    """Real widgets, grabbed. Needs a display — `QT_QPA_PLATFORM=offscreen` works."""
    # The video, not a still, because half of what these screenshots are for is
    # the transport bar — and it disables itself on a single image, which is
    # correct behaviour and a useless picture of it.
    images = sample_images()
    source_path = VIDEO if VIDEO.exists() else (images[0] if images else None)
    if source_path is None:
        print("skipped shots: neither voo1.mp4 nor sample/ is here")
        return

    from PyQt6.QtWidgets import QApplication

    from core.source import FrameSource
    from ui.dialogs import (
        AnalyseDialog,
        ExportDialog,
        OptimiseDialog,
        PreferencesDialog,
        RosbagDialog,
    )
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("analyser")
    window = MainWindow(FrameSource(str(source_path)))
    window.resize(1400, 820)
    window.show()

    # The first frame arrives from the worker thread, so there is nothing worth
    # grabbing until it has. Pump the loop until the viewer holds a pixmap rather
    # than sleeping a guessed number of seconds.
    from PyQt6.QtCore import QDeadlineTimer

    deadline = QDeadlineTimer(10_000)
    while not deadline.hasExpired():
        app.processEvents()
        pixmap = window.video.pixmap()
        if pixmap is not None and not pixmap.isNull():
            break
    else:
        print("  warning: no frame rendered in 10 s, grabbing anyway")

    def settle(ms: int = 700) -> None:
        """Pump the loop for real time, not for a number of iterations.

        The worker renders on its own thread at the source's frame rate, so a
        thousand `processEvents` calls in the same microsecond still grab the
        frame from before the settings changed.
        """
        timer = QDeadlineTimer(ms)
        while not timer.hasExpired():
            app.processEvents()

    print("shots:")
    shot("window_overview", window.grab())

    for index, name in enumerate(("tab_adjust", "tab_global", "tab_local", "tab_structures",
                                  "tab_motion")):
        window.tabs.setCurrentIndex(index)
        settle()
        shot(name, window.tabs.grab())

    # A region, with a threshold on so the guarantee is visible rather than
    # implied: inside the rectangle is analysed, outside is the raw decoded frame.
    # Set through `apply_settings`, the same flat-dict path a loaded settings.json
    # takes, so the tabs and the worker both end up holding it.
    width, height = window.source.size
    window.tabs.setCurrentIndex(0)
    window.apply_settings({
        "threshold_kind": "Otsu",
        "roi_on": True,
        "roi_x": width // 5,
        "roi_y": height // 6,
        "roi_w": width // 2,
        "roi_h": height // 2,
    })
    settle()
    shot("window_region", window.grab())
    window.apply_settings({"threshold_kind": "None", "roi_on": False,
                           "roi_x": 0, "roi_y": 0, "roi_w": 0, "roi_h": 0})
    settle()

    # Built, laid out and grabbed — never `exec()`-ed, which would block here
    # waiting for a click that is not coming. Width is pinned rather than left to
    # `adjustSize`, which lets a word-wrapped note stretch a dialog to 1400 px.
    for name, factory in (
        ("dialog_export", ExportDialog),
        ("dialog_analyse", AnalyseDialog),
        ("dialog_optimise", OptimiseDialog),
        ("dialog_rosbag", RosbagDialog),
        ("dialog_preferences", lambda parent: PreferencesDialog(parent, lambda: None)),
    ):
        dialog = factory(window)
        dialog.resize(620, dialog.sizeHint().height())
        settle(250)
        shot(name, dialog.grab())
        dialog.deleteLater()

    window.close()


# --- block 3: the dataset jobs ---------------------------------------------


def dataset() -> None:
    """The survey's five figures and one Pareto table, from `sample/`."""
    annotations = SAMPLE / "_annotations.coco.json"
    if not annotations.exists():
        print("skipped dataset: sample/_annotations.coco.json is not here (gitignored)")
        return

    work = ROOT / "build" / "docs-dataset"
    work.mkdir(parents=True, exist_ok=True)

    print("dataset survey:")
    from dataset.stats import analyse as survey

    job = survey(str(annotations), str(SAMPLE), str(work), n=20)
    result = None
    try:
        while True:
            next(job)
    except StopIteration as stop:
        result = stop.value
    for figure in result["figures"]:
        shutil.copyfile(work / figure, OUT / f"dataset_{figure}")
        print(f"  dataset_{figure}")

    print("optimiser front:")
    from dataset.optimise import search

    # A neutral output directory, because the dialog prints the path it wrote to
    # and a screenshot in published documentation should not carry someone's home
    # directory. Sixty trials over eight images rather than a token handful — a
    # front of three near-identical rows illustrates nothing.
    out = Path(tempfile.gettempdir()) / "goncanalyser-docs"
    out.mkdir(parents=True, exist_ok=True)
    job = search(str(annotations), str(SAMPLE), str(out), trials=60, n=8)
    try:
        while True:
            next(job)
    except StopIteration as stop:
        front = stop.value

    from PyQt6.QtWidgets import QApplication

    from ui.dialogs import ParetoDialog

    app = QApplication.instance() or QApplication([])
    pareto = ParetoDialog(None, front)
    # Wide enough for every column. Its own size hint shrinks to the text and
    # scrolls Coverage and Changed off the right, which are two of the three
    # things the table exists to show.
    pareto.resize(820, 460)
    app.processEvents()
    shot("dialog_pareto", pareto.grab())
    pareto.deleteLater()


BLOCKS = {"strips": strips, "shots": shots, "dataset": dataset}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else BLOCKS
    for name in wanted:
        if name not in BLOCKS:
            print(f"unknown block {name!r}; pick from {', '.join(BLOCKS)}")
            return 1
        BLOCKS[name]()
    print(f"\nwrote {len(list(OUT.iterdir()))} files to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
