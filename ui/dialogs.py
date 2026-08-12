"""The menu's windows: what to export, what to survey, and preferences.

All of them are small and modal because all of them are one-shot questions — you
answer once and the answer is acted on. That is the case a blocking dialog is
actually for, as distinct from the tuning controls, which live in the
always-visible tabs precisely so they never block the view.

`DashboardDialog` is the exception that proves it: it blocks nothing worth doing,
because by the time it opens the survey it displays has already finished.
"""

import json
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from core.settings import cache_file
from core.source import ANY_FILTER
from features.report import FORMATS

LABELS = {
    "settings": "settings.json — every control's value, reloadable",
    "csv": "CSV tables — metrics.csv plus one file per object kind",
    "overlays": "overlays/ — the processed frames as PNG",
    "objects": "objects/ — every moving object, cropped out of the source",
}


def open_source(parent) -> str:
    """Ask for one file. Returns "" when cancelled."""
    path, _ = QFileDialog.getOpenFileName(parent, "Open image or video", "", ANY_FILTER)
    return path


def open_folder(parent) -> str:
    """Ask for a folder of images. Returns "" when cancelled."""
    return QFileDialog.getExistingDirectory(parent, "Open image folder")


def open_settings(parent) -> str:
    """Ask for a settings.json to load. Returns "" when cancelled."""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Load settings", "", "JSON (*.json);;All files (*)"
    )
    return path


def open_report(parent) -> str:
    """Ask for a past optimisation's front.json to reopen. Returns "" when cancelled."""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Open a saved optimisation report", "", "Optimisation report (front.json);;All files (*)"
    )
    return path


def _dialog_cache_file() -> Path:
    """Where a dataset dialog's last answers live between opens.

    A sibling of `core.settings.cache_file()`, same per-platform config
    directory, different file — this is dialog-input state (paths, trial
    count, weights), not the image-processing `Settings` that file holds.
    """
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(root) / "dataset_dialogs.json"


def _load_dialog_options(name: str) -> dict:
    """The last answers for one dialog class, or {} if there are none yet.

    Never raises, the same discipline as `core.settings.load_cached` — a
    missing or unreadable cache just means the dialog starts blank, as it
    always used to.
    """
    try:
        cache = json.loads(_dialog_cache_file().read_text())
        return cache.get(name, {}) if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_dialog_options(name: str, options: dict) -> None:
    """Remember one dialog class's answers, keeping every other class's."""
    try:
        cache = json.loads(_dialog_cache_file().read_text())
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    cache[name] = options
    try:
        path = _dialog_cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2) + "\n")
    except OSError:
        pass


