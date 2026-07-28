"""The main window: layout, transport, and the wiring between panel and worker.

Layout is the side-by-side one asked for — a scrollable control panel on the
left, the video on the right with its transport bar underneath.

This class owns no image processing at all. Its whole job is:

    control panel changed  ->  build a Settings  ->  hand it to the worker
    worker emitted a frame ->  paint it in the QLabel

Every section reports through the same `changed` signal into `push_settings()`,
so adding a control never means adding a connection here.
"""

import json
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from processing.labels import LabelStore
from processing.pipeline import Settings
from processing.video_thread import ExportThread, VideoThread

from .controls import BasicSection, LabelSection, PlumeSection

PANEL_WIDTH = 380


def cache_file() -> Path:
    """Where the panel's state lives between runs.

    Qt already knows the per-platform config directory, so there is no path to
    hard-code and nothing to get wrong on Windows — ~/.config/video-tuner on
    Linux, ~/Library/Preferences/video-tuner on macOS.
    """
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(root) / "settings.json"


def label_dir() -> Path:
    """Where per-video label files live, beside the settings cache."""
    return cache_file().parent / "labels"


def load_cached() -> dict:
    """The last session's settings, or an empty dict if there is no usable file.

    Never raises. A missing, unreadable or half-written cache is not worth
    refusing to start over — the sections fall back to their own defaults, and
    the next quit overwrites it.
    """
    try:
        data = json.loads(cache_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cached(settings) -> None:
    """Write the settings back. Also never raises — this runs during shutdown."""
    try:
        path = cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2) + "\n")
    except OSError:
        pass


