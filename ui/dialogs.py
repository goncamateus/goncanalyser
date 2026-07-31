"""The File menu's windows: choosing what to export, and preferences.

Both are small and modal because both are one-shot questions — you answer once
and the answer is acted on. That is the case a blocking dialog is actually for,
as distinct from the tuning controls, which live in the always-visible tabs
precisely so they never block the view.
"""

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.settings import cache_file
from core.source import ANY_FILTER
from features.report import FORMATS

LABELS = {
    "json": "report.json — settings and per-frame metrics",
    "csv": "CSV tables — metrics.csv plus one file per object kind",
    "overlays": "overlays/ — the processed frames as PNG",
}


def open_source(parent) -> str:
    """Ask for one file. Returns "" when cancelled."""
    path, _ = QFileDialog.getOpenFileName(parent, "Open image or video", "", ANY_FILTER)
    return path


def open_folder(parent) -> str:
    """Ask for a folder of images. Returns "" when cancelled."""
    return QFileDialog.getExistingDirectory(parent, "Open image folder")


class ExportDialog(QDialog):
    """Where to write the report, and which parts of it to write."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Export analysis")
        self.setMinimumWidth(460)

        self.boxes = {name: QCheckBox(LABELS[name]) for name in FORMATS}
        self.boxes["json"].setChecked(True)
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