class ExportDialog(QDialog):
    """Where to write the report, and which parts of it to write."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Export analysis")
        self.setMinimumWidth(460)

        self.boxes = {name: QCheckBox(LABELS[name]) for name in FORMATS}
        self.boxes["settings"].setChecked(True)
        self.boxes["csv"].setChecked(True)

        self.folder = QLineEdit()
        self.folder.setPlaceholderText("choose an output folder…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

        column = QVBoxLayout(self)
        column.addWidget(QLabel("<b>Include</b>"))
        for box in self.boxes.values():
            column.addWidget(box)
            box.toggled.connect(self._refresh)
        column.addWidget(QLabel("<b>Output folder</b>"))
        column.addLayout(row)
        column.addWidget(
            QLabel(
                "<i>Every frame is re-analysed with the current settings. With HOG on "
                "that is roughly a quarter-second a frame.</i>"
            )
        )
        column.addWidget(buttons)

        self.folder.textChanged.connect(self._refresh)
        self._refresh()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Export to…")
        if chosen:
            self.folder.setText(chosen)

    def _refresh(self) -> None:
        """No folder or nothing ticked means there is nothing to do."""
        self.ok.setEnabled(bool(self.folder.text()) and any(b.isChecked() for b in self.boxes.values()))

    def choices(self) -> tuple[str, tuple[str, ...]]:
        return self.folder.text(), tuple(n for n, b in self.boxes.items() if b.isChecked())

    @staticmethod
    def ask(parent) -> tuple[str, tuple[str, ...]] | None:
        dialog = ExportDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.choices()


def _path_row(placeholder: str, slot) -> tuple[QLineEdit, QHBoxLayout]:
    """A path box with a Browse button, the way ExportDialog does its one."""
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    browse = QPushButton("Browse…")
    browse.clicked.connect(slot)
    row = QHBoxLayout()
    row.addWidget(line, 1)
    row.addWidget(browse)
    return line, row


class _DatasetInputs(QDialog):
    """Where the ground truth is. Shared by both dataset jobs, run by neither.

    Surveying a dataset and tuning against it are separate questions with
    separate answers — and separate dependencies, since only one of them needs
    matplotlib and only the other needs optuna. What they do share is *where the
    data is*, so that part lives here and the verbs subclass it rather than one
    dialog growing a mode.
    """

    def __init__(self, parent, title: str, note: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)

        self.annotations, ann_row = _path_row("instances_val2017.json…", self._browse_json)
        self.images, images_row = _path_row("the folder those images live in…", self._browse_images)
        self.folder, out_row = _path_row("where to write the results…", self._browse_out)

        self.count = QSpinBox()
        self.count.setRange(1, 100_000)
        self.count.setValue(150)
        # ponytail: typed, not a combo box. Filling a combo means parsing the whole
        # 45 MB annotation file inside the dialog to read one key. The worker
        # validates the name and its error lists every valid one, which is the same
        # information one keystroke later. A combo when that stops being enough.
        self.category = QLineEdit()
        self.category.setPlaceholderText("blank = every class")

        form = QFormLayout()
        form.addRow("Annotations", ann_row)
        form.addRow("Images folder", images_row)
        form.addRow("Output folder", out_row)
        form.addRow("Images to sample", self.count)
        form.addRow("Class", self.category)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)

        self.page = QVBoxLayout(self)
        self.page.addWidget(QLabel("<b>COCO segmentation dataset</b>"))
        self.page.addLayout(form)
        # Subclasses insert their own controls here, between the paths and the
        # closing note, by appending to `page` before `finish()` adds the buttons.
        self.note = QLabel(f"<i>{note}</i>")
        self.note.setWordWrap(True)

        for widget in (self.annotations, self.images, self.folder):
            widget.textChanged.connect(self._refresh)

    def finish(self) -> None:
        """Close the layout. Called by each subclass once its own rows are in."""
        self.page.addWidget(self.note)
        self.page.addWidget(self.buttons)
        self._refresh()

    def _browse_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "COCO annotations", "", "COCO annotations (*.json);;All files (*)"
        )
        if path:
            self.annotations.setText(path)
            # The images almost always sit beside the annotations — either in the
            # same folder, as a Roboflow export does, or in a sibling named after
            # the split, as instances_val2017.json next to val2017/. Guessing right
            # is free; guessing wrong costs one click.
            here = Path(path).parent
            split = here.parent / Path(path).stem.split("_")[-1]
            guess = split if split.is_dir() else here
            if guess.is_dir() and not self.images.text():
                self.images.setText(str(guess))

    def _browse_images(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Images folder")
        if chosen:
            self.images.setText(chosen)

    def _browse_out(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Write the results to…")
        if chosen:
            self.folder.setText(chosen)

    def _refresh(self) -> None:
        self.ok.setEnabled(all(w.text() for w in (self.annotations, self.images, self.folder)))

    def options(self) -> dict:
        """Keyword arguments for the job. Subclasses add their own."""
        return {
            "ann_path": self.annotations.text(),
            "images_dir": self.images.text(),
            "out_dir": self.folder.text(),
            "n": self.count.value(),
            "category": self.category.text().strip(),
        }

    def restore(self, data: dict) -> None:
        """The inverse of `options`: put a previous run's answers back in the boxes.

        `setText` on the three path fields re-triggers `_refresh` through the
        `textChanged` connection above, so the OK button's enabled state comes
        back correct without any extra wiring. Subclasses restore their own
        controls the same way, calling this first.
        """
        self.annotations.setText(data.get("ann_path", ""))
        self.images.setText(data.get("images_dir", ""))
        self.folder.setText(data.get("out_dir", ""))
        if "n" in data:
            self.count.setValue(data["n"])
        self.category.setText(data.get("category", ""))

    @classmethod
    def ask(cls, parent) -> dict | None:
        dialog = cls(parent)
        dialog.restore(_load_dialog_options(cls.__name__))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        options = dialog.options()
        _save_dialog_options(cls.__name__, options)
        return options


class AnalyseDialog(_DatasetInputs):
    """Survey what separates annotated pixels from their background."""

    def __init__(self, parent):
        super().__init__(
            parent,
            "Analyse dataset",
            "The annotation statistics cover the whole file. The colour, texture, "
            "frequency and heatmap panels are measured over the sample, which is "
            "decoded once.",
        )
        self.count.setToolTip(
            "images decoded for the pixel metrics; the annotation\n"
            "statistics always cover the whole file"
        )
        self.finish()


class OptimiseDialog(_DatasetInputs):
    """Search the settings that best reproduce the ground-truth masks."""

    def __init__(self, parent):
        super().__init__(
            parent,
            "Optimise against dataset",
            "The sample is decoded once, then the chain re-runs over it every "
            "trial — trials × images frames.",
        )
        self.count.setValue(50)  # every trial pays for this one, unlike a survey
        self.count.setToolTip("images every trial is scored over")

        self.trials = QSpinBox()
        self.trials.setRange(5, 5000)
        self.trials.setValue(100)

        self.weights = []
        weights_row = QHBoxLayout()
        for name, value, tip in (
            ("α IoU", 1.0, "overlap between the predicted and the true mask"),
            ("β recall", 0.5, "share of the true mask that was found"),
            ("γ spill", 0.5, "share of the background wrongly included"),
        ):
            box = QDoubleSpinBox()
            box.setRange(0.0, 100.0)
            box.setSingleStep(0.5)
            box.setValue(value)
            box.setToolTip(tip)
            self.weights.append(box)
            weights_row.addWidget(QLabel(name))
            weights_row.addWidget(box)

        group = QGroupBox("Search")
        column = QVBoxLayout(group)
        form = QFormLayout()
        form.addRow("Trials", self.trials)
        column.addLayout(form)
        column.addWidget(QLabel("<b>Objective</b>  f = α·IoU + β·recall − γ·background spill"))
        column.addLayout(weights_row)
        hint = QLabel(
            "<i>γ is divided by the background, so on small objects it barely "
            "penalises a mask that covers everything — raise it well above 1 when "
            "the result comes back over-segmented.<br><br>"
            "Searches the twelve parameters that reach the contour mask: every "
            "Image Adjustment knob, plus the contour mode and minimum area. HOG, "
            "LBP, SIFT, ORB, edges, Hough, corners and blobs describe the frame "
            "rather than segmenting it, so they cannot change the score.</i>"
        )
        hint.setWordWrap(True)
        column.addWidget(hint)

        self.page.addWidget(group)

        choose = self.buttons.addButton("Choose result…", QDialogButtonBox.ButtonRole.ActionRole)
        choose.setToolTip("reopen a past run's report and apply one of its trade-offs")
        choose.clicked.connect(self._choose_result)

        self.finish()

    def restore(self, data: dict) -> None:
        super().restore(data)
        if "trials" in data:
            self.trials.setValue(data["trials"])
        weights = data.get("weights")
        if weights and len(weights) == len(self.weights):
            for box, value in zip(self.weights, weights):
                box.setValue(value)

    def options(self) -> dict:
        return {
            **super().options(),
            "trials": self.trials.value(),
            "weights": tuple(box.value() for box in self.weights),
        }

    def _choose_result(self) -> None:
        """Reopen a past run's front and apply one of its trade-offs directly.

        No search runs: this hands the saved report to the same picker
        `on_optimised` shows when a search finishes, and applying does exactly
        what it always did. Then the dialog closes as if Cancel had been
        pressed — `ask()` sees no accepted result, so `_run_dataset` starts no
        job, which is correct: there is nothing left to search for.
        """
        path = open_report(self)
        if not path:
            return
        try:
            result = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot open report", str(exc))
            return
        result.setdefault("dir", str(Path(path).parent))
        chosen = ParetoDialog.ask(self, result)
        if chosen is not None:
            self.parent().apply_settings(chosen["settings"])
            self.reject()


class RosbagDialog(QDialog):
    """Which topic to pull frames from, and where they land as PNG/JPG.

    Not a `_DatasetInputs` subclass — a bag has a topic to choose, not a COCO
    annotations file, a class name, or a sample count, so the field set does
    not match closely enough for inheritance to earn its keep.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Extract from ROS bag")
        self.setMinimumWidth(560)
        self._wanted_topic = ""

        self.bag, bag_row = _path_row("a .db3 file…", self._browse_bag)
        self.folder, out_row = _path_row("where to write the frames…", self._browse_out)

        self.topic = QComboBox()
        self.topic.setEnabled(False)

        self.format = QComboBox()
        self.format.addItems(["png", "jpg"])

        self.status = QLabel()
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Bag", bag_row)
        form.addRow("Topic", self.topic)
        form.addRow("Output folder", out_row)
        form.addRow("Format", self.format)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)

        column = QVBoxLayout(self)
        column.addWidget(QLabel("<b>ROS2 bag (.db3)</b>"))
        column.addLayout(form)
        column.addWidget(self.status)
        column.addWidget(QLabel(
            "<i>Every message on the chosen topic is written as one frame — "
            "sensor_msgs/Image and CompressedImage both work. A bare .db3 with "
            "no metadata.yaml alongside it reads fine; the topic list comes "
            "from the file itself.</i>"
        ))
        column.addWidget(self.buttons)

        self.bag.textChanged.connect(self._peek)
        self.folder.textChanged.connect(self._refresh)
        self.topic.currentTextChanged.connect(self._on_topic_changed)
        self._refresh()

    def _browse_bag(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "ROS2 bag", "", "ROS2 bag (*.db3);;All files (*)"
        )
        if path:
            self.bag.setText(path)

    def _browse_out(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Write the frames to…")
        if chosen:
            self.folder.setText(chosen)

    def _peek(self) -> None:
        """The bag's topic list — fast, no messages are decoded here."""
        self.topic.clear()
        self.topic.setEnabled(False)
        self.status.setText("")
        path = self.bag.text()
        if not path:
            self._refresh()
            return
        from dataset.rosbag import image_topics

        try:
            topics = image_topics(path)
        # Whatever a file that isn't really a rosbag2 sqlite database throws —
        # this is a best-effort status line, not a reason to crash the dialog.
        except Exception as exc:
            self.status.setText(f"cannot read this bag: {exc}")
            self._refresh()
            return
        if not topics:
            self.status.setText("no image topics in this bag")
            self._refresh()
            return
        self.topic.addItems(topics)  # a fresh combo defaults to the first entry
        self.topic.setEnabled(True)
        if self._wanted_topic in topics:
            self.topic.setCurrentText(self._wanted_topic)
        elif len(topics) > 1:
            self.status.setText(f"{len(topics)} image topics found")
        self._refresh()

    def _on_topic_changed(self, text: str) -> None:
        if text:  # not the empty string `_peek` clears the combo down to
            self._wanted_topic = text
        self._refresh()

    def _refresh(self) -> None:
        self.ok.setEnabled(
            bool(self.bag.text() and self.folder.text() and self.topic.currentText())
        )

    def options(self) -> dict:
        return {
            "bag_path": self.bag.text(),
            "topic": self.topic.currentText(),
            "out_dir": self.folder.text(),
            "fmt": self.format.currentText(),
        }

    def restore(self, data: dict) -> None:
        self._wanted_topic = data.get("topic", "")
        self.bag.setText(data.get("bag_path", ""))  # re-peeks, reselects the topic above
        self.folder.setText(data.get("out_dir", ""))
        if data.get("fmt") in ("png", "jpg"):
            self.format.setCurrentText(data["fmt"])

    @classmethod
    def ask(cls, parent) -> dict | None:
        dialog = cls(parent)
        dialog.restore(_load_dialog_options(cls.__name__))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        options = dialog.options()
        _save_dialog_options(cls.__name__, options)
        return options


class DashboardDialog(QDialog):
    """The survey's figures, one per tab, plus the numbers behind them.

    Display only — every figure was composed and written to disk by
    `dataset.stats`, and the folder button is there because a PNG is more useful
    in whatever the reader already uses for pictures than in a Qt label.
    """

    def __init__(self, parent, result: dict):
        super().__init__(parent)
        self.setWindowTitle("Dataset analysis")
        self.resize(1100, 720)
        folder = Path(result.get("dir", ""))

        tabs = QTabWidget()
        summary = result.get("summary", {})
        tabs.addTab(_scrolled(QLabel(_summary_html(summary))), "Summary")
        for name in result.get("figures", ()):
            label = QLabel()
            pixmap = QPixmap(str(folder / name))
            if pixmap.isNull():
                continue
            label.setPixmap(pixmap)
            tabs.addTab(_scrolled(label), Path(name).stem.title())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        open_folder = buttons.addButton("Open folder", QDialogButtonBox.ButtonRole.ActionRole)
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        )

        column = QVBoxLayout(self)
        column.addWidget(tabs, 1)
        column.addWidget(buttons)


