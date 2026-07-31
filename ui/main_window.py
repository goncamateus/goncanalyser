"""The main window: layout, transport, and the wiring between tabs and worker.

Layout is viewer LEFT, controls RIGHT, in a `QTabWidget` — one tab per menu
group. The menu bar does not open a second copy of anything: `Image Adjustment`,
`Global`, `Local` and `Structures` raise their tab, so there is exactly one
definition of every control and it is always one click away without covering the
image.

This class owns no image processing at all. Its whole job is:

    a tab changed        ->  build a Settings  ->  hand it to the worker
    worker emitted a frame ->  paint it in the QLabel

Every tab reports through the same `changed` signal into `push_settings()`, so
adding a control never means adding a connection here.
"""

from dataclasses import asdict

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.settings import VIEWS, Settings, load_cached, save_cached
from core.source import FrameSource, SourceError
from core.worker import ReportThread, Worker

from .controls import AdjustTab, GlobalTab, LocalTab, StructuresTab
from .dialogs import ExportDialog, PreferencesDialog, open_folder, open_source
from .viewer import Viewer

PANEL_WIDTH = 400

# (menu title, tab title, tab class). One entry drives both the tab bar and the
# menu action, so the two cannot drift apart.
TABS = (
    ("Image Adjustment", "Adjust", AdjustTab),
    ("Global", "Global", GlobalTab),
    ("Local", "Local", LocalTab),
    ("Structures", "Structures", StructuresTab),
)


