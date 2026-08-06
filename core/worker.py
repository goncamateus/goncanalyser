"""The QThreads. Everything expensive happens here, never on the GUI thread.

Decoding, the whole OpenCV chain and the BGR->QImage conversion all run in
`Worker.run()`. The GUI only receives finished QImages through a signal, so
dragging a slider never competes with a 200 ms HOG for the main loop.

Communication is deliberately one-directional and lock-free:

    GUI -> worker : plain attribute assignment (`settings`, `playing`, `_seek`,
                    `previews`). Rebinding an attribute is atomic and `Settings`
                    is frozen, so the worker always reads a consistent snapshot.
    worker -> GUI : Qt signals, which Qt queues across the thread boundary.
"""

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from features.motion import MotionState

from .pipeline import analyse, composite, summarise
from .settings import Settings
from .source import FrameSource


def to_qimage(bgr: np.ndarray) -> QImage:
    """BGR ndarray -> QImage that owns its pixels.

    The `.copy()` is not optional: QImage wraps the numpy buffer without taking a
    reference to it, so the array would be freed the moment this function returns
    and the widget would paint garbage.
    """
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class Worker(QThread):
    """Reads one source and emits processed frames until stopped."""

    frame_ready = pyqtSignal(QImage)  # a finished, displayable frame
    preview_ready = pyqtSignal(str, QImage)  # a named canvas for a tab's thumbnail
    opened = pyqtSignal(int, float)  # frame count, fps
    position = pyqtSignal(int)  # current frame index, so the seek bar follows
    measured = pyqtSignal(int, dict)  # frame index + metrics, for the readouts
    status = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source: FrameSource, settings: Settings):
        super().__init__()
        self.source = source
        self.settings = settings  # rebound by the GUI, never mutated in place
        # Canvases the visible tab wants a thumbnail of. Rebound wholesale by the
        # GUI, same lock-free deal as `settings` — converting every canvas to a
        # QImage every frame would be pure waste when nothing is looking at it.
        self.previews: tuple[str, ...] = ()
        self.playing = source.is_video
        # The one piece of the chain that outlives a frame. Owned here rather
        # than by the pipeline so a running export cannot share — and disturb —
        # the background model the viewer is looking at.
        self.motion = MotionState()
        self._running = True
        self._index = 0  # the frame being displayed
        self._seek: int | None = None

    # --- control surface, all called from the GUI thread --------------------

    def stop(self) -> None:
        """Ask the loop to finish and block until it has. Safe to call twice."""
        self._running = False
        self.wait()

    def toggle(self) -> None:
        self.playing = not self.playing and self.source.is_video

    def seek(self, index: int) -> None:
        self._seek = max(0, index)

    def step(self, frames: int) -> None:
        """Pause and move a few frames. Negative steps backwards."""
        self.playing = False
        self._seek = max(0, self._index + frames)

    # --- the worker loop ----------------------------------------------------

    def run(self) -> None:
        count, fps = self.source.count, self.source.fps
        delay = max(1, int(1000 / fps)) if fps else 40
        self.opened.emit(count, fps)

        raw: np.ndarray | None = None  # the decoded frame for self._index
        last_state: tuple | None = None  # (settings, previews) the last draw used

        while self._running:
            s = self.settings  # one snapshot per iteration, never re-read below
            previews = self.previews

            if self._seek is not None:
                self._index, self._seek = self._seek, None
                raw = None

            if raw is None:
                raw = self.source.read(self._index)
                if raw is None:
                    # Past the end, or an unreadable file. Back up onto the last
                    # frame that worked rather than sitting on a blank window.
                    self.playing = False
                    if self._index == 0:
                        self.failed.emit(f"no frames in {self.source.path}")
                        return
                    self._index -= 1
                    continue
            elif self.playing:
                nxt = self.source.read(self._index + 1)
                if nxt is None:
                    self.playing = False  # end of file: sit on the last good frame
                    self.status.emit("end of source")
                    self.msleep(50)
                    continue
                raw, self._index = nxt, self._index + 1
            elif (s, previews) == last_state:
                # Paused on a frame nobody re-tuned: nothing new to draw, and
                # redrawing anyway would spin a core on a still image.
                self.msleep(30)
                continue

            last_state = (s, previews)
            # `at` names the frame, which is what lets the motion state tell a
            # step forward from a seek from a paused re-render of the same frame.
            result = analyse(raw, s, self.motion.at(self._index))
            canvas = composite(result, s)

            self.frame_ready.emit(to_qimage(canvas))
            for name in previews:
                image = result.canvases.get(name)
                if image is not None:
                    self.preview_ready.emit(name, to_qimage(image))
            self.position.emit(self._index)
            self.measured.emit(self._index, result.metrics)

            end = f"/{count - 1}" if count else ""
            self.status.emit(
                f"{self.source.name(self._index)}  [{self._index}{end}]  "
                f"{canvas.shape[1]}x{canvas.shape[0]}  {summarise(result.metrics)}  "
                f"{'playing' if self.playing else 'paused'}"
            )
            self.msleep(delay if self.playing else 10)


class ReportThread(QThread):
    """Walks every frame and writes the analysis report, without freezing the window.

    A report re-runs the whole chain over the whole source — with HOG on, that is
    a quarter-second a frame — which is far too long to spend on the GUI thread.
    `report.write` is a generator precisely so this wrapper can be this small and
    stay the only Qt-aware part of the export path.
    """

    progress = pyqtSignal(int, int)  # done, total
    finished_with = pyqtSignal(dict)  # counts and the paths written
    failed = pyqtSignal(str)

    def __init__(self, path: str, settings: Settings, out_dir: str, formats: tuple[str, ...]):
        super().__init__()
        self.path = path
        self.settings = settings
        self.out_dir = out_dir
        self.formats = formats

    def run(self) -> None:
        from features.report import write

        try:
            steps = write(self.path, self.settings, self.out_dir, self.formats)
            while True:
                try:
                    done, total = next(steps)
                except StopIteration as finished:
                    # The generator's return value carries the summary.
                    self.finished_with.emit(finished.value or {})
                    return
                self.progress.emit(done, total)
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class DatasetThread(QThread):
    """Runs one long dataset job off the GUI thread. Knows nothing about which.

    The same three signals and the same generator-draining loop as `ReportThread`,
    because `dataset.stats.analyse` and `dataset.optimise.search` deliberately have
    the same shape as `report.write`. Both jobs are minutes long: a survey decodes
    a few hundred images, and a study runs the whole chain once per image per
    trial.

    It takes the generator function rather than a mode string, so surveying and
    tuning share this wrapper without either being reachable from the other. They
    are independent jobs with independent dependencies — only one needs
    matplotlib, only the other needs optuna — and the window imports whichever it
    is about to run, which is also where a missing optional group gets reported.
    """

    progress = pyqtSignal(int, int)  # done, total
    finished_with = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, job, options: dict):
        super().__init__()
        self.job = job  # a generator function yielding (done, total)
        self.options = options

    def run(self) -> None:
        try:
            steps = self.job(**self.options)
            while True:
                try:
                    done, total = next(steps)
                except StopIteration as finished:
                    self.finished_with.emit(finished.value or {})
                    return
                self.progress.emit(done, total)
        # KeyError is a malformed annotation file — one missing "bbox" three
        # hundred images in should not take the application down.
        except (OSError, ValueError, KeyError) as exc:
            self.failed.emit(str(exc))
