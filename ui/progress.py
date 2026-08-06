"""Watching a long job: a pie in the status bar, and a window you can dismiss.

A dataset survey is minutes and a hundred-trial search can be tens of them. That
is far too long to hold a modal dialog in front of the workspace, and far too
long to show nothing at all — so it is both, and they are the same job.

`JobDialog` is **modeless**, and its Hide button hides it rather than cancelling
anything. `PieProgress` lives in the status bar for as long as the job does, and
clicking it brings the window back. The pie is what makes hiding safe: dismissing
the dialog cannot leave the job invisible, because the status bar keeps a filling
circle in the corner until it finishes.
"""

import time

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

PIE = 18  # diameter in px. The status bar grows to fit it, so this sets the height.
TEXT = 40  # room for "100%" beside it
PAD = 8  # trailing gap, so it does not sit under the corner resize grip


class PieProgress(QWidget):
    """A filling pie with its percentage. Click to bring its job's window back.

    Painted rather than assembled: Qt has a progress *bar* and no progress pie,
    and `drawPie` with an arc length is the whole of it. Colours come from the
    palette so it follows the platform theme instead of picking a blue that is
    wrong on half of them.

    It carries its own percentage because a bare circle this size is a coloured
    dot in the corner of a status bar — findable once you know it is there, and
    invisible until then. The number is what makes it read as progress.
    """

    clicked = pyqtSignal()

    def __init__(self, size: int = PIE):
        super().__init__()
        self.done = self.total = 0
        self.share = ""
        self.diameter = size
        self.setFixedSize(size + TEXT + PAD, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(self.diameter + TEXT + PAD, self.diameter)

    def track(self, done: int, total: int, label: str = "") -> None:
        self.done, self.total = done, total
        self.share = f"{done / total:.0%}" if total else "…"
        self.setToolTip(f"{label} {done}/{total} ({self.share}) — click to show".strip())
        self.setVisible(True)
        self.update()  # repaint, not recompute; QWidget.update is a paint request

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRect(0, 0, self.diameter, self.diameter).adjusted(1, 1, -1, -1)

        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle)

        if self.total > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().highlight())
            # Angles are sixteenths of a degree, and negative sweeps clockwise —
            # from twelve o'clock, which is the direction a clock face implies.
            painter.drawPie(circle, 90 * 16, -int(360 * 16 * self.done / self.total))

        painter.setPen(self.palette().windowText().color())
        painter.drawText(
            QRect(self.diameter + 4, 0, TEXT, self.diameter),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.share,
        )

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit()


class JobDialog(QDialog):
    """Modeless progress for one long job. Hiding it does not stop anything.

    Two buttons that sound similar and are not: **Hide** puts the window away and
    leaves the work running; **Cancel** stops the work. Cancelling is cooperative,
    so it takes effect at the end of the step in flight — one trial for a search,
    one image for a survey — and the window says "stopping…" rather than
    pretending it was instant.
    """

    cancelled = pyqtSignal()

    def __init__(self, parent, title: str, note: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setMinimumWidth(420)
        self._started = time.monotonic()
        self.stopping = False

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indeterminate until the first tick arrives
        self.detail = QLabel("starting…")
        self.detail.setWordWrap(True)

        buttons = QDialogButtonBox()
        buttons.addButton("Hide", QDialogButtonBox.ButtonRole.RejectRole)
        self.cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.cancel.clicked.connect(self._cancel)
        buttons.rejected.connect(self.hide)

        column = QVBoxLayout(self)
        column.addWidget(QLabel(note))
        column.addWidget(self.bar)
        column.addWidget(self.detail)
        column.addWidget(
            QLabel("<i>Hiding this leaves the job running — the pie in the status "
                   "bar keeps its place, and clicking it brings this back.</i>")
        )
        column.addWidget(buttons)

    def _cancel(self) -> None:
        """Ask for a stop and say so. The window does not own the thread."""
        self.stopping = True
        self.cancel.setEnabled(False)
        self.bar.setRange(0, 0)  # back to indeterminate: the count no longer means anything
        self.detail.setText("stopping — finishing the step already running…")
        self.cancelled.emit()

    def track(self, done: int, total: int, label: str = "") -> None:
        if self.stopping:
            return  # a late tick must not overwrite "stopping…" with a countdown
        if total and self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)

        spent = time.monotonic() - self._started
        left = ""
        if done and total > done:
            # Linear from the mean so far. Every step here costs the same — one
            # image decoded, or one trial scored over a fixed sample — so the
            # naive estimate is the honest one rather than a placeholder.
            left = f" · about {_clock(spent / done * (total - done))} left"
        self.detail.setText(f"{label}\n{_clock(spent)} elapsed{left}".strip())

    def closeEvent(self, event) -> None:
        """The window's X means hide, like the button. Nothing here owns the job."""
        event.ignore()
        self.hide()


def _clock(seconds: float) -> str:
    """Coarse on purpose: nobody watching a ten-minute job wants three decimals."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def _demo() -> None:
    """The pie sweeps with its job, and hiding the dialog does not stop it."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    pie = PieProgress()
    assert pie.isHidden(), "an idle job must not leave a pie in the status bar"
    pie.track(0, 100)
    assert pie.isVisible() and "0/100" in pie.toolTip()
    pie.track(25, 100, "optimising")
    assert "25/100" in pie.toolTip() and "25%" in pie.toolTip(), pie.toolTip()

    # It has to survive the states a real job passes through, including the ones
    # that divide by zero if taken literally.
    for done, total in ((0, 0), (0, 10), (10, 10), (7, 3)):
        pie.track(done, total)
        pie.render(pie.grab())  # forces paintEvent, which is where the maths is

    seen = []
    pie.clicked.connect(lambda: seen.append(True))
    pie.mousePressEvent(None)
    assert seen, "clicking the pie must ask for the window back"

    dialog = JobDialog(None, "Optimising", "a search")
    assert not dialog.isModal(), "a job window must not block the workspace"
    dialog.track(3, 60, "trial 3/60")
    assert dialog.bar.maximum() == 60 and dialog.bar.value() == 3
    assert "elapsed" in dialog.detail.text()

    dialog.show()
    dialog.close()  # the X, not the button
    assert dialog.isHidden(), "closing must hide"
    dialog.show()
    assert dialog.isVisible(), "and it must come back"

    # Hide and Cancel are the two buttons that sound alike. Hiding asks for
    # nothing; cancelling asks once, and cannot be asked twice.
    stops = []
    dialog.cancelled.connect(lambda: stops.append(True))
    dialog.hide()
    assert not stops, "hiding must not stop the job"

    dialog.cancel.click()
    assert stops == [True] and dialog.stopping
    assert not dialog.cancel.isEnabled(), "cancel must not be clickable twice"
    assert "stopping" in dialog.detail.text()

    # Ticks already in flight when Cancel was pressed must not paint over it.
    dialog.track(4, 60, "trial 4/60")
    assert "stopping" in dialog.detail.text(), dialog.detail.text()

    assert _clock(9) == "9s" and _clock(75) == "1m 15s" and _clock(3700) == "1h 01m"

    print("progress ok")
    del app


if __name__ == "__main__":
    _demo()
