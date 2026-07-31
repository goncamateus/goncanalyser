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

        self.group("Selection")
        self.enabled = self.check("Limit analysis to a region", field="roi_on")
        self.draw = self.button("Draw region on the image", lambda: None)
        self.x = self.spin("X", tip="left edge, px", field="roi_x")
        self.y = self.spin("Y", tip="top edge, px", field="roi_y")
        self.w = self.spin("W", tip="0 = out to the right edge", field="roi_w")
        self.h = self.spin("H", tip="0 = out to the bottom edge", field="roi_h")
        self.button("Reset to the full frame", self.reset_region)
        self.note(
            "Everything is measured <b>inside the rectangle only</b> — the frame "
            "around it stays on screen as context and never reaches the numbers. "
            "Arrows step by 10; <b>0</b> for W or H means out to the edge.<br><br>"
            "Exported coordinates are translated back to full-frame pixels, so a "
            "CSV means the same thing with a region as without one."
        )

        self.stretch()

    def reset_region(self) -> None:
        """Back to the whole frame, without disturbing the other three tabs."""
        for spin in (self.x, self.y, self.w, self.h):
            spin.setValue(0)

    def set_frame_size(self, width: int, height: int) -> None:
        """Cap the boxes at the source's dimensions, so a rect cannot be typed off-frame."""
        for spin, limit in ((self.x, width), (self.y, height), (self.w, width), (self.h, height)):
            spin.setMaximum(max(0, limit))
