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

import json
from dataclasses import asdict
from pathlib import Path

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
from core.worker import DatasetThread, ReportThread, Worker

from .controls import AdjustTab, GlobalTab, LocalTab, MotionTab, StructuresTab
from .dialogs import (
    AnalyseDialog,
    DashboardDialog,
    ExportDialog,
    OptimiseDialog,
    PreferencesDialog,
    open_folder,
    open_settings,
    open_source,
)
from .progress import JobDialog, PieProgress
from .viewer import Viewer

PANEL_WIDTH = 400

# (menu title, tab title, tab class). One entry drives both the tab bar and the
# menu action, so the two cannot drift apart.
TABS = (
    ("Image Adjustment", "Adjust", AdjustTab),
    ("Global", "Global", GlobalTab),
    ("Local", "Local", LocalTab),
    ("Structures", "Structures", StructuresTab),
    ("Motion", "Motion", MotionTab),
)


class MainWindow(QMainWindow):
    """One window, one source, one worker thread."""

    def __init__(self, source: FrameSource):
        super().__init__()
        self.source = source
        self.worker: Worker | None = None  # set at the end of __init__
        self.exporter: ReportThread | None = None
        self.dataset: DatasetThread | None = None
        self.job: JobDialog | None = None  # the running job's window, if any
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
        # Same path the File menu's loader takes; it is a no-op on the worker,
        # which does not exist yet, and leaves `self.settings` ready for it.
        self.apply_settings(load_cached())

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._viewer(), 1)
        layout.addWidget(self._panel())
        self.setCentralWidget(central)
        self._menus()
        self.setWindowTitle(f"Analyser — {source.path}")
        # The dataset jobs get their own corner of the status bar. They cannot
        # share `showMessage` with the frame worker, which writes a line there on
        # every frame — a hundred a second even while paused — and would wipe
        # anything they had to say before it could be read.
        self.pie = PieProgress()
        self.pie.clicked.connect(self.show_job)
        self.job_status = QLabel()
        self.statusBar().addPermanentWidget(self.job_status)
        self.statusBar().addPermanentWidget(self.pie)
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
            ("Load settings…", "Ctrl+L", self.load_settings),
            ("Export analysis…", "Ctrl+S", self.export),
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

        # The one header entry that is a menu rather than a tab. Two verbs, and
        # they are genuinely separate jobs: different questions, different output,
        # different optional dependencies. Neither is a mode of the other, so
        # neither is a checkbox inside the other's dialog.
        dataset = bar.addMenu("Dataset")
        for text, keys, slot in (
            ("Analyse…", "Ctrl+D", self.analyse_dataset),
            ("Optimise…", "Ctrl+Shift+D", self.optimise_dataset),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(slot)
            dataset.addAction(action)

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

    def apply_settings(self, values: dict) -> None:
        """Put a saved settings dict into the controls and push it once.

        Fields the dict does not carry keep whatever the widget already has, so
        this takes the cache, an export's `settings.json`, or a partial hand-
        written file just as happily.
        """
        for section in self.sections:
            section.restore(values)
        self.view.setCurrentText(values.get("view", Settings().view))
        self.push_settings()

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

        self.apply_settings(blank)
        self.statusBar().showMessage(note)

    def load_settings(self) -> None:
        """Take the tuning out of an exported settings.json and put it back.

        An export carries the settings that produced it precisely so a run can be
        reproduced; this is the other half of that. The app's own cache file
        works too — the same flat dict, only not nested under "settings".
        """
        path = open_settings(self)
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
            values = data.get("settings", data) if isinstance(data, dict) else None
            if not isinstance(values, dict):
                raise ValueError("no settings in this file")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot load settings", str(exc))
            return

        self.apply_settings(values)
        self.statusBar().showMessage(f"settings loaded from {Path(path).name}")

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

    # --- dataset ------------------------------------------------------------

    def analyse_dataset(self) -> None:
        """Survey what separates a dataset's annotated pixels from its background."""
        try:
            from dataset.stats import analyse
        except ImportError as exc:
            self._no_dataset_tools(exc)
            return
        self._run_dataset(analyse, AnalyseDialog, "analysing", self.on_analysed)

    def optimise_dataset(self) -> None:
        """Search the settings that best reproduce a dataset's masks."""
        try:
            from dataset.optimise import search
        except ImportError as exc:
            self._no_dataset_tools(exc)
            return
        self._run_dataset(search, OptimiseDialog, "optimising", self.on_optimised,
                          # Trial zero is whatever is on screen, so the search starts
                          # from the tuning already done by hand and the result is
                          # always comparable against it.
                          seed=asdict(self.settings))

    def _no_dataset_tools(self, exc: ImportError) -> None:
        """Name the one package that is missing, not the whole group.

        Surveying needs matplotlib and tuning needs optuna, and neither needs the
        other's. Reporting both would send someone installing a dependency the
        thing they asked for does not use.
        """
        QMessageBox.information(
            self,
            "Dataset tools not installed",
            f"This needs {exc.name}, which ships separately from the app.\n\n"
            "Install it with:\n\n    uv sync --group dataset",
        )

    def _run_dataset(self, job, dialog, verb: str, done, **extra) -> None:
        """Ask for the inputs, then drive one dataset job on its own thread."""
        if self.dataset is not None:
            self._say("a dataset job is already running")
            self.show_job()  # they probably hid it and forgot, so put it back
            return
        options = dialog.ask(self)
        if options is None:
            return
        self._say("")

        self.job = JobDialog(self, verb.capitalize(), f"{verb.capitalize()} a dataset.")
        self.dataset = DatasetThread(job, {**options, **extra})
        self.job.cancelled.connect(self.cancel_dataset)
        self.dataset.progress.connect(self.on_dataset_progress)
        self.dataset.finished_with.connect(done)
        self.dataset.failed.connect(self.on_dataset_failed)
        # Qt's own signal, emitted whenever run() returns — including the cancelled
        # case, which produces no result and so reaches neither slot above. Without
        # it a stopped job would leave its pie up and block the next one forever.
        self.dataset.finished.connect(self._end_dataset)
        self.dataset.start()
        self.job.show()

    def cancel_dataset(self) -> None:
        """Ask the running job to stop. It ends after the step already in flight."""
        if self.dataset is not None:
            self.dataset.requestInterruption()
            self._say("stopping the dataset job…")

    def _say(self, text: str) -> None:
        """Say something the frame worker will not immediately talk over."""
        self.job_status.setText(text)

    def on_dataset_progress(self, at: int, total: int, label: str) -> None:
        """One tick, to all three places that show it."""
        self.pie.track(at, total, label)
        if self.job is not None:
            self.job.track(at, total, label)
        self._say(label or f"{at}/{total}…")

    def show_job(self) -> None:
        """The pie was clicked. Bring the running job's window back to the front."""
        if self.job is not None:
            self.job.show()
            self.job.raise_()
            self.job.activateWindow()

    def _end_dataset(self) -> None:
        """Whatever happened, the job is over: clear the thread, pie and window.

        Idempotent, because it runs twice on a normal finish — once from the slot
        that got the result, once from the thread's own `finished` — and only once
        when the job was cancelled, which is the case that needs the second.
        """
        # Asked of the dialog, not the thread. `QThread.isInterruptionRequested`
        # reports false once the thread has finished, and by the time this runs it
        # always has — so the flag that survives is the one recording the click.
        if self.job is not None and self.job.stopping:
            self._say("dataset job cancelled")
        self.dataset = None
        self.pie.hide()
        if self.job is not None:
            self.job.deleteLater()
            self.job = None

    def on_analysed(self, result: dict) -> None:
        self._end_dataset()
        summary = result.get("summary", {})
        self._say(
            f"analysed {summary.get('images_sampled', 0)} images "
            f"({summary.get('annotations', 0)} annotations)"
        )
        DashboardDialog(self, result).exec()

    def on_optimised(self, result: dict) -> None:
        """Offer the winner. Applying it is the same path a loaded file takes."""
        self._end_dataset()
        changed = result.get("changed") or {}
        parts = result.get("parts") or {}
        lines = "\n".join(f"    {k} = {v}" for k, v in sorted(changed.items()))
        detail = ""
        if parts:
            detail = (
                f"\nIoU {parts['iou']}   recall {parts['recall']}   "
                f"background spill {parts['spill']}\n"
                f"The mask covers {parts['coverage'] * 100:.1f}% of the frame; "
                f"the ground truth covers {parts['truth'] * 100:.1f}%.\n"
            )
        if result.get("oversegmented"):
            detail += (
                "\nThat is a lot more than the ground truth. The spill term is "
                "divided by the background, so on objects this small it barely "
                "penalises a mask that covers everything. Raise γ and run again "
                "if you want a tighter mask.\n"
            )
        box = QMessageBox(self)
        box.setWindowTitle("Optimisation finished")
        box.setText(
            f"Best f(θ) = {result.get('score')} over {result.get('images')} images, "
            f"up from {result.get('baseline')} at the current settings.\n"
            f"{detail}\n"
            f"{len(changed)} parameters changed:\n{lines}\n\n"
            f"Saved to {result.get('dir')}/best_settings.json"
        )
        apply = box.addButton("Apply", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is apply:
            self.apply_settings(result["best"])
            self._say(f"optimised settings applied — f(θ) = {result.get('score')}")

    def on_dataset_failed(self, message: str) -> None:
        self._end_dataset()
        QMessageBox.warning(self, "Dataset analysis failed", message)

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
        if self.dataset is not None:
            # Ask first, then join. A survey of six hundred images is minutes of
            # waiting, and a window that will not close is indistinguishable from
            # one that has hung — the more so now the job's own window can be hidden.
            self.dataset.requestInterruption()
            self.dataset.wait()
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
