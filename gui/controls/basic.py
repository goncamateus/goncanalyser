"""Section A — brightness, contrast, saturation, gamma, and the colour space view."""

from processing.pipeline import COLOR_SPACES

from .base import Section


class BasicSection(Section):
    """Cosmetic adjustments. These run first, before anything is detected."""

    def __init__(self):
        super().__init__("A · Basic Adjustments")
        # Ranges chosen so the middle of every slider is the identity setting the
        # pipeline short-circuits on.
        self.brightness = self.knob(
            "Brightness", -100, 100, 0, tip="additive offset", field="brightness", cast=int
        )
        self.contrast = self.knob(
            "Contrast", 0.1, 3.0, 1.0, 100, "multiplicative gain", field="contrast"
        )
        self.saturation = self.knob(
            "Saturation", 0.0, 3.0, 1.0, 100, "0 = grey, 1 = untouched", field="saturation"
        )
        self.gamma = self.knob(
            "Gamma", 0.1, 3.0, 1.0, 100, "<1 darkens, >1 lifts shadows", field="gamma"
        )

        self.space = self.combo(COLOR_SPACES.keys(), field="color_space")
        self.note("HSV and LAB are drawn as raw channels, i.e. false colour.")