class ParetoDialog(QDialog):
    """The optimiser's trade-offs: several non-dominated points, not one winner.

    IoU, recall and background spill are searched together rather than folded
    into one score, so tightening the mask can trade IoU against recall with
    nothing left to declare a single trial "best" — more than one can be
    non-dominated. Applying is picking a row, not accepting a verdict; the
    highest-scoring one by the panel's own weights is selected by default.
    """

    COLUMNS = ("f(θ)", "IoU", "Recall", "Spill", "Coverage", "Changed")

    def __init__(self, parent, result: dict):
        super().__init__(parent)
        self.setWindowTitle("Optimisation finished")
        self.resize(720, 420)
        # A single-entry fallback keeps this dialog usable against an older
        # result dict that only ever had one winner and no front.
        self.front = result.get("front") or [
            {
                "settings": result.get("best", {}),
                "parts": result.get("parts", {}),
                "score": result.get("score"),
                "oversegmented": result.get("oversegmented", False),
                "changed": result.get("changed", {}),
            }
        ]

        header = QLabel(
            f"{len(self.front)} non-dominated trade-off(s) over {result.get('images')} "
            f"images, up from f(θ) = {result.get('baseline')} at the current settings."
        )
        header.setWordWrap(True)

        table = QTableWidget(len(self.front), len(self.COLUMNS))
        table.setHorizontalHeaderLabels(self.COLUMNS)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for row, entry in enumerate(self.front):
            parts = entry.get("parts", {})
            coverage = f"{parts.get('coverage', 0) * 100:.1f}%"
            if entry.get("oversegmented"):
                coverage += "  ⚠ oversegmented"
            values = (
                str(entry.get("score")),
                str(parts.get("iou")),
                str(parts.get("recall")),
                str(parts.get("spill")),
                coverage,
                str(len(entry.get("changed") or {})),
            )
            for col, text in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        if self.front:
            table.selectRow(0)  # the highest-scoring trade-off by the panel's weights
        self.table = table

        column = QVBoxLayout(self)
        column.addWidget(header)
        column.addWidget(table, 1)
        if any(entry.get("oversegmented") for entry in self.front):
            hint = QLabel(
                "<i>⚠ marks a trade-off covering far more than the ground "
                "truth. The spill term is divided by the background, so on "
                "objects this small it barely penalises a mask that covers "
                "everything — raise γ and run again for a tighter one.</i>"
            )
            hint.setWordWrap(True)
            column.addWidget(hint)
        column.addWidget(QLabel(f"<i>Saved to {result.get('dir')}/best_settings.json</i>"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        apply = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.clicked.connect(self.accept)
        column.addWidget(buttons)

    def chosen(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        return self.front[rows[0].row()] if rows else None

    @staticmethod
    def ask(parent, result: dict) -> dict | None:
        """Show the front; return the chosen trade-off's entry, or None if declined."""
        dialog = ParetoDialog(parent, result)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.chosen()


def _scrolled(widget) -> QScrollArea:
    """A figure is wider than any sensible window; scroll it rather than shrink it.

    Deliberately not `setWidgetResizable(True)`: that is right for the control
    tabs, which reflow, and wrong for a chart, which would be squashed to the
    window and made unreadable at the one moment it has something to say.
    """
    scroll = QScrollArea()
    scroll.setWidget(widget)
    return scroll


def _summary_html(summary: dict) -> str:
    """The headline numbers as a table. Ratios first — they are the whole point."""
    rows = "".join(
        f"<tr><td style='padding-right:24px'>{key.replace('_', ' ')}</td><td>{value}</td></tr>"
        for key, value in summary.items()
    )
    return (
        "<h3>Dataset summary</h3>"
        "<p><i>A <b>ratio</b> near 1.0 means annotated pixels look like their "
        "background by that measure, and it is not a signal to threshold on.</i></p>"
        f"<table>{rows}</table>"
    )


class PreferencesDialog(QDialog):
    """Deliberately thin. The knobs are the tabs; this is only what is left over."""

    def __init__(self, parent, on_reset):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(460)

        path = QLineEdit(str(cache_file()))
        path.setReadOnly(True)

        reset = QPushButton("Reset every control to its default")
        reset.clicked.connect(lambda: (on_reset(), self.accept()))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        column = QVBoxLayout(self)
        column.addWidget(QLabel("<b>Settings file</b>"))
        column.addWidget(path)
        column.addWidget(
            QLabel(
                "Written on quit and restored on the next launch. Deleting it also "
                "resets everything; a corrupt one is ignored rather than fatal."
            )
        )
        column.addWidget(reset)
        column.addWidget(buttons)
