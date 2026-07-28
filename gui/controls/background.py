"""Section C — background subtraction: model choice, its knobs, and the view mode."""

from PyQt6.QtCore import pyqtSignal

from .base import Section


class BackgroundSection(Section):
    """MOG2/KNN with every tunable OpenCV exposes actually exposed.

    `history` and `varThreshold` are constructor arguments, so moving either one
    rebuilds the model and throws the learned background away — see
    `processing.pipeline.BackgroundModel`. `learning_rate` is the only one that
    can change on a live model, since it is an argument to `.apply()`.
    """

    reset_requested = pyqtSignal()

    def __init__(self):
        super().__init__("C · Background Subtraction")
        self.enabled = self.check("Enable background subtraction")
        self.model = self.combo(("MOG2", "KNN"))
        self.history = self.knob(
            "History (frames)", 1, 2000, 500, tip="how far back the model remembers"
        )
        self.var_threshold = self.knob(
            "varThreshold / dist2Threshold",
            1,
            200,
            16,
            tip="how different a pixel must be to count as foreground",
        )
        # -1 is OpenCV's "pick a rate from history"; 0 freezes the model, 1
        # re-learns the background from the current frame alone.
        self.learning_rate = self.knob(
            "Learning rate (-1 = auto)", -1.0, 1.0, -1.0, 100, "passed to .apply()"
        )
        self.view = self.combo(("Motion Mask", "Foreground"))
        self.button("Reset background model", self.reset_requested.emit)
        self.note("Both models assume a fixed camera. Moving footage makes nearly "
                  "every pixel foreground — drop the learning rate to see why.")

    def values(self) -> dict:
        return {
            "bgsub_on": self.enabled.isChecked(),
            "bgsub_knn": self.model.currentIndex() == 1,
            "history": int(self.history.value()),
            "var_threshold": self.var_threshold.value(),
            "learning_rate": self.learning_rate.value(),
            "mask_only": self.view.currentIndex() == 0,
        }