class MainWindow(QMainWindow):
    """One window, one source, one worker thread."""

    def __init__(self, source: FrameSource):
        super().__init__()
        self.source = source
        self.worker: Worker | None = None  # set at the end of __init__
        self.exporter: ReportThread | None = None
        self.frames = 0
        self._undo: dict | None = None  # settings from before the last Ctrl+R

        self.tabs = QTabWidget()
        self.sections = []
        for _, title, factory in TABS:
            section = factory()
            self.sections.append(section)
            self.tabs.addTab(self._scrolled(section), title)

        # Built here rather than in `_viewer` so it exists before the first
        # `_collect` — otherwise the restored view would be dropped on the floor
        # and every session would start on "Source".
        self.view = QComboBox()
        self.view.addItems(VIEWS)

        # Pick up where the last session left off. Fields the file does not carry
        # keep the widget defaults, so an old cache survives a new knob.
        cached = load_cached()
        for section in self.sections:
            section.restore(cached)
        self.view.setCurrentText(cached.get("view", Settings().view))
        self.settings = self._collect()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._viewer(), 1)
        layout.addWidget(self._panel())
        self.setCentralWidget(central)
        self._menus()
        self.setWindowTitle(f"Analyser — {source.path}")
        self.statusBar().showMessage("starting…")

        # Every tab routes to the one method that rebuilds Settings.
        for section in self.sections:
            section.changed.connect(self.push_settings)
        self.tabs.currentChanged.connect(self.push_previews)

        # The Selection group lives on the Adjust tab but needs the viewer, which
        # the tab has no business knowing about — so the window connects them.
        self.adjust = self.sections[0]
        self.adjust.draw.clicked.connect(self.arm_draw)
        self.view.currentIndexChanged.connect(self.refresh_draw)
        self.on_source_changed()

        for keys, slot in (
            ("Space", self.toggle_play),
            (".", lambda: self.step(+1)),
            (",", lambda: self.step(-1)),
        ):
            QShortcut(QKeySequence(keys), self, slot)

        self.worker = self._start_worker()
        self.push_previews()

    # --- layout -------------------------------------------------------------

    def _scrolled(self, widget: QWidget) -> QScrollArea:
        """A tab is taller than the window; the scroll area is per-tab, not global."""
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        return scroll

    def _panel(self) -> QWidget:
        self.tabs.setFixedWidth(PANEL_WIDTH)
        return self.tabs

    def _viewer(self) -> QWidget:
        """Image on top, view picker and transport bar underneath."""
        self.video = Viewer()
        self.video.selected.connect(self.on_region_drawn)

        # `self.view` is the one control that does not belong to a tab — it
        # decides which tab's output is on screen, so it sits with the image.
        # It was built in __init__; only the connection is made here, after the
        # restore, so restoring does not count as user input.
        self.view.currentIndexChanged.connect(self.push_settings)

        self.play_button = self._button("Pause", self.toggle_play)
        _fix_width(self.play_button, "Play", "Pause")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.valueChanged.connect(self.on_seek)
        self.frame_label = QLabel("—")

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("View"))
        row.addWidget(self.view)
        self.back = self._button("◀", lambda: self.step(-1))
        self.forward = self._button("▶", lambda: self.step(+1))
        row.addWidget(self.back)
        row.addWidget(self.play_button)
        row.addWidget(self.forward)
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

    def _menus(self) -> None:
        bar = self.menuBar()
        files = bar.addMenu("File")
        # "Ctrl+…" is the portable spelling, not a Windows-ism: Qt maps Ctrl in a
        # QKeySequence onto Command on macOS, so these are Cmd+W and Cmd+Q there
        # and Ctrl+W and Ctrl+Q everywhere else. QKeySequence.StandardKey.Close
        # would *not* do — outside macOS it means Ctrl+F4, which is the MDI
        # close-child binding and not what anyone reaches for.
        for text, keys, slot in (
            ("Open image or video…", "Ctrl+O", self.open_file),
            ("Open image folder…", "Ctrl+Shift+O", self.open_dir),
            ("Export analysis…", "Ctrl+E", self.export),
            ("Reset all controls", "Ctrl+R", self.reset_settings),
            ("Preferences…", "Ctrl+,", self.preferences),
            ("Close window", "Ctrl+W", self.close),
            ("Quit", "Ctrl+Q", self.close),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(slot)
            files.addAction(action)

        # The four analysis menus raise their tab rather than opening a window:
        # one definition of every control, and the image never gets covered.
        for index, (title, _, _) in enumerate(TABS):
            action = QAction(title, self)
            action.triggered.connect(lambda _=False, i=index: self.tabs.setCurrentIndex(i))
            bar.addAction(action)

    # --- region of interest -------------------------------------------------

    def on_source_changed(self) -> None:
        """Tell the viewer and the spinboxes how big the frames are.

        From the source rather than from a painted frame: the Histogram view
        paints a 512x256 plot, which would cap the boxes at the size of a chart.
        """
        width, height = self.source.size
        self.video.source_size = QSize(width, height)
        self.adjust.set_frame_size(width, height)
        self.refresh_draw()

    def arm_draw(self) -> None:
        self.video.arm(True)
        self.statusBar().showMessage("drag a rectangle on the image")

    def refresh_draw(self) -> None:
        """Drawing is meaningless over the Histogram — that is a plot, not the frame."""
        on_frame = self.view.currentText() != "Histogram"
        self.adjust.draw.setEnabled(on_frame and not self.source.size == (0, 0))
        self.adjust.draw.setToolTip(
            "" if on_frame else "switch off the Histogram view to draw on the frame"
        )
        if not on_frame:
            self.video.arm(False)

    def on_region_drawn(self, x: int, y: int, w: int, h: int) -> None:
        """A drag finished. Fill the four boxes and switch the region on.

        Muted, then one push: writing four spinboxes would otherwise rebuild and
        re-send Settings four times, and the worker would render three frames
        nobody asked for.
        """
        for spin, value in (
            (self.adjust.x, x), (self.adjust.y, y),
            (self.adjust.w, w), (self.adjust.h, h),
        ):
            _muted(spin, lambda s=spin, v=value: s.setValue(v))
        _muted(self.adjust.enabled, lambda: self.adjust.enabled.setChecked(True))
        self.push_settings()
        self.statusBar().showMessage(f"region {x}, {y}  {w}x{h}")

    # --- settings -----------------------------------------------------------

    def _collect(self) -> Settings:
        """Merge the tabs' dicts into one immutable Settings."""
        merged: dict = {"view": self.view.currentText()}
        for section in self.sections:
            merged.update(section.values())
        return Settings(**merged)

    def push_settings(self) -> None:
        """Rebuild Settings and rebind it on the worker — one atomic assignment."""
        self.settings = self._collect()
        if self.worker:
            self.worker.settings = self.settings
        # A tab's previews depend on its own checkboxes, so a toggle can change
        # what needs rendering as well as what needs computing.
        self.push_previews()

    def push_previews(self) -> None:
        """Tell the worker which thumbnails the *visible* tab wants, and no others.

        Converting every canvas to a QImage every frame would be pure waste when
        the tab that shows it is not on screen.
        """
        if not self.worker:
            return
        self.worker.previews = self.sections[self.tabs.currentIndex()].previews()

    def reset_settings(self) -> None:
        """Every control back to its default. Ctrl+R, or the Preferences button.

        No confirmation prompt: a shortcut that stops to ask is not worth having,
        and the previous values are stashed so a mistyped Ctrl+R costs one more
        keystroke rather than the last twenty minutes of tuning.
        """
        blank = asdict(Settings())
        if self.settings == Settings():
            if self._undo is None:
                self.statusBar().showMessage("already at defaults")
                return
            blank, self._undo = self._undo, None  # second press: put it back
            note = "controls restored"
        else:
            self._undo = asdict(self.settings)
            note = "controls reset — Ctrl+R again to undo"

        for section in self.sections:
            section.restore(blank)
        self.view.setCurrentText(blank["view"])
        self.push_settings()
        self.statusBar().showMessage(note)

    # --- worker -------------------------------------------------------------

    def _start_worker(self) -> Worker:
        worker = Worker(self.source, self.settings)
        worker.frame_ready.connect(self.show_frame)
        worker.preview_ready.connect(self.show_preview)
        worker.opened.connect(self.on_opened)
        worker.position.connect(self.on_position)
        worker.status.connect(self.statusBar().showMessage)
        worker.failed.connect(self.statusBar().showMessage)
        worker.start()
        return worker

    # --- File menu ----------------------------------------------------------

    def open_file(self) -> None:
        self._reopen(open_source(self))

    def open_dir(self) -> None:
        self._reopen(open_folder(self))

    def _reopen(self, path: str) -> None:
        """Swap the source without losing a single knob.

        A whole new window would drop the tuning you just did, and tuning is the
        thing you carry from one image to the next.
        """
        if not path:
            return
        try:
            source = FrameSource(path)
        except SourceError as exc:
            QMessageBox.warning(self, "Cannot open", str(exc))
            return

        if self.worker:
            self.worker.stop()
        self.source.release()
        self.source = source
        self.setWindowTitle(f"Analyser — {path}")
        self.on_source_changed()
        self.worker = self._start_worker()
        self.push_previews()

    def export(self) -> None:
        if self.exporter is not None:
            self.statusBar().showMessage("an export is already running")
            return
        chosen = ExportDialog.ask(self)
        if chosen is None:
            return
        out_dir, formats = chosen

        self.exporter = ReportThread(str(self.source.path), self.settings, out_dir, formats)
        self.exporter.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"exporting {done}/{total}…")
        )
        self.exporter.finished_with.connect(self.on_exported)
        self.exporter.failed.connect(self.on_export_failed)
        self.exporter.start()

    def on_exported(self, result: dict) -> None:
        self.exporter = None
        self.statusBar().showMessage(
            f"exported {result.get('frames', 0)} frames to {result.get('dir')} "
            f"— {', '.join(result.get('written') or ['nothing'])}"
        )

    def on_export_failed(self, message: str) -> None:
        self.exporter = None
        QMessageBox.warning(self, "Export failed", message)

    def preferences(self) -> None:
        PreferencesDialog(self, self.reset_settings).exec()

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
        self.frames = count
        single = count <= 1
        # A single image has nothing to scrub, step through or play. Leaving the
        # transport live on one would just be four controls that do nothing.
        self.seek.setEnabled(not single)
        _muted(self.seek, lambda: self.seek.setRange(0, max(0, count - 1)))
        for widget in (self.play_button, self.back, self.forward):
            widget.setEnabled(not single)
        self.play_button.setText("Pause" if self.worker and self.worker.playing else "Play")
        kind = f"{count} frames @ {fps:.1f} fps" if fps else f"{count} image(s)"
        self.statusBar().showMessage(kind)

    def on_position(self, index: int) -> None:
        # Signals muted: the worker moved the frame, so echoing it back as a user
        # seek would loop — and would fight anyone dragging the handle.
        _muted(self.seek, lambda: self.seek.setValue(index))
        self.frame_label.setText(str(index))

    # --- painting -----------------------------------------------------------

    def show_frame(self, image: QImage) -> None:
        self.video.show_image(image)

    def show_preview(self, name: str, image: QImage) -> None:
        self.sections[self.tabs.currentIndex()].show_preview(name, image)

    def closeEvent(self, event) -> None:
        """Join the threads before the window dies, or Qt warns about a live one."""
        if self.worker:
            self.worker.stop()
            self.worker = None
        if self.exporter is not None:
            self.exporter.wait()
        self.source.release()
        save_cached(self.settings)
        super().closeEvent(event)


def _muted(widget, action) -> None:
    """Change a widget from code without it reporting the change back as input."""
    widget.blockSignals(True)
    action()
    widget.blockSignals(False)


def _fix_width(button: QPushButton, *texts: str) -> None:
    """Pin a button to the widest label it will ever show.

    A button whose text toggles — "Pause" to "Play" — otherwise resizes on every
    press and shoves the rest of the transport bar sideways under it.

    Measured by asking Qt for each label's `sizeHint` rather than hard-coding a
    number, so it stays correct under a different font, DPI or platform style.
    """
    current = button.text()
    widest = 0
    for text in texts:
        button.setText(text)
        widest = max(widest, button.sizeHint().width())
    button.setText(current)
    button.setFixedWidth(widest)
