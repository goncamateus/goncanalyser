"""Image Adjustment tab — the preprocessing every other tab reads."""

from features.adjust import BLURS, COLOR_SPACES, THRESHOLDS

from .base import Section


class AdjustTab(Section):
    def __init__(self):
        super().__init__()

        self.group("Tone")
        self.knob(
            "Brightness", -100, 100, 0, tip="additive offset", field="brightness", cast=int
        )
        self.knob("Contrast", 0.1, 3.0, 1.0, 100, "multiplicative gain", field="contrast")
        self.knob("Saturation", 0.0, 3.0, 1.0, 100, "0 = grey, 1 = untouched", field="saturation")
        self.knob("Gamma", 0.1, 3.0, 1.0, 100, "<1 darkens, >1 lifts shadows", field="gamma")

        self.group("Colour space")
        self.combo(COLOR_SPACES.keys(), field="color_space")
        self.note(
            "Converted <b>before</b> everything downstream, so edges, keypoints and "
            "texture all measure the space you pick here. HSV, HLS and LAB are drawn "
            "as raw channels, i.e. false colour."
        )

        self.group("Smoothing")
        self.combo(BLURS, field="blur_kind")
        self.knob(
            "Kernel", 0, 31, 0, tip="0 or 1 = off; even values round up",
            field="blur", cast=int,
        )
        self.note("Median beats Gaussian on salt-and-pepper noise and keeps edges sharper.")

        self.group("Threshold")
        self.combo(THRESHOLDS, field="threshold_kind")
        self.knob("Level", 0, 255, 127, tip="ignored by Otsu and the adaptive modes",
                  field="threshold", cast=int)
        self.knob(
            "Adaptive neighbourhood", 3, 51, 11,
            tip="the two adaptive modes only; odd, and clamped to >= 3",
            field="adaptive_block", cast=int,
        )
        self.note(
            "The result is what the <b>contour finder</b> reads, so a contour that "
            "looks wrong is usually a threshold that is wrong. Switch the view to "
            "<i>Threshold</i> to see exactly what it is being handed."
        )

        self.stretch()
