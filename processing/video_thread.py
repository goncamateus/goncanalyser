"""The QThread that decodes video and renders frames, off the GUI thread.

Everything expensive — `cap.read()`, the whole OpenCV pipeline, the BGR->QImage
conversion — happens in `run()`. The GUI only receives finished QImages through a
signal, so dragging a slider never competes with decoding for the main loop.

Communication is deliberately one-directional and lock-free:

    GUI -> worker : plain attribute assignment (`settings`, `playing`, `_seek`).
                    Rebinding an attribute is atomic, and `Settings` is frozen,
                    so the worker always reads a self-consistent snapshot.
    worker -> GUI : Qt signals, which Qt queues across the thread boundary.
"""

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from .pipeline import Pipeline, Settings


def to_qimage(bgr: np.ndarray) -> QImage:
    """BGR ndarray -> QImage that owns its pixels.

    The `.copy()` is not optional: QImage wraps the numpy buffer without taking a
    reference to it, so the array would be freed the moment this function returns
    and the widget would paint garbage.
    """
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class VideoThread(QThread):
    """Decodes one video file and emits processed frames until stopped."""

    frame_ready = pyqtSignal(QImage)  # a finished, displayable frame
    opened = pyqtSignal(int, float)  # frame count, fps — once the file is readable
    position = pyqtSignal(int)  # current frame index, so the seek bar follows
    status = pyqtSignal(str)  # one line for the status bar
    failed = pyqtSignal(str)  # the file could not be opened

    def __init__(self, path: str, settings: Settings):
        super().__init__()
        self.path = path
        self.settings = settings  # rebound by the GUI, never mutated in place
        self.playing = True
        self._running = True
        self._index = 0  # frame the worker is currently sitting on
        self._seek: int | None = None  # a frame index the GUI asked us to jump to
        self._pipeline = Pipeline()

    # --- control surface, all called from the GUI thread --------------------

    def stop(self) -> None:
        """Ask the loop to finish and block until it has. Safe to call twice."""
        self._running = False
        self.wait()

    def toggle(self) -> None:
        self.playing = not self.playing

    def seek(self, index: int) -> None:
        self._seek = max(0, index)

    def step(self, frames: int) -> None:
        """Pause and move a few frames. Negative steps backwards."""
        self.playing = False
        self._seek = max(0, self._index + frames)

    def reset_background(self) -> None:
        self._pipeline.reset_background()

    # --- the worker loop ----------------------------------------------------

    def run(self) -> None:
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            self.failed.emit(f"cannot open {self.path}")
            return

        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        delay = max(1, int(1000 / fps)) if fps and fps > 1 else 33
        self.opened.emit(count, fps)

        raw: np.ndarray | None = None  # the last decoded frame, kept for re-renders
        last_settings: Settings | None = None

        try:
            while self._running:
                s = self.settings  # one snapshot per iteration, never re-read below

                # A seek is the only thing that touches the file position:
                # CAP_PROP_POS_FRAMES forces a keyframe hunt, so doing it per
                # frame during playback would be far slower than reading ahead.
                if self._seek is not None:
                    self._index, self._seek = self._seek, None
                    cap.set(cv2.CAP_PROP_POS_FRAMES, self._index)
                    raw = None

                if self.playing or raw is None:
                    ok, frame = cap.read()
                    if not ok:
                        # End of file (or a bad frame): stop advancing and sit on
                        # the last good frame so the controls still preview.
                        self.playing = False
                        if raw is None:
                            self.status.emit("no frames to read")
                            break
                        self.msleep(50)
                        continue
                    raw = frame
                    self._index = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                elif s == last_settings:  # dataclass equality, not identity
                    # Paused on a frame nobody re-tuned: nothing new to draw, and
                    # redrawing anyway would spin a core on a still image.
                    self.msleep(30)
                    continue

                last_settings = s
                work, note = self._pipeline.process(raw, s)

                self.frame_ready.emit(to_qimage(work))
                self.position.emit(self._index)
                self.status.emit(
                    f"frame {self._index}/{max(0, count - 1)}  "
                    f"{work.shape[1]}x{work.shape[0]}"
                    f"{note}  "
                    f"{'playing' if self.playing else 'paused'}"
                )
                self.msleep(delay if self.playing else 10)
        finally:
            cap.release()
