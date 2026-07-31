"""Global tab — whole-image descriptors: colour histograms, HOG, LBP."""

from features.color import SPACES
from features.texture import LBP_METHODS

from .base import Preview, Section


class GlobalTab(Section):
    def __init__(self):
        super().__init__()

        self.group("Colour histogram")
        self.combo(SPACES.keys(), field="hist_space")
        self.hist = Preview(160)
        self._column.addWidget(self.hist)
        self.note("Always measured — three calcHist calls are cheaper than a checkbox.")

        self.group("HOG — Histogram of Oriented Gradients")
        self.hog_on = self.check("Compute HOG", field="hog_on")
        self.knob("Orientations", 2, 18, 9, tip="gradient direction bins per cell",
                  field="hog_orientations", cast=int)
        self.knob("Cell (px)", 2, 32, 8, tip="pixels per cell, square",
                  field="hog_cell", cast=int)
        self.knob("Block (cells)", 1, 6, 2, tip="cells per normalisation block",
                  field="hog_block", cast=int)
        self.hog = Preview()
        self._column.addWidget(self.hog)
        self.note(
            "<b>Slow: 150-300 ms a frame at 640x512.</b> It runs off the GUI thread so "
            "nothing freezes, but video playback will drop frames while this is on."
        )

        self.group("LBP — Local Binary Patterns")
        self.lbp_on = self.check("Compute LBP", field="lbp_on")
        self.knob("Neighbours (P)", 1, 24, 8, tip="sample points on the circle",
                  field="lbp_points", cast=int)
        self.knob("Radius (R)", 1, 8, 1, tip="circle radius in px",
                  field="lbp_radius", cast=int)
        self.combo(LBP_METHODS, field="lbp_method")
        self.lbp = Preview()
        self._column.addWidget(self.lbp)
        self.note("Entropy in the status bar is high for varied texture, low for flat.")

        self.stretch()

    def previews(self) -> tuple[str, ...]:
        """Only ask the worker for thumbnails that are actually being produced."""
        names = ["Histogram"]
        if self.hog_on.isChecked():
            names.append("HOG")
        if self.lbp_on.isChecked():
            names.append("LBP")
        return tuple(names)

    def show_preview(self, name: str, image) -> None:
        target = {"Histogram": self.hist, "HOG": self.hog, "LBP": self.lbp}.get(name)
        if target is not None:
            target.show_image(image)
