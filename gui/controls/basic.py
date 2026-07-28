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

        # 0 is off. Quieting sensor noise here is what stops the background model
        # calling every speckle a moving object — it reads the frame this section
        # produces, not the raw one.
        self.blur = self.knob(
            "Blur (denoise)", 0, 31, 0, tip="0 or 1 = off; even values round up",
            field="blur", cast=int,
        )

        self.space = self.combo(COLOR_SPACES.keys(), field="color_space")
        self.note(
            "This picks <b>what the plume detector measures</b>, not just the view: "
            "each space hands it that space's lightness-like channel — HLS/LAB <i>L</i>, "
            "HSV <i>V</i>, or grey. <b>Default (BGR)</b> leaves the picture alone and "
            "measures HLS lightness, which is the proxy calibrated on these clips.<br><br>"
            "HLS, HSV and LAB are <i>drawn</i> as raw channels, i.e. false colour."
        )
