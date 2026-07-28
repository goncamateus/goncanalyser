"""Section B — background subtraction: model choice, its knobs, and the view mode."""

from PyQt6.QtCore import pyqtSignal

from processing.motion import GMC_METHODS
from processing.pipeline import BG_MODELS, COMPENSATED

from .base import Section

BLOCKS = ("1", "2", "4", "8")  # model resolution, in pixels per Gaussian
VIEWS = ("Motion Mask", "Foreground")  # first entry means Settings.mask_only


class BackgroundSection(Section):
    """Three models, with every tunable OpenCV (or the paper) exposes.

    MOG2 and KNN take `history` and `varThreshold` at construction time, so
    moving either rebuilds the model and throws the learned background away —
    see `processing.pipeline.BackgroundModel`. The compensated model reuses those
    same two sliders as its age cap and its detection threshold, which is why it
    adds only the knobs that have no equivalent in the other two.
    """

    reset_requested = pyqtSignal()

    def __init__(self):
        super().__init__("B · Background Subtraction")
        self.enabled = self.check("Enable background subtraction", field="bgsub_on")
        self.model = self.combo(BG_MODELS, field="bg_model")
        self.history = self.knob(
            "History (frames)", 1, 2000, 500, tip="how far back the model remembers",
            field="history", cast=int,
        )
        self.var_threshold = self.knob(
            "varThreshold / dist2Threshold",
            1,
            200,
            16,
            tip="how different a pixel must be to count as foreground",
            field="var_threshold",
        )
        # -1 is "let the model choose": OpenCV picks a rate from history, the
        # compensated model uses the paper's 1/age schedule. 0 freezes the model,
        # 1 re-learns the background from the current frame alone.
        self.learning_rate = self.knob(
            "Learning rate (-1 = auto)", -1.0, 1.0, -1.0, 100, "MOG2/KNN: .apply(); SGM: 1/age",
            field="learning_rate",
        )
        self.view = self.combo(
            VIEWS,
            field="mask_only",
            cast=lambda text: text == VIEWS[0],
            back=lambda flag: VIEWS[0] if flag else VIEWS[1],
        )
        self.button("Reset background model", self.reset_requested.emit)

        # --- compensated model only -----------------------------------------
        self.note("<b>Moving camera</b> — the knobs below apply to the compensated model.")
        self.gmc = self.combo(GMC_METHODS, field="gmc_method")
        self.homography = self.check(
            "Full homography (else 4-dof similarity)", field="gmc_homography"
        )
        self.block = self.combo(BLOCKS, field="block", cast=int, back=str)
        self.block.setCurrentText("4")
        self.edge_tolerance = self.knob(
            "Parallax tolerance", 0.0, 8.0, 1.5, 100, "slack charged per unit of edge gradient",
            field="edge_tolerance",
        )
        self.min_age = self.knob(
            "Min age (frames)", 0, 120, 10, tip="how long a cell is modelled before it may report",
            field="min_age", cast=int,
        )
        self.note(
            "MOG2 and KNN model a fixed pixel grid, so on drone footage they charge the "
            "camera's own motion to the foreground. The compensated model estimates that "
            "motion and warps its background model to follow it.<br><br>"
            "Keep <b>History</b> short there: once camera motion is cancelled, a plume "
            "venting from one spot is stationary, and a long history will learn it as "
            "background. What still gives it away is that it churns."
        )

        # Grey out what does not apply, and do it once now for the initial model.
        self._gmc_only = (
            self.gmc,
            self.homography,
            self.block,
            self.edge_tolerance,
            self.min_age,
        )
        self.model.currentIndexChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        compensated = self.model.currentText() == COMPENSATED
        for widget in self._gmc_only:
            widget.setEnabled(compensated)

    def restore(self, data: dict) -> None:
        # The base class blocks signals while restoring, so the model combo's
        # enable/disable wiring never fires — run it once afterwards.
        super().restore(data)
        self._sync_enabled()