class MainWindow(QMainWindow):
    """One window, one video file, one worker thread."""

    def __init__(self, path: str):
        super().__init__()
        self.setWindowTitle(f"Video Tuner — {path}")
        self.path = path
        self.worker: VideoThread | None = None  # set at the end of __init__

        # Panel order mirrors the frame chain: adjust, then detect, then label.
        self.basic = BasicSection()
        self.plume = PlumeSection()
        self.labelling = LabelSection()
        self.sections = (self.basic, self.plume, self.labelling)
        # Pick up where the last session left off. Fields the file does not carry
        # keep the widget defaults, so an old cache survives a new knob.
        # cached = load_cached()
        # for section in self.sections:
        #     section.restore(cached)
        self.settings = self._collect()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._panel())
        layout.addWidget(self._video_area(), 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("starting…")

        # Every section routes to the one method that rebuilds Settings.
        for section in self.sections:
            section.changed.connect(self.push_settings)
        self.labelling.export_requested.connect(self.export_dataset)
        self.labelling.clear_requested.connect(self.clear_labels)

        # What the current frame offers to label, refreshed by the worker.
        self.frame_index = 0
        self.anchors: list = []
        self.frames = 0
        self.frame_shape = (512, 640)  # replaced by the first frame that arrives
        self.exporter: ExportThread | None = None
        self.store = LabelStore(path, label_dir(), asdict(self.settings)).load()
        self.refresh_labels()

        for keys, slot in (
            ("Space", self.toggle_play),
            (".", lambda: self.step(+1)),
            (",", lambda: self.step(-1)),
            ("N", self.reject_frame),
            ("U", self.unlabel_frame),
        ):
            QShortcut(QKeySequence(keys), self, slot)
        # One shortcut per digit; the default argument pins the value, or every
        # lambda would close over the same `digit` and all ten would pick #9.
        for digit in range(10):
            QShortcut(QKeySequence(str(digit)), self, lambda d=digit: self.pick(d))

        self.worker = self._start_worker()

    # --- layout -------------------------------------------------------------

    def _panel(self) -> QWidget:
        """The sections stacked in a scroll area, fixed width on the left."""
        inner = QWidget()
        column = QVBoxLayout(inner)
        for section in self.sections:
            column.addWidget(section)
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(PANEL_WIDTH)
        return scroll

    def _video_area(self) -> QWidget:
        """Video label on top, transport bar underneath."""
        self.video = QLabel("waiting for the first frame…")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setMinimumSize(640, 360)
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.play_button = self._button("Pause", self.toggle_play)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.valueChanged.connect(self.on_seek)
        self.frame_label = QLabel("—")

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._button("◀", lambda: self.step(-1)))
        row.addWidget(self.play_button)
        row.addWidget(self._button("▶", lambda: self.step(+1)))
        row.addWidget(self.seek, 1)
        row.addWidget(self.frame_label)

        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.video, 1)
        column.addWidget(bar)
        return area

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    # --- settings -----------------------------------------------------------

    def _collect(self) -> Settings:
        """Merge the sections' dicts into one immutable Settings."""
        merged: dict = {}
        for section in self.sections:
            merged.update(section.values())
        return Settings(**merged)

    def push_settings(self) -> None:
        """Rebuild Settings and rebind it on the worker — one atomic assignment."""
        self.settings = self._collect()
        if self.worker:
            self.worker.settings = self.settings

    # --- worker -------------------------------------------------------------

    def _start_worker(self) -> VideoThread:
        worker = VideoThread(self.path, self.settings)
        worker.frame_ready.connect(self.show_frame)
        worker.opened.connect(self.on_opened)
        worker.position.connect(self.on_position)
        worker.detected.connect(self.on_detected)
        worker.status.connect(self.statusBar().showMessage)
        worker.failed.connect(self.statusBar().showMessage)
        worker.chosen = self._chosen_map()
        worker.start()
        return worker

    # --- labelling ----------------------------------------------------------

    def on_detected(self, index: int, anchors: list) -> None:
        """The worker just drew a frame: remember what it offers to label.

        Then re-resolve the tick for it. This settles rather than looping: the
        push makes the worker redraw once with the tick, that redraw emits the
        same anchors, and the second resolve produces the same value the worker
        already has, so its paused-frame check stops the cycle there.
        """
        self.frame_index, self.anchors = index, anchors
        self.refresh_labels()

    def _chosen_map(self) -> dict:
        """{frame: detection index} for the worker's tick, re-anchored to *now*.

        Only the current frame can be resolved here — the anchors for any other
        frame belong to a detection run that has not happened. That is enough:
        the tick is only ever drawn on the frame being displayed.
        """
        chosen = {}
        picked = self.store.chosen(self.frame_index, self.anchors, self._shape())
        if picked is not None:
            chosen[self.frame_index] = picked
        return chosen

    def _shape(self) -> tuple[int, int]:
        """Frame size for the anchor tolerance, in *image* pixels.

        Not the pixmap's: that one is scaled to the widget, so reading it would
        make the tolerance depend on how big the window happens to be.
        """
        return self.frame_shape

    def pick(self, index: int) -> None:
        """Label detection #index on the current frame as the real plume."""
        if not self.store.pick(self.frame_index, self.anchors, index):
            self.statusBar().showMessage(f"no plume #{index} on this frame")
            return
        self.refresh_labels()

    def reject_frame(self) -> None:
        """No plume here — a reviewed frame, and a negative sample."""
        self.store.reject(self.frame_index)
        self.refresh_labels()

    def unlabel_frame(self) -> None:
        self.store.clear(self.frame_index)
        self.refresh_labels()

    def clear_labels(self) -> None:
        counts = self.store.summary()
        if not counts["total"]:
            return
        confirm = QMessageBox.question(
            self,
            "Clear all labels",
            f"Throw away all {counts['total']} labels for this clip?",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.store.clear_all()
            self.refresh_labels()

    def refresh_labels(self) -> None:
        """Push the labels at the worker and repaint the section's readout."""
        self.store.config = asdict(self.settings)
        if self.worker:
            self.worker.chosen = self._chosen_map()
        self.labelling.show_summary(self.store.summary(), self.frames, self._label_state())

    def _label_state(self) -> str:
        """How this frame reads right now, in the four states it can be in."""
        label = self.store.get(self.frame_index)
        if label is None:
            return "unlabelled"
        if label.rejected:
            return "no plume (negative)"
        picked = self.store.chosen(self.frame_index, self.anchors, self._shape())
        # Labelled, but re-anchoring found nothing near the stored point: the
        # detector no longer produces the plume that was picked.
        return f"plume #{picked}" if picked is not None else "lost — re-label this frame"

    # --- export -------------------------------------------------------------

    def export_dataset(self) -> None:
        if self.exporter is not None:
            return  # already running; the button stays live but does nothing
        if not self.store.labels:
            self.statusBar().showMessage("nothing labelled yet")
            return
        out = QFileDialog.getExistingDirectory(self, "Export COCO dataset to…")
        if not out:
            return

        self.exporter = ExportThread(self.path, self.settings, self.store, out)
        self.exporter.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"exporting {done}/{total}…")
        )
        self.exporter.finished_with.connect(self.on_exported)
        self.exporter.failed.connect(self.statusBar().showMessage)
        self.exporter.start()

    def on_exported(self, result: dict) -> None:
        self.exporter = None
        lost = result.get("lost") or []
        # A lost label is the one thing here worth interrupting for: it means a
        # pick no longer matches any detection, so those frames are missing from
        # the dataset and the user would otherwise never know.
        note = f" · {len(lost)} lost (re-label frames {lost[:5]}…)" if lost else ""
        self.statusBar().showMessage(
            f"exported {result.get('images', 0)} images, "
            f"{result.get('annotations', 0)} annotations{note}"
        )

    # --- transport ----------------------------------------------------------

    def toggle_play(self) -> None:
        if self.worker:
            self.worker.toggle()
            self.play_button.setText("Pause" if self.worker.playing else "Play")

    def step(self, direction: int) -> None:
        if self.worker:
            self.worker.step(direction)
            self.play_button.setText("Play")

    def on_seek(self, value: int) -> None:
        if self.worker:
            self.worker.seek(value)

    def on_opened(self, count: int, fps: float) -> None:
        self.seek.setEnabled(count > 0)
        _muted(self.seek, lambda: self.seek.setRange(0, max(0, count - 1)))
        self.frames = count
        self.refresh_labels()
        self.statusBar().showMessage(f"{count} frames @ {fps:.1f} fps")

    def on_position(self, index: int) -> None:
        # Signals muted: the worker moved the frame, so echoing it back as a user
        # seek would loop — and would fight anyone dragging the handle.
        _muted(self.seek, lambda: self.seek.setValue(index))
        self.frame_label.setText(str(index))

    # --- painting -----------------------------------------------------------

    def show_frame(self, image: QImage) -> None:
        # Image pixels, before the scale-to-widget below: the anchor tolerance is
        # measured in these, and must not move when the window is resized.
        self.frame_shape = (image.height(), image.width())
        self.video.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.video.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def closeEvent(self, event) -> None:
        """Join the worker before the window dies, or Qt warns about a live thread."""
        if self.worker:
            self.worker.stop()
            self.worker = None
        save_cached(self.settings)
        super().closeEvent(event)


def _muted(widget, action) -> None:
    """Change a widget from code without it reporting the change back as input."""
    widget.blockSignals(True)
    action()
    widget.blockSignals(False)
