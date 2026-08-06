"""The menu's windows: what to export, what to survey, and preferences.

All of them are small and modal because all of them are one-shot questions — you
answer once and the answer is acted on. That is the case a blocking dialog is
actually for, as distinct from the tuning controls, which live in the
always-visible tabs precisely so they never block the view.

`DashboardDialog` is the exception that proves it: it blocks nothing worth doing,
because by the time it opens the survey it displays has already finished.
"""

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
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


class DatasetDialog(QDialog):
    """Where the ground truth is, and which of the two things to do with it.

    One dialog, two verbs. Surveying a dataset and tuning against it need exactly
    the same three paths, the same sample and the same class filter; two nav
    buttons would mean typing all of that twice to answer two halves of one
    question.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Analyse dataset")
        self.setMinimumWidth(560)
        self.mode = "analyse"

        self.annotations, ann_row = self._pick("instances_val2017.json…", self._browse_json)
        self.images, images_row = self._pick("the folder those images live in…", self._browse_images)
        self.folder, out_row = self._pick("where to write the report…", self._browse_out)

        self.count = QSpinBox()
        self.count.setRange(1, 100_000)
        self.count.setValue(150)
        self.count.setToolTip("images decoded for the pixel metrics; the annotation\n"
                              "statistics always cover the whole file")
        # ponytail: typed, not a combo box. Filling a combo means parsing the whole
        # 45 MB annotation file inside the dialog to read one key. The worker
        # validates the name and its error lists every valid one, which is the same
        # information one keystroke later. A combo when that stops being enough.
        self.category = QLineEdit()
        self.category.setPlaceholderText("blank = every class")

        inputs = QFormLayout()
        inputs.addRow("Annotations", ann_row)
        inputs.addRow("Images folder", images_row)
        inputs.addRow("Output folder", out_row)
        inputs.addRow("Images to sample", self.count)
        inputs.addRow("Class", self.category)

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
            box.setRange(0.0, 10.0)
            box.setSingleStep(0.1)
            box.setValue(value)
            box.setToolTip(tip)
            self.weights.append(box)
            weights_row.addWidget(QLabel(name))
            weights_row.addWidget(box)

        tuning = QGroupBox("Optimise only")
        column = QVBoxLayout(tuning)
        form = QFormLayout()
        form.addRow("Trials", self.trials)
        column.addLayout(form)
        column.addWidget(QLabel("<b>Objective</b>  f = α·IoU + β·recall − γ·background spill"))
        column.addLayout(weights_row)
        column.addWidget(
            QLabel(
                "<i>Searches the twelve parameters that reach the contour mask: every "
                "Image Adjustment knob, plus the contour mode and minimum area. HOG, "
                "LBP, SIFT, ORB, edges, Hough, corners and blobs describe the frame "
                "rather than segmenting it, so they cannot change the score.</i>"
            )
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.analyse = buttons.addButton("Analyse", QDialogButtonBox.ButtonRole.AcceptRole)
        self.optimise = buttons.addButton("Optimise", QDialogButtonBox.ButtonRole.AcceptRole)
        self.analyse.clicked.connect(lambda: setattr(self, "mode", "analyse"))
        self.optimise.clicked.connect(lambda: setattr(self, "mode", "optimise"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        page = QVBoxLayout(self)
        page.addWidget(QLabel("<b>COCO segmentation dataset</b>"))
        page.addLayout(inputs)
        page.addWidget(tuning)
        page.addWidget(
            QLabel(
                "<i>Analyse decodes the sample once. Optimise decodes it once and then "
                "re-runs the chain over it every trial — trials × images frames.</i>"
            )
        )
        page.addWidget(buttons)

        for widget in (self.annotations, self.images, self.folder):
            widget.textChanged.connect(self._refresh)
        self._refresh()

    def _pick(self, placeholder: str, slot) -> tuple[QLineEdit, QHBoxLayout]:
        """A path box with a Browse button, the way ExportDialog does its one."""
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        browse = QPushButton("Browse…")
        browse.clicked.connect(slot)
        row = QHBoxLayout()
        row.addWidget(line, 1)
        row.addWidget(browse)
        return line, row

    def _browse_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "COCO annotations", "", "COCO annotations (*.json);;All files (*)"
        )
        if path:
            self.annotations.setText(path)
            # The images almost always sit beside the annotations in a sibling
            # folder named after the split — instances_val2017.json next to
            # val2017/. Guessing it right is free; guessing it wrong costs a click.
            guess = Path(path).parent.parent / Path(path).stem.split("_")[-1]
            if guess.is_dir() and not self.images.text():
                self.images.setText(str(guess))

    def _browse_images(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Images folder")
        if chosen:
            self.images.setText(chosen)

    def _browse_out(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Write the report to…")
        if chosen:
            self.folder.setText(chosen)

    def _refresh(self) -> None:
        ready = all(w.text() for w in (self.annotations, self.images, self.folder))
        self.analyse.setEnabled(ready)
        self.optimise.setEnabled(ready)

    def choices(self) -> tuple[str, dict]:
        """(mode, keyword arguments for the job). `seed` is the window's to add."""
        options = {
            "ann_path": self.annotations.text(),
            "images_dir": self.images.text(),
            "out_dir": self.folder.text(),
            "n": self.count.value(),
            "category": self.category.text().strip(),
        }
        if self.mode == "optimise":
            options["trials"] = self.trials.value()
            options["weights"] = tuple(box.value() for box in self.weights)
        return self.mode, options

    @staticmethod
    def ask(parent) -> tuple[str, dict] | None:
        dialog = DatasetDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.choices()


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
