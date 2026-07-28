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
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from processing.pipeline import Settings
from processing.video_thread import VideoThread

from .controls import BasicSection, PlumeSection

PANEL_WIDTH = 380


def cache_file() -> Path:
    """Where the panel's state lives between runs.

    Qt already knows the per-platform config directory, so there is no path to
    hard-code and nothing to get wrong on Windows — ~/.config/video-tuner on
    Linux, ~/Library/Preferences/video-tuner on macOS.
    """
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(root) / "settings.json"


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

        # Panel order mirrors the frame chain: adjust, then detect.
        self.basic = BasicSection()
        self.plume = PlumeSection()
        self.sections = (self.basic, self.plume)
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

        for keys, slot in (
            ("Space", self.toggle_play),
            (".", lambda: self.step(+1)),
            (",", lambda: self.step(-1)),
        ):
            QShortcut(QKeySequence(keys), self, slot)

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
        worker.status.connect(self.statusBar().showMessage)
        worker.failed.connect(self.statusBar().showMessage)
        worker.start()
        return worker

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
        self.statusBar().showMessage(f"{count} frames @ {fps:.1f} fps")

    def on_position(self, index: int) -> None:
        # Signals muted: the worker moved the frame, so echoing it back as a user
        # seek would loop — and would fight anyone dragging the handle.
        _muted(self.seek, lambda: self.seek.setValue(index))
        self.frame_label.setText(str(index))

    # --- painting -----------------------------------------------------------

    def show_frame(self, image: QImage) -> None:
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
